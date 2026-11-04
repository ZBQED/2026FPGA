"""Finite Full Hand peer for direct Nav frames; no TCN or camera device access."""
from pathlib import Path
import hashlib,json,os,signal,socket,time,traceback
import numpy as np
from full_hand_runtime import FullHand
from rpc_protocol import send_packet,recv_packet


def run(root,cfg,key):
    def stop(*unused):raise InterruptedError('Stop after current native call')
    signal.signal(signal.SIGTERM,stop)
    board=cfg.get('peer_board','qiming');address={'qiming':'192.168.1.30','pynq':'192.168.1.20'}[board]
    r=dict(status='SAME_FRAME_HAND_STARTING',board=board,session_id=cfg['session_id'],rows=[],errors=[],
           camera_opened=False,TCN_RUN=0,actual_NN_PL_RUN=0,full_frame_acceptance=False)
    def save():
        p=root/'rpc_actual.json.tmp';p.write_text(json.dumps(r,separators=(',',':')));p.replace(root/'rpc_actual.json')
    model=server=conn=clock=None
    try:
        assert len(key)==32 and Path('/proc/sys/kernel/random/boot_id').read_text().strip()==cfg['boot_id']
        for name,digest in json.loads((root/'package_manifest.json').read_text()).items():
            assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,name
        plan=json.loads((root/'full_hand/hand_plan.json').read_text())
        assert plan['source_hand_sha256']=='74aa6f9a1d2834b20e289cb2ee5ccd92e555bb93425fa7db35d68d43875fef0a'
        model=FullHand(root/'full_hand');model.trace(False)
        if board=='qiming':
            import qualified_clock
            clock=qualified_clock.prepare(root);qualified_clock.fast(clock);r['clock_experiment']=clock
        server=socket.socket();server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        server.bind((address,5115));server.listen(1);server.settimeout(180)
        r['status']='SAME_FRAME_HAND_READY';save();conn,peer=server.accept()
        assert peer[0]=='192.168.1.10','Only direct Nav peer permitted'
        conn.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        last=-1;hello=False
        while True:
            packet_wait=time.monotonic_ns()
            head,body=recv_packet(conn,key,timeout=60,max_body=224*224*3)
            packet_ready=time.monotonic_ns()
            assert head['session_id']==cfg['session_id']
            if head['operation']=='hello':
                assert not hello and not body;hello=True
                send_packet(conn,key,dict(operation='ready',session_id=cfg['session_id'],board=board,actual_NN_PL_RUN=0));continue
            assert hello
            if head['operation']=='close':
                assert not body and len(r['rows'])==6
                send_packet(conn,key,dict(operation='closed',session_id=cfg['session_id'],calls=6,actual_NN_PL_RUN=r['actual_NN_PL_RUN']));break
            assert head['operation']=='hand' and len(r['rows'])<6 and head['frame_id']>last
            assert head['shape']==[224,224,3] and head['dtype']=='int8' and len(body)==224*224*3
            assert hashlib.sha256(body).hexdigest()==head['input_sha256']
            identity=hashlib.sha256(json.dumps([cfg['session_id'],head['frame_id'],head['capture_ns']],separators=(',',':')).encode()).hexdigest()
            assert head['source_identity_sha256']==identity
            assert head['roi_scope']=='FIXED_TEST_ROI_NOT_PALM_DETECTION'
            received=time.monotonic_ns();x=np.frombuffer(body,np.int8).reshape(224,224,3)
            heads,stats=model.infer(x);done=time.monotonic_ns();assert np.isfinite(heads).all()
            r['actual_NN_PL_RUN']+=stats['PL_jobs'];last=head['frame_id']
            raw=heads.astype('<f4',copy=False).tobytes()
            row=dict(frame_id=last,source_identity_sha256=identity,input_sha256=head['input_sha256'],
                     source_capture_ns=head['capture_ns'],received_ns=received,done_ns=done,stats=stats,
                     output_sha256=hashlib.sha256(raw).hexdigest(),native_dma_guards_pass=True)
            row.update(packet_wait_ns=packet_wait,packet_ready_ns=packet_ready,reply_ready_ns=time.monotonic_ns())
            r['rows'].append(row)
            send_packet(conn,key,dict(operation='hand_result',session_id=cfg['session_id'],board=board,**row),raw)
            row['reply_sent_ns']=time.monotonic_ns()
        r['status']='SAME_FRAME_HAND_PASS'
    except BaseException as error:
        r.update(status='SAME_FRAME_HAND_FAILED',traceback=traceback.format_exc());r['errors'].append(type(error).__name__+': '+str(error))
    finally:
        if conn:conn.close()
        if server:server.close()
        if model:model.close()
        if clock:qualified_clock.restore(clock)
        r['all_device_fds_closed']=not any(p.exists() and os.path.realpath(str(p))=='/dev/gesture-i8-pl0' for p in Path('/proc/self/fd').iterdir())
        save()
    if r['errors'] or not r['all_device_fds_closed']:raise RuntimeError('Same-frame Full Hand failed; evidence retained')
