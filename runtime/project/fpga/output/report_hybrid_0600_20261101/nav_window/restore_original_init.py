#!/usr/bin/python3 -B
"""Private original9ebc restore, bound to the actual pre-v18 TIM9 originals."""
from pathlib import Path
import hashlib,json,os,stat,subprocess,sys,time
ROOT=Path('/opt/gesture-nav-report-hybrid-0600-r1');STATE=Path('/run/gesture-nav-report-hybrid-0600-r1-restore');OLD=Path('/opt/gesture-nav-h49-cold');KEEP=[]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def journal(status,**values):
 row=dict(status=status,boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),**values)
 with(STATE/'journal.jsonl').open('a')as f:f.write(json.dumps(row,sort_keys=True)+'\n');f.flush()
 print('NAV_H49_RESTORE '+json.dumps(row,sort_keys=True),flush=True)
def restore_exact_light_argv(network,original):
 from cold_peripherals_current import role_identities,frame_header
 import signal
 target='/opt/medcomm/qt_dual_display/camera_light_key.py'
 expected=[json.loads(v)for v in original['peripherals']['expected_original_role_commands']if target in json.loads(v)]
 assert len(expected)==1 and expected[0]in(['python3',target],['/usr/bin/python3','-B',target])
 found=[(pid,row)for pid,row in role_identities().items()if target in row['command']];assert len(found)==1
 pid,row=found[0]
 if row['command']!=expected[0]:
  assert row['command']==['/usr/bin/python3','-B',target] and expected[0]==['python3',target] and row['cwd']=='/' and row['exe']=='/usr/bin/python3.7'
  current=Path('/proc',pid,'stat').read_text();assert current[current.rfind(')')+2:].split()[19]==row['ticks']
  os.kill(int(pid),signal.SIGTERM);end=time.monotonic()+8
  while any(target in v['command']for v in role_identities().values()):
   assert time.monotonic()<end,'Lamp did not exit gracefully; no forcedkill/recovery';time.sleep(.1)
  try:os.waitpid(int(pid),os.WNOHANG)
  except ChildProcessError:pass
  logpath=Path('/var/log/medcomm-camera_light_key.log');offset=logpath.stat().st_size if logpath.exists()else 0
  stream=logpath.open('ab');KEEP.append(stream);child=subprocess.Popen(expected[0],cwd='/',stdin=subprocess.DEVNULL,stdout=stream,stderr=stream,close_fds=True);KEEP.append(child)
  Path('/run/medcomm/camera_light_key.pid').write_text(str(child.pid)+'\n');end=time.monotonic()+12;fresh=''
  while time.monotonic()<end:
   assert child.poll()is None,'Exactargv lamp exited'
   with logpath.open('rb')as f:f.seek(offset);fresh=f.read().decode(errors='replace')
   if 'CAMERA_LIGHT_READY 'in fresh:break
   time.sleep(.2)
  assert 'CAMERA_LIGHT_READY 'in fresh and 'Camera combined I2C transfer failed'not in fresh and 'Camera I2C transfer failed'not in fresh
  journal('ORIGINAL_LAMP_EXACT_ARGV_RESTORED_AFTER_PRIVATE_READY',old_pid=int(pid),new_pid=child.pid,argv=expected[0],fresh_ready_log=fresh)
 assert sorted(json.dumps(v['command'])for v in role_identities().values())==original['peripherals']['expected_original_role_commands']
 return frame_header()

def main():
 if os.getpid()!=1:print('PLAN_ONLY_NO_ORIGINAL_STARTUP_OR_REBOOT');return
 assert os.geteuid()==0
 for path,kind in(('/proc','proc'),('/sys','sysfs'),('/dev','devtmpfs'),('/run','tmpfs')):
  Path(path).mkdir(exist_ok=True)
  if not os.path.ismount(path):subprocess.run(['/bin/mount','-t',kind,kind,path],check=True)
 STATE.mkdir(mode=0o700,exist_ok=False)
 sys.path.insert(0,str(ROOT));from cold_fs import prepare
 prepare()
 from cold_network import ColdNetwork
 old=json.loads((OLD/'cold_bindings.json').read_text());network=ColdNetwork(STATE,old['network']);KEEP.append(network);network.start()
 journal('RESTORE_PS_MIO_SSH_READY_AWAIT_EXPLICIT_ORIGINAL_BIT_PROVENANCE')
 cfg=json.loads((ROOT/'candidate_bindings.json').read_text());assert cfg['root_execution_authorized']is True
 assert'gesture_nav_yolo_fused31_restore=1'in Path('/proc/cmdline').read_text()
 assert Path('/proc/device-tree/amba_pl/keypoint-conv@80000000/compatible').read_bytes()==b'gesture,keypoint-conv-f32-v1\0'
 assert not Path('/sys/module/gesture_nav_i8_driver_v18').exists()
 assert not Path('/sys/module/gesture_nav_yolo_fused_v31').exists()
 assert not Path('/sys/module/gesture_nav_yolo_raw_v30').exists()
 for n,d in cfg['payload_files'].items():assert sha(ROOT/n)==d,n
 original=json.loads((ROOT/'current_original_bindings.json').read_text());assert sha(OLD/'cold_bindings.json')==original['old_network_bindings_source_sha256']
 path=STATE/'host_handoff.json'
 while not path.exists():time.sleep(.2)
 s=path.lstat();assert stat.S_ISREG(s.st_mode)and not path.is_symlink()and s.st_uid==0 and stat.S_IMODE(s.st_mode)==0o600 and s.st_nlink==1
 proof=json.loads(path.read_text());boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
 from reset_entry import validate
 validate(proof,boot,cfg['restore_script_sha256'])
 assert proof['original_bit_sha256']=='9ebc8afd90222ed84f8efc55008400bfc409c1efd99c79edeb442f3492be72d5'
 assert proof['original_private_FIT_sha256']==cfg['restore_FIT_sha256']
 from original_python_paths import configure
 configure(original['original_path_setup_sha256']);sys.path.insert(0,str(ROOT))
 from cold_peripherals_current import start_original,frame_header
 roles=start_original(network,original['peripherals']);journal('ORIGINAL_CAMERA_UI_TOUCH_CPU_WORKER_STARTED',camera_header=frame_header(),processes=roles['processes'])
 private_binding=cfg['private_nav_ready'];private_ready=ROOT/private_binding['file']
 assert sha(private_ready)==private_binding['sha256'] and sha(private_binding['original_source_path'])==private_binding['original_source_sha256']
 for name in('attempted.json','result.json','ready'):assert not(Path('/run/gesture-nav-ready')/name).exists(),'New restoreboot has an existing readiness marker; preserve it and refuse replay'
 ready_log=(STATE/'nav_ready_private.log').open('ab');KEEP.append(ready_log)
 ready_child=subprocess.Popen(['/usr/bin/python3','-B',str(private_ready),'--run'],cwd='/',stdin=subprocess.DEVNULL,stdout=ready_log,stderr=ready_log,close_fds=True);KEEP.append(ready_child)
 journal('PRIVATE_FROZEN_CTOR_READY_STARTED',pid=ready_child.pid,private_clone_sha256=private_binding['sha256'],original_source_sha256=private_binding['original_source_sha256'])
 end=time.monotonic()+65;ready=None
 while time.monotonic()<end:
  p=Path('/run/gesture-nav-ready/result.json')
  try:ready=json.loads(p.read_text())
  except(OSError,ValueError):ready=None
  if ready and ready.get('status')=='READY'and ready.get('boot_id')==boot:break
  time.sleep(.3)
 assert ready and ready.get('status')=='READY'and ready.get('boot_id')==boot
 assert ready_child.wait(timeout=10)==0,'Private readiness child failed; no restorationREADY claim'
 restore_exact_light_argv(network,original)
 journal('ORIGINAL_BIT_PRIVATE_FUNCTIONAL_RESTORATION_READY_REQUIRE_ROOT_INDEPENDENT_AUDIT',camera_header=frame_header(),current_original_binding_sha256=sha(ROOT/'current_original_bindings.json'))
 while True:time.sleep(1)
if __name__=='__main__':
 try:main()
 except BaseException as exc:
  if os.getpid()!=1:raise
  try:journal('ORIGINAL_RESTORE_PRESERVED_HOLD_FAILURE',error_type=type(exc).__name__,error=str(exc)[:256])
  except BaseException:pass
  while True:time.sleep(1)
