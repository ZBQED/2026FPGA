"""Exact local USB ownership handoff for one private Qt evdevmouse source.
No input grab, generated events, source file changes, or Goodix use.
"""
from pathlib import Path
import errno,json,os,socket,stat,struct,subprocess,time
from evdev_source import EvdevSource,discover
ROOT=Path('/opt/nav-usb-touch-local')
RUN=Path('/run/nav-usb-touch-local')
SOCKET=Path('/run/medcomm-touch/patient.sock')
COMMAND=['/usr/bin/python3','-B',str(ROOT/'nav_usb_touch_local.py'),'--execute']
PINS={'nav_usb_touch_local.py': '4aff858a726c32f44a70fde14f6248c68c8aca0d24c9639ca35f23ec668ca995', 'evdev_source.py': '92966beddc12916426aca32583e625b733eb32985efc47a766c2f7b836680eff', 'service.py': 'b224bb88d6a6bc58caccd012272a4aaaf413851c456a70e4cfe8febe3b539021', 'nav-usb-touch-local': '4f0d9d0807168e56a2276122f93fa4eb9bc62c173b16f0d3d6194adc2e7db7f2'}

class DirectTouch:
 def __init__(self,g):
  self.g=g;self.suspended=False;self.device=None
  self.receipt=dict(mode='Qt_evdevmouse_direct_unique_USB_Mouse',synthetic_clicks=0,input_grab=False,Goodix_used=False,original_source_files_changed=False,local_service_was_alive=None,local_service_suspended=False,local_service_restored=False)
 def check_sources(self):
  manifest=json.loads((ROOT/'manifest.json').read_text())
  for name,digest in PINS.items():
   assert self.g.sha(ROOT/name)==digest and manifest['files'][name]['sha256']==digest,'Local touch service source differs: '+name
  assert self.g.sha('/etc/init.d/nav-usb-touch-local')==PINS['nav-usb-touch-local'],'Local touch init differs'
 def snapshot(self):
  self.check_sources()
  try:saved=json.loads((RUN/'owner.json').read_text())
  except FileNotFoundError:saved=None
  found=[]
  for proc in Path('/proc').iterdir():
   if not proc.name.isdigit():continue
   row=self.g.identity(int(proc.name))
   if row and row['argv']==COMMAND:found.append(row)
  assert len(found)<=1,'Duplicate exact local touch daemons'
  actual=self.g.identity(saved['pid'])if saved else None
  alive=self.g.same_record(saved,actual)
  if alive:
   assert actual['argv']==COMMAND and actual['exe']=='/usr/bin/python3.7' and actual['cwd']==str(ROOT) and actual['state']not in('T','t'),'Unexpected local touch owner'
   assert len(found)==1 and self.g.same_record(actual,found[0])
  else:assert not found,'Exact local touch process lacks matching owner receipt'
  self.owner=saved;self.was_alive=bool(alive)
  self.receipt.update(local_service_was_alive=self.was_alive,local_owner_before=actual if alive else saved)
  probe=self.probe_up()
  holders=self.input_holders(self.device)
  assert all(row['pid']==actual['pid']for row in holders)if alive else not holders,'Unexpected USB reader before handoff'
  self.receipt.update(device_preflight=probe,USB_holders_before=holders,preflight_monotonic_ns=time.monotonic_ns())
 def probe_up(self):
  path=discover();assert path,'Unique verified USB Mouse absent'
  source=EvdevSource(path)
  try:
   assert not source.initial_down and source.is_up(),'Real USB touch is held; release before start, no generated release'
   row=dict(device=path,identity=source.identity,ranges=source.ranges,real_all_up=True,observed_monotonic_ns=time.monotonic_ns())
  finally:source.close()
  if self.device is not None:assert self.device==path,'USB device changed during exact handoff'
  self.device=path
  return row
 def input_holders(self,path):
  expected=os.stat(path);assert stat.S_ISCHR(expected.st_mode)
  found=[]
  for proc in Path('/proc').iterdir():
   if not proc.name.isdigit():continue
   try:
    for fd in(proc/'fd').iterdir():
     try:
      actual=os.stat(str(fd))
      if stat.S_ISCHR(actual.st_mode)and actual.st_rdev==expected.st_rdev:found.append(dict(pid=int(proc.name),fd=int(fd.name),target=os.readlink(str(fd))))
     except OSError as exc:
      if exc.errno not in(errno.ENOENT,errno.ESRCH,errno.EBADF):raise
   except OSError as exc:
    if exc.errno not in(errno.ENOENT,errno.ESRCH):raise
  return found
 def service(self,action):
  self.check_sources()
  result=subprocess.run(['/usr/bin/python3','-B',str(ROOT/'service.py'),action],cwd=str(ROOT),env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=14,check=False)
  assert result.returncode==0,'Local service '+action+' failed: '+result.stderr.decode('utf-8','replace')[-1000:]
  return json.loads(result.stdout.decode('utf-8'))
 def suspend(self):
  assert self.receipt['local_service_was_alive']is not None and not self.suspended
  # Mark before normal stop, so a later assertion still retains resume duty.
  self.suspended=True;self.receipt['local_service_suspended']=True
  if self.was_alive:
   assert self.g.same(self.owner),'Local daemon identity changed before normal stop'
   stopped=self.service('stop');self.receipt['local_service_stop_actual']=stopped
   assert not stopped['alive']and not self.g.same(self.owner),'Original local touch owner still alive'
   report=stopped['status'];assert report and self.g.same_record(report['owner'],self.owner)and report['status']=='STOPPED_CANCELLED'and report['input_open']is False,'Missing real local daemon close receipt'
  assert not self.input_holders(self.device),'USB reader remains after local daemon stop'
  self.receipt.update(local_owner_closed=True,local_owner_FDs_and_sockets_closed=True,device_after_suspend=self.probe_up())
 def private_ui(self,env,args):
  assert self.suspended and not self.input_holders(self.device)
  self.receipt['device_immediately_before_Qt']=self.probe_up()
  # The inherited original patient argv must not already contain another plugin.
  assert not any(a=='-plugin'or a.startswith('-plugin=')for a in args),'Unexpected original input plugin argv'
  clean=dict(env)
  for key in('QT_QPA_EVDEV_MOUSE_PARAMETERS','QT_QPA_EVDEV_TOUCHSCREEN_PARAMETERS','QT_QPA_GENERIC_PLUGINS'):clean.pop(key,None)
  clean.update(MEDCOMM_TOUCH_SOCKET='',QT_QPA_FB_DISABLE_INPUT='1')
  plugin='evdevmouse:'+self.device+':abs:nocompress'
  self.receipt.update(private_Qt_plugin=plugin,MEDCOMM_TOUCH_SOCKET='',QT_QPA_FB_DISABLE_INPUT='1',private_Qt_input_variables_cleared=True)
  return clean,list(args)+['-plugin',plugin]
 def verify_private(self,record,log_path=None):
  assert self.g.same(record),'Private UI identity changed'
  assert discover()==self.device,'USB identity/unique Mouse interface changed'
  holders=self.input_holders(self.device)
  assert len(holders)==1 and holders[0]['pid']==record['pid'],'Qt must be sole open verified USB reader'
  inputs=[]
  for fd in Path('/proc',str(record['pid']),'fd').iterdir():
   try:
    target=os.readlink(str(fd))
    if target.startswith('/dev/input/'):inputs.append(target)
   except FileNotFoundError:pass
  assert inputs==[self.device],'Private UI opened another input source/Goodix'
  env=dict(x.decode().split('=',1)for x in Path('/proc',str(record['pid']),'environ').read_bytes().split(b'\0')if b'='in x)
  assert env.get('MEDCOMM_TOUCH_SOCKET')==''and env.get('QT_QPA_FB_DISABLE_INPUT')=='1'
  assert all(key not in env for key in('QT_QPA_EVDEV_MOUSE_PARAMETERS','QT_QPA_EVDEV_TOUCHSCREEN_PARAMETERS','QT_QPA_GENERIC_PLUGINS'))
  assert record['argv'][-2:]==['-plugin',self.receipt['private_Qt_plugin']]and record['argv'].count('-plugin')==1
  if log_path:
   text=Path(log_path).read_text(errors='replace')[-16000:]
   bad=('No such plugin for spec','Failed to create input handler','Cannot open input device','Could not load the Qt platform plugin')
   assert not any(token in text for token in bad),'Qt input/plugin failure in private log'
  self.receipt.update(private_UI_USB_FDs=holders,private_UI_other_input_FDs=[],private_UI_input_verified_monotonic_ns=time.monotonic_ns(),single_direct_source_verified=True)
  return holders
 def original_socket(self,patient):
  assert self.g.same(patient),'Restored patient identity changed'
  directory=SOCKET.parent.lstat();info=SOCKET.lstat();mode=stat.S_IMODE(info.st_mode)
  assert stat.S_ISDIR(directory.st_mode)and directory.st_uid==0 and not directory.st_mode&0o077,'Touch directory is not root private'
  assert stat.S_ISSOCK(info.st_mode)and info.st_uid==0 and not(mode&0o077)and(mode&0o600)==0o600,'Touch socket permissions not root private rw'
  # Qt UserAccessOption binds under a private temporary name and exposes the
  # public socket through the filesystem. Verify the real peer and LISTEN inode.
  with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)as probe:
   probe.settimeout(1.);probe.connect(str(SOCKET));pid,uid,gid=struct.unpack('3i',probe.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
   assert pid==patient['pid']and uid==0,'Public socket is not served by exact restored root patient'
  assert self.g.same(patient),'Restored patient changed during socket probe'
  after=SOCKET.lstat();assert (info.st_dev,info.st_ino)==(after.st_dev,after.st_ino),'Public socket changed during probe'
  fds={}
  for fd in Path('/proc',str(patient['pid']),'fd').iterdir():
   try:fds[int(fd.name)]=os.readlink(str(fd))
   except FileNotFoundError:pass
  rows=[v.split()for v in Path('/proc/net/unix').read_text().splitlines()[1:]];listeners=[]
  for row in rows:
   if len(row)>=7 and int(row[3],16)&0x10000 and row[4]=='0001'and row[5]=='01':
    owned=[fd for fd,target in fds.items()if target=='socket:['+row[6]+']']
    if owned:listeners.append(dict(inode=int(row[6]),listening_FDs=owned,kernel_path=row[7]if len(row)>7 else None))
  assert len(listeners)==1,'Restored patient must own exactly one Unix stream listener'
  return dict(patient=patient,path=str(SOCKET),socket_mode=oct(mode),peer_pid=pid,peer_uid=uid,probe_payload_bytes=0,listener=listeners[0],verified_monotonic_ns=time.monotonic_ns())
 def restore_after_original(self,patient):
  if not self.suspended:return
  if Path(self.device).exists():assert not self.input_holders(self.device),'Private direct Qt input still open; never overlap sources'
  deadline=time.monotonic()+8.;last=None
  while True:
   try:self.receipt['restored_original_socket']=self.original_socket(patient);break
   except(AssertionError,OSError)as exc:
    last=type(exc).__name__+': '+str(exc)
    if time.monotonic()>=deadline:raise RuntimeError('Original socket not ready: '+last)
    time.sleep(.1)
  if self.was_alive:
   row=self.service('start');self.receipt['local_service_restore_actual']=row
   assert row['alive']and self.g.same(row['owner'])and row['owner']['argv']==COMMAND,'Local touch daemon did not regain exact ownership'
   self.receipt['local_service_restored']=True
  else:self.receipt['local_service_restore_skipped_originally_not_alive']=True
  self.receipt['handoff_restored_monotonic_ns']=time.monotonic_ns()
