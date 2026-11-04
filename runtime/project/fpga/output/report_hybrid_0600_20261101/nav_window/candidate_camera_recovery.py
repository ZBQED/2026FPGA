"""Candidate-only bounded startup IIC recovery; no restart, sensor, FPGA or clock operations."""
from pathlib import Path
import hashlib,json,os,re,stat,struct,subprocess,time
MODULE=Path('/opt/gesture-tcn-20261022/deployment/camera_recovery_20261023/camera_xiic_recover.ko')
MODULE_SHA='ebcc06f52d23a399ff45dc69f2b7d87320a0c241cc3b71a3bd83eb8212e64c58'
ATTEMPT=Path('/run/gesture-nav-candidate-camera-iic-attempted.json')
def save(path,value):path.write_text(json.dumps(value,indent=2)+'\n')
def ebusy_evidence(text):
 return bool(re.search(r'ov5640[^\n]*ov5640_write_reg: error: addr=0x3103, val=0x11',text)and re.search(r'ret\s*=\s*-16 for entity ov5640',text))
def audit_no_users():
 modules=[q.name for q in Path('/sys/module').iterdir()if q.name.startswith('gesture_')or q.name=='camera_xiic_recover'];users=[];leases=[]
 for p in Path('/proc').iterdir():
  if not p.name.isdigit():continue
  try:
   for q in(p/'fd').iterdir():
    try:target=os.readlink(str(q))
    except(FileNotFoundError,ProcessLookupError):continue
    if target.startswith('/dev/i2c-'):users.append(dict(pid=int(p.name),fd=q.name,target=target))
    if target.startswith('/dev/gesture'):leases.append(dict(pid=int(p.name),fd=q.name,target=target))
   if '/dev/gesture'in(p/'maps').read_text():leases.append(dict(pid=int(p.name),mapping=True))
  except(FileNotFoundError,ProcessLookupError):continue
 return dict(gesture_or_recovery_modules=modules,user_i2c_FDs=users,gesture_FD_VMA=leases)
def assert_quiet(a):
 assert not a['gesture_or_recovery_modules']and not a['user_i2c_FDs']and not a['gesture_FD_VMA'],'I2C user or candidate/recovery module/lease is active; no recovery'
def once(network,*,deadline):
 path=network.state/'camera_iic_recovery_actual.json';report=dict(status='CAMERA_IIC_RECOVERY_STARTED',boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),module=str(MODULE),module_sha256=MODULE_SHA,attempted=False,commands=[],sensor_GPIO_FCLK_FPGA_or_system_reset=False,camera_process_restart=False)
 def command(argv):
  row=dict(argv=argv,started_ns=time.monotonic_ns(),returncode=None);report['commands'].append(row);save(path,report)
  remaining=deadline-time.monotonic();assert remaining>0,'Candidatecamera total60s deadline reached; no further command'
  child=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,close_fds=True);network.children.append(child)
  try:out,err=child.communicate(timeout=min(12,remaining))
  except subprocess.TimeoutExpired:
   row.update(status='UNFINISHED_CHILD_RETAINED_NO_KILL_OR_RETRY',pid=child.pid);save(path,report);raise RuntimeError('Recovery helper unfinished; retain child and hold, no kill/unload/retry')
  row.update(returncode=child.returncode,stdout=out.decode('utf-8','replace'),stderr=err.decode('utf-8','replace'),ended_ns=time.monotonic_ns());save(path,report)
  assert child.returncode==0,'Startup recovery command returned failure; no retry'
  return row['stdout']
 try:
  assert os.getpid()==1 and os.geteuid()==0
  assert MODULE.is_file()and MODULE.stat().st_uid==0 and hashlib.sha256(MODULE.read_bytes()).hexdigest()==MODULE_SHA,'Frozen recovery module mismatch'
  kernel=command(['/bin/dmesg']);report['kernel_before_tail']=kernel[-32768:];assert ebusy_evidence(report['kernel_before_tail']),'No exact current-boot ov5640 EBUSY signature; no recovery'
  report['audit_before']=audit_no_users();assert_quiet(report['audit_before'])
  # O_EXCL marker is consumed before either helper insertion; never delete or overwrite it.
  fd=os.open(str(ATTEMPT),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,'w')as stream:json.dump(dict(boot_id=report['boot_id'],module_sha256=MODULE_SHA,monotonic_ns=time.monotonic_ns()),stream);stream.flush();os.fsync(stream.fileno())
  report['attempted']=True;save(path,report)
  command(['/sbin/insmod',str(MODULE),'recover=0']);command(['/sbin/rmmod','camera_xiic_recover'])
  report['kernel_after_dryrun_tail']=command(['/bin/dmesg'])[-32768:]
  report['audit_before_recover']=audit_no_users();assert_quiet(report['audit_before_recover'])
  command(['/sbin/insmod',str(MODULE),'recover=1']);command(['/sbin/rmmod','camera_xiic_recover'])
  report['kernel_after_recover_tail']=command(['/bin/dmesg'])[-32768:];report['audit_after']=audit_no_users();assert not report['audit_after']['gesture_or_recovery_modules']and not report['audit_after']['gesture_FD_VMA'],'Helper/candidate module or lease remains after recovery'
  report.update(status='CANDIDATE_STARTUP_ONE_GUARDED_IIC_RECOVERY_RETURNED_CONTINUE_ORIGINAL_CAMERA_LOOP',recover0_calls=1,recover1_calls=1,helper_unloaded=True)
  return report
 except BaseException as exc:report.update(status='FAIL_CANDIDATE_STARTUP_IIC_RECOVERY_HOLD',error_type=type(exc).__name__,error=str(exc));raise
 finally:save(path,report)
def wait_candidate_camera(network,frame_header,*,recover_once=once,clock=time.monotonic,sleep=time.sleep):
 path=network.state/'camera_startup_actual.json';start=clock();previous=None;advances=0;recovery=False;report=dict(status='CAMERA_STARTUP_STARTED',samples=[],initial_wait_s=20,total_budget_s=60,recovery_attempted=False,candidate_driver_or_NN_started=False)
 try:
  while clock()-start<60:
   sample=dict(elapsed_s=clock()-start)
   try:current=frame_header();sample['header']=list(current)
   except(OSError,RuntimeError,struct.error)as exc:current=None;sample.update(error_type=type(exc).__name__,error=str(exc))
   if current and previous and current[:2]==previous[:2]and 0<((current[2]-previous[2])&0xffffffff)<0x80000000:advances+=1
   previous=current;sample['advances']=advances;report['samples'].append(sample);save(path,report)
   if advances>=3:
    report.update(status='ORIGINAL_CAMERA_ADVANCED_BEFORE_CANDIDATE_IO',advances=advances,final_header=list(current),recovery_attempted=recovery,elapsed_s=clock()-start);return current,advances
   if clock()-start>=20 and not recovery:
    recovery=True;report['recovery_attempted']=True;save(path,report);recover_once(network,deadline=start+60)
   sleep(.5)
  raise RuntimeError('Original shared camera did not advance after one guarded IIC attempt within60s; no restart/reset/retry')
 except BaseException as exc:report.update(status='FAIL_ORIGINAL_CAMERA_STARTUP_HOLD',error_type=type(exc).__name__,error=str(exc));raise
 finally:report.update(elapsed_s=clock()-start);save(path,report)
