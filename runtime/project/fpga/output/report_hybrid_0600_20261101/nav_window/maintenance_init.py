#!/usr/bin/python3 -B
"""ABI31 one-shot PID1 template; fresh full-bit provenance required before fused DMA."""
from pathlib import Path
import hashlib,json,os,stat,subprocess,sys,time
ROOT=Path('/opt/gesture-nav-report-hybrid-0600-r1');STATE=Path('/run/gesture-nav-report-hybrid-0600-r1');OLD=Path('/opt/gesture-nav-h49-cold')
KEEP=[]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def journal(state,**values):
 row=dict(state=state,boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),monotonic_ns=time.monotonic_ns(),**values)
 with(STATE/'journal.jsonl').open('a')as f:f.write(json.dumps(row,sort_keys=True)+'\n');f.flush()
 print('NAV_V18_JOURNAL '+json.dumps(row,sort_keys=True),flush=True)
def frozen(path):
 p=Path(path);s=p.lstat();assert stat.S_ISREG(s.st_mode)and not p.is_symlink()and s.st_uid==0 and s.st_nlink==1 and stat.S_IMODE(s.st_mode)==0o600
 return json.loads(p.read_text())
def returned(argv,seconds,pass_fds=(),allow_returned_failure=False):
 stream=(STATE/('child_%02d.log'%len(KEEP))).open('xb')
 p=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,pass_fds=pass_fds);KEEP.append((p,stream))
 end=time.monotonic()+seconds
 while p.poll()is None:
  if time.monotonic()>=end:raise RuntimeError('Retain unfinished helper and every hardware resource; no kill/unload/reset')
  time.sleep(.1)
 stream.close()
 if p.returncode and not allow_returned_failure:raise RuntimeError('Child returned failure; inspect local retained log')
 return p.returncode
def leases():
 rows=[]
 for p in Path('/proc').iterdir():
  if not p.name.isdigit():continue
  try:
   for f in(p/'fd').iterdir():
    try:v=os.readlink(f)
    except FileNotFoundError:continue
    if v.startswith('/dev/gesture'):rows.append([int(p.name),'FD'])
   if '/dev/gesture'in(p/'maps').read_text():rows.append([int(p.name),'VMA'])
  except(FileNotFoundError,ProcessLookupError):pass
 return rows
def main():
 if os.getpid()!=1:print('PLAN_ONLY_NO_MOUNT_NETWORK_MODULE_DEVICE_OR_REBOOT');return
 assert os.geteuid()==0
 for path,kind in(('/proc','proc'),('/sys','sysfs'),('/dev','devtmpfs'),('/run','tmpfs')):
  Path(path).mkdir(exist_ok=True)
  if not os.path.ismount(path):subprocess.run(['/bin/mount','-t',kind,kind,path],check=True)
 STATE.mkdir(mode=0o700,exist_ok=False)
 sys.path.insert(0,str(ROOT))
 from cold_fs import prepare
 prepare()
 from cold_network import ColdNetwork
 oldcfg=json.loads((OLD/'cold_bindings.json').read_text())
 network=ColdNetwork(STATE,oldcfg['network']);KEEP.append(network);network.start()
 journal('PS_MIO_SSH_READY_AWAIT_HOST_PROVENANCE')
 cfg=frozen(ROOT/'candidate_bindings.json')
 assert cfg['root_execution_authorized']is True and cfg['arm_watchdog']is False
 assert Path('/proc/cmdline').read_text().strip()==cfg['bootargs']
 assert Path('/proc/device-tree/amba_pl/keypoint-conv@80000000/compatible').read_bytes()==b'gesture,nav-yolo-fused-v31\0'
 assert os.uname().release=='5.4.0-xilinx-v2020.2'
 for name,digest in cfg['payload_files'].items():assert sha(ROOT/name)==digest,name
 assert sha(OLD/'cold_bindings.json')==cfg['old_cold_bindings_sha256']
 handoff=STATE/'host_handoff.json'
 while not handoff.exists():time.sleep(.2)
 proof=frozen(handoff);boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
 from reset_entry import validate
 validate(proof,boot,cfg['candidate_script_sha256'],cfg['prior_boot_id'])
 assert proof['bit_sha256']==cfg['bit_sha256']and proof['FIT_sha256']==cfg['FIT_sha256']and proof['root_complete_trial_reviewed']is True
 from original_python_paths import configure
 configure(oldcfg['original_path_setup_sha256']);sys.path.insert(0,str(ROOT))
 from cold_peripherals_current import start_original,role_identities,frame_header
 originals=json.loads((ROOT/'current_original_bindings.json').read_text())
 original=start_original(network,originals['peripherals'],allow_candidate_iic_recovery=True);journal('ORIGINAL_VIDEO_INPUT_CPU_ROLES_READY_BEFORE_YOLO',camera_header=frame_header(),roles=original['processes'])
 keeper=os.open('/dev/dri/card1',os.O_RDWR|os.O_CLOEXEC|os.O_NONBLOCK|os.O_NOFOLLOW);KEEP.append(keeper)
 (STATE/'allow-clock').write_text(boot+'\n');os.chmod(STATE/'allow-clock',0o600)
 capture=STATE/'original_mode.bin';mode=ROOT/'runtime/cold_mode_helper_arm';reader=ROOT/'runtime/cold_shadow_reader_arm'
 for action in('--capture-shared','--apply-49499-shared'):
  returned([str(mode),action,str(keeper),str(capture)],12,(keeper,))
 # Both same-fd DRM mode and fixed hardware shadow are checked before and after
 # the only Hand invocation; no lastclose or modeset can overlap Hand DMA.
 from clock_observer import ClockObserver
 observer=ClockObserver(keeper,capture);assert observer.matches()
 returned([str(reader),'--read-fixed-shadow'],5)
 (STATE/'allow-clock').unlink()
 journal('HDMI_49499_KEEPER_STABLE_BEFORE_YOLO')
 assert not leases()and not Path('/sys/module/gesture_pl_driver').exists()
 assert not Path('/sys/module/gesture_nav_yolo_fused_v31').exists()
 assert not Path('/sys/module/gesture_nav_yolo_raw_v30').exists()
 # Coherent4MiB pool uses dma_alloc_coherent; actual probe/INFO13 decides current allocation.
 module=ROOT/'driver/gesture_nav_yolo_fused_v31.ko'
 bind_rc=returned(['/sbin/insmod',str(module)],12,allow_returned_failure=True)
 actual_path=STATE/'yolo_actual.json'
 if bind_rc or not Path('/dev/gesture-nav-yolo-fused0').exists():
  rc=1;actual=dict(status='DRIVER_PROBE_OR_POOL_BIND_FAILED_BEFORE_MODEL_START',driver_bind_returncode=bind_rc,actual_NN_PL_RUN=0,hardware_RUN=0,owner_opened=False,owner_closed_healthy=False,PS_NN_MAC=0)
  def diagnostic_read(path):
   try:return Path(path).read_text().strip()
   except OSError:return None
  try:kernel_log=subprocess.check_output(['/bin/dmesg'],stderr=subprocess.STDOUT,timeout=5).decode('utf-8','replace')[-16000:]
  except BaseException as ex:kernel_log='dmesg unavailable:'+type(ex).__name__
  base=Path('/proc/device-tree/amba_pl/keypoint-conv@80000000')
  actual['driver_probe_diagnostics']=dict(kernel_tail=kernel_log,buddyinfo=diagnostic_read('/proc/buddyinfo'),meminfo=diagnostic_read('/proc/meminfo'),modules=diagnostic_read('/proc/modules'),DT={n:(base/n).read_bytes().hex()if(base/n).exists()else None for n in('compatible','reg','reg-names','status','reset-gpios')},platform_devices=[str(p)for p in Path('/sys/bus/platform/devices').glob('*80000000*')],registered_driver=Path('/sys/bus/platform/drivers/gesture-nav-yolo-fused-v31').exists(),child_logs={p.name:p.read_text(errors='replace')[-5000:]for p in STATE.glob('child_*.log')})
  actual['driver_probe_diagnostics']['platform_details']={str(q):dict(modalias=diagnostic_read(q/'modalias'),uevent=diagnostic_read(q/'uevent'),driver_link=str((q/'driver').resolve())if(q/'driver').exists()else None)for q in Path('/sys/bus/platform/devices').glob('*80000000*')}
  actual['driver_probe_diagnostics']['misc_sysfs_dev']=diagnostic_read('/sys/class/misc/gesture-nav-yolo-fused0/dev')
  actual['driver_probe_diagnostics']['proc_misc']=diagnostic_read('/proc/misc')
  actual['driver_probe_diagnostics']['deferred_devices']=diagnostic_read('/sys/kernel/debug/devices_deferred')
  actual['driver_probe_diagnostics']['pagetypeinfo']=(diagnostic_read('/proc/pagetypeinfo')or'')[-12000:]
  journal('DRIVER_PROBE_FAILED_NN_START0',returncode=bind_rc)
 else:
  journal('NAV_YOLO_FUSED31_DRIVER_BOUND',module_sha256=sha(module))
  manifest=json.loads((ROOT/'qualified_manifest.json').read_text())
  fresh=dict(candidate_loaded_by_current_window=True,boot_id=boot,candidate_bit_sha256=cfg['bit_sha256'],candidate_hwh_sha256=manifest['hwh_sha256'],controller_pid=os.getpid(),loaded_monotonic_ns=time.monotonic_ns())
  (STATE/'fresh_context.json').write_text(json.dumps(fresh,indent=2))
  rc=returned(['/usr/bin/python3','-B',str(ROOT/'measure_person_fused.py'),'--execute','--lib',str(ROOT/'native/libperson192_navfused.so'),'--expected-boot',boot,'--qualified-manifest',str(ROOT/'qualified_manifest.json'),'--fresh-context',str(STATE/'fresh_context.json'),'--output',str(STATE/'yolo_actual.json'),'--cpu','1','--nice','-15','--startup-lock-libraries','--drm-fd',str(keeper)],864000,(keeper,),allow_returned_failure=True)
  actual=json.loads(actual_path.read_text())if actual_path.exists()else dict(status='CHILD_RETURNED_BEFORE_RESULT',returncode=rc,hardware_RUN=None,PL_RUN_count_known=False,child_logs={p.name:p.read_text(errors='replace')[-8192:]for p in STATE.glob('child_*.log')},startup_error_evidence_retained=True)
 if not actual_path.exists():actual_path.write_text(json.dumps(actual,indent=2))
 passed=rc==0 and actual.get('status') in('PASS','NAV_YOLO79_FULL_PL_INTEGER_EXACT_PASS','NAV_YOLO79_LIVE_INTEGER_SCOPE_COMPLETE')and actual.get('actual_NN_PL_RUN',0)>=0 and actual.get('owner_closed_healthy')is True
 # A returned child plus allFD/VMA0 and this SHA-pinned driver's refcnt0 is a
 # known-idle release proof: every kernel submit is synchronous and any timeout
 # pins the module globally. Never infer it from FD absence alone.
 refs=Path('/sys/module/gesture_nav_yolo_fused_v31/refcnt');module_was_loaded=refs.exists()
 assert not leases()and (not refs.exists()or refs.read_text().strip()=='0')
 assert observer.matches()
 if refs.exists():returned(['/sbin/rmmod','gesture_nav_yolo_fused_v31'],10)
 assert not Path('/sys/module/gesture_nav_yolo_fused_v31').exists()and not leases()
 (STATE/'allow-clock').write_text(boot+'\n');os.chmod(STATE/'allow-clock',0o600)
 returned([str(reader),'--read-fixed-shadow'],5);(STATE/'allow-clock').unlink()
 assert observer.matches()
 receipt=dict(status='NAV_V18_YOLO79_EXACT_KNOWN_IDLE_READY_FOR_EXPLICIT_RESTORE'if passed else'NAV_V18_QUIET_RETURNED_FAILURE_KNOWN_IDLE_READY_FOR_EXPLICIT_RESTORE',boot_id=boot,bit_sha256=cfg['bit_sha256'],numeric_pass=passed,child_returncode=rc,
  admission_stopped=True,all_submitted_ioctls_returned=True,healthy_known_idle=True,FD_VMA_closed=True,driver_normally_unloaded=module_was_loaded,
  refcnt_zero_before_unload=True if module_was_loaded else None,module_absent=True,quarantined=False,actual_hardware_RUN=actual.get('actual_NN_PL_RUN'),
  no_neural_START_because_model_never_called=bool(bind_rc or actual.get('status')=='DRIVER_PROBE_OR_POOL_BIND_FAILED_BEFORE_MODEL_START'),driver_module_was_loaded=module_was_loaded,
  same_HDMImode_before_after=True,original_camera_advanced=frame_header()[2]!=original['camera_header'][2],
  actual_result_sha256=sha(STATE/'yolo_actual.json'),HDMI_latency_included=False)
 (STATE/'known_idle_stop.json').write_text(json.dumps(receipt,indent=2));os.chmod(STATE/'known_idle_stop.json',0o600)
 journal('YOLO79_EXACT_KNOWN_IDLE_AWAIT_EXPLICIT_RESTORE'if passed else'QUIET_FAILURE_KNOWN_IDLE_AWAIT_EXPLICIT_RESTORE',receipt=receipt)
 # PID1 retains the DRM file. Host's separate restore action checks the exact
 # receipt and observed full-bit boot; reboot return0 alone is never success.
 while True:time.sleep(1)
if __name__=='__main__':
 try:main()
 except BaseException as exc:
  if os.getpid()!=1:raise
  try:journal('PRESERVED_HOLD_FAILURE',error_type=type(exc).__name__,error=str(exc)[:256],automatic_reset=False)
  except BaseException:pass
  while True:time.sleep(1)
