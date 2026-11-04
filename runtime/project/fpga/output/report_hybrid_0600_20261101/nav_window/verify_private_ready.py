"""Directed offline real-ctor/probe and READY-failure gate checks. No I2C/board/NN."""
from pathlib import Path
from types import SimpleNamespace
import ast,contextlib,copy,ctypes as C,errno,hashlib,io,json,uuid
N=Path(__file__).resolve().parent;R=N.parents[3];P=next(p.parent for p in N.parents if p.name=='output');O=P/'output/gesture_board_deploy_20261022/deployment/nav_persistent_v3/nav_ready.py';L=O.parent.parent/'camera_recovery_20261023/camera_light_key_candidate.py';private=N/'nav_ready_private.py';before=O.read_bytes();old=ast.parse(before);new=ast.parse(private.read_bytes());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
oldfunc={n.name:n for n in old.body if isinstance(n,ast.FunctionDef)};newfunc={n.name:n for n in new.body if isinstance(n,ast.FunctionDef)}
for name,node in oldfunc.items():
 if name!='probe':assert ast.dump(node,include_attributes=False)==ast.dump(newfunc[name],include_attributes=False),name
probe=newfunc['probe'];assert not any(isinstance(n,ast.Call)and isinstance(n.func,ast.Attribute)and n.func.attr=='read'for n in ast.walk(probe));assert sum(isinstance(n,ast.Call)and isinstance(n.func,ast.Attribute)and n.func.attr=='CameraLamp'for n in ast.walk(probe))==1
lampclass=next(n for n in ast.parse(L.read_bytes()).body if isinstance(n,ast.ClassDef)and n.name=='CameraLamp');execute=newfunc['execute'];outer=next(n for n in execute.body if isinstance(n,ast.Try)and any(isinstance(h.type,ast.Name)and h.type.id=='Exception'for h in n.handlers));sensor=next(i for i,n in enumerate(outer.body)if isinstance(n,ast.Assign)and isinstance(n.targets[0],ast.Subscript)and isinstance(n.targets[0].slice,ast.Constant)and n.targets[0].slice.value=='sensor');gate=ast.fix_missing_locations(ast.Module(body=[ast.Try(body=outer.body[sensor:],handlers=outer.handlers,orelse=outer.orelse,finalbody=outer.finalbody),execute.body[-1]],type_ignores=[]));work=N/'offline_private_ready_checks';work.mkdir(exist_ok=True);work.resolve().relative_to(N.resolve());results=[]
for mode in('success','constructor_EBUSY','constructor_wrong_ID'):
 reads=[];closed=[]
 class Device:
  name='0-003c'
  def is_symlink(self):return True
 def ctorpath(p):assert str(p)=='/sys/bus/i2c/drivers/ov5640';return SimpleNamespace(iterdir=lambda:[Device()])
 class Ioctl:
  def __call__(self,*a):raise AssertionError('No actual ioctl admitted in offline test')
 FakeC=SimpleNamespace(CDLL=lambda *a,**k:SimpleNamespace(ioctl=Ioctl()),c_int=C.c_int,c_ulong=C.c_ulong,c_void_p=C.c_void_p)
 env=dict(Path=ctorpath,os=SimpleNamespace(O_RDWR=2,open=lambda *a:123,close=lambda fd:closed.append(fd)),C=FakeC)
 exec(compile(ast.Module(body=[lampclass],type_ignores=[]),'<actual_frozen_0e6_CameraLamp>','exec'),env);Lamp=env['CameraLamp']
 def fake_read(self,register):
  reads.append(register);assert len(reads)<=2,'Redundant hardwareIDread attempted'
  if mode=='constructor_EBUSY':raise OSError(errno.EBUSY,'OFFLINE_FAKE_CTOR_BUSY')
  return 0 if mode=='constructor_wrong_ID'else{0x300a:0x56,0x300b:0x40}[register]
 Lamp.read=fake_read
 loader=SimpleNamespace(exec_module=lambda m:setattr(m,'CameraLamp',Lamp));util=SimpleNamespace(spec_from_file_location=lambda *a:SimpleNamespace(loader=loader),module_from_spec=lambda s:SimpleNamespace())
 pe=dict(importlib=SimpleNamespace(util=util),LIGHT=Path('/opt/medcomm/qt_dual_display/camera_light_key.py'),LIGHT_SHA=sha(L),json=json);exec(compile(ast.Module(body=[probe],type_ignores=[]),'<actual_private_probe>','exec'),pe)
 def command(args,timeout=12):
  assert args[-1]=='--probe';stream=io.StringIO()
  with contextlib.redirect_stdout(stream):pe['probe']()
  return stream.getvalue()
 state=work/(mode+'_'+uuid.uuid4().hex[:8]);state.mkdir();state.resolve().relative_to(work.resolve());report=dict(status='IN_PROGRESS',reset_attempted=False)
 kernelpath=lambda p:SimpleNamespace(exists=lambda:True,is_char_device=lambda:True)
 ge=dict(report=report,loaded=False,stopped=False,STATE=state,boot='offline-mock-boot',cmd=command,sys=SimpleNamespace(executable='/usr/bin/python3'),__file__=str(private),json=json,Path=kernelpath,time=SimpleNamespace(monotonic=lambda:0,time=lambda:1,sleep=lambda s:None),start_or_adopt_light=lambda:222,wait_video=lambda seconds:(16,208,100),registers=lambda:{'0x41600104':0xc0},DRIVER='not-used',MODULE='not-used')
 exitcode=0
 with contextlib.redirect_stdout(io.StringIO()):
  try:exec(compile(copy.deepcopy(gate),'<actual_READY_DEGRADED_and_fatal_gate>','exec'),ge)
  except SystemExit as e:exitcode=e.code
 saved=json.loads((state/'result.json').read_text());ready=(state/'ready').exists();assert closed==[123]
 if mode=='success':assert reads==[0x300a,0x300b]and exitcode==0 and ready and saved['status']=='READY' and saved['sensor']['chip_id']==0x5640 and saved['sensor']['validated_by']=='frozen ctor'
 else:assert exitcode==1 and not ready and saved['status']=='DEGRADED' and saved['error']
 results.append(dict(case=mode,actual_frozen_ctor_read_registers=reads,close_calls=1,exitcode=exitcode,result_status=saved['status'],ready_marker=ready))
assert O.read_bytes()==before
restore=(N/'restore_original_init.py').read_text(encoding='utf-8');prepare=(N/'prepare_window.py').read_text(encoding='utf-8');assert "network.run_returned(['/etc/init.d/gesture-nav-ready','start'],15)"not in restore and "KEEP.append(ready_child)"in restore and "ready_child.wait(timeout=10)==0"in restore and "sha(private_binding['original_source_path'])"in restore;assert "payload['nav_ready_private.py']"in prepare and "payload['nav_ready_private_contract.json']"in prepare and "cfg['private_nav_ready']"in prepare
for p in N.glob('*.py'):ast.parse(p.read_text(encoding='utf-8-sig'),filename=str(p))
r=dict(status='PRIVATE_READY_EXACT_DIFF_REAL_FROZEN_CTOR_AND_FAILURE_REJECTION_PASS',original_source_sha256=sha(O),private_clone_sha256=sha(private),all_original_functions_except_probe_AST_identical=True,original_attempted_single_guarded_recover_and_fatal_READY_gate_preserved=True,private_probe_redundant_ID_reads=0,cases=results,restore_uses_private_background_child_KEEP_and_true_READY_exit0=True,exact_lamp_argv_restore_gate_retained=True,payload_clone_original_source_SHA_bound=True,helpers_profile_recompile_required=False,source_files_sha256={str(p):sha(p)for p in(private,N/'restore_original_init.py',N/'prepare_window.py',Path(__file__).resolve())},scope='Directed actualfrozenctor+actualprivateprobe and actualREADY/error-finally controlgate with fakeI2C/paths, no realhardware or readiness claimed',board_operations=0,NN_RUN=0,original_source_changed=False,H5_changed=False)
(N/'nav_ready_private_checks.json').write_text(json.dumps(r,indent=2)+'\n',encoding='utf-8');print(json.dumps(r,indent=2))
