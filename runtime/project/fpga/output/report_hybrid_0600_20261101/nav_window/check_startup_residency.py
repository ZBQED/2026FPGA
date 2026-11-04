"""Focused control-only failure injection; does not touch actual mappings or call mlock."""
from pathlib import Path
import ast,hashlib,importlib.util,json,types
N=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('candidate_startup_residency',N/'startup_residency.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
native='/opt/gesture-nav-report-hybrid-0600-r1/native/libperson192_navfused.so'
base='\n'.join(['1000-3000 r-xp 0000 00:01 100 '+native,'4000-6000 r--p 0000 00:01 101 /lib/libc-2.30.so','7000-8000 r-xp 0000 00:01 102 /lib/libm-2.30.so','9000-a000 r-xp 0000 00:01 103 /lib/ld-2.30.so','b000-c000 r-xp 0000 00:01 104 /lib/libgcc_s.so.1','d000-e000 rw-p 0000 00:00 0 [heap]','f000-10000 rw-s 0000 00:01 200 /dev/gesture-nav-yolo-fused0','11000-12000 rw-p 0000 00:01 201 /run/session_key','13000-14000 r-xp 0000 00:01 202 /tmp/libc-2.30.so','15000-16000 ---p 0000 00:01 203 /lib/libc-2.30.so','17000-18000 r--p 0000 00:01 204 /lib/libc-2.30.so (deleted)'])
results=[]
for mode in ('valid','mlock_ENOMEM','mlock_EPERM','inconsistent_errno','not_regular','probe_failure','missing_native','over_cap','overlap','device_native'):
 text=base;ref=native;probes=[];locks=[];receipt={}
 if mode=='missing_native':text=text.replace(native,'/tmp/unapproved.so')
 if mode=='over_cap':text=text.replace('1000-3000','1000-1102000')
 if mode=='overlap':text+='\n2000-4000 r-xp 0000 00:01 105 /lib/libc-2.30.so'
 if mode=='device_native':ref='/dev/evil.so';text=text.replace(native,ref)
 def probe(address):
  if mode=='probe_failure':raise OSError('injected read fault before lock')
  probes.append(address)
 def lock(address,size):
  locks.append((address,size))
  return (-1,12)if mode=='mlock_ENOMEM'else(-1,1)if mode=='mlock_EPERM'else(0,1)if mode=='inconsistent_errno'else(0,0)
 failed=False
 try:m.lock_library_mappings(ref,receipt,maps_text=text,page_size=4096,probe=probe,locker=lock,file_checker=lambda p:mode!='not_regular')
 except(AssertionError,OSError):failed=True
 assert failed==(mode!='valid')
 if mode=='valid':
  assert receipt['status']=='STARTUP_LIBRARY_RESIDENCY_LOCKED'and receipt['all_selected_mappings_locked']and receipt['selected_pages']==7 and len(probes)==7 and len(locks)==5
  assert all(r['prefault_pages_completed']==r['pages']and r['mlock_return']==r['mlock_errno']==0 and 'start'not in r and 'end'not in r for r in receipt['rows'])
 else:assert receipt['status']=='FAIL_STARTUP_LIBRARY_RESIDENCY'and receipt['all_selected_mappings_locked']is False
 if mode in ('missing_native','over_cap','overlap','not_regular','device_native'):assert not probes and not locks
 assert receipt['memory_bytes_recorded']is False and receipt['anonymous_device_CMA_key_maps_selected']is False
 results.append(dict(case=mode,failed_closed=failed,probe_count=len(probes),lock_count=len(locks),pass_expected=True))
source=(N/'measure_person_fused.py').read_text(encoding='utf-8');tree=ast.parse(source)
# All native timer statements are in a single for-loop body; resource snapshots strictly surround the timer.
loop=next(n for n in ast.walk(tree)if isinstance(n,ast.For)and isinstance(n.iter,ast.Call)and isinstance(n.iter.func,ast.Name)and n.iter.func.id=='range'and ast.unparse(n.iter)=='range(a.rounds)')
texts=[ast.unparse(n)for n in loop.body]
find=lambda term:next(i for i,s in enumerate(texts)if term in s)
assert find('ru_before = thread_usage()')<find("row['infer_start_monotonic_ns'] = now()")<find('d.yp_infer_q(')<find("row['infer_end_monotonic_ns'] = now()")<find('ru_after = thread_usage()')
assert "'--startup-lock-libraries'"in(N/'maintenance_init.py').read_text(encoding='utf-8')
assert "payload['startup_residency.py']"in(N/'prepare_window.py').read_text(encoding='utf-8')
assert not any(x in(N/'startup_residency.py').read_text(encoding='utf-8')for x in ('mlockall','/dev/mem','yp_infer','send_packet','ctypes.string_at'))
r=dict(status='RT1_BOUNDED_LIBRARY_SELECTION_MLOCK_FAILCLOSED_AND_RESOURCE_TIMER_SCOPE_PASS',cases=results,actual_mlock_calls=0,actual_memory_probes=0,CPU_NN_RUN=0,PL_RUN=0,board_operations=0,resource_samples_outside_native_elapsed_timer=True,no_session_or_autogroup_write=True,sources_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in(N/'startup_residency.py',N/'measure_person_fused.py',N/'maintenance_init.py',N/'prepare_window.py',Path(__file__).resolve())})
(N/'startup_residency_checks.json').write_text(json.dumps(r,indent=2)+'\n',encoding='utf-8');print(json.dumps(r,indent=2))
