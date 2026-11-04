"""Explicit realtime Q prepare/launch/status/stop. Importing never connects."""
from pathlib import Path
import argparse,ast,hashlib,importlib.util,json,os,re,sys,tarfile,uuid
import paramiko
H=Path(__file__).resolve().parent;P=next(p.parent for p in H.parents if p.name=='output');OLD=H.parent/'qiming_hand_tcn_joint_20261030'
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def dump(name,value):(H/name).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
def helpers():
 support=H.parent/'host_support';ready=json.loads((H/'q_host_ready.json').read_text(encoding='utf-8'))
 for name,digest in ready['host_helper_files'].items():
  if hashlib.sha256((support/name).read_bytes()).hexdigest()!=digest:raise RuntimeError('Hybrid host helper SHA differs: '+name)
 spec=importlib.util.spec_from_file_location('_hybrid_q_root',support/'qiming_root.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 spec=importlib.util.spec_from_file_location('_hybrid_boardctl',support/'boardctl.py');board=importlib.util.module_from_spec(spec);spec.loader.exec_module(board)
 return module.connect,module.execute,board

last_owned_active=None
last_prepare_outcome={'status':'NOT_STARTED','controller_dispatch_requested':False}
def _latch_owned(active):
 global last_owned_active,last_prepare_outcome
 if type(active)is not dict or active.get('controller_identity_verified')is not True:raise RuntimeError('Controller identity not actually verified')
 ident=active.get('controller_identity');window=active.get('window_id');root=active.get('root')
 if not isinstance(window,str)or not re.fullmatch('qlive_'+'[0-9a-f]{16}',window)or root!='/root/'+window:raise RuntimeError('Private controller window identity differs')
 if type(active.get('pid'))is not int or active['pid']<2 or type(active.get('start_ticks'))is not int or active['start_ticks']<=0:raise RuntimeError('Invalid current controller PID/start')
 if not isinstance(active.get('boot_id'),str)or not re.fullmatch('[0-9a-f-]{36}',active['boot_id']):raise RuntimeError('Actual controller boot identity required')
 if type(ident)is not dict or any(ident.get(k)!=active[k]for k in('pid','start_ticks')):raise RuntimeError('Controller owner envelope differs')
 argv=ident.get('argv')
 if not isinstance(argv,list)or len(argv)!=4 or argv[1:]!=['-B',root+'/'+'q_rpc_controller.py','--execute']or not argv[0].startswith('/'):raise RuntimeError('Verified controller argv differs')
 if any(not isinstance(ident.get(k),str)or not ident[k].startswith('/')for k in('cwd','exe')):raise RuntimeError('Verified controller cwd/exe required')
 last_owned_active=json.loads(json.dumps(active));last_prepare_outcome.update(status='PREPARE_IDENTITY_VERIFIED',owned=True,boot_id=active['boot_id'],window_id=window)
 return active

def prepare(*,source_scope='live_pc_ram',fixture_kind='hand'):
 global last_owned_active,last_prepare_outcome
 last_owned_active=None;last_prepare_outcome={'status':'PREPARE_STARTED','controller_dispatch_requested':False,'owned':False}
 try:
  active=_prepare_owned_impl(source_scope=source_scope,fixture_kind=fixture_kind)
  if last_owned_active is None:_latch_owned(active)
  last_prepare_outcome.update(status='PREPARE_COMPLETE',owned=True)
  return active
 except BaseException as exc:
  last_prepare_outcome.update(status='PREPARE_PARTIAL_OWNERSHIP_KNOWN'if last_owned_active is not None else'PREPARE_PARTIAL_OWNERSHIP_UNKNOWN'if last_prepare_outcome.get('controller_dispatch_requested')else'PREPARE_FAILED_BEFORE_CONTROLLER_DISPATCH',owned=last_owned_active is not None,error_type=type(exc).__name__)
  raise

def _prepare_owned_impl(*,source_scope='live_pc_ram',fixture_kind='hand')->dict:
 if source_scope not in ('live_pc_ram','fixed_fixture','live_nav_ram'):raise ValueError('Explicit live or fixed-fixture scope required')
 if fixture_kind not in ('hand', 'same_frame_hand', 'same_frame_perception', 'same_frame_perception_tcn', 'same_frame_perception_heads', 'person_raw', 'person_hand_parallel', 'person_hand_parallel_pinned', 'resident_chain', 'resident_halfadd', 'resident_lut', 'resident_workspace', 'resident_workspace_fastadd', 'dw_alignment', 'movenet_split', 'movenet_quant', 'full_hand', 'full_hand_clock', 'full_hand_tcn', 'full_palm', 'full_palm_clock', 'full_palm_ps_compare', 'full_body_channels', 'full_body_cache_compare', 'full_body_integer_compare', 'full_body_halfadd_compare', 'full_hand_cache_compare', 'full_palm_cache_compare', 'full_palm_fused_compare', 'full_palm_add32_compare', 'full_palm_lut_compare', 'full_palm_burst_compare') or (source_scope not in ('fixed_fixture','live_nav_ram') and fixture_kind!='hand') or (source_scope=='live_nav_ram' and fixture_kind not in ('same_frame_hand','same_frame_perception','same_frame_perception_tcn','same_frame_perception_heads')):raise ValueError('Unknown fixed fixture')
 if(H/'active.json').exists():
  active=json.loads((H/'active.json').read_text(encoding='utf-8'));current=status(active)
  if current['alive']:
   if active.get('source_scope','live_pc_ram')!=source_scope:raise RuntimeError('Active Q session has a different input scope')
   if active.get('fixture_kind','hand')!=fixture_kind:raise RuntimeError('Active Q session has a different fixed fixture')
   return active
  if not current.get('restored'):
   receipt=current.get('receipt')or{}
   previous_boot_completed=(current.get('boot_id')!=active['boot_id'] and receipt.get('boot_id')==active['boot_id'] and receipt.get('window_id')==active['window_id'] and receipt.get('original_service_restored')is True and not receipt.get('restore_error'))
   if not previous_boot_completed:raise RuntimeError('Previous Q lifecycle is not restored; preserve it before another session')
   dump(active['window_id']+'_completed_before_reboot.json',dict(previous_boot_id=active['boot_id'],current_boot_id=current['boot_id'],receipt=receipt,new_boot_requires_fresh_admission=True))
  (H/'active.json').replace(H/(active['window_id']+'_completed_active.json'))
 ready=json.loads((H/'q_host_ready.json').read_text(encoding='utf-8'));bound=dict(ready['files'])
 if fixture_kind=='same_frame_perception_heads':
  admission=json.loads(Path(bound['person_raw/shared_admission.json']['path']).read_text(encoding='utf-8'))
  fixtures=('full_palm/fixture.npz','full_hand/full_hand_fixture.npz','tcn508a/seven_words.npz')if admission['status']=='Q_SHARED_REVALIDATION_REQUIRED'else()
  bound={name:row for name,row in bound.items()if('/'not in name and not name.endswith('.npz'))or name.split('/')[0]in('wiring','person_raw','shared_workspace')or name in fixtures}
  for name in fixtures:assert name in bound and Path(bound[name]['path']).is_file(),name
 files={name:Path(row['path'])for name,row in bound.items()}
 for name,p in files.items():
  if sha(p)!=bound[name]['sha256']:raise RuntimeError('Local bound Q package differs: '+name)
 if sha(H/'q_host.py')!=ready['host_sha256']:raise RuntimeError('Q host differs from checked ready revision')
 connect,execute,board=helpers()
 window='qlive_'+uuid.uuid4().hex[:16]
 c=connect('qiming')
 try:
  state=(H/'window_state.py').read_text(encoding='utf-8')
  codec=(H/'metadata_codec.py').read_text(encoding='utf-8')
  code=state+"\nos.environ.update(XILINX_XRT='/usr',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')\n"+codec+"\nfrom pynq import PL\nassert os.geteuid()==0\nassert module_refs(NEW_MODULE)is None and module_refs('gesture_pl_i8_driver_v16')is None and module_refs('gesture_pl_i8_driver_v17')is None\npid=mainpid(POSE)\nassert pid>1 and idle_server(pid)\na=check_original_assets();ls=leases();assert ls and all(x['pid']==pid for x in ls)\nassert {p.name for p in DTROOT.iterdir()}=={'gesture_cnn_i8','gesture_touch_usb_phy'}\nprint(json.dumps(dict(boot_id=boot(),pose_pid=pid,pose_process=process(pid),clocks=clocks(),touch=touch_snapshot(),metadata=snapshot_pl_metadata(PL),original_assets=a,leases=ls,admission_monotonic_ns=time.monotonic_ns())))"
  current=json.loads(execute(c,code,None,timeout=120));dump(window+'_q_fresh_admission.json',current)
  cfg=dict(boot_id=current['boot_id'],pose_pid=current['pose_pid'],pose_process=current['pose_process'],session_id=None,window_id=window,clocks=current['clocks'],touch=current['touch'],metadata=current['metadata'],admission_monotonic_ns=current['admission_monotonic_ns'],source_scope=source_scope,fixture_kind=fixture_kind,realtime_authorized=True,authorization_evidence='User authorized deployment and finite recoverable tests on 2026-11-01; fixed fixtures while user is away from camera')
  cfgfile=H/(window+'_config.json');cfgfile.write_text(json.dumps(cfg,indent=2),encoding='utf-8');files['window_config.json']=cfgfile
  lite_files={}
  hashes={name:sha(p)for name,p in files.items()};upload='/home/xilinx/'+window+'_stage';remote='/root/'+window;sf=c.open_sftp()
  try:
   sf.mkdir(upload,0o700)
   for name,p in files.items():
    currentdir=upload;parent=Path(name).parent.as_posix()
    if parent!='.':
     for part in parent.split('/'):
      currentdir+='/'+part
      try:sf.mkdir(currentdir,0o700)
      except OSError:pass
    sf.put(str(p),upload+'/'+name)
  finally:sf.close()
  stage=r"""
from pathlib import Path
import json,sys,tarfile,hashlib,os
cfg=json.load(sys.stdin);os.umask(0o077);assert os.geteuid()==0;u=Path(cfg['upload']);root=Path(cfg['root']);assert not root.exists();assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==cfg['boot_id'];root.mkdir(mode=0o700)
for name,digest in cfg['files'].items():
 data=(u/name).read_bytes();assert hashlib.sha256(data).hexdigest()==digest;target=root/name;target.resolve().relative_to(root.resolve());target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data);target.chmod(0o600)
(root/'package_manifest.json').write_text(json.dumps(dict({n:d for n,d in cfg['files'].items()if n!='window_config.json'},**cfg['lite_files']),indent=2));(root/'package_manifest.json').chmod(0o600)
print(json.dumps(dict(staged=True,files=len(cfg['files']),extracted_files=len(cfg['lite_files']))))
"""
  staged=json.loads(execute(c,stage,dict(upload=upload,root=remote,boot_id=cfg['boot_id'],files=hashes,lite_files=lite_files),timeout=90));dump(window+'_staged_actual.json',staged)
  code=r"""
from pathlib import Path
import json,sys,subprocess,os
cfg=json.load(sys.stdin);root=Path(cfg['root']);os.umask(0o077)
with(root/'controller.log').open('x')as log:
 p=subprocess.Popen(['/usr/local/share/pynq-venv/bin/python3','-B',str(root/'q_rpc_controller.py'),'--execute'],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',XILINX_XRT='/usr'))
 fields=Path('/proc',str(p.pid),'stat').read_text().rsplit(')',1)[1].split();out=dict(root=str(root),pid=p.pid,start_ticks=int(fields[19]),boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),session_id=None,window_id=cfg['window_id']);import time
 expected_argv=['/usr/local/share/pynq-venv/bin/python3','-B',str(root/'q_rpc_controller.py'),'--execute'];deadline=time.monotonic()+2;previous=None;verified=None
 while time.monotonic()<deadline:
  if p.poll()is not None:raise RuntimeError('Controller exited before stable identity; ownership unknown')
  try:
   q=Path('/proc',str(p.pid));fields=(q/'stat').read_text().rsplit(')',1)[1].split();argv=[os.fsdecode(x)for x in(q/'cmdline').read_bytes().split(bytes([0]))if x];current=dict(pid=p.pid,start_ticks=int(fields[19]),argv=argv,cwd=os.readlink(str(q/'cwd')),exe=os.readlink(str(q/'exe')))
   if fields[0]!='Z'and argv==expected_argv and current['exe']==os.path.realpath(expected_argv[0]):
    if current==previous:verified=current;break
    previous=current
   else:previous=None
  except(FileNotFoundError,ProcessLookupError):pass
  time.sleep(.02)
 if verified is None:raise RuntimeError('Controller exec identity unproven; no guessed PID')
 out.update(controller_identity=verified,controller_identity_verified=True,pid=verified['pid'],start_ticks=verified['start_ticks'])
 (root/'controller_process.json').write_text(json.dumps(out));print(json.dumps(out))
"""
  last_prepare_outcome.update(controller_dispatch_requested=True,window_id=window,private_root=remote);active=json.loads(execute(c,code,dict(root=remote,window_id=window),timeout=20));active['source_scope']=source_scope;active['fixture_kind']=fixture_kind;_latch_owned(active);dump(window+'_active.json',active);dump('active.json',active);return active
 finally:c.close()
def status(active=None,*,compact=False)->dict:
 if active is None:active=json.loads((H/'active.json').read_text(encoding='utf-8'))
 if not re.fullmatch('/root/qlive_[0-9a-f]{16}',active.get('root','')):raise ValueError('Private Q live window path required')
 connect,execute,_=helpers();c=connect('qiming')
 try:
  code=r"""
from pathlib import Path
import json,sys,os
cfg=json.load(sys.stdin);root=Path(cfg['root']);boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();result={}
for name in('window_receipt.json','rpc_actual.json'):
 p=root/name
 try:result[name]=json.loads(p.read_text())
 except(FileNotFoundError,ValueError):result[name]=None
for name in('controller.log','worker_stderr.log'):
 p=root/name;result[name]=p.read_text(errors='replace')[-3000:]if p.exists()else None
p=Path('/proc',str(cfg['pid']));alive=False
if p.exists():
 try:fields=(p/'stat').read_text().rsplit(')',1)[1].split();actual=dict(pid=cfg['pid'],start_ticks=int(fields[19]),argv=[os.fsdecode(x)for x in(p/'cmdline').read_bytes().split(bytes([0]))if x],cwd=os.readlink(str(p/'cwd')),exe=os.readlink(str(p/'exe')));alive=fields[0]!='Z'and cfg.get('controller_identity_verified')is True and actual==cfg.get('controller_identity')and boot==cfg['boot_id']
 except OSError:pass
receipt=result['window_receipt.json'];worker=result['rpc_actual.json'];state=(receipt or{}).get('status','STARTING')
if not alive and receipt is None:state='PREFLIGHT_FAILED'
if alive and(worker or{}).get('status')=='RPC_READY':state='RPC_READY'
restored=not alive and boot==cfg['boot_id']and(receipt or{}).get('original_service_restored')is True and not(receipt or{}).get('restore_error')
result.update(status=state,alive=alive,controller_identity_verified=alive,restored=restored,restore_error=(receipt or{}).get('restore_error'),receipt=receipt,worker=worker,boot_id=boot,control_socket_ready=(root/'control.sock').exists())
if cfg.get('_compact'):
 result.pop('window_receipt.json',None);result.pop('rpc_actual.json',None)
 result['receipt']={k:(receipt or{}).get(k) for k in ('status','original_service_restored','restore_error','worker_returncode','activation_error','worker')}
print(json.dumps(result))
"""
  result=json.loads(execute(c,code,dict(active,_compact=compact),timeout=20));dump(active['window_id']+'_progress_actual.json',result);return result
 finally:c.close()

def _control(active,request):
 connect,execute,_=helpers();c=connect('qiming')
 try:
  # Use literal line-delimited JSON; session key travels only in SSH stdin and Unix RAM socket.
  code=r"""
import json,socket,sys
p=json.load(sys.stdin);s=socket.socket(socket.AF_UNIX);s.settimeout(45);s.connect(p['root']+'/control.sock');s.sendall((json.dumps(p['request'])+'\n').encode());data=b''
while b'\n'not in data:
 part=s.recv(65536)
 if not part:raise RuntimeError('Lifecycle control closed before response')
 data+=part
s.close();print(data.decode().strip())
"""
  return json.loads(execute(c,code,dict(root=active['root'],request=request),timeout=60))
 finally:c.close()
def launch(key:bytes,session:str,*,source_scope='live_pc_ram',fixture_kind='hand')->dict:
 if not isinstance(key,bytes)or len(key)!=32 or re.fullmatch('[A-Za-z0-9_-]{8,64}',session)is None:raise ValueError('32byte RAM key and publicsession required')
 active=prepare(source_scope=source_scope,fixture_kind=fixture_kind);deadline=__import__('time').monotonic()+120
 while True:
  try:current=status(active)
  except(paramiko.SSHException,TimeoutError,OSError):
   if __import__('time').monotonic()>=deadline:raise
   __import__('time').sleep(.5);continue
  if current['status']=='HARDWARE_READY_AWAIT_COORDINATOR_KEY'and current['control_socket_ready']:break
  if 'FAIL'in current['status']or not current['alive']:raise RuntimeError('Realtime Q activation failed; inspect actual receipt before stop')
  if __import__('time').monotonic()>=deadline:raise TimeoutError('Q activation deadline; no retry/reload')
  __import__('time').sleep(.2)
 reply=_control(active,dict(operation='start',session_id=session,_key_hex=key.hex()))
 if 'error'in reply:raise RuntimeError(reply['error'])
 active=dict(active,session_id=session);dump('active.json',active);return active
def stop(active=None):
 if active is None:active=json.loads((H/'active.json').read_text(encoding='utf-8'))
 return _control(active,dict(operation='stop'))
if __name__=='__main__':print(json.dumps(dict(status='PREPARED_ONLY_NO_BOARD_ACTION',API='prepare()/launch(key32,session)/status(active=None)/stop(active=None)')))
