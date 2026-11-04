"""Direct Nav -> Q/P Full Hand join from existing TIM9 shared camera frames."""
from pathlib import Path
import sys
sys.path.append('/opt/gesture-tcn-20261022/stdlib_compat')
import concurrent.futures,hashlib,json,socket,sys,time,traceback
import numpy as np
from timed_camera import TimedCameraReader
from rpc_protocol import send_packet,recv_packet


def main():
    cfg=json.load(sys.stdin);key=bytes.fromhex(cfg.pop('key'));session=cfg['session_id']
    r=dict(status='STARTING',session_id=session,rows=[],errors=[],PC_core_inference=0,
           physical_camera_opened=False,TCN_RUN=0,HDMI_modified=False,full_frame_acceptance=False,
           roi_scope='FIXED_TEST_ROI_NOT_PALM_DETECTION',clock_scope='Nav CLOCK_MONOTONIC capture-to-join; remote durations use own clocks')
    camera=None;sockets=[]
    try:
        camera=TimedCameraReader('/run/medcomm/camera.frame',fresh_on_open=True,stall_seconds=3.)
        deadline=time.monotonic()+90
        for address in ('192.168.1.30','192.168.1.20'):
            while True:
                try:conn=socket.create_connection((address,5115),timeout=2);break
                except OSError:
                    if time.monotonic()>deadline:raise
                    time.sleep(.2)
            conn.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1);sockets.append(conn)
            send_packet(conn,key,dict(operation='hello',session_id=session));head,body=recv_packet(conn,key,timeout=10)
            assert head['operation']=='ready' and head['session_id']==session and not body
        def infer(index,head,payload):
            start=time.monotonic_ns();send_packet(sockets[index],key,head,payload)
            sent=time.monotonic_ns()
            reply,raw=recv_packet(sockets[index],key,timeout=20);end=time.monotonic_ns()
            assert reply['operation']=='hand_result' and reply['session_id']==session
            for name in ('frame_id','source_identity_sha256','input_sha256'):assert reply[name]==head[name],name
            assert reply['source_capture_ns']==head['capture_ns'] and len(raw)==44*4
            assert hashlib.sha256(raw).hexdigest()==reply['output_sha256'] and reply['native_dma_guards_pass']
            return dict(nav_send_ns=start,nav_sent_ns=sent,nav_reply_ns=end,send_ns=sent-start,roundtrip_ns=end-start,remote=reply),raw
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            last=-1
            for ordinal in range(6):
                frame=camera.read(timeout=3);meta=frame.metadata;fid=int(meta['source_sequence'])
                assert fid>last and meta['capture_timestamp_tag']=='TIM9' and meta['capture_provenance_available'];last=fid
                original=np.ascontiguousarray(frame.bgr)
                identity=hashlib.sha256(json.dumps([session,fid,meta['capture_complete_monotonic_ns']],separators=(',',':')).encode()).hexdigest()
                start=time.monotonic_ns();jobs={}
                # First two frames send an identical crop for a live cross-board oracle.
                for index in (1,0):
                    left=176 if ordinal<2 or index==0 else 400
                    # XOR flips the sign bit: the exact bytes of uint8 -> int8 minus 128.
                    payload=np.bitwise_xor(original[128:352,left:left+224,::-1],np.uint8(128)).tobytes()
                    head=dict(operation='hand',session_id=session,frame_id=fid,source_identity_sha256=identity,
                              capture_ns=meta['capture_complete_monotonic_ns'],input_sha256=hashlib.sha256(payload).hexdigest(),
                              shape=[224,224,3],dtype='int8',roi=[left,128,224,224],roi_scope=r['roi_scope'])
                    jobs[index]=pool.submit(infer,index,head,payload)
                dispatched=time.monotonic_ns()
                # Retain the complete pixel hash while both boards compute. The wire
                # identity binds session/frame/EOF; each crop has its own HMAC and hash.
                source=hashlib.sha256(original).hexdigest();hashed=time.monotonic_ns()
                results=[jobs[index].result() for index in range(2)];done=time.monotonic_ns()
                exact=results[0][1]==results[1][1] if ordinal<2 else None
                assert exact is not False,'Live identical inputs differ across Q/P'
                r['rows'].append(dict(frame_id=fid,camera=meta,source_sha256=source,source_identity_sha256=identity,
                    identity_scope='SHA256 of JSON [session_id,frame_id,capture_EOF_ns]; full pixel SHA retained separately',
                    preprocess_and_submit_ns=dispatched-start,overlapped_full_pixel_hash_ns=hashed-dispatched,branches=[x[0] for x in results],
                    identical_crop_cross_board_exact=exact,crop_dispatch_join_ns=done-start,
                    capture_EOF_to_join_ns=done-meta['capture_complete_monotonic_ns'],
                    parallel_RPC_overlap_ns=max(0,min(x[0]['nav_reply_ns'] for x in results)-max(x[0]['nav_send_ns'] for x in results))))
        for conn in sockets:
            send_packet(conn,key,dict(operation='close',session_id=session));reply,body=recv_packet(conn,key,timeout=10)
            assert reply['operation']=='closed' and reply['actual_NN_PL_RUN']==300 and not body
        r['status']='SIX_REAL_FRAMES_DIRECT_DUAL_FULL_HAND_PASS'
    except BaseException as error:
        r.update(status='FAILED',traceback=traceback.format_exc());r['errors'].append(type(error).__name__+': '+str(error))
    finally:
        for conn in sockets:conn.close()
        if camera:camera.close()
        Path(__file__).with_name('result.json').write_text(json.dumps(r,indent=2)+'\n')
        print(json.dumps(r))
    if r['errors']:raise SystemExit(1)


if __name__=='__main__':
    if sys.argv[1:]==['--check']:
        camera=TimedCameraReader('/run/medcomm/camera.frame',fresh_on_open=True,stall_seconds=3.)
        try:
            frame=camera.read(timeout=3)
            assert frame.metadata['capture_timestamp_tag']=='TIM9' and frame.metadata['capture_provenance_available']
            print(json.dumps(dict(status='NAV_IMPORT_AND_SHARED_TIM9_PASS',camera=frame.metadata,shape=list(frame.bgr.shape),physical_camera_opened=False)))
        finally:camera.close()
    else:main()
