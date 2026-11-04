"""Private unchanged r12 UI for real report inference, sealed same-source image pairs.
No DRM open, generated touch, pixel files, model inference or PL operation in this module.
"""
from pathlib import Path
import collections,ctypes,fcntl,hashlib,json,math,os,signal,stat,struct,subprocess,time
import nav_demo_common as g
from nav_direct_touch import DirectTouch
H=Path(__file__).resolve().parent
PreparedImage=collections.namedtuple('PreparedImage','raw digest hash_ns')

def prepare_image(raw):
 assert type(raw)is bytes and len(raw)==1152000
 start=time.monotonic_ns();digest=hashlib.sha256(raw).hexdigest()
 return PreparedImage(raw,digest,time.monotonic_ns()-start)

def memfd():
 if hasattr(os,'memfd_create'):return os.memfd_create('gesture-report-source',3)
 libc=ctypes.CDLL(None,use_errno=True)
 if hasattr(libc,'memfd_create'):
  f=libc.memfd_create;f.argtypes=(ctypes.c_char_p,ctypes.c_uint);f.restype=ctypes.c_int;fd=f(b'gesture-report-source',3)
 else:
  assert os.uname().machine.startswith('arm') and not os.uname().machine.startswith('aarch64')
  libc.syscall.restype=ctypes.c_long;fd=int(libc.syscall(ctypes.c_long(385),ctypes.c_char_p(b'gesture-report-source'),ctypes.c_uint(3)))
 if fd<0:raise OSError(ctypes.get_errno(),'Anonymous sealed image RAM unavailable')
 return fd

def sealed_image(raw,fid,ordinal,capture,pid,ticks):
 assert type(raw)is bytes and len(raw)==1152000
 fd=memfd();nonce=os.urandom(16)
 try:
  os.fchmod(fd,0o600);header=struct.pack('<8sQQQQ16s8x',b'PCFRM01\0',fid,ordinal,capture,len(raw),nonce)
  for part in (header,raw):
   view=memoryview(part)
   while view:
    n=os.write(fd,view)
    if n<=0:raise OSError('No memfd write progress')
    view=view[n:]
  fcntl.fcntl(fd,1033,15);assert fcntl.fcntl(fd,1034)==15
  return fd,dict(bridge_pid=pid,bridge_start_ticks=str(ticks),fd=fd,nonce=nonce.hex(),body_bytes=len(raw),header_bytes=64,pixel_format='BGR888')
 except BaseException:os.close(fd);raise

def process_rows():return [r for p in Path('/proc').iterdir() if p.name.isdigit() for r in [g.identity(int(p.name))] if r]
def stop_owned(record,timeout=10):
 if not g.same(record):return
 os.kill(record['pid'],signal.SIGTERM);deadline=time.monotonic()+timeout
 while g.same(record) and time.monotonic()<deadline:time.sleep(.03)
 if g.same(record):raise RuntimeError('Owned UI did not close; no forced kill')

def validate_overlay(v):
 def number(x):return type(x)in(int,float) and math.isfinite(x)
 def points(p,m,n):
  assert type(p)is list and type(m)is list and len(p)==len(m)==n
  for xy,ok in zip(p,m):
   assert len(xy)==2 and all(number(z) for z in xy) and type(ok)is bool
   assert not ok or (0<=xy[0]<800 and 0<=xy[1]<480)
 def box(b):assert len(b)==4 and all(number(x) for x in b) and 0<=b[0]<b[2]<=800 and 0<=b[1]<b[3]<=480
 points(v['body_points'],v['body_valid'],17);assert len(v['person_boxes'])<=32 and len(v['hands'])<=2
 assert len(v['person_scores'])==len(v['person_boxes']) and all(number(x) and 0<=x<=1 for x in v['person_scores'])
 for b in v['person_boxes']:box(b)
 for h in v['hands']:
  points(h['points'],h['valid'],21);box(h['box']);assert h.get('side')in('Left','Right',None) and h.get('color_side')in('Left','Right')
  assert number(h['whole_hand_presence']) and 0<=h['whole_hand_presence']<=1
 assert len(v.get('body_aux',[]))<=2
 for a in v.get('body_aux',[]):assert a['name']in('FOREHEAD','CHEST');points([a['point']],[a['valid']],1)

class LiveDisplay:
 def __init__(self,fd,session,observer,touch_mode='usb_direct'):
  self.observer=observer;self.session=session;self.root=Path('/run/gesture-pc-demo-report-'+os.urandom(8).hex());self.ui=None;self.ui_identity=None;self.patient=None;self.supervisor=None;self.paused=False;self.log=None;self.lockfd=None;self.touch=DirectTouch(g);self.fds=collections.deque();self.ordinal=0;self.last_fid=-1;self.last_capture=0;self.closed=False
  if touch_mode=='inherit':
   from inherited_touch import InheritedTouch
   self.touch=InheritedTouch(g)
  else:assert touch_mode=='usb_direct'
 def start(self):
  startup=time.monotonic_ns()
  assert os.geteuid()==0 and self.observer.matches();self.root.mkdir(mode=0o700,exist_ok=False)
  self.lockfd=os.open('/run/gesture-pc-demo-ui.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);s=os.fstat(self.lockfd);assert stat.S_ISREG(s.st_mode) and s.st_uid==0 and s.st_nlink==1;fcntl.flock(self.lockfd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  rows=process_rows();patients=[r for r in rows if r['argv'][0]==g.TARGET and '--patient'in r['argv'] and '--staff'not in r['argv']];supervisors=[r for r in rows if g.SUPERVISOR in r['argv']];assert len(patients)==len(supervisors)==1
  self.patient=patients[0];self.supervisor=supervisors[0];assert self.patient['state']not in('T','t','Z') and self.supervisor['state']not in('T','t','Z');self.original_sha=g.sha('/proc/%d/exe'%self.patient['pid']);assert self.original_sha=='40eb46aaecd020dda2d8b97a98e9e4b34e19338e1af72e4bf496b5d1420b7efe'
  assets=json.loads((H/'runtime_assets.json').read_text());assert g.sha(H/'medcomm_touch_ui.realtime')==assets['UI_sha256']=='e0507f9035958a57f3397cf05c692181f21f2f3862bc147989bcc770b1ba9931'
  assert g.sha(H/'liblive_integer_frame.so')==assets['display_library_sha256']
  env=dict(x.decode().split('=',1) for x in Path('/proc',str(self.patient['pid']),'environ').read_bytes().split(b'\0') if b'='in x)
  self.touch.snapshot();self.touch.suspend();os.kill(self.supervisor['pid'],signal.SIGSTOP);self.paused=True;deadline=time.monotonic()+2
  while g.same(self.supervisor) and g.identity(self.supervisor['pid'])['state']not in('T','t') and time.monotonic()<deadline:time.sleep(.02)
  assert g.same(self.supervisor) and g.identity(self.supervisor['pid'])['state']in('T','t');stop_owned(self.patient)
  boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();env=g.sanitised_ui_environment(env,str(self.root),self.session,boot);env['LD_LIBRARY_PATH']=str(H)+(':'+env['LD_LIBRARY_PATH'] if env.get('LD_LIBRARY_PATH') else '')
  env['MEDCOMM_V18_POLL_MS']='1'
  env,args=self.touch.private_ui(env,[str(H/'medcomm_touch_ui.realtime')]+self.patient['argv'][1:]);self.log=(self.root/'ui.log').open('xb');self.ui=subprocess.Popen(args,env=env,cwd=self.patient['cwd'],stdin=subprocess.DEVNULL,stdout=self.log,stderr=subprocess.STDOUT,start_new_session=True);self.ui_identity=g.identity(self.ui.pid);time.sleep(.35);assert self.ui.poll()is None;self.touch.verify_private(self.ui_identity,self.root/'ui.log')
  self.boot=boot;self.pid=os.getpid();self.ticks=g.identity(self.pid)['start_ticks'];assert self.observer.matches()
  return dict(root=str(self.root),UI_pid=self.ui.pid,UI_sha256=assets['UI_sha256'],mode='r12_sealed_original_image_and_report_current_coordinates',source_pairing='sealed_anonymous_memfd',direct_touch=self.touch.receipt,startup_ns=time.monotonic_ns()-startup,persistent_image_files=0,new_DRM_open=False,new_modeset=False,physical_HDMI_latency_claimed=False)
 def prepare(self,raw,fid,capture):
  prepared=prepare_image(raw)
  fd,info=sealed_image(raw,fid,self.ordinal+1,capture,self.pid,self.ticks)
  self.fds.append(fd)
  while len(self.fds)>3:os.close(self.fds.popleft())
  return prepared,(fid,capture,self.ordinal+1,fd,info)
 def present(self,original,source,identity,inferred,metadata,validated_composite_sha256=None,prepared_image=None,prepared_seal=None):
  present_started=time.monotonic_ns()
  assert self.ui and self.ui.poll()is None and g.same(self.ui_identity) and self.observer.matches()
  identity_checked=time.monotonic_ns()
  if prepared_image is None:raw=original.tobytes();digest=hashlib.sha256(raw).hexdigest()
  else:
   assert type(prepared_image)is PreparedImage and type(prepared_image.raw)is bytes
   base=original
   while getattr(base,'base',None)is not None:base=base.base
   assert base is prepared_image.raw and original.shape==(480,800,3) and original.dtype.name=='uint8' and original.flags.c_contiguous and not original.flags.writeable and original.nbytes==1152000
   raw=prepared_image.raw;digest=prepared_image.digest
  assert digest==source['capture_sha256']==validated_composite_sha256
  assert identity['frame_id']==source['frame_id'] and identity['timestamp_ms']==source['capture_ns']//1000000 and 0<source['capture_ns']<=source['observed_ns']<=inferred
  v=metadata['overlay'];validate_overlay(v);assert v['version']==1 and v['session_id']==self.session and v['frame_id']==source['frame_id'] and v['selected_ordinal']==self.ordinal+1 and v['source_pixels_sha256']==source['logical_sha256']
  assert source['frame_id']>self.last_fid and source['capture_ns']>self.last_capture
  if prepared_seal is None:
   fd,info=sealed_image(raw,source['frame_id'],self.ordinal+1,source['capture_ns'],self.pid,self.ticks)
   self.fds.append(fd)
  else:
   fid,capture,ordinal,fd,info=prepared_seal
   assert (fid,capture,ordinal)==(source['frame_id'],source['capture_ns'],self.ordinal+1) and fd in self.fds
  sealed_ns=time.monotonic_ns()
  out=dict(v,boot_id=self.boot,source_capture_ns=str(source['capture_ns']),bridge_received_ns=str(time.monotonic_ns()),image_memfd=info,source_frame_pairing='same_original_camera_image_and_coordinates',image_files_written=False,inference_placement=metadata.get('inference_placement','Nav_PersonPL_QHandTCNPL_PYNQHandPL_PC_PalmBodyCUDA'))
  g.dump(self.root/'overlay_current.json',out,compact=True)
  published_ns=time.monotonic_ns()
  while len(self.fds)>3:os.close(self.fds.popleft())
  self.ordinal+=1;self.last_fid=source['frame_id'];self.last_capture=source['capture_ns'];deadline=time.monotonic()+3
  while True:
   assert self.ui.poll()is None
   try:ack=json.loads((self.root/'overlay_draw_ack.json').read_text())
   except (FileNotFoundError,ValueError):ack={}
   if ack.get('session_id')==self.session and ack.get('boot_id')==self.boot and ack.get('image_selected_ordinal')==self.ordinal:
    assert ack['source_frame_pairing_verified']is True and ack['image_source_frame_id']==ack['source_frame_id']==source['frame_id'] and ack['framebuffer_copy_only']is True
    copied=int(ack['framebuffer_copy_done_ns']);assert copied>=inferred
    if ack.get('geometry_drawn'):assert ack['body_valid_points']==sum(v['body_valid'])
    return dict(framebuffer_copy_ack=ack,source_frame_pairing_verified=True,capture_EOF_to_framebuffer_copy_ns=copied-source['capture_ns'],framebuffer_copy_only=True,physical_HDMI_latency_claimed=False,persistent_image_files_created=False,immutable_image_hash_reused=prepared_image is not None,presentation_profile_ns=dict(identity=identity_checked-present_started,validation_and_seal=sealed_ns-identity_checked,publish=published_ns-sealed_ns,publication_to_first_read=int(ack['pair_first_read_ns'])-published_ns,ack_return=time.monotonic_ns()-published_ns))
   if time.monotonic()>=deadline:raise TimeoutError('No source-paired r12 framebuffer copy ACK; no optical or vblank claim')
   time.sleep(.001)
 def close(self):
  if self.closed:return dict(already_closed=True)
  result={}
  if self.ui:
   if self.ui.poll()is None:
    assert self.ui_identity;stop_owned(self.ui_identity)
   self.ui.wait(timeout=2)
  while self.fds:os.close(self.fds.popleft())
  if self.paused:
   assert g.same(self.supervisor);os.kill(self.supervisor['pid'],signal.SIGCONT);deadline=time.monotonic()+12
   while time.monotonic()<deadline:
    found=[r for r in process_rows() if r['argv']==self.patient['argv']]
    if len(found)==1 and g.sha('/proc/%d/exe'%found[0]['pid'])==self.original_sha:result['original_patient_restored']=True;restored=found[0];break
    time.sleep(.1)
   assert result.get('original_patient_restored')
  else:restored=self.patient
  if self.touch.suspended:
   assert restored;self.touch.restore_after_original(restored);result['direct_touch_restore']=self.touch.receipt
  if restored and hasattr(self.touch,'verify_restored'):self.touch.verify_restored(restored)
  if self.log:self.log.close()
  if self.lockfd is not None:fcntl.flock(self.lockfd,fcntl.LOCK_UN);os.close(self.lockfd);self.lockfd=None
  assert self.observer.matches();result.update(HDMI_mode_unchanged=True,pixels_written_to_files=False,source_memfds_closed=True);self.closed=True;return result
