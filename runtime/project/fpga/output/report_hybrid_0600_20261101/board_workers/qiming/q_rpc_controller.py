"""User-authorized Q realtime lifecycle; hardware remains until explicit STOP."""
from pathlib import Path
import argparse,hashlib,json,os,re,signal,socket,struct,subprocess,time
from metadata_codec import snapshot_pl_metadata
H=Path(__file__).resolve().parent;PY='/usr/local/share/pynq-venv/bin/python3'
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--execute',action='store_true');a=ap.parse_args()
 if not a.execute:print('PLAN_ONLY_NO_BOARD_ACTION');return
 os.environ.update(XILINX_XRT='/usr',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
 import fcntl,window_state as s
 from pynq import PL
 cfg=json.loads((H/'window_config.json').read_text());manifest=json.loads((H/'package_manifest.json').read_text());r=dict(status='PREFLIGHT',boot_id=s.boot(),window_id=cfg['window_id'],session_id=None,original_service_restored=False,actions=[],errors=[],model_warmup_RUN=0);receipt=H/'window_receipt.json';worker=None;out=err=None;changed=False;detached=False;stop_requested=False;firmware=Path('/lib/firmware')/('q_realtime_'+cfg['window_id']+'.bin')
 def save():s.dump(receipt,r)
 def metadata():return snapshot_pl_metadata(PL)
 def unchanged():
  assert s.boot()==before['boot_id']and s.touch_snapshot()==before['touch']and s.clocks()==before['clock']and metadata()==before['metadata'],'Touch/clock/metadata changed; block reconfiguration'
 def identity(pid):return s.process(pid)
 def alive(p):
  try:return identity(p['pid'])==p and Path('/proc',str(p['pid']),'stat').read_text().rsplit(')',1)[1].split()[0]!='Z'
  except OSError:return False
 lock=os.open('/run/lock/gesture-qiming-v11-window.lock',os.O_RDWR|os.O_CREAT,0o600);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 assert os.geteuid()==0 and cfg['realtime_authorized']is True and cfg['source_scope']in('live_pc_ram','fixed_fixture','live_nav_ram')and cfg['boot_id']==s.boot()
 assert 0<=time.monotonic_ns()-cfg['admission_monotonic_ns']<=300_000_000_000
 for n,d in manifest.items():assert s.sha(H/n)==d,n
 module=H/'gesture_pl_i8_driver_v14.ko';overlay=None
 assert not cfg.get('fixture_kind','').endswith(('_add_compare','_mul_compare'))
 assert s.sha(H/'candidate.bit')=='326695c02344bf5adf2deccda81ebf4d03fc20995a32383a309373620e205783'
 assert s.sha(module)=='73f0b2391e4707e149b966f9bac588492aa8bc3093a865bc8295269720f953ba'
 before=dict(boot_id=s.boot(),clock=s.clocks(),touch=s.touch_snapshot(),pose=s.process(s.mainpid(s.POSE)),metadata=metadata(),assets=s.check_original_assets());r['before']=before;save();assert before['pose']==cfg['pose_process']and before['metadata']==cfg['metadata']and before['clock']==cfg['clocks']and before['touch']==cfg['touch']
 try:
  assert s.module_refs(s.NEW_MODULE)is None and s.module_refs(s.OLD_MODULE)is not None and {p.name for p in s.DTROOT.iterdir()}=={'gesture_cnn_i8','gesture_touch_usb_phy'}
  deadline=time.monotonic()+10
  while not s.idle_server(cfg['pose_pid']):
   assert time.monotonic()<deadline,'Old Pose not accept-idle';time.sleep(.1)
  assert s.leases()and all(x['pid']==cfg['pose_pid']for x in s.leases())
  unchanged();s.command('systemctl','stop',s.POSE);r['pose_stopped']=True;save();assert not s.leases();s.detach(s.OLD_MODULE);detached=True;r['old_detached']=True;save()
  assert not firmware.exists();firmware.write_bytes(s.bit2bin((H/'candidate.bit').read_bytes()));r['candidate_load_attempted']=True;save();s.download_bin(firmware,before['clock']);changed=True;r['candidate_load_completed']=True;save()
  r['candidate_info']=s.attach(module,overlay);r['int8_info']=s.info(True);r['prelu_info']=s.info(prelu=True)
  unchanged();r.update(status='HARDWARE_READY_AWAIT_COORDINATOR_KEY',qualified_bit_sha256=s.sha(H/'candidate.bit'),touch_preserved=True);save()
 except BaseException as exc:r.update(status='ACTIVATION_FAILED_HOLD_AWAIT_STOP',activation_error=type(exc).__name__+': '+str(exc));save()
 control=socket.socket(socket.AF_UNIX);control.bind(str(H/'control.sock'));os.chmod(H/'control.sock',0o600);control.listen(4);control.settimeout(.25)
 while not stop_requested:
  if worker is not None and worker.poll()is not None and r['status']=='LIVE_WORKER_STARTED':r.update(status='WORKER_EXITED_HARDWARE_HELD_AWAIT_STOP',worker_returncode=worker.returncode);save()
  try:conn,_=control.accept()
  except socket.timeout:continue
  with conn:
   try:
    pid,uid,gid=struct.unpack('3i',conn.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12));assert uid==0;conn.settimeout(3);data=b''
    while b'\n'not in data:
     part=conn.recv(4096-len(data));assert part and len(data)<4096;data+=part
    request=json.loads(data.split(b'\n',1)[0]);op=request['operation']
    if op=='start':
     assert r['status']=='HARDWARE_READY_AWAIT_COORDINATOR_KEY'and worker is None
     session=request['session_id'];assert re.fullmatch(r'[A-Za-z0-9_-]{8,64}',session);key=bytes.fromhex(request.pop('_key_hex'));assert len(key)==32
     cfg['session_id']=session;s.dump(H/'window_config.json',cfg);out=(H/'worker_stdout.log').open('x');err=(H/'worker_stderr.log').open('x');worker=subprocess.Popen([PY,'-B',str(H/'q_rpc_worker.py'),'--execute'],stdin=subprocess.PIPE,stdout=out,stderr=err,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',XILINX_XRT='/usr'));worker.stdin.write(key);worker.stdin.close();del key;r.update(status='LIVE_WORKER_STARTED',session_id=session,worker=identity(worker.pid));save();reply=dict(status='LIVE_WORKER_STARTED',worker_pid=worker.pid)
    elif op=='stop':stop_requested=True;r['status']='EXPLICIT_STOP_REQUESTED';save();reply=dict(status='STOP_REQUEST_ACCEPTED')
    elif op=='status':reply=r
    else:raise ValueError('Unknown lifecycle operation')
    conn.sendall((json.dumps(reply)+'\n').encode())
   except BaseException as exc:
    try:conn.sendall((json.dumps(dict(error=type(exc).__name__+': '+str(exc)))+'\n').encode())
    except OSError as send_error:
     r['control_reply_lost']=r.get('control_reply_lost',0)+1;r['control_reply_lost_errno']=send_error.errno;save()
 control.close();(H/'control.sock').unlink()
 try:
  if worker is not None and worker.poll()is None:
   assert alive(r['worker']);os.kill(worker.pid,signal.SIGTERM)
   try:worker.wait(timeout=35)
   except subprocess.TimeoutExpired:raise RuntimeError('Owned worker retained; no forced kill/detach/restore')
  if out:out.close()
  if err:err.close()
  unchanged()
  if r.get('candidate_load_attempted')and not changed:raise RuntimeError('Unknown download state; preserve')
  if s.module_refs(s.NEW_MODULE)is not None:s.detach(s.NEW_MODULE,int8=True,known_no_run=worker is None)
  elif s.CNN_DT.exists()and detached:raise RuntimeError('Unknown partial candidate DT state')
  if changed:
   assert not s.leases()and s.module_refs(s.NEW_MODULE)is None and s.module_refs(s.OLD_MODULE)is None;s.download_bin(s.ORIGINAL_BIN,before['clock'])
  if detached and s.module_refs(s.OLD_MODULE)is None:r['restored_info']=s.attach(s.BASE/'hardware/gesture_pl_i8_driver.ko')
  if r.get('pose_stopped'):r['pose_restore']=s.restore_pose()
  unchanged();s.check_original_assets();r.update(status='EXPLICIT_STOP_ORIGINALS_RESTORED',original_service_restored=True)
  if firmware.exists():firmware.unlink()
 except BaseException as exc:r.update(status='BLOCKED_UNHEALTHY_NO_FORCE',restore_error=type(exc).__name__+': '+str(exc))
 save();os.close(lock)
if __name__=='__main__':main()
