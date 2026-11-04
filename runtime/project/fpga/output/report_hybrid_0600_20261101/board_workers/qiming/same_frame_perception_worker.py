"""Finite actual-frame requests; Q holds Palm/Body/Hand, P holds Full Hand."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib,json,os,signal,socket,time,traceback
import numpy as np
from rpc_protocol import send_packet,recv_packet


def run(root,cfg,key):
    def stop(*args):raise InterruptedError('Stop after current native call')
    signal.signal(signal.SIGTERM,stop)
    board=cfg.get('peer_board','qiming');q=board=='qiming'
    hybrid=cfg['fixture_kind']=='same_frame_perception_heads'
    semantic=q and cfg['fixture_kind']in('same_frame_perception_tcn','same_frame_perception_heads')
    balanced=cfg['fixture_kind']=='same_frame_perception_balanced'
    r=dict(status='SAME_FRAME_PERCEPTION_STARTING',board=board,rows=[],errors=[],actual_NN_PL_RUN=0,
           TCN_RUN=0,camera_opened=False,full_frame_acceptance=False)
    def save():
        p=root/'rpc_actual.json.tmp';p.write_text(json.dumps(r,separators=(',',':')));p.replace(root/'rpc_actual.json')
    model=person=owner=clock=server=conn=hand_pool=None;original_affinity=None;frames={};request=0
    try:
        assert len(key)==32 and Path('/proc/sys/kernel/random/boot_id').read_text().strip()==cfg['boot_id']
        for name,digest in json.loads((root/'package_manifest.json').read_text()).items():
            assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,name
        if q:
            from resident_models import ResidentModels
            import qualified_clock
            if semantic:
                from shared_perception_tcn import SharedPerceptionTCN
                model=SharedPerceptionTCN(root,cfg['session_id'],person_fpga=hybrid)
            else:model=ResidentModels(root,halfadd=True,palm_lut=True)
            clock=qualified_clock.prepare(root);qualified_clock.fast(clock)
            if hybrid:
                admission=json.loads((root/'person_raw/shared_admission.json').read_text())
                assert admission['status']in('Q_PERSON_HAND_TCN_SHARED_SINGLE_FD_PASS','Q_SHARED_REVALIDATION_REQUIRED')
                for name,digest in admission['qualified_files'].items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,name
                model.guards();assert model.person.api.yf2_fpga_guards()==0
                if admission['status']=='Q_SHARED_REVALIDATION_REQUIRED':
                    from shared_person_startup import validate
                    fresh=validate(model,root);fresh.update(source_run=cfg['session_id'],qualified_files=admission['qualified_files'])
                    r['fresh_shared_admission']=fresh
                else:r['reused_shared_admission']=dict(source_run=admission['source_run'],same_qualified_files=True,new_frozen_NN_RUN=0)
                save()
        else:
            from full_hand_runtime import FullHand
            from person_raw_runtime import PersonRaw
            owner=os.open('/dev/gesture-i8-pl0',os.O_RDWR)
            person=PersonRaw(root/'person_raw',owner)
            if balanced:
                from resident_models import ResidentModels
                assert person.api.yf2_fpga_pool_used()<json.loads((root/'shared_workspace/manifest.json').read_text())['boundary_guard']
                model=ResidentModels(root,workspace=True,parent_fd=owner)
            else:model=FullHand(root/'full_hand',parent_fd=owner);model.trace(False)
        server=socket.socket();server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        server.bind(('192.168.1.30'if q else'192.168.1.20',5115));server.listen(1);server.settimeout(180)
        r['status']='SAME_FRAME_PERCEPTION_READY';save();conn,peer=server.accept();assert peer[0]=='192.168.1.10'
        conn.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        hello=False
        while True:
            head,body=recv_packet(conn,key,timeout=90,max_body=192*192*3+224*224*3)
            assert head['session_id']==cfg['session_id']
            op=head['operation']
            if op=='hello':
                assert not hello and not body;hello=True
                send_packet(conn,key,dict(operation='ready',session_id=cfg['session_id']));continue
            assert hello
            if op=='close':
                assert not body and 1<=len(frames)<=1024
                send_packet(conn,key,dict(operation='closed',session_id=cfg['session_id'],actual_NN_PL_RUN=r['actual_NN_PL_RUN']));break
            assert head['request_index']==request and request<4096;request+=1
            fid=head['frame_id'];stamp=head['capture_ns']
            identity=hashlib.sha256(json.dumps([cfg['session_id'],fid,stamp],separators=(',',':')).encode()).hexdigest()
            assert head['source_identity_sha256']==identity and head['_authenticated_body_sha256']==head['input_sha256']
            assert (fid in frames and frames[fid]==stamp) or (fid>max(frames,default=-1) and len(frames)<1024)
            frames[fid]=stamp
            dtype='int8'if op=='person'else'float32'
            if op=='person_hand':
                assert hybrid and q and head['shape']==[192*192*3+224*224*3]and head['dtype']=='int8'and len(body)==192*192*3+224*224*3
                if hand_pool is None:
                    original_affinity=os.sched_getaffinity(0);cores=sorted(original_affinity);assert len(cores)>=2
                    os.sched_setaffinity(0,{cores[0]})
                    hand_pool=ThreadPoolExecutor(max_workers=1,initializer=lambda:os.sched_setaffinity(0,{cores[1]}))
                x=np.frombuffer(body,np.int8);px=x[:192*192*3].reshape(192,192,3);hx=x[192*192*3:].reshape(224,224,3)
                started=time.monotonic_ns();future=hand_pool.submit(model.infer,'full_hand',hx)
                ph,ps=model.person.infer(px);hh,hs=future.result(timeout=10);elapsed=time.monotonic_ns()-started
                assert np.isfinite(hh).all();raw=ph.tobytes()+hh.astype('<f4',copy=False).tobytes();dtype='bytes'
                stats=dict(PL_jobs=ps['PL_jobs']+hs['PL_jobs'],complete_call_ns=elapsed,Person=ps,Hand=hs,person_bytes=ph.nbytes,hand_values=hh.size,thread_pinning=True)
            elif op=='semantic_frame':
                assert semantic and head['dtype']=='json'and head['shape']==[]
                value=model.semantic_frame(json.loads(body),fid,stamp)
                raw=json.dumps(value,separators=(',',':'),allow_nan=False).encode();dtype='json'
                stats=dict(PL_jobs=value['actual_PL_RUNs'],complete_call_ns=value['complete_call_ns'],TCN_RUN=value['TCN_RUN'])
                r['TCN_RUN']+=value['TCN_RUN']
            elif op=='skip_hand':
                assert not q and not body;raw=b'';stats=dict(PL_jobs=0,complete_call_ns=0)
            else:
                shapes={'person':(192,192,3),'palm':(192,192,3),'body':(256,192,3),'hand':(224,224,3)}
                assert op in (('person','hand')if hybrid else('palm','body','hand')if q else('person','palm','hand')if balanced else('person','hand')) and head['shape']==list(shapes[op]) and len(body)==int(np.prod(shapes[op]))
                x=np.frombuffer(body,np.int8).reshape(shapes[op])
                if hybrid and op=='person':heads,stats=model.person.infer(x)
                elif q:heads,stats=model.infer({'palm':'full_palm_fused_cached','body':'full_body_channels_cached','hand':'full_hand'}[op],x)
                elif op=='person':heads,stats=person.infer(x)
                elif balanced:heads,stats=model.infer({'palm':'full_palm_fused_cached','hand':'full_hand'}[op],x)
                else:heads,stats=model.infer(x)
                if balanced:assert person.api.yf2_fpga_guards()==0;model.guards()
                assert np.isfinite(heads).all();raw=heads.astype(np.int8 if op=='person'else'<f4',copy=False).tobytes()
            r['actual_NN_PL_RUN']+=stats['PL_jobs']
            row=dict(operation=op,frame_id=fid,source_capture_ns=stamp,source_identity_sha256=identity,
                     input_sha256=head['input_sha256'],output_sha256=hashlib.sha256(raw).hexdigest(),output_dtype=dtype,stats=stats)
            r['rows'].append(row)
            send_packet(conn,key,dict(operation='result',session_id=cfg['session_id'],request_index=head['request_index'],**{k:v for k,v in row.items()if k!='operation'}),raw)
        r['status']='SAME_FRAME_PERCEPTION_PASS'
    except BaseException as error:
        r.update(status='SAME_FRAME_PERCEPTION_FAILED',traceback=traceback.format_exc());r['errors'].append(str(error))
    finally:
        if conn:conn.close()
        if server:server.close()
        if hand_pool:hand_pool.shutdown(wait=True)
        for label,obj in [('model',model),('person',person)]:
            try:
                if obj:obj.close()
            except BaseException as error:r['errors'].append(label+' close: '+str(error))
        if owner is not None:os.close(owner)
        try:
            if clock:qualified_clock.restore(clock)
        except BaseException as error:r['errors'].append('Clock restore: '+str(error))
        if original_affinity is not None:os.sched_setaffinity(0,original_affinity)
        if r['errors']:r['status']='SAME_FRAME_PERCEPTION_FAILED'
        r['all_device_fds_closed']=not any(p.exists()and os.path.realpath(str(p))=='/dev/gesture-i8-pl0'for p in Path('/proc/self/fd').iterdir());save()
    if r['errors']or not r['all_device_fds_closed']:raise RuntimeError('Current-frame perception worker failed')
