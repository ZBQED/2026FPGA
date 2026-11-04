"""Read-only Nav restore baseline. Only fixed PS clock registers use /dev/mem."""

from pathlib import Path

import hashlib,json,mmap,os,re,stat,struct,time

ROOT='/opt/gesture-tcn-20261022'

PREFIXES=('/opt/medcomm/','/opt/gesture-touch/','/opt/gesture-v4-worker-',ROOT+'/app_runner/')

SOURCE_FILES=('/bin/sync','/bin/mount','/sbin/reboot','/sbin/init','/etc/init.d/medcomm-ui','/etc/init.d/gesture-touch','/etc/init.d/gesture-nav-ready','/etc/init.d/gesture-display-ready',

 '/etc/init.d/gesture-v4-worker-5764ea3f-navigator','/opt/medcomm/camera_loop.sh','/opt/medcomm/medcomm_camera',

 '/opt/medcomm/qt_dual_display/shared_service.py','/opt/medcomm/qt_dual_display/staff_screen.py','/opt/medcomm/qt_dual_display/patient_screen.py',

 ROOT+'/app_runner/service_control.py',ROOT+'/pl_runtime/gesture_pl_driver.ko',

 ROOT+'/deployment/nav_display_restore/restore_display.py','/opt/gesture-nav-h49-cold/cold_bindings.json','/opt/gesture-nav-h49-cold/restore_original_init.py')

SD_NAMES=('BOOT.BIN','boot.scr','image.ub','trial-cnn-v3-20261022.bit','trial-cnn-v3-original-kernel-cma128-20261022.ub','trial-cnn-v3-20261022.scr',

 'nav-h49-restore-20261027.bit','nav-h49-restore-20261027.ub','nav-h49-restore-entry-v3-20261027.scr','nav-h49-original-recovery-assets-check-v4-20261027.scr')

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def text(p):

 try:return Path(p).read_text().strip()

 except OSError:return None

def file_fact(p):

 p=Path(p)

 if not p.is_file():return None

 s=p.stat();return dict(sha256=sha(p),bytes=s.st_size,uid=s.st_uid,mode=oct(stat.S_IMODE(s.st_mode)))

def safe_argv(argv):

 # Exact known app arguments are needed to restore this live publisher. Keys

 # remain paths; no file content or literal credential argument is accepted.

 for a in argv:

  if re.search(r'(?i)(--?(?:password|passwd|secret|token|rpc-key)(?:=|$))',a)and a not in('--rpc-key-file',):raise RuntimeError('Literal credential argument rejected before persistence')

  if re.search(r'://[^/\s]*:[^/\s]*@',a):raise RuntimeError('Credential-bearing URL rejected before persistence')

 return argv

def process(p):

 a=[x.decode()for x in(p/'cmdline').read_bytes().split(b'\0')if x]

 v=(p/'stat').read_text().rsplit(')',1)[1].split()

 return dict(pid=int(p.name),start_ticks=int(v[19]),state=v[0],argv=safe_argv(a),cwd=os.readlink(p/'cwd'),exe=os.readlink(p/'exe'))

def camera():

 p=Path('/run/medcomm/camera.frame')

 try:

  with p.open('rb')as f:h=list(struct.unpack('<5I',f.read(20)));s=os.fstat(f.fileno())

  return dict(magic=h[0],sequence=h[1],width=h[2],height=h[3],stride=h[4],device=s.st_dev,inode=s.st_ino,bytes=s.st_size)

 except OSError:return None

def ps_clocks():

 # These seven fixed ZynqPS SLCR clock controls are read-only observations.

 # No PL MMIO, unlock register, ioctl, masks, writes or computed address input.

 offsets=(0x100,0x104,0x108,0x170,0x180,0x190,0x1a0)

 fd=os.open('/dev/mem',os.O_RDONLY|os.O_CLOEXEC|os.O_SYNC)

 try:

  view=mmap.mmap(fd,4096,flags=mmap.MAP_SHARED,prot=mmap.PROT_READ,offset=0xf8000000)

  try:return {hex(o):struct.unpack_from('<I',view,o)[0]for o in offsets}

  finally:view.close()

 finally:os.close(fd)

def snapshot():

 roles=[];owners=[];scan_errors=[]

 for p in Path('/proc').iterdir():

  if not p.name.isdigit()or int(p.name)==os.getpid():continue

  try:

   argv=[x.decode()for x in(p/'cmdline').read_bytes().split(b'\0')if x]

   if any(a.startswith(PREFIXES)for a in argv):roles.append(process(p))

   targets=[]

   for f in(p/'fd').iterdir():

    try:target=os.readlink(f)

    except FileNotFoundError:continue

    if target.startswith(('/dev/gesture','/dev/dri/','/dev/fb','/dev/video','/dev/media','/dev/input/','/dev/snd/','/dev/i2c-')):targets.append(dict(fd=int(f.name),target=target))

   maps=[s for s in(p/'maps').read_text().splitlines()if re.search(r'/dev/(?:gesture|dri/|fb|video|media|input/|snd/|i2c-)',s)]

   if targets or maps:owners.append(dict(pid=int(p.name),fds=targets,device_mappings=maps))

  except(FileNotFoundError,ProcessLookupError):pass

  except PermissionError:scan_errors.append(int(p.name))

 files={p:file_fact(p)for p in SOURCE_FILES}

 sd='/media/sd-mmcblk0p1';sd_files={str(Path(sd)/n):file_fact(Path(sd)/n)for n in SD_NAMES}

 hdmi={}

 for p in Path('/sys/class/drm').glob('card*-*'):

  hdmi[p.name]=dict(status=text(p/'status'),modes=text(p/'modes'),edid_sha256=sha(p/'edid')if(p/'edid').is_file()else None)

 inputs={p.name:dict(name=text(p/'device/name'),phys=text(p/'device/phys'),capabilities_key=text(p/'device/capabilities/key'))for p in Path('/sys/class/input').glob('event*')}

 fbs={p.name:dict(name=text(p/'name'),virtual_size=text(p/'virtual_size'),bits_per_pixel=text(p/'bits_per_pixel'),stride=text(p/'stride'))for p in Path('/sys/class/graphics').glob('fb*')}

 mounts=[r.split()[:4]for r in Path('/proc/mounts').read_text().splitlines()if r.split()[0]=='/dev/mmcblk0p1'and r.split()[2]=='vfat']

 return dict(status='NAV_READONLY_RESTORE_BASELINE_FIXED_PS_CLOCKS_NO_PL_DEVICE_OR_MMIO',boot_id=text('/proc/sys/kernel/random/boot_id'),monotonic_ns=time.monotonic_ns(),kernel=os.uname().release,SD_mounts=mounts,PS_clock_registers=ps_clocks(),

  roles=sorted(roles,key=lambda r:r['pid']),device_owners=owners,proc_scan_errors=scan_errors,camera=camera(),HDMI=hdmi,framebuffers=fbs,input_devices=inputs,

  sound_cards=text('/proc/asound/cards'),sound_pcm=text('/proc/asound/pcm'),modules=[x for x in Path('/proc/modules').read_text().splitlines()if x.startswith(('gesture_','camera_xiic'))],

  source_files=files,SD_restore_assets=sd_files,whole_FDT_sha256=sha('/sys/firmware/fdt'),

  current_loaded_bit_proven=False,current_loaded_bit_proof='No same-boot explicit loaded-bit receipt was found; installed SD/restore SHA is not a configuration readback',

  network=dict(eth0_MAC=text('/sys/class/net/eth0/address'),device=os.path.realpath('/sys/class/net/eth0/device'),driver=os.path.realpath('/sys/class/net/eth0/device/driver'),operstate=text('/sys/class/net/eth0/operstate')),

  clock_snapshot_scope='Fixed seven PS SLCR clock controls through O_RDONLY/PROT_READ only; no PL MMIO, DRM fd/modeset or clock change; configured clock values derived from the seven PS SLCR registers')

SOURCE_FILES=tuple(sorted(set(SOURCE_FILES)|set(['/etc/default/dropbear', '/etc/init.d/dropbear', '/etc/init.d/gesture-display-ready', '/etc/init.d/gesture-nav-ready', '/etc/init.d/gesture-recognition', '/etc/init.d/gesture-touch', '/etc/init.d/gesture-v4-worker-5764ea3f-navigator', '/etc/init.d/medcomm-ui', '/etc/init.d/networking', '/etc/init.d/udev', '/etc/network/interfaces', '/etc/udev/udev.conf', '/opt/gesture-tcn-20261022/app_runner/continuous_int8_service.py', '/opt/gesture-tcn-20261022/app_runner/continuous_service.py', '/opt/gesture-tcn-20261022/app_runner/gesture-recognition', '/opt/gesture-tcn-20261022/app_runner/install.sh', '/opt/gesture-tcn-20261022/app_runner/run.sh', '/opt/gesture-tcn-20261022/app_runner/run_gesture.py', '/opt/gesture-tcn-20261022/app_runner/service_control.py', '/opt/gesture-tcn-20261022/app_runner/start.sh', '/opt/gesture-tcn-20261022/app_runner/status.sh', '/opt/gesture-tcn-20261022/app_runner/stop.sh', '/opt/gesture-tcn-20261022/app_runner/ui_bridge.py', '/opt/gesture-tcn-20261022/app_runner/validate_pointwise_image.sh', '/opt/gesture-tcn-20261022/deployment/nav_display_restore/display_profile.json', '/opt/gesture-tcn-20261022/deployment/nav_display_restore/manifest.json', '/opt/gesture-tcn-20261022/deployment/nav_display_restore/restore_display.py', '/opt/gesture-tcn-20261022/deployment/nav_display_restore/screen_verified.edid', '/opt/gesture-touch/nav_touch_receiver.py', '/opt/gesture-v4-worker-5764ea3f-navigator/deployment.json', '/opt/medcomm/camera_loop.sh', '/opt/medcomm/medcomm_camera', '/opt/medcomm/medcomm_touch_ui', '/opt/medcomm/medcomm_ui', '/opt/medcomm/qt_dual_display/camera_light_key.py', '/opt/medcomm/qt_dual_display/display_controls.py', '/opt/medcomm/qt_dual_display/patient_screen.py', '/opt/medcomm/qt_dual_display/shared_service.py', '/opt/medcomm/qt_dual_display/staff_screen.py', '/sbin/ifconfig', '/sbin/ip', '/sbin/udevadm', '/sbin/udevd', '/usr/sbin/dropbear'])))

SOURCE_FILES=tuple(sorted(set(SOURCE_FILES)|set(['/opt/medcomm/medcomm_touch_ui', '/opt/medcomm/qt_dual_display/backend_server.py', '/opt/medcomm/qt_dual_display/shared_service.py', '/opt/medcomm/qt_dual_display/dialogue_printer.py', '/opt/medcomm/qt_dual_display/printer_backend/__init__.py', '/opt/medcomm/qt_dual_display/printer_backend/dp628_backend.py', '/opt/medcomm/qt_dual_display/printer_backend/dp628_usb_binding.json'])))

if __name__=='__main__':print(json.dumps(snapshot()))

