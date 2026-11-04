"""Persistent authenticated Q live Hand + original integer word policy on one owner/thread."""
from pathlib import Path
import argparse,ctypes as C,hashlib,importlib.util,json,os,select,socket,sys,time,traceback
import itertools
import signal
import numpy as np
from rpc_protocol import send_packet,recv_packet,ConnectionClosed
from q_live_policy import LivePolicy,validate_frame
H=Path(__file__).resolve().parent;ns=time.monotonic_ns
sha=lambda b:hashlib.sha256(b).hexdigest()
class GracefulStop(Exception):pass
def requested_stop(*unused):raise GracefulStop('Explicit controller stop after native returns')

def module(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def read_key():
 out=bytearray();deadline=time.monotonic()+10
 while len(out)<32:
  left=deadline-time.monotonic()
  if left<=0 or not select.select([sys.stdin.buffer],[],[],left)[0]:raise TimeoutError('32byte stdin key required within10s')
  part=os.read(sys.stdin.fileno(),32-len(out))
  if not part:raise ValueError('32byte in-memory key required')
  out.extend(part)
 return bytes(out)
def event_summary(event):
 if event is None:return None
 result={k:v for k,v in event.items()if k not in('model_runs','features')}
 for name in('model_runs','features'):
  if name in event:result[name+'_sha256']=sha(json.dumps(event[name],sort_keys=True,separators=(',',':'),ensure_ascii=True).encode())
 return result
def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--execute',action='store_true');a=ap.parse_args()
 if not a.execute:print(json.dumps(dict(status='PREPARED_ONLY_NO_BOARD_ACTION',persistent=True,per_frame_max_Hand_calls=3,per_Hand_START=51,per_TCN_profile_START=16,warmup_RUN=0)));return
 cfg=json.loads((H/'window_config.json').read_text());session_key=read_key();policy=LivePolicy(cfg['session_id'])
 if cfg.get('source_scope')in('fixed_fixture','live_nav_ram'):
  if cfg.get('fixture_kind')in('person_hand_parallel','person_hand_parallel_pinned'):
   from fixed_person_hand_parallel import run
   return run(H,cfg)
  if cfg.get('fixture_kind')=='person_raw':
   from fixed_person_raw_worker import run
   return run(H,cfg)
  if cfg.get('fixture_kind')in('same_frame_perception','same_frame_perception_tcn','same_frame_perception_heads'):
   from same_frame_perception_worker import run
   return run(H,cfg,session_key)
  if cfg.get('fixture_kind')in('resident_chain','resident_halfadd','resident_lut','resident_workspace','resident_workspace_fastadd'):
   from fixed_resident_worker import run
   return run(H,cfg)
  if cfg.get('fixture_kind')=='same_frame_hand':
   from same_frame_hand_worker import run
   return run(H,cfg,session_key)
  if cfg.get('fixture_kind')in('full_palm','full_palm_clock','full_palm_add_compare','full_hand_add_compare','full_palm_ps_compare','full_body_channels','full_body_cache_compare','full_body_integer_compare','full_body_halfadd_compare','full_hand_cache_compare','full_palm_cache_compare','full_palm_fused_compare','full_palm_add32_compare','full_palm_lut_compare','full_palm_burst_compare','full_hand_mul_compare','full_palm_mul_compare','full_body_mul_compare'):
   from fixed_graph_worker import run
  elif cfg.get('fixture_kind')=='full_hand_tcn':
   from fixed_full_tcn_worker import run
  elif cfg.get('fixture_kind')in('full_hand','full_hand_clock'):
   from fixed_full_hand_worker import run
  elif cfg.get('fixture_kind')=='movenet_split':
   from fixed_movenet_worker import run
  elif cfg.get('fixture_kind')=='movenet_quant':
   from fixed_movenet_quant_worker import run
  elif cfg.get('fixture_kind','hand')=='dw_alignment':
   from fixed_dw_worker import run
  else:
   assert cfg.get('fixture_kind','hand')=='hand'
   from fixed_hand_worker import run
  del session_key
  return run(H,cfg)
 if cfg.get('source_scope')!='live_pc_ram'or cfg.get('realtime_authorized')is not True:raise ValueError('Explicit user-authorized realtime live scope required')
 r=dict(status='STARTUP',rows=[],current_frames=[],errors=[],model_warmup_RUN=0,actual_NN_PL_RUN=0,TCN_RUN=0,source_scope='live_pc_ram',numeric_reference_available=False,board_local_capture=False,frame_pixels_persisted=False,semantic_policy_changed=True,word_admission_policy='Q15_ge19661_60percent',Hand_RUN_count_complete=True,TCN_RUN_count_complete=True)
 backend=tcn=None;sock=conn=None;trace=[];signal.signal(signal.SIGTERM,requested_stop)
 def save():
  tmp=H/'rpc_actual.json.tmp';tmp.write_text(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8');tmp.chmod(0o600);os.replace(tmp,H/'rpc_actual.json')
 def stats():
  v=(C.c_uint64*7)()
  if backend.api.gpo_owner_stats(backend.owner,4,v):raise RuntimeError(backend.api.gpo_owner_error().decode())
  return list(v)
 def fds():
  out=[]
  for p in Path('/proc/self/fd').iterdir():
   try:
    if os.readlink(p)=='/dev/gesture-i8-pl0':out.append(int(p.name))
   except OSError:pass
  return sorted(out)
 def tcn_stats():return {name:tcn.stats(name)for name in('primary','roof')}
 try:
  if Path('/proc/sys/kernel/random/boot_id').read_text().strip()!=cfg['boot_id']or fds():raise RuntimeError('Fresh boot/owner admission failed')
  manifest=json.loads((H/'package_manifest.json').read_text())
  for name,digest in manifest.items():
   if sha((H/name).read_bytes())!=digest:raise RuntimeError('Staged package differs: '+name)
  b=module('live_q_backend',H/'lite/lite_int8_backend.py');shared=module('live_q_shared',H/'lite/shared_tcn/shared_tcn.py')
  sys.path.insert(0,str(H/'wiring'));word=module('live_original_word_integer',H/'wiring/word_integer.py')
  start=ns();backend=b.LiteInt8Backend(H/'lite','hardware',1);backend.load('hand');tcn=shared.SharedTCN(backend.api,backend.owner,H/'lite/shared_tcn/assets');owner=fds()
  if len(owner)!=1 or stats()[0]or stats()[4]or any(v[0]for v in tcn_stats().values()):raise RuntimeError('One shared owner and no startup NN required')
  original_infer=tcn.infer
  def traced(profile,values,mask):
   report=original_infer(profile,values,mask);trace.append(report);return report
  tcn.infer=traced;classifier=word.IntegerClassifier(tcn,H/'wiring/classes.json');segmenter=word.IntegerWordSegmenter(classifier.classify)
  r['startup_ns']=ns()-start;r['policy']=dict(rest_confirm_us=650000,stop_tail_us=150000,start_us=120000,min_word_us=250000,gap_reset_us=1000000,confidence_min_Q15=19661,velocity_adjacency='Q_assigned_processed_sequence_plus_real_source_dt',source_frame_id_unchanged=True,word_integer_sha256=sha((H/'wiring/word_integer.py').read_bytes()))
  sock=socket.socket();sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);sock.bind(('192.168.1.30',5105));sock.listen(1);sock.settimeout(None)
  r.update(status='RPC_READY',boot_id=cfg['boot_id'],session_id=cfg['session_id']);save();conn,peer=sock.accept()
  if peer[0]!='192.168.1.100':raise RuntimeError('PC peer rejected')
  conn.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1);hello=False;closed=False
  for packet in itertools.count():
   remaining=120
   try:head,body=recv_packet(conn,session_key,timeout=remaining,max_body=150528)
   except ConnectionClosed:
    r['peer_EOF']=True
    if any(not item['current_done']for item in policy.frames.values()):raise ValueError('Peer EOF with Hand frame lacking final current_frame')
    closed=True;break
   if head.get('session_id')!=cfg['session_id']:raise ValueError('Session identity differs')
   operation=head.get('operation')
   if operation=='hello':
    if hello or body:raise ValueError('At most one empty HELLO')
    hello=True;send_packet(conn,session_key,dict(operation='ready',session_id=cfg['session_id'],model_preloaded=True,actual_NN_PL_RUN=0,persistent=True,per_frame_max_Hand_calls=3));continue
   if operation=='close':
    if any(not item['current_done']for item in policy.frames.values()):raise ValueError('CLOSE requires exactly one final current_frame for every admitted capture')
    if body:raise ValueError('Empty CLOSE required')
    send_packet(conn,session_key,dict(operation='closed',session_id=cfg['session_id'],actual_NN_PL_RUN=stats()[0],TCN_RUN=sum(v[0]for v in tcn_stats().values()),Hand_calls=policy.hand_calls,current_frames=policy.current_calls));closed=True;break
   if not hello:raise ValueError('Authenticated HELLO required before live operations')
   received=ns();slot=policy.admit(head,body,operation)
   if operation=='hand':
    policy.commit(head,slot,operation);x=np.frombuffer(body,np.int8).reshape(1,224,224,3);before=stats();trace_before=len(backend.trace)
    r['rows']=r['rows'][-7:]
    row=dict(frame_id=head['frame_id'],stream_id=head['stream_id'],timestamp_us=head['timestamp_us'],request_id=head['request_id'],source_pixels_sha256=head['source_pixels_sha256'],input_sha256=head['input_sha256'],call_in_frame=slot['hand_calls'],numeric_reference_available=False,four_heads_exact=None,integer_heads_returned=True,status='RUNNING');r['rows'].append(row);save()
    started=ns()
    try:heads=backend.infer_int8('hand',x)
    finally:done=ns();row.update(infer_start_ns=started,infer_end_ns=done,complete_ns=done-started)
    after=stats()
    if after[0]-before[0]!=51 or after[4]-before[4]!=1 or after[5]or after[6]or fds()!=owner or len(heads)!=4 or len(backend.trace)-trace_before!=1:raise RuntimeError('Hand51RUN/integer-head/same-owner proof failed')
    row.update(status='COMPLETED',actual_NN_PL_RUN=51,received_ns=received,heads_sha256=[sha(v.tobytes())for v in heads],native={k:v for k,v in backend.trace[-1].items()if not k.startswith('_')});r['actual_NN_PL_RUN']=after[0]
    descriptions=[];offset=0
    for value in heads:
     if value.dtype!=np.int8:raise RuntimeError('Integer heads required')
     descriptions.append(dict(offset=offset,shape=list(value.shape),dtype='int8',bytes=value.nbytes,sha256=sha(value.tobytes())));offset+=value.nbytes
    send_packet(conn,session_key,dict(operation='hand_result',session_id=cfg['session_id'],**{k:row[k]for k in('frame_id','stream_id','timestamp_us','request_id','source_pixels_sha256','input_sha256','call_in_frame','numeric_reference_available','four_heads_exact','integer_heads_returned','complete_ns')},heads=descriptions,actual_NN_PL_RUN=51,actual_PL_RUN=51,output_order_to_official_lite=backend.cache['hand']['receipt']['output_order_to_official_lite']),b''.join(v.tobytes()for v in heads));row['reply_sent_ns']=ns();backend.trace.clear();save()
   elif operation=='current_frame':
    ff=json.loads(body.decode('utf-8'));validate_frame(ff,head);policy.commit(head,slot,operation);ff['processed_sequence']=policy.current_calls;before=tcn_stats();obefore={n:tcn.stats(n,True)for n in('primary','roof')};trace_before=len(trace);state_before=segmenter.state;started=ns();event=segmenter.update(ff);done=ns();after=tcn_stats();oafter={n:tcn.stats(n,True)for n in('primary','roof')};delta={n:after[n][0]-before[n][0]for n in before};jobs=sum(delta.values());called=trace[trace_before:]
    if any(v not in(0,16)for v in delta.values())or jobs!=sum(v['actual_PL_RUNs']for v in called) or fds()!=owner:raise RuntimeError('TCN actual0/16/32 same-owner job proof failed')
    for name in before:
     if oafter[name][0]-obefore[name][0]!=delta[name]or oafter[name][5]or oafter[name][6]:raise RuntimeError('Shared TCN owner delta/health failed')
    if(event is None and jobs)or(event is not None and event.get('actual_PL_RUNs')!=jobs):raise RuntimeError('Original word event/native transaction count differs')
    compact=[{k:v[k]for k in('profile','class_index','actual_PL_RUNs','integer_model_infer_ns','driver_ns','core_invoke_ns','head_invoke_ns')}for v in called]
    row=dict(frame_id=head['frame_id'],stream_id=head['stream_id'],timestamp_us=head['timestamp_us'],source_pixels_sha256=head['source_pixels_sha256'],input_sha256=head['input_sha256'],state_before=state_before,state=segmenter.state,event=event,last_committed_result=segmenter.last_result,actual_NN_PL_RUN=jobs,TCN_RUN=jobs,profiles_jobs_delta=delta,trace=compact,complete_ns=done-started,source_frame_count=len(segmenter.frames),processed_sequence=ff['processed_sequence'],preformed_old_window_used=False,old_coordinate_substitution=False)
    r['current_frames']=r['current_frames'][-7:];r['current_frames'].append(row);r['TCN_RUN']=sum(v[0]for v in after.values());save()
    reply=dict(operation='current_frame_result',session_id=cfg['session_id'],**{k:row[k]for k in('frame_id','stream_id','timestamp_us','source_pixels_sha256','input_sha256','state_before','state','actual_NN_PL_RUN','TCN_RUN','profiles_jobs_delta','trace','complete_ns','source_frame_count','processed_sequence','preformed_old_window_used','old_coordinate_substitution')},event=event_summary(event),last_committed_result=event_summary(segmenter.last_result),numeric_reference_available=False)
    send_packet(conn,session_key,reply);row['reply_sent_ns']=ns();trace.clear();save()
  if not closed:raise RuntimeError('Persistent session ended without authenticated close')
  r['status']='Q_LIVE_SESSION_CLOSED_HEALTHY'
 except GracefulStop:r['status']='EXPLICIT_STOP_FINAL_COUNTS_RETAINED';r['explicit_stop_requested']=True
 except BaseException as exc:r['errors'].append(type(exc).__name__+': '+str(exc));r['traceback']=traceback.format_exc();r['status']='FAILED_ROWS_RETAINED'
 finally:
  if conn:conn.close()
  if sock:sock.close()
  if backend:
   try:r['final_hand_stats']=stats();r['actual_NN_PL_RUN']=r['final_hand_stats'][0]
   except BaseException as exc:r['Hand_RUN_count_complete']=False;r['errors'].append('Handstats:'+str(exc))
  if tcn:
   try:r['final_tcn_stats']=tcn_stats();r['TCN_RUN']=sum(v[0]for v in r['final_tcn_stats'].values());tcn.close()
   except BaseException as exc:r['TCN_RUN_count_complete']=False;r['errors'].append('TCNclose:'+str(exc))
  if backend:
   try:backend.close()
   except GracefulStop:r['status']='EXPLICIT_STOP_FINAL_COUNTS_RETAINED';r['explicit_stop_requested']=True
   except BaseException as exc:r['errors'].append('Handclose:'+str(exc))
  r['all_device_fds_closed']=not fds();r['Hand_calls_admitted']=policy.hand_calls;r['current_frames_admitted']=policy.current_calls;r['capture_frames_admitted']=policy.capture_frames;r['all_admitted_frames_finalized']=all(item['current_done']for item in policy.frames.values());save()
 if r['errors']or not r['all_device_fds_closed']:raise SystemExit(1)
if __name__=='__main__':main()
