"""Controlled Qiming lifecycle helpers. Importing performs no hardware action."""
from pathlib import Path
from array import array
import fcntl,hashlib,json,mmap,os,struct,subprocess,time
BASE=Path('/opt/gesture-qiming-int8-production')
DTROOT=Path('/sys/kernel/config/device-tree/overlays')
CNN_DT=DTROOT/'gesture_cnn_i8'
TOUCH_DT=DTROOT/'gesture_touch_usb_phy'
DEVICE=Path('/dev/gesture-i8-pl0')
POSE='gesture-qiming-int8-pose.service'
TOUCH='gesture-qiming-int8-touch-sender.service'
OLD_MODULE='gesture_pl_i8_driver'
NEW_MODULE='gesture_pl_i8_driver_v14'
MANAGER=Path('/sys/class/fpga_manager/fpga0')
PINS={
 'hardware/qiming_int8_burst.bit':'0055479a0da81ab958616dfc7c308f052466d9a7b77634e32c744bd6e88b3506',
 'hardware/qiming_int8_burst.hwh':'5289ac761e72841d9ac3acbf0b482ca8df7ecfea03b9cef5548c8e21c2e5f93d',
 'hardware/gesture_pl_i8_driver.ko':'8e39017e1e0e373802cf0de571a4422531214807392dc9c355b8a897865f5979',
 'hardware/qiming_int8_overlay.dtbo':'11d89efe2c452ea7ad2e80f30f565931c0f86e6d3f6ae696d7bc35b5d632efe1',
 'start_pl.sh':'f51f97f5f83e11041a889dbb1c20073a873774be3000b098225ebe3fe7aa0c13',
 'loader.py':'9241c90c862fbd4fdc3d7abe14198827307a2c117822501a3bdfc009fbce8e5c',
}
ORIGINAL_BIN=Path('/lib/firmware/qiming_int8_burst.bin')
ORIGINAL_BIN_SHA='f5a646d567ffafe9a8ab85e88a30c1cb779a225a770f75160f7f26824622fb58'
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def command(*args):return subprocess.check_output(list(args),stderr=subprocess.STDOUT,text=True).strip()
def dump(path,data):
 path=Path(path);tmp=path.with_suffix(path.suffix+'.tmp')
 tmp.write_text(json.dumps(data,indent=2));tmp.chmod(0o600);os.replace(str(tmp),str(path))
def boot():return Path('/proc/sys/kernel/random/boot_id').read_text().strip()
def mainpid(unit):return int(command('systemctl','show',unit,'-p','MainPID','--value'))
def process(pid):
 q=Path('/proc')/str(pid);v=(q/'stat').read_text().rsplit(')',1)[1].split()
 return dict(pid=pid,start_ticks=int(v[19]),cmd_sha256=sha(q/'cmdline'))
def touch_snapshot():
 return dict(process=process(mainpid(TOUCH)),overlay_status=(TOUCH_DT/'status').read_text().strip())
def read_regs(base,offsets):
 fd=os.open('/dev/mem',os.O_RDONLY|os.O_SYNC)
 try:
  with mmap.mmap(fd,4096,mmap.MAP_SHARED,mmap.PROT_READ,offset=base) as mm:
   return {hex(x):struct.unpack_from('<I',mm,x)[0] for x in offsets}
 finally:os.close(fd)
def clocks():return read_regs(0xf8000000,(0x100,0x104,0x108,0x170,0x180,0x190,0x1a0))
def core_idle():return bool(read_regs(0x80000000,(0,))['0x0']&4)
def leases():
 result=[]
 for q in Path('/proc').iterdir():
  if not q.name.isdigit() or int(q.name)==os.getpid():continue
  try:
   for fd in (q/'fd').iterdir():
    try:
     target=os.readlink(str(fd))
     if (target[:-10] if target.endswith(' (deleted)') else target)==str(DEVICE):result.append(dict(pid=int(q.name),fd=fd.name))
    except OSError:pass
   if any(line.endswith(' '+str(DEVICE)) for line in (q/'maps').read_text().splitlines()):
    result.append(dict(pid=int(q.name),mapped=True))
  except (OSError,ProcessLookupError):pass
 return result
def module_refs(name):
 q=Path('/sys/module')/name/'refcnt'
 return int(q.read_text()) if q.exists() else None
def info(int8=False,prelu=False):
 fd=os.open(str(DEVICE),os.O_RDWR)
 try:
  data=bytearray(48);fcntl.ioctl(fd,0x80304984 if prelu else 0x80304982 if int8 else 0x80304980,data,True)
  row=struct.unpack('<12I',data)
  assert row[0]==0x3849504b and row[1]==(4 if prelu else 3 if int8 else 2) and row[2]==16*1024*1024
  assert row[8]==(31 if prelu else 15 if int8 else 7) and row[9:]==(0,0,0)
  return dict(magic=row[0],abi=row[1],features=row[8],pool_bytes=row[2])
 finally:os.close(fd)
def idle_server(pid):
 if (Path('/proc')/str(pid)/'wchan').read_text().strip()!='inet_csk_accept':return False
 listeners=0
 for line in Path('/proc/net/tcp').read_text().splitlines()[1:]:
  v=line.split()
  if int(v[1].split(':')[1],16)!=5092:continue
  # FIN_WAIT2/TIME_WAIT with inode0 are orphaned, already-closed sockets.
  # The serial barrier plus accept() sleep proves Pose has no active request;
  # waiting for a stopped client's FIN would otherwise reject a healthy idle.
  if v[3] in ('05','06') and v[9]=='0':continue
  if v[3]!='0A' or v[4]!='00000000:00000000':return False
  listeners+=1
 return listeners==1
def bit2bin(contents):
 """Same .bit payload extraction/word byteswap as installed PYNQ bit2bin."""
 offset=2+struct.unpack_from('>H',contents,0)[0]+2
 while True:
  desc=contents[offset];offset+=1
  if desc==0x65:
   size=struct.unpack_from('>I',contents,offset)[0];offset+=4
   assert offset+size==len(contents) and size%4==0
   words=array('I');words.frombytes(contents[offset:]);assert words.itemsize==4
   words.byteswap();return words.tobytes()
  assert desc in (0x61,0x62,0x63,0x64)
  size=struct.unpack_from('>H',contents,offset)[0];offset+=2+size
def check_original_assets():
 for name,digest in PINS.items():assert sha(BASE/name)==digest,name
 assert sha(ORIGINAL_BIN)==ORIGINAL_BIN_SHA
 converted=bit2bin((BASE/'hardware/qiming_int8_burst.bit').read_bytes())
 assert hashlib.sha256(converted).hexdigest()==ORIGINAL_BIN_SHA
 return dict(paths={name:str(BASE/name) for name in PINS},sha256=PINS,
  original_firmware_bin=str(ORIGINAL_BIN),bin_sha256=ORIGINAL_BIN_SHA)
def download_bin(path,clock_before):
 path=Path(path);assert path.parent==Path('/lib/firmware') and path.is_file()
 assert clocks()==clock_before
 (MANAGER/'flags').write_text('0');(MANAGER/'firmware').write_text(path.name)
 assert (MANAGER/'state').read_text().strip()=='operating'
 assert clocks()==clock_before
def detach(module,int8=False,known_no_run=False):
 assert not leases(),'Device FD or VMA remains; no detach'
 if DEVICE.exists():info(int8);assert core_idle(),'Core not idle; no detach'
 else:assert known_no_run and core_idle(),'Unknown DMA state; no detach'
 assert module_refs(module)==0,'Module reference/quarantine remains; no detach'
 if CNN_DT.exists():CNN_DT.rmdir()
 if module_refs(module) is not None:command('/sbin/rmmod',module)
 assert not DEVICE.exists()
def attach(module):
 command('/sbin/insmod',str(module));CNN_DT.mkdir()
 (CNN_DT/'dtbo').write_bytes((BASE/'hardware/qiming_int8_overlay.dtbo').read_bytes())
 deadline=time.monotonic()+5
 while not DEVICE.exists() and time.monotonic()<deadline:time.sleep(.05)
 assert (CNN_DT/'status').read_text().strip()=='applied' and DEVICE.exists()
 return info(module.name.startswith('gesture_pl_i8_driver_v11'))
def restore_pose():
 command('systemctl','start',POSE);deadline=time.monotonic()+45
 while time.monotonic()<deadline:
  try:
   pid=mainpid(POSE);state=json.loads(Path('/run/gesture-qiming-int8-production/pose.json').read_text())
   owners=leases()
   if pid>1 and state.get('pid')==pid and state.get('status')=='READY' and owners and all(x['pid']==pid for x in owners):
    return dict(process=process(pid),leases=owners,state=state)
  except (OSError,ValueError,subprocess.CalledProcessError):pass
  time.sleep(.1)
 raise RuntimeError('Original Pose did not become READY; no further reload attempted')
