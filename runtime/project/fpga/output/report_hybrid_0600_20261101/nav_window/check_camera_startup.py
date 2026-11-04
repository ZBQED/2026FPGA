"""Control-only replay of candidate recovery guards; no actual commands, modules or boards."""
from pathlib import Path
from types import SimpleNamespace
import ast,hashlib,importlib.util,json,os,subprocess,time
N=Path(__file__).resolve().parent;S=N.parent/'cold_prepare_complete120_r9';W=N/'offline_camera_contract_work';W.mkdir(exist_ok=True)
real=Path;root=next(p.parent for p in N.parents if p.name=='output');module=root/'output/gesture_board_deploy_20261022/deployment/camera_recovery_20261023/camera_xiic_recover.ko';assert hashlib.sha256(module.read_bytes()).hexdigest()=='ebcc06f52d23a399ff45dc69f2b7d87320a0c241cc3b71a3bd83eb8212e64c58'
spec=importlib.util.spec_from_file_location('rt1_camera',N/'candidate_camera_recovery.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
sig='ov5640 0-003c: ov5640_write_reg: error: addr=0x3103, val=0x11\nxilinx-video amba_pl:vcap_dvp: ret = -16 for entity ov5640 0-003c\n';results=[]
for mode in('valid','no_signature','active_i2c_FD','gesture_module','existing_marker','late_i2c_FD','dryrun_failure','recover_failure'):
 work=W/mode;work.mkdir(exist_ok=True);boot=work/'boot.txt';boot.write_text('offlineboot');marker=work/'attempted.json'
 if mode=='existing_marker':marker.write_text('existing evidence')
 m.Path=lambda p:boot if str(p)=='/proc/sys/kernel/random/boot_id'else real(p);m.MODULE=module;m.ATTEMPT=marker;m.os=SimpleNamespace(getpid=lambda:1,geteuid=lambda:0,open=os.open,fdopen=os.fdopen,fsync=os.fsync,O_WRONLY=os.O_WRONLY,O_CREAT=os.O_CREAT,O_EXCL=os.O_EXCL)
 commands=[];audits=[]
 def audit():
  a=dict(gesture_or_recovery_modules=['gesture_pl_driver']if mode=='gesture_module'else[],user_i2c_FDs=[{'pid':99}]if mode=='active_i2c_FD'or mode=='late_i2c_FD'and audits else[],gesture_FD_VMA=[]);audits.append(a);return a
 m.audit_no_users=audit
 class Child:
  def __init__(self,argv,**kw):
   commands.append(argv);self.argv=argv;self.pid=123;self.returncode=1 if(mode=='dryrun_failure'and'recover=0'in argv)or(mode=='recover_failure'and'recover=1'in argv)else 0
  def communicate(self,timeout):assert 0<timeout<=12;return ((b'no current EBUSY'if mode=='no_signature'else sig.encode())if self.argv==['/bin/dmesg']else b'',b'injected failure'if self.returncode else b'')
 m.subprocess=SimpleNamespace(Popen=Child,PIPE=subprocess.PIPE,DEVNULL=subprocess.DEVNULL,TimeoutExpired=subprocess.TimeoutExpired)
 failed=False
 try:r=m.once(SimpleNamespace(state=work,children=[]),deadline=time.monotonic()+40)
 except(AssertionError,FileExistsError):failed=True
 assert failed==(mode!='valid')
 inserted=[a for a in commands if a[0]=='/sbin/insmod']
 if mode=='valid':assert len(inserted)==2 and [a[-1]for a in inserted]==['recover=0','recover=1']and r['recover0_calls']==r['recover1_calls']==1 and r['helper_unloaded']
 if mode in('no_signature','active_i2c_FD','gesture_module','existing_marker'):assert not inserted
 if mode in('late_i2c_FD','dryrun_failure'):assert [a[-1]for a in inserted]==['recover=0']
 result=json.loads((work/'camera_iic_recovery_actual.json').read_text());assert(result['status'].startswith('FAIL_'))==failed
 if mode not in('no_signature','active_i2c_FD','gesture_module'):assert marker.exists()
 results.append(dict(case=mode,rejected=failed,insmod_parameters=[a[-1]for a in inserted],pass_expected=True))
# Observer proves no gratuitous recovery when frames advance, one attempt when stalled, and total finite hold.
m.Path=real;observer=[]
for mode in('fresh_frames','one_recovery_then_frames','no_frames_60s'):
 work=W/mode;work.mkdir(exist_ok=True);tick=[0.0];calls=[];seq=[0]
 def clock():return tick[0]
 def sleep(seconds):tick[0]+=seconds
 def frame():
  if mode=='no_frames_60s'or mode=='one_recovery_then_frames'and not calls:raise FileNotFoundError('injected no frame')
  seq[0]+=1;return (1,2,seq[0])
 def once(network,deadline):calls.append(deadline)
 failed=False
 try:header,advances=m.wait_candidate_camera(SimpleNamespace(state=work),frame,recover_once=once,clock=clock,sleep=sleep)
 except RuntimeError:failed=True
 assert failed==(mode=='no_frames_60s')and len(calls)==(0 if mode=='fresh_frames'else 1)
 row=json.loads((work/'camera_startup_actual.json').read_text());assert row['total_budget_s']==60 and row['candidate_driver_or_NN_started']is False
 if not failed:assert row['status']=='ORIGINAL_CAMERA_ADVANCED_BEFORE_CANDIDATE_IO'and advances>=3
 else:assert row['elapsed_s']==60 and row['status']=='FAIL_ORIGINAL_CAMERA_STARTUP_HOLD'
 observer.append(dict(case=mode,rejected=failed,recovery_calls=len(calls),elapsed_s=tick[0],pass_expected=True))
# Default original restore follows byte-for-byte-equivalent old20s gate; only candidate opts in.
old=ast.parse((S/'cold_peripherals_current.py').read_text(encoding='utf-8'));new=ast.parse((N/'cold_peripherals_current.py').read_text(encoding='utf-8'));a=next(x for x in old.body if isinstance(x,ast.FunctionDef)and x.name=='start_original');b=next(x for x in new.body if isinstance(x,ast.FunctionDef)and x.name=='start_original');choice=next(x for x in b.body if isinstance(x,ast.If)and ast.unparse(x.test)=='allow_candidate_iic_recovery');start=next(i for i,x in enumerate(a.body)if 'end = time.monotonic() + 20'in ast.unparse(x));end=next(i for i,x in enumerate(a.body[start:],start)if isinstance(x,ast.If)and 'advances < 3'in ast.unparse(x.test));assert ast.dump(ast.Module(body=choice.orelse,type_ignores=[]),include_attributes=False)==ast.dump(ast.Module(body=a.body[start:end+1],type_ignores=[]),include_attributes=False)
assert ast.literal_eval(b.args.kw_defaults[0])is False
assert (N/'restore_original_init.py').read_bytes()==(S/'restore_original_init.py').read_bytes().replace(b'cmp9',b'rt1')
assert 'allow_candidate_iic_recovery=True'in(N/'maintenance_init.py').read_text(encoding='utf-8')
r=dict(status='RT1_CANDIDATE_ONLY_GUARDED_CAMERA_RECOVERY_AND_UNCHANGED_RESTORE_DEFAULT_PASS',guard_cases=results,observer_cases=observer,restore_default_original20s_AST_exact=True,restore_script_only_private_identity_changed=True,exclusive_perboot_marker_preserved=True,actual_commands_or_modules=0,NN_RUN=0,board_operations=0,source_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in(N/'candidate_camera_recovery.py',N/'cold_peripherals_current.py',N/'maintenance_init.py',N/'restore_original_init.py',Path(__file__).resolve())})
(N/'camera_startup_checks.json').write_text(json.dumps(r,indent=2)+'\n',encoding='utf-8');print(json.dumps(r,indent=2))
