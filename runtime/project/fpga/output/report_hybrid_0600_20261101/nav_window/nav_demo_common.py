"""Read-only identity/camera/source guards for private PC demo UI lifecycle."""
from pathlib import Path
import errno,hashlib,json,os,stat,struct,time
TARGET='/opt/medcomm/medcomm_touch_ui'
SUPERVISOR='/opt/medcomm/qt_dual_display/patient_screen.py'
PREFIXES=('/opt/medcomm/','/opt/gesture-touch/','/opt/gesture-v4-worker-','/opt/gesture-tcn-20261022/app_runner/')
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(path,value,compact=False):
 p=Path(path);q=p.with_name(p.name+'.next');data=json.dumps(value,ensure_ascii=True,indent=None if compact else 2,separators=(',',':')if compact else None,allow_nan=False).encode();fd=os.open(str(q),os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
 with os.fdopen(fd,'wb')as f:f.write(data)
 os.replace(str(q),str(p))
def identity(pid):
 try:
  p=Path('/proc',str(pid));v=(p/'stat').read_text().rsplit(')',1)[1].split();a=[x.decode()for x in(p/'cmdline').read_bytes().split(b'\0')if x]
  if not a:return None
  return dict(pid=int(pid),start_ticks=int(v[19]),state=v[0],argv=a,cwd=os.readlink(str(p/'cwd')),exe=os.readlink(str(p/'exe')))
 except(FileNotFoundError,ProcessLookupError):return None

def same_record(a,b):return bool(a and b and b.get('state')!='Z'and all(a.get(k)==b.get(k)for k in('pid','start_ticks','argv','cwd','exe')))
def same(p):return same_record(p,identity(p['pid']))
def camera_header():
 p=Path('/run/medcomm/camera.frame')
 with p.open('rb')as f:raw=f.read(20);s=os.fstat(f.fileno())
 if len(raw)!=20:raise RuntimeError('Camera header incomplete; no restart')
 v=struct.unpack('<5I',raw)
 if v[0]!=0x4d43414d or tuple(v[2:])!=(800,480,2400)or s.st_size!=64+3*800*480*3:raise RuntimeError('Original shared camera ABI differs')
 return dict(device=s.st_dev,inode=s.st_ino,sequence=v[1],width=v[2],height=v[3],stride=v[4],bytes=s.st_size)
def advanced(a,b):return all(a[k]==b[k]for k in('device','inode','width','height','stride','bytes'))and 0<((b['sequence']-a['sequence'])&0xffffffff)<0x80000000

def observe(bindings):
 assert os.geteuid()==0
 roles=[];leases=[];errors=[]
 for p in Path('/proc').iterdir():
  if not p.name.isdigit():continue
  try:
   row=identity(int(p.name))
   if row and any(x.startswith(PREFIXES)for x in row['argv']):roles.append(row)
   fds=[]
   for fd in(p/'fd').iterdir():
    try:
     target=os.readlink(str(fd))
     if '/dev/gesture'in target:fds.append(target)
    except(FileNotFoundError,ProcessLookupError):pass
   maps=[v for v in(p/'maps').read_text().splitlines()if'/dev/gesture'in v]
   if fds or maps:leases.append(dict(pid=int(p.name),FDs=fds,VMAs=maps))
  except(FileNotFoundError,ProcessLookupError):pass
  except OSError as e:errors.append(dict(pid=int(p.name),errno=e.errno))
 assert not errors and not leases,'NN lease/proc scan failure; no board action permitted'
 modules=[v.split()for v in Path('/proc/modules').read_text().splitlines()]
 gesture=[v for v in modules if v[0].startswith('gesture_')]
 assert len(gesture)==1 and gesture[0][0]=='gesture_pl_driver'and gesture[0][2]=='0'and gesture[0][4]=='Live','Require original Live/ref0 driver only'
 facts={}
 for name,pin in bindings['files'].items():
  p=Path(name);s=p.stat();fact=dict(sha256=sha(p),bytes=s.st_size,uid=s.st_uid,mode=oct(stat.S_IMODE(s.st_mode)))
  assert all(fact.get(k)==v for k,v in pin.items()),'Original source differs: '+name
  facts[name]=fact
 fb={}
 for name in('virtual_size','bits_per_pixel','stride','mode'):
  p=Path('/sys/class/graphics/fb1')/name;fb[name]=p.read_text().strip()if p.exists()else None
 return dict(boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),monotonic_ns=time.monotonic_ns(),roles=roles,source_files=facts,driver=gesture[0],NN_FD_VMA=leases,frame=camera_header(),fb1=fb,bootargs=Path('/proc/cmdline').read_text().strip(),FDT_sha256=sha('/sys/firmware/fdt'))

def role_key(p):return json.dumps(p['argv'],separators=(',',':'))
def original_roles(row,bindings):
 assert sorted(role_key(v)for v in row['roles'])==sorted(json.dumps(v,separators=(',',':'))for v in bindings['expected_role_commands']),'Original eleven role commands differ'
 assert all(p['state']not in('Z','T','t')for p in row['roles'])
 patient=[p for p in row['roles']if p['argv'][0]==TARGET and '--patient'in p['argv']and '--staff'not in p['argv']]
 supervisor=[p for p in row['roles']if SUPERVISOR in p['argv']]
 assert len(patient)==len(supervisor)==1
 return patient[0],supervisor[0]

def preserved(before,current,patient,supervisor,restored=False):
 assert current['boot_id']==before['boot_id']and current['source_files']==before['source_files']and current['driver']==before['driver']and current['fb1']==before['fb1']and current['bootargs']==before['bootargs']and current['FDT_sha256']==before['FDT_sha256']
 old=[p for p in before['roles']if p['pid']!=patient['pid']];new=[p for p in current['roles']if not(p['argv']==patient['argv'])]
 assert len(old)==len(new)and all(any(same_record(a,b)for b in new)for a in old),'Protected original role identity changed'
 assert same_record(supervisor,next((p for p in current['roles']if p['pid']==supervisor['pid']),None))
 if restored:
  found=[p for p in current['roles']if p['argv']==patient['argv']]
  assert len(found)==1 and found[0]['state']not in('Z','T','t')and found[0]['cwd']==patient['cwd']and found[0]['exe']==TARGET
  assert sha('/proc/%d/exe'%found[0]['pid'])==before['source_files'][TARGET]['sha256']
  assert next(p for p in current['roles']if p['pid']==supervisor['pid'])['state']not in('T','t')
  return found[0]
 assert not any(p['argv']==patient['argv']for p in current['roles']),'Original patient UI must be stopped while private UI owns fb1'

def original_bit_provenance(boot_id,expected):
 proofs=[]
 for p in Path('/run').glob('gesture-nav-yolo-fused31-*-restore/host_handoff.json'):
  value=json.loads(p.read_text())
  if value.get('boot_id')!=boot_id:continue
  assert value.get('original_bit_sha256')==expected and value.get('explicit_full_bit_loadb_succeeded')is True and value.get('kernel_start_observed')is True
  proofs.append(dict(path=str(p),sha256=sha(p),proof=value))
 if proofs:
  assert len(proofs)==1,'Ambiguous current-boot full-bit handoff proof'
  return proofs[0]
 # Camera/display-only all-PC mode never programs fabric or opens the NN driver.
 # After user power-cycle accept the freshly observed working original runtime;
 # retain its exact boot/FDT/driver/roles/assets and do not claim a fabric SHA.
 assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==boot_id
 assert sha(TARGET)=='40eb46aaecd020dda2d8b97a98e9e4b34e19338e1af72e4bf496b5d1420b7efe'
 driver=[v.split()for v in Path('/proc/modules').read_text().splitlines()if v.startswith('gesture_')]
 assert len(driver)==1 and driver[0][0]=='gesture_pl_driver'and driver[0][2]=='0'and driver[0][4]=='Live'
 first=camera_header();time.sleep(.25);last=camera_header();assert advanced(first,last)
 return dict(kind='CURRENT_BOOT_ORIGINAL_WORKING_CAMERA_DISPLAY_RUNTIME_SNAPSHOT',boot_id=boot_id,original_UI_sha256=sha(TARGET),driver=driver[0],camera_first=first,camera_last=last,FDT_sha256=sha('/sys/firmware/fdt'),FPGA_programming_performed=False,NN_driver_open_performed=False,actual_fabric_bit_hash_claimed=False,legacy_expected_bit_sha256=expected)


def sanitised_ui_environment(env,state,session,boot):
 # Original environment remains RAM-only; remove every v18/live integer mode.
 out={k:v for k,v in env.items()if not(k.startswith('MEDCOMM_V18_')or k.startswith('MEDCOMM_LIVE_')or k.startswith('MEDCOMM_PC_DEMO_'))}
 out.update(MEDCOMM_PC_DEMO_ROOT=state,MEDCOMM_PC_DEMO_SESSION_ID=session,MEDCOMM_PC_DEMO_BOOT_ID=boot,MEDCOMM_DIRECT_PREVIEW='1',PYTHONDONTWRITEBYTECODE='1')
 return out
