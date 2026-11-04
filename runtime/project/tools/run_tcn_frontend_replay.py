"""Replay saved landmark packets into Q FPGA TCN; no camera or display claim."""
from pathlib import Path
import importlib.util,json,secrets,subprocess,sys,time,traceback
import psutil
W=Path(__file__).resolve().parents[1];V=W/'fpga/output/report_hybrid_0600_20261101'


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def main():
    for p in psutil.process_iter(['name','cmdline']):
        if p.info['name'].lower()=='python.exe'and any(str(a).replace('\\','/').lower()==str(W/'tools/run_add_checkpoint_recovery.py').replace('\\','/').lower()for a in p.info['cmdline']or[]):
            assert p.status()==psutil.STATUS_STOPPED,'Pause the verified route coordinator before taking Q'
    subprocess.run([sys.executable,'-B',str(W/'tools/refresh_candidate.py')],check=True,cwd=W)
    host=module('q_replay_host',V/'board_workers/qiming/q_host.py');nav=module('nav_replay_relay',V/'board_workers/host_support/boardctl.py')
    reference=json.loads((W/'data/reference/tcn_landmark_replay.json').read_text('utf-8'))
    payloads=reference['payloads']
    run=W/'runs'/('tcn_frontend_replay_'+time.strftime('%Y%m%d_%H%M%S'));run.mkdir()
    r=dict(status='PREPARING',source_scope='fixed_fixture_saved_landmarks',camera_opened=False,display_used=False,errors=[]);active=None
    def save():(run/'result.json').write_text(json.dumps(r,indent=2)+'\n')
    try:
        key=secrets.token_bytes(32);session='saved_landmarks_'+secrets.token_hex(8)
        active=host.launch(key,session,source_scope='fixed_fixture',fixture_kind='same_frame_perception_heads');r['active']=active;save()
        deadline=time.monotonic()+60
        while True:
            state=host.status(active,compact=True);worker=state.get('worker')or{}
            if worker.get('status')=='SAME_FRAME_PERCEPTION_READY':break
            if 'FAIL'in worker.get('status','')or not state.get('alive'):raise RuntimeError('Q worker startup failed: '+str(worker.get('errors')))
            if time.monotonic()>deadline:raise TimeoutError('Q worker startup timeout')
            time.sleep(.2)
        code=(V/'pc_runtime/rpc_protocol.py').read_text()+'''
import sys
d=json.load(sys.stdin);key=bytes.fromhex(d['key']);session=d['session'];events=[]
deadline=time.monotonic()+90
while True:
    try:c=socket.create_connection(('192.168.1.30',5115),timeout=2);break
    except OSError:
        if time.monotonic()>deadline:raise
        time.sleep(.2)
c.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
try:
    send_packet(c,key,dict(operation='hello',session_id=session));reply,b=recv_packet(c,key);assert reply['operation']=='ready'
    for index,x in enumerate(d['rows']):
        raw=json.dumps(dict(image_size=[800,480],body=x['body'],hands=x['hands']),separators=(',',':'),allow_nan=False).encode()
        identity=hashlib.sha256(json.dumps([session,x['frame_id'],x['capture_ns']],separators=(',',':')).encode()).hexdigest()
        h=dict(operation='semantic_frame',session_id=session,request_index=index,frame_id=x['frame_id'],capture_ns=x['capture_ns'],source_identity_sha256=identity,input_sha256=hashlib.sha256(raw).hexdigest(),dtype='json',shape=[])
        send_packet(c,key,h,raw);reply,b=recv_packet(c,key,timeout=30,max_body=300000)
        for field in ('frame_id','request_index','source_identity_sha256','input_sha256'):assert reply[field]==h[field]
        assert reply['source_capture_ns']==x['capture_ns']and reply['output_sha256']==reply['_authenticated_body_sha256']
        value=json.loads(b)
        if value['event']:events.append(value)
    send_packet(c,key,dict(operation='close',session_id=session));reply,b=recv_packet(c,key);assert reply['operation']=='closed'
    print(json.dumps(dict(status='SAVED_LANDMARKS_Q_TCN_PASS',frames=len(d['rows']),events=events,actual_PL_RUNs=sum(v['actual_PL_RUNs']for v in events))))
finally:c.close()
'''
        remote=nav.run('navigator',code,dict(key=key.hex(),session=session,rows=payloads),timeout=120);assert remote['rc']==0,remote
        r['replay']=json.loads(remote['stdout']);expected=reference['expected_events']
        assert len(expected)==len(r['replay']['events'])
        for old,value in zip(expected,r['replay']['events']):
            new=value['event']
            for field in ('label','gesture','confidence_Q15','accepted_by_original_gate','actual_PL_RUNs','source_frame_ids','features'):assert new[field]==old[field],field
            for a,b in zip(old['model_runs'],new['model_runs']):
                for field in ('profile','class_index','logits_int16','probabilities_Q15','actual_PL_RUNs'):assert a[field]==b[field],field
        r['status']='Q_TCN_FRONTEND_REPLAY_EXACT_AWAIT_RESTORE';save()
    except BaseException as error:
        r.update(status='FAILED',traceback=traceback.format_exc());r['errors'].append(str(error));active=active or getattr(host,'last_owned_active',None)
    finally:
        if active:
            try:
                state=host.status(active,compact=True)
                if state.get('alive'):host.stop(active)
                deadline=time.monotonic()+150
                while True:
                    state=host.status(active,compact=True);r['restore']=state;save()
                    if state.get('restored'):break
                    if time.monotonic()>deadline or state.get('restore_error'):raise RuntimeError('Q restoration not confirmed')
                    time.sleep(1)
                assert state['worker']['all_device_fds_closed']
            except BaseException as error:r['errors'].append('Restore: '+str(error))
        if r['status']=='Q_TCN_FRONTEND_REPLAY_EXACT_AWAIT_RESTORE'and not r['errors']:r['status']='Q_TCN_FRONTEND_REPLAY_EXACT_RESTORED'
        save()
    print(json.dumps(dict(status=r['status'],run=str(run),errors=r['errors'])))
    if r['errors']:raise SystemExit(1)


if __name__=='__main__':main()
