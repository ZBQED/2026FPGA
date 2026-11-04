"""Bounded startup page residency for explicitly selected readable library file VMAs only."""
from pathlib import PurePosixPath
import ctypes as C,os,re,stat,time
CAP_BYTES=16*1024*1024
SYSTEM_LIBRARY=re.compile(r'(?:libc(?:-[0-9.]+)?\.so(?:\.[0-9]+)*|libm(?:-[0-9.]+)?\.so(?:\.[0-9]+)*|libgcc_s\.so(?:\.[0-9]+)*|ld-linux[^/]*\.so(?:\.[0-9]+)*|ld-[0-9.]+\.so)\Z')
def plan_file_mappings(text,native_path,page_size=4096,cap_bytes=CAP_BYTES):
 assert page_size>0 and cap_bytes==CAP_BYTES
 rows=[];native_found=False
 for line in text.splitlines():
  fields=line.split(None,5)
  if len(fields)!=6:continue
  address,perms,offset,device,inode,filename=fields
  if not perms.startswith('r')or not filename.startswith('/')or filename.endswith(' (deleted)')or inode=='0':continue
  if filename.startswith(('/dev/','/proc/','/sys/','/run/')):continue
  p=PurePosixPath(filename)
  native=filename==native_path
  system=(filename.startswith('/lib/')or filename.startswith('/usr/lib/'))and SYSTEM_LIBRARY.fullmatch(p.name)is not None
  if not(native or system):continue
  first,last=(int(x,16)for x in address.split('-'));assert first%page_size==last%page_size==0 and last>first
  assert not any(first<r['end']and last>r['start']for r in rows),'Overlapping selected VMAs'
  rows.append(dict(start=first,end=last,filename=filename,perms=perms,bytes=last-first,pages=(last-first)//page_size,native=native));native_found|=native
 assert native_found,'No readable mapping of exact SHA-verified native library'
 assert sum(r['bytes']for r in rows)<=cap_bytes,'Selected library file mappings exceed 16MiB startup cap'
 return rows

def lock_library_mappings(native_path,receipt,*,maps_text=None,page_size=None,probe=None,locker=None,file_checker=None):
 receipt.update(status='STARTUP_LIBRARY_RESIDENCY_STARTED',cap_bytes=CAP_BYTES,anonymous_device_CMA_key_maps_selected=False,memory_bytes_recorded=False,model_NN_RUN=0,rows=[])
 try:
  if maps_text is None:
   with open('/proc/self/maps')as f:maps_text=f.read()
  if page_size is None:page_size=os.sysconf('SC_PAGESIZE')
  plan=plan_file_mappings(maps_text,str(native_path),page_size)
  receipt['selected_bytes']=sum(r['bytes']for r in plan);receipt['selected_pages']=sum(r['pages']for r in plan)
  if file_checker is None:file_checker=lambda name:stat.S_ISREG(os.stat(name).st_mode)
  if probe is None:probe=lambda address:C.c_ubyte.from_address(address).value
  if locker is None:
   libc=C.CDLL(None,use_errno=True);mlock=libc.mlock;mlock.argtypes=[C.c_void_p,C.c_size_t];mlock.restype=C.c_int
   def locker(address,size):
    C.set_errno(0);rc=mlock(address,size);return rc,C.get_errno()if rc else 0
  start=time.monotonic_ns()
  for item in plan:
   row={k:v for k,v in item.items()if k not in('start','end')};row.update(prefault_pages_completed=0,mlock_return=None,mlock_errno=None);receipt['rows'].append(row)
   assert file_checker(item['filename']),'Selected VMA is not a regular library file'
   for address in range(item['start'],item['end'],page_size):probe(address);row['prefault_pages_completed']+=1
   rc,error=locker(item['start'],item['bytes']);row.update(mlock_return=rc,mlock_errno=error)
   assert rc==0 and error==0,'Startup mlock failed for selected library mapping, errno=%s'%error
  receipt.update(status='STARTUP_LIBRARY_RESIDENCY_LOCKED',elapsed_ns=time.monotonic_ns()-start,all_selected_mappings_locked=True)
  return receipt
 except BaseException as exc:
  receipt.update(status='FAIL_STARTUP_LIBRARY_RESIDENCY',all_selected_mappings_locked=False,error_type=type(exc).__name__,error=str(exc));raise
