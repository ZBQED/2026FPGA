"""One detached finite PYNQ Full Hand window, restoring the actual boot entry."""
from pathlib import Path
import ast
import hashlib
import importlib.util
import json
import time
import uuid
import sys
import paramiko

WORK=Path(__file__).resolve().parents[1]
V=WORK/'fpga/output/report_hybrid_0600_20261101'
PACKAGE=V/'board_workers/pynq/runtime_package'
SAME_FRAME=None


def main():
    run=WORK/'runs'/('p_full_hand_'+time.strftime('%Y%m%d_%H%M%S'));run.mkdir()
    main.last_run=run
    session=SAME_FRAME['session_id'] if SAME_FRAME else 'phand_'+uuid.uuid4().hex[:16]
    restore=json.loads((WORK/'runs/pynq_current_restore.json').read_text(encoding='utf-8'))
    cfg=dict(boot_id=restore['boot_id'],session_id=session,source_scope='fixed_fixture',fixture_kind='full_hand',
             pair_repeats=int(sys.argv[1])if SAME_FRAME is None and len(sys.argv)>1 else 3,
             authorization='User authorized three boards and autonomous FPGA deployment; frozen fixtures while away')
    if SAME_FRAME:cfg.update(fixture_kind=SAME_FRAME.get('fixture_kind','same_frame_hand'),peer_board='pynq',source_scope=SAME_FRAME.get('source_scope','live_nav_ram'))
    (run/'window_config.json').write_text(json.dumps(cfg,indent=2)+'\n',encoding='utf-8')
    q=json.loads((PACKAGE/'qualified_rpc_manifest.json').read_text(encoding='utf-8'))
    files={'controller.py':WORK/'pynq_full_hand/controller.py',
           'fixed_full_hand_worker.py':V/'q_worker/fixed_full_hand_worker.py',
           'window_config.json':run/'window_config.json','restore_identity.json':WORK/'runs/pynq_current_restore.json',
           'hardware_qualification.json':PACKAGE/'qualified_rpc_manifest.json'}
    for n in ('raw_window_helpers.py','metadata_codec.py','b25_context.py'):files[n]=PACKAGE/n
    for n,key in [('candidate.bit','bit'),('candidate.hwh','hwh'),('gesture_pynq_hand_i8.ko','module'),('hand_overlay_100mhz.dtbo','dtbo')]:
        files['hardware/'+n]=PACKAGE/q['files'][key]['file']
    for n in ('libfull_hand_pl.so','hand_weights.bin','hand_plan.json','full_hand_fixture.npz','full_hand_layer_hashes.json'):
        files['full_hand/'+n]=WORK/'models/full_hand'/n
    if SAME_FRAME:
        for name in ('same_frame_hand_worker.py','same_frame_perception_worker.py','full_hand_runtime.py','rpc_protocol.py'):
            files[name]=V/'q_worker'/name if name!='rpc_protocol.py' else V/'pc_runtime'/name
        if cfg['fixture_kind']in('person_raw','same_frame_perception','person_palm_hand','same_frame_perception_balanced'):
            for name in ('libyf2_raw_pl.so','layers.json'):files['person_raw/'+name]=WORK/'models/person_raw_pl'/name
            files['fixed_person_raw_worker.py']=V/'q_worker/fixed_person_raw_worker.py'
            files['full_palm/fixture.npz']=WORK/'models/full_palm/fixture.npz'
            files['person_raw_runtime.py']=V/'q_worker/person_raw_runtime.py'
        if cfg['fixture_kind']in('person_palm_hand','same_frame_perception_balanced'):
            files['resident_models.py']=V/'q_worker/resident_models.py'
            for name in ('layout.json','manifest.json'):files['shared_workspace/'+name]=WORK/'models/shared_workspace'/name
            for folder in ('full_palm_fused_cached','full_body_channels_cached','full_hand'):
                for name in ('libfull_hand_pl.so','hand_weights.bin'):files['shared_workspace/'+folder+'/'+name]=WORK/'models/shared_workspace'/folder/name
            files['tcn508a/runtime/libgesture_lite_i8_v12.so']=WORK/'models/tcn508a/minimal/runtime/libgesture_lite_i8_v12.so'
    for path in files.values():
        if path.suffix=='.py':ast.parse(path.read_text(encoding='utf-8'),filename=str(path))
    hashes={n:hashlib.sha256(p.read_bytes()).hexdigest() for n,p in files.items()}
    spec=importlib.util.spec_from_file_location('finite_p_root',V/'board_workers/host_support/pynq_root.py')
    host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)
    c=host.connect('pynq');stage='/home/xilinx/light_try_'+session;root='/root/light_try_'+session
    result=dict(status='STAGING',session_id=session,root=root,run=str(run),source_scope=cfg['source_scope'])
    def save():(run/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    save()
    try:
        sf=c.open_sftp()
        try:
            sf.mkdir(stage,0o700)
            for n,p in files.items():
                current=stage
                for part in Path(n).parent.parts:
                    current+='/'+part
                    try:sf.mkdir(current,0o700)
                    except OSError:pass
                sf.put(str(p),stage+'/'+n)
        finally:sf.close()
        source=r'''
from pathlib import Path
import hashlib,json,os,subprocess,sys,time
p=json.load(sys.stdin);d=Path(p['root']);assert not d.exists();assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==p['boot_id'];os.umask(0o077);d.mkdir(mode=0o700)
for name,digest in p['files'].items():
 data=(Path(p['stage'])/name).read_bytes();assert hashlib.sha256(data).hexdigest()==digest
 target=d/name;target.resolve().relative_to(d.resolve());target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
(d/'package_manifest.json').write_text(json.dumps(p['files']))
with (d/'controller.log').open('x') as log:
 child=subprocess.Popen([sys.executable,'-B',str(d/'controller.py')],cwd=str(d),stdin=subprocess.PIPE if p.get('key') else subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1'))
 if p.get('key'):child.stdin.write(bytes.fromhex(p['key']));child.stdin.close()
 proc=Path('/proc',str(child.pid));fields=(proc/'stat').read_text().rsplit(')',1)[1].split();identity=dict(pid=child.pid,start_ticks=int(fields[19]),boot_id=p['boot_id'],root=str(d))
 (d/'controller_process.json').write_text(json.dumps(identity));print(json.dumps(identity))
'''
        active=json.loads(host.execute(c,source,dict(root=root,stage=stage,files=hashes,boot_id=cfg['boot_id'],key=SAME_FRAME['key'].hex() if SAME_FRAME else None),timeout=30))
        result['active']=active;result['status']='CONTROLLER_RUNNING';save()
    except BaseException as e:
        result['error']=type(e).__name__+': '+str(e);save();raise
    finally:c.close()
    source=r'''
from pathlib import Path
import json,sys
p=json.load(sys.stdin);d=Path(p['root']);r={}
for name in ['window_receipt.json','rpc_actual.json']:
 f=d/name
 if f.exists():r[name]=json.loads(f.read_text())
r['boot_id']=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
f=d/'controller.log';r['log_tail']=f.read_text(errors='replace')[-2000:] if f.exists() else None
print(json.dumps(r))
'''
    deadline=time.monotonic()+330
    while time.monotonic()<deadline:
        c=None
        try:
            c=host.connect('pynq');state=json.loads(host.execute(c,source,active,timeout=15))
        except (TimeoutError,EOFError,OSError,paramiko.SSHException)as error:
            result.setdefault('collection_transient_errors',[]).append(type(error).__name__+': '+str(error));save();time.sleep(1);continue
        finally:
            if c:c.close()
        result['state']=state;receipt=state.get('window_receipt.json') or {};result['status']=receipt.get('status','STARTING');save()
        if state['boot_id']!=active['boot_id']:raise RuntimeError('PYNQ boot changed; preserve controller evidence')
        if result['status'] in ('FIXTURE_PASS_ORIGINAL_RESTORED','FIXTURE_FAILED_ORIGINAL_RESTORED','BLOCKED_UNHEALTHY_NO_FORCE'):break
        time.sleep(.7)
    else:raise TimeoutError('Finite P controller still active; preserved without forced stop')
    model=state.get('rpc_actual.json') or {}
    print(json.dumps(dict(status=result['status'],run=str(run),PL_RUN=model.get('actual_NN_PL_RUN'),
                          calls=len(model.get('rows',[])),restored=receipt.get('original_service_restored'),
                          errors=receipt.get('errors'),restore_error=receipt.get('restore_error'))))
    if result['status']!='FIXTURE_PASS_ORIGINAL_RESTORED':raise SystemExit(1)


if __name__=='__main__':main()
