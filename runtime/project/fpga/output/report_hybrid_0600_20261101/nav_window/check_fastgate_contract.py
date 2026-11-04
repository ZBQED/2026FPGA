"""Fault-inject real compact validation/diagnostic code with recorded counters; no NN/boards."""
from pathlib import Path
from types import SimpleNamespace
import ast,copy,ctypes as C,hashlib,importlib.util,json,socket,time
import numpy as np
N=Path(__file__).resolve().parent;R=N.parents[2];H=R/'parallel_complete120_startuplock_r10_20261031';A=N.parent/'cold_prepare_complete120_r1';W=N/'offline_contract_work';W.mkdir(exist_ok=True);W.resolve().relative_to(N.resolve())
source=(N/'measure_person_fused.py').read_text(encoding='utf-8');tree=ast.parse(source);main=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='main');savedef=next(n for n in main.body if isinstance(n,ast.FunctionDef)and n.name=='save');boxdef=next(n for n in tree.body if isinstance(n,ast.ClassDef)and n.name=='Box')
a=source.index('   st=stage_buffer;');b=source.index("  assert len(r['rounds'])==a.rounds",a);chunk='\n'.join(s[3:]for s in source[a:b].splitlines());code=compile(chunk,str(N/'measure_person_fused.py')+'::actual_compact_to_drain','exec');actual=json.loads((A/'yolo_actual.json').read_text(encoding='utf-8'));expected=json.loads((H/'current_case_expected.json').read_text(encoding='utf-8'));assert actual['status']=='NAV_YOLO79_FULL_PL_INTEGER_EXACT_PASS'
results=[];positive_ack=None
for mode in('valid','bad_counter_after_reply','bad_MAC_after_reply','bad_PS_after_reply','bad_callback_after_reply','bad_failure_after_reply','bad_total_before_reply','negative_native_count_before_reply','bad_guard_before_reply','bad_head_before_reply','bad_box_before_reply','corrupt_expanded_after_reply','counter_SD_write_failure_after_reply','receipt_SD_write_failure_after_reply','final_fullsave_failure_after_ACK'):
 work=W/mode;work.mkdir(exist_ok=True);work.resolve().relative_to(W.resolve());events=[];env=dict(np=np,C=C,Path=Path,json=json,time=time,now=time.monotonic_ns,sha=lambda b:hashlib.sha256(b).hexdigest(),names=[x['name']for x in actual['rounds'][0]['per_layer']],n=0,last=1,session='offline_rt1_contract',expected_q_sha=actual['approved_quantized_input_sha256'],EXPECTED_PIXEL=expected['source_pixels_sha256'])
 exec(compile(ast.Module(body=[boxdef,savedef],type_ignores=[]),'<actual_production_defs>','exec'),env)
 Box=env['Box'];out=(Box*32)();row_actual=actual['rounds'][0]
 for k,item in enumerate(row_actual['boxes_Q16']):
  for field,value in item.items():setattr(out[k],field,value)
 heads=np.zeros(64,np.int8);la=np.zeros((79,20),np.uint64);lb=np.zeros_like(la)
 for i,layer in enumerate(row_actual['per_layer']):la[i,:16]=layer['delta'];la[i,18]=layer['node'];la[i,19]=layer['planned_NN_MAC']
 row=dict(stats_delta=list(row_actual['stats_delta']),actual_NN_PL_RUN=79,ioctl_attempts=79,PL_NN_MAC_completed=31650912,complete_Person_wall_ns=row_actual['complete_Person_wall_ns'],infer_end_monotonic_ns=time.monotonic_ns()-10000)
 class DriverStub:
  def yp_stats(self,target):
   for i,v in enumerate(row_actual['person_stage_stats_ns_and_counts']):target[i]=v
   return 8
  def yp_copy_heads(self,p):return heads.size
  def yp_pl_error(self):return b'offline no NN'
 env.update(stage_buffer=(C.c_uint64*8)(),ls=lambda out:la,layer_after=la,la=la,lb=lb,row=row,r=dict(rounds=[row]),out=out,heads=heads,count=len(row_actual['boxes_Q16']),d=DriverStub(),EXPECTED_HEAD=hashlib.sha256(heads.tobytes()).hexdigest(),EXPECTED_BOX=copy.deepcopy(row_actual['boxes_Q16']),receipt=time.monotonic_ns()-20000,rpc=None,key=None,a=SimpleNamespace(output=str(work/'receipt.json')))
 if mode=='bad_counter_after_reply':la[0,1]=0
 if mode=='bad_MAC_after_reply':la[0,13]-=1
 if mode=='bad_PS_after_reply':la[0,8]=1
 if mode=='bad_callback_after_reply':la[0,0]=0
 if mode=='bad_failure_after_reply':la[0,15]=1
 if mode=='bad_total_before_reply':row['actual_NN_PL_RUN']=78
 if mode=='negative_native_count_before_reply':env['count']=-3
 if mode=='bad_guard_before_reply':row['stats_delta'][5]-=1
 if mode=='bad_head_before_reply':env['EXPECTED_HEAD']='0'*64
 if mode=='bad_box_before_reply':out[0].x1+=1
 if mode=='counter_SD_write_failure_after_reply':(work/'layer_delta_00.u64').mkdir(exist_ok=True)
 if mode=='receipt_SD_write_failure_after_reply':p=work/'receipt_as_directory';p.mkdir(exist_ok=True);env['a'].output=str(p)
 def send_packet(conn,key,header):
  events.append(header['operation'])
  if header['operation']=='person_result':
   assert header['compact_validation_pass'] and header['diagnostics_drained'] is False and header['pre_reply_per_layer_vector_validated']is False and header['compact_validation_scope']=='global8_native_guard_exact_head_box_only'
   if mode=='corrupt_expanded_after_reply':env['la'][0,13]=0
  else:
   assert header['operation']=='person_diagnostics_drained' and header['diagnostics_drained'] and header['raw_counter_and_light_receipt_saved_before_ack'] and header['full_expansion_saved_before_ack'] is False;assert hashlib.sha256((work/'layer_delta_00.u64').read_bytes()).hexdigest()==header['per_layer_counter_sha256'];saved=json.loads(Path(env['a'].output).read_text());assert saved['rounds'][0]['status']=='PASS' and 'per_layer'not in saved['rounds'][0] and saved['rounds'][0]['raw_counter_and_light_receipt_saved_before_ack'] and saved['rounds'][0]['per_layer_counter_binary']['sha256']==header['per_layer_counter_sha256']
   env['ack']=dict(header)
 env['send_packet']=send_packet;failure=None
 try:exec(code,env)
 except(AssertionError,OSError)as ex:failure=type(ex).__name__
 if mode=='valid':
  assert failure is None and events==['person_result','person_diagnostics_drained'] and env['row']['postreply_diagnostics_drained'];positive_ack=env['ack'];env['save'](full=True);final=json.loads(Path(env['a'].output).read_text());assert len(final['rounds'][0]['per_layer'])==79 and np.array_equal(np.asarray([v['delta']for v in final['rounds'][0]['per_layer']],np.uint64),np.frombuffer((work/'layer_delta_00.u64').read_bytes(),'<u8').reshape(79,16))
 elif mode=='final_fullsave_failure_after_ACK':
  assert failure is None and events==['person_result','person_diagnostics_drained'];bad=work/'final_fullsave_as_directory';bad.mkdir(exist_ok=True);env['a'].output=str(bad)
  try:env['save'](full=True)
  except OSError as ex:failure=type(ex).__name__
  assert failure,'A full final receipt write failure must propagate, preventing process exit0/strict acceptance'
 elif mode.endswith('before_reply'):assert failure and events==[]
 else:assert failure and events==['person_result'] and 'ack'not in env
 results.append(dict(case=mode,events=events,failure=failure,pass_expected=True))
# The production PC receiver rejects missing, wrong or incomplete drain acknowledgements.
pt=ast.parse((H/'pc_pipeline.py').read_text());cls=next(n for n in pt.body if isinstance(n,ast.ClassDef));method=next(n for n in cls.body if isinstance(n,ast.FunctionDef)and n.name=='recv_nav_diagnostics');pc=[]
for mode in('valid','bad_frame','bad_source','pending_diagnostics','unsaved_receipt','missing_ack'):
 ack=copy.deepcopy(positive_ack)
 if mode=='bad_frame':ack['frame_id']=2
 if mode=='bad_source':ack['source_pixels_sha256']='wrong'
 if mode=='pending_diagnostics':ack['diagnostics_drained']=False
 if mode=='unsaved_receipt':ack['raw_counter_and_light_receipt_saved_before_ack']=False
 def recv(*a,**k):
  if mode=='missing_ack':raise EOFError('offline missing mandatory drain ack')
  return ack,b''
 env=dict(ns=time.perf_counter_ns,ms=lambda a,b:(b-a)/1e6,recv_packet=recv,PIX=expected['source_pixels_sha256']);exec(compile(ast.Module(body=[method],type_ignores=[]),'<actual_PC_drain_receiver>','exec'),env);failure=None
 try:env['recv_nav_diagnostics'](None,None,None,'offline_rt1_contract',1)
 except(AssertionError,EOFError)as ex:failure=type(ex).__name__
 assert (failure is None)==(mode=='valid');pc.append(dict(case=mode,rejected=failure is not None,pass_expected=True))
# A missing/error drain future prevents the real completion timestamp assignment.
completion="tcn_result_done=ns();nav_diag,nav_diag_timing=ndf.result(timeout=35);done=ns()";assert completion in(H/'pc_pipeline.py').read_text()
class MissingDrain:
 def result(self,timeout):raise EOFError('offline missing diagnostics')
env=dict(ns=time.perf_counter_ns,ndf=MissingDrain())
try:exec(completion,env)
except EOFError:pass
assert 'done'not in env
# Optional probes preserve the existing authenticated byte protocol in both directions.
def load(n,p):
 spec=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
new=load('cmp6_protocol',H/'rpc_protocol.py');old=load('cmp1_protocol',R/'parallel_complete120_20261031/rpc_protocol.py');key=bytes(range(32));body=bytes(range(128));header=dict(operation='offline_contract',frame_id=1);probe={};a,b=socket.socketpair()
try:
 new.send_packet(a,key,header,body,probe=probe);got,data=old.recv_packet(b,key);assert data==body and got['operation']==header['operation'];assert probe['entry_ns']<=probe['header_encoded_ns']<=probe['hmac_complete_ns']<=probe['sendall_enter_ns']<=probe['sendall_return_ns'];old.send_packet(b,key,header,body);got,data=new.recv_packet(a,key);assert data==body
finally:a.close();b.close()
result=dict(final_fullsave_failure_propagates_after_ACK=True,final_full79_expansion_equal_raw_counter_bytes=True,light_receipt_excludes_expanded_layers_before_ACK=True,source_files_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in(N/'measure_person_fused.py',H/'pc_pipeline.py',H/'rpc_protocol.py',Path(__file__).resolve(),A/'yolo_actual.json')},status='RT1_GLOBAL_CRITICAL_GATE_AND_POSTREPLY_VECTOR_MANDATORY_DRAIN_FAULT_INJECTION_PASS',production_chunk_replayed=True,synthetic_driver_stub_no_native_invoke=True,source_counters_from=str(A/'yolo_actual.json'),Nav_cases=results,PC_drain_cases=pc,missing_drain_prevents_completion_timestamp=True,new_old_wire_bidirectional_interop_pass=True,CPU_NN_RUN=0,GPU_NN_RUN=0,PL_RUN=0,board_operations=0,scope='Control-flow/fault injection only; no new numerical/hardware acceptance claimed')

# Every byte of the payload is checked against actual-startup reference bytes; test exact production assert.
ingress=next(x for x in ast.walk(tree)if isinstance(x,ast.Assert)and 'reference_q_bytes'in ast.unparse(x.test));ingress_code=compile(ast.Module(body=[ingress],type_ignores=[]),'<actual_rt1_full_bytewise_ingress_assert>','exec');input_cases=[]
ref=bytes(range(256))*432
assert len(ref)==110592
base=dict(input_sha256='approved_startup_q_sha',source_pixels_sha256=expected['source_pixels_sha256'],operation='person_q',shape=[192,192,3],dtype='int8',parent_size=[640,480])
for mode in ('valid','byte0','byte_middle','byte_last','short','bad_header_sha','bad_source','bad_shape'):
 body=ref;header=copy.deepcopy(base)
 if mode.startswith('byte'):
  at={'byte0':0,'byte_middle':55300,'byte_last':110591}[mode];b=bytearray(body);b[at]^=1;body=bytes(b)
 if mode=='short':body=body[:-1]
 if mode=='bad_header_sha':header['input_sha256']='wrong'
 if mode=='bad_source':header['source_pixels_sha256']='wrong'
 if mode=='bad_shape':header['shape']=[1,1,3]
 failed=False
 try:exec(ingress_code,dict(body=body,header=header,reference_q_bytes=ref,expected_q_sha=base['input_sha256'],EXPECTED_PIXEL=base['source_pixels_sha256']))
 except AssertionError:failed=True
 assert failed==(mode!='valid');input_cases.append(dict(case=mode,rejected=failed,pass_expected=True))
result['input_bytewise_actual_assert_cases']=input_cases
result['input_perframe_SHA_removed']=not any(isinstance(x,ast.Call)and isinstance(x.func,ast.Name)and x.func.id=='sha'and x.args and isinstance(x.args[0],ast.Name)and x.args[0].id=='body'for x in ast.walk(tree))
result['per_layer_vector_gate_moved_not_removed']=source.index('delta=la[:,:16]-lb[:,:16]')>source.index("operation='person_result'")and source.index('delta=la[:,:16]-lb[:,:16]')<source.index("operation='person_diagnostics_drained'")
assert result['input_perframe_SHA_removed']and result['per_layer_vector_gate_moved_not_removed']

(N/'fastgate_contract_checks.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,indent=2))


