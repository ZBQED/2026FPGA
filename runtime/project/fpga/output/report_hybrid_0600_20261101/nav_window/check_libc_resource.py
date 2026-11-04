"""No optional resource module, no native/model/board execution: verify libc ABI binding and retained error bytes."""
from pathlib import Path
from types import SimpleNamespace
import ast,ctypes as C,hashlib,importlib.util,io,json
N=Path(__file__).resolve().parent;W=N/'offline_libc_contract_work';W.mkdir(exist_ok=True)
spec=importlib.util.spec_from_file_location('thread_usage_candidate',N/'thread_usage_libc.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
assert C.sizeof(C.c_long)==4 and C.sizeof(m.RUsage)==72 and [getattr(m.RUsage,k).offset for k in m.COUNTERS]==[32,36,64,68]
results=[]
for mode in('valid_zero','valid_counts','errno_failure','negative_counter'):
 calls=[]
 class Call:
  def __call__(self,who,p):
   calls.append(who);out=C.cast(p,C.POINTER(m.RUsage)).contents
   for name,value in zip(m.COUNTERS,(939,1,1,14)if mode!='valid_zero'else(0,0,0,0)):setattr(out,name,value)
   if mode=='negative_counter':out.ru_minflt=-1
   if mode=='errno_failure':C.set_errno(22);return -1
   return 0
 call=Call();sample=m.make_thread_usage(SimpleNamespace(getrusage=call));failed=False
 try:row=sample()
 except(AssertionError,OSError):failed=True
 assert failed==(mode in('errno_failure','negative_counter')) and calls==[1]
 assert call.argtypes==[C.c_int,C.POINTER(m.RUsage)]and call.restype==C.c_int
 if not failed:assert set(row)==set(m.COUNTERS)and all(type(v)is int and v>=0 for v in row.values())
 results.append(dict(case=mode,expected_fail_closed=failed,who=1,pass_expected=True))
source=(N/'measure_person_fused.py').read_text(encoding='utf-8');tree=ast.parse(source);assert not any(isinstance(x,(ast.Import,ast.ImportFrom))and('resource'in ast.unparse(x))for x in tree.body)
main=next(x for x in tree.body if isinstance(x,ast.FunctionDef)and x.name=='main');tr=next(x for x in main.body if isinstance(x,ast.Try));assert any(isinstance(x,ast.ImportFrom)and x.module=='thread_usage_libc'for x in tr.body)
assert 'RUSAGE_THREAD immediately outside native wall timer'in source
# Exercise actual no-result fallback assignment against a real F-backed error log.
work=W/'maintenance';work.mkdir(exist_ok=True);raw=b'Traceback: ModuleNotFoundError: No module named resource\n';(work/'child_05.log').write_bytes(raw)
mt=ast.parse((N/'maintenance_init.py').read_text(encoding='utf-8'));stmt=next(x for x in ast.walk(mt)if isinstance(x,ast.Assign)and isinstance(x.value,ast.IfExp)and 'CHILD_RETURNED_BEFORE_RESULT'in ast.unparse(x.value));env=dict(actual_path=work/'nonexistent_result.json',rc=1,STATE=work,json=json);exec(compile(ast.Module(body=[stmt],type_ignores=[]),'<actual_missing_result_fallback>','exec'),env);assert env['actual']['returncode']==1 and env['actual']['hardware_RUN']is None and env['actual']['PL_RUN_count_known']is False and 'No module named resource'in env['actual']['child_logs']['child_05.log']
# Exercise actual SFTP collection function with fake transport carrying real original error bytes.
ft=ast.parse((N/'fused_window.py').read_text(encoding='utf-8'));fn=next(x for x in ft.body if isinstance(x,ast.FunctionDef)and x.name=='collect_failure_child_logs');downloads=[]
for mode in('valid','wrong_hash','unsafe_name'):
 h=W/mode;h.mkdir(exist_ok=True);rows=[]
 class SFTP:
  def open(self,path,mode):return io.BytesIO(raw)
  def close(self):pass
 class SSH:
  def open_sftp(self):return SFTP()
 desc=dict(name='../child_05.log'if mode=='unsafe_name'else'child_05.log',bytes=len(raw),sha256='0'*64 if mode=='wrong_hash'else hashlib.sha256(raw).hexdigest());env=dict(Path=Path,H=h,STATE='/run/rt1',hashlib=hashlib,sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest(),dump=lambda n,v:rows.append((n,v)));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<actual_error_log_collector>','exec'),env);failed=False
 try:r=env['collect_failure_child_logs'](SSH(),dict(boot_id='offline',child_log_files=[desc]))
 except AssertionError:failed=True
 assert failed==(mode!='valid')
 if not failed:assert(h/'failed_child_logs/child_05.log').read_bytes()==raw and r['status']=='ACTUAL_CHILD_LOGS_DOWNLOADED_HASH_VERIFIED_BEFORE_RESTORE'and r['before_restore']
 downloads.append(dict(case=mode,rejected=failed,pass_expected=True))
result=dict(status='RT1_LIBC_ARM32_ABI_CONTROL_AND_PREMAIN_FAILURE_EVIDENCE_RETENTION_PASS',ctypes_layout=dict(long_bytes=C.sizeof(C.c_long),rusage_bytes=C.sizeof(m.RUsage),counter_offsets=[32,36,64,68]),sample_cases=results,log_download_cases=downloads,missing_result_actual_fallback_executed=True,libc_binding_inside_main_try=True,optional_Python_resource_import_removed=True,actual_libc_syscalls=0,NN_RUN=0,board_operations=0,source_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in(N/'thread_usage_libc.py',N/'measure_person_fused.py',N/'maintenance_init.py',N/'fused_window.py',Path(__file__).resolve())})
(N/'libc_resource_checks.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,indent=2))
