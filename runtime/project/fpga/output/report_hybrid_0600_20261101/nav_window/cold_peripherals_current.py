"""Exact original camera/UI/touch/CPU-worker starts, before Hand probe only."""
from pathlib import Path
import hashlib,json,os,struct,time
from cold_network import require_file

def role_identities():
 rows={}
 for p in Path('/proc').iterdir():
  if not p.name.isdigit() or int(p.name)==os.getpid():continue
  try:
   argv=(p/'cmdline').read_bytes().rstrip(b'\0').split(b'\0')
   if not any(a.startswith((b'/opt/medcomm/',b'/opt/gesture-touch/',b'/opt/gesture-v4-worker-',b'/opt/gesture-tcn-20261022/app_runner/')) for a in argv):continue
   s=(p/'stat').read_text();f=s[s.rfind(')')+2:].split()
   rows[p.name]=dict(command=[a.decode() for a in argv],ticks=f[19],cwd=os.readlink(str(p/'cwd')),exe=os.readlink(str(p/'exe')))
  except (FileNotFoundError,ProcessLookupError):continue
 return rows
def frame_header():
 p=Path('/run/medcomm/camera.frame');s=p.stat()
 with p.open('rb') as f:v=struct.unpack('<5I',f.read(20))
 if v[0]!=0x4d43414d or tuple(v[2:])!=(800,480,2400) or s.st_size!=64+3*800*480*3:raise RuntimeError('Original shared camera ABI differs')
 return s.st_dev,s.st_ino,v[1]
def start_original(network,bindings,*,allow_candidate_iic_recovery=False):
 if os.getpid()!=1 or bindings.get('root_original_startup_whitelist_reviewed') is not True:raise RuntimeError('Exact original source whitelist review required')
 if Path('/sys/module/gesture_nav_hand_driver').exists():raise RuntimeError('No original startup after Hand probe')
 for name,row in bindings['files'].items():require_file(name,bindings['files'])
 # Do not call rcS/rc5 or gesture-recognition/nav-ready. Original nav-ready
 # loads the old CNN. Background display-ready is also excluded while Hand
 # exists; an optional one-shot must finish before the final 49499 setup.
 display='/opt/gesture-tcn-20261022/deployment/nav_display_restore/restore_display.py'
 if bindings.get('foreground_display_hpd_reviewed') is True:
  require_file(display,bindings['files'])
  network.run_returned(['/usr/bin/python3','-B',display,'--run'],42)
  hpd=json.loads(Path('/run/gesture-display-ready/result.json').read_bytes())
  if hpd.get('status')!='VIDEO_READY_TOUCH_UNVERIFIED' or hpd.get('boot_id')!=Path('/proc/sys/kernel/random/boot_id').read_text().strip() or hpd.get('edid_sha256')!='521b95fe153a71edd7f151b05813c6555c05d2166812b01e45446811b5f0d598' or hpd.get('fb1') is not True:raise RuntimeError('Original foreground HPD did not produce expected fresh framebuffer/EDID')
 for args in [['/etc/init.d/medcomm-ui','start'],['/etc/init.d/gesture-touch','start'],['/etc/init.d/gesture-v4-worker-5764ea3f-navigator','start']]:
  require_file(args[0],bindings['files']);network.run_returned(args,12)
 if allow_candidate_iic_recovery:
  from candidate_camera_recovery import wait_candidate_camera
  previous,advances=wait_candidate_camera(network,frame_header)
 else:
  end=time.monotonic()+20;previous=None;advances=0
  while time.monotonic()<end:
   try:current=frame_header()
   except (OSError,RuntimeError):current=None
   if current and previous and current[:2]==previous[:2] and 0<(current[2]-previous[2])&0xffffffff<0x80000000:advances+=1
   previous=current
   if advances>=3:break
   time.sleep(.5)
  if advances<3:raise RuntimeError('Original shared camera did not advance; no automatic camera restart/reset')
 # Current boot's init script uses python3 without -B for this one CPU role.
 # Restore the exact recorded pre-window argv before the all11 identity gate.
 # This executes only before any Hand module/FD/submission, never during DMA.
 target='/opt/medcomm/qt_dual_display/camera_light_key.py'
 expected=[json.loads(s)for s in bindings['expected_original_role_commands']if target in json.loads(s)]
 assert len(expected)==1 and expected[0]in(['python3',target],['/usr/bin/python3','-B',target])
 rows=[(pid,r)for pid,r in role_identities().items()if target in r['command']]
 assert len(rows)==1
 pid,row=rows[0]
 if row['command']!=expected[0]:
  assert row['command']==['python3',target]and row['cwd']=='/'and row['exe']=='/usr/bin/python3.7'
  assert not any(Path('/sys/module',n).exists()for n in('gesture_nav_i8_driver_v18','gesture_pl_driver','gesture_nav_hand_driver','gesture_nav_yolo_fused_v31','gesture_nav_yolo_raw_v30'))
  assert not Path('/dev/gesture-nav-i8-pl0').exists()
  assert not Path('/dev/gesture-nav-yolo-fused0').exists()
  statline=Path('/proc',pid,'stat').read_text();assert statline[statline.rfind(')')+2:].split()[19]==row['ticks']
  import signal,subprocess
  os.kill(int(pid),signal.SIGTERM)
  until=time.monotonic()+5
  while any(target in r['command']for r in role_identities().values()):
   if time.monotonic()>=until:raise RuntimeError('Exact CPU key/light process did not gracefully exit; no force kill')
   time.sleep(.1)
  try:os.waitpid(int(pid),os.WNOHANG)
  except ChildProcessError:pass
  log=(network.state/'current_camera_light.log').open('xb');network.streams.append(log)
  child=subprocess.Popen(expected[0],cwd='/',stdin=subprocess.PIPE,stdout=log,stderr=log,close_fds=True);network.children.append(child)
 end=time.monotonic()+10
 while True:
  identities=role_identities()
  observed=sorted(json.dumps(r['command']) for r in identities.values())
  if observed==bindings['expected_original_role_commands']:break
  if time.monotonic()>=end:raise RuntimeError('Original11 roles not alive before clock capture; no Hand probe')
  time.sleep(.2)
 if not any(any(a.endswith('/medcomm_camera') for a in r['command']) for r in identities.values()):raise RuntimeError('Original capture owner missing')
 return dict(processes=identities,camera_header=previous,camera_advances=advances,display_stable_with_keeper_proven=False)
