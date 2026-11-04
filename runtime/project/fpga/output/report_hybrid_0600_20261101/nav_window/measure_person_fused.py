"""Eight actual TIM9 frames, resident integer Nav Person, authenticated PC GPU/board merge and real HDMI ACK. No image persistence."""

from pathlib import Path

import argparse,ctypes as C,hashlib,json,os,socket,time,sys,traceback

import numpy as np

import signal

from rpc_protocol import send_packet,recv_packet

from clock_observer import ClockObserver

from nav_live_display import LiveDisplay

H=Path(__file__).resolve().parent

ns=time.monotonic_ns

sha=lambda b:hashlib.sha256(b).hexdigest()

class Box(C.Structure):

 _fields_=[(k,C.c_int32)for k in('x1','y1','x2','y2','score_q15','cate')]+[(k,C.c_uint32)for k in('score_q30','ordinal')]

def main():

 ap=argparse.ArgumentParser();ap.add_argument('--execute',action='store_true');ap.add_argument('--lib');ap.add_argument('--fixture');ap.add_argument('--expected-boot');ap.add_argument('--qualified-manifest');ap.add_argument('--fresh-context');ap.add_argument('--output');ap.add_argument('--rounds',type=int,default=8);ap.add_argument('--cpu',type=int,default=1);ap.add_argument('--nice',type=int,default=-15);ap.add_argument('--drm-fd',type=int);ap.add_argument('--startup-lock-libraries',action='store_true');a=ap.parse_args()

 if not a.execute:print(json.dumps({'plan_only':True,'NN_RUN':0}));return

 assert a.drm_fd>=3

 stop=[False]

 signal.signal(signal.SIGTERM,lambda *_:stop.__setitem__(0,True));signal.signal(signal.SIGINT,lambda *_:stop.__setitem__(0,True))

 r=dict(status='STARTUP',rounds=[],failures=[],actual_NN_PL_RUN=0,PL_RUN_count_known=True,business_messages_sent=0,business_bytes_sent=0,PS_NN_MAC=0,source_scope='live_local_PC_RAM',model_warmup_RUN=0,new_sensor_capture_authorized=True,persistent_images_created=False,dynamic_frame_numeric_oracle_available=False);d=display=camera=listener=rpc=key_listener=None;opened=False;out=Path(a.output)

 def save():

  temp=out.with_suffix(out.suffix+'.tmp');temp.write_text(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8');os.replace(temp,out)

 def stats():

  v=(C.c_uint64*8)();assert d.yp_pl_stats(v)==8;return list(v)

 def owners():

  z=[]

  for p in Path('/proc/self/fd').iterdir():

   try:

    if os.readlink(p)=='/dev/gesture-nav-yolo-fused0':z.append(int(p.name))

   except OSError:pass

  return z

 try:

  boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();assert boot==a.expected_boot;q=json.loads(Path(a.qualified_manifest).read_text());context=json.loads(Path(a.fresh_context).read_text());assert q['qualified'] and context['candidate_loaded_by_current_window'] and context['boot_id']==boot and context['candidate_bit_sha256']==q['bit_sha256'] and context['candidate_hwh_sha256']==q['hwh_sha256'] and context['controller_pid']==os.getppid() and 0<=ns()-context['loaded_monotonic_ns']<=300000000000

  assert sha(Path(a.lib).read_bytes())==q['lib_sha256'];assert Path('/sys/class/fpga_manager/fpga0/state').read_text().strip()=='operating';os.sched_setaffinity(0,{a.cpu});os.nice(a.nice);r['process_scheduling']=dict(affinity=sorted(os.sched_getaffinity(0)),nice=os.getpriority(os.PRIO_PROCESS,0),policy=os.sched_getscheduler(0))

  observer=ClockObserver(a.drm_fd,out.parent/'original_mode.bin');assert observer.matches()

  pins={'/home/root/gesture-capture-time-v8/timed_camera.py':'a68fe119ad2696fda1c693de20c2779fa9332a8dbd3ad5396986bcd199a43bc8','/home/root/gesture-capture-time-v8/libcamera_timed_arm.so':'c981f26b23f783b245a2a0831f02d9c3b8d0945fe68534b6f539a08147b62cc2'}

  for p,v in pins.items():assert sha(Path(p).read_bytes())==v

  sys.path.insert(0,'/home/root/gesture-capture-time-v8');from timed_camera import TimedCameraReader

  from integer_image import IntegerImage

  image=IntegerImage();camera=TimedCameraReader('/run/medcomm/camera.frame',fresh_on_open=True,stall_seconds=3.)

  d=C.CDLL(a.lib);d.yp_infer.argtypes=[C.c_void_p,C.c_int,C.c_int,C.POINTER(Box),C.c_int];d.yp_copy_heads.argtypes=[C.c_void_p];d.yp_infer_q.argtypes=[C.c_void_p,C.c_int,C.c_int,C.c_int,C.POINTER(Box),C.c_int];d.yp_pl_all_layer_stats.argtypes=[C.c_void_p,C.c_int];d.yp_pl_error.restype=C.c_char_p;d.yp_pl_backend.restype=C.c_char_p;assert d.yp_pl_backend()==b'NAV_DELIVERY_FUSED_INT8_ABI31_ALL79_MAC_NO_PS_FALLBACK';d.yp_prefault_workspace.argtypes=[];d.yp_prefault_workspace.restype=C.c_int;assert d.yp_prefault_workspace()==1861564;assert d.yp_prepare_pl_weights()==79;assert d.yp_pl_open()==0;opened=True;assert len(owners())==1

  if a.startup_lock_libraries:

   from startup_residency import lock_library_mappings

   r['startup_library_residency']={};lock_library_mappings(str(Path(a.lib).resolve()),r['startup_library_residency'])

  layers_before=np.empty((79,20),np.uint64);layers_after=np.empty_like(layers_before)

  kp=out.parent/'session_key.sock';assert not kp.exists();key_listener=socket.socket(socket.AF_UNIX);key_listener.bind(str(kp));os.chmod(kp,0o600);key_listener.listen(1);key_listener.settimeout(120);r['rpc_status']='WAIT_IN_MEMORY_KEY';save();kc,_=key_listener.accept();kc.settimeout(10);key=b''

  while len(key)<32:

   b=kc.recv(32-len(key));assert b;key+=b

  kc.close();key_listener.close();key_listener=None;kp.unlink();listener=socket.socket();listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);listener.bind(('192.168.1.10',5104));listener.listen(1);listener.settimeout(600);r['rpc_status']='READY';save();rpc,peer=listener.accept();assert peer[0]=='192.168.1.100';rpc.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1);session=None;last=-1

  ordinal=0

  r['status']='REALTIME_RUNNING';save()

  while not stop[0]:

   h,body=recv_packet(rpc,key,timeout=600,max_body=0)

   if h.get('operation')=='close':

    assert not body and type(h.get('session_id'))is str and 1<=len(h['session_id'])<=128;session=session or h['session_id'];assert h['session_id']==session;send_packet(rpc,key,dict(operation='closed',session_id=session,actual_NN_PL_RUN=r['actual_NN_PL_RUN']));break

   assert h['operation']=='capture' and not body;session=session or h['session_id'];assert h['session_id']==session

   if display is None:display=LiveDisplay(a.drm_fd,session,observer);r['display_setup']=display.start();save()

   selected=ns();frame=camera.read(timeout=3);meta=dict(frame.metadata);fid=int(meta['source_sequence']);capture=int(meta['capture_complete_monotonic_ns']);observed=int(meta['observed_monotonic_ns']);assert fid>last and meta['capture_timestamp_tag']=='TIM9' and meta['capture_provenance_available'] and meta['kernel_queue_delay_included'];last=fid;original=np.ascontiguousarray(frame.bgr);assert original.shape==(480,800,3);pixels=original.tobytes();source=dict(frame_id=fid,capture_ns=capture,observed_ns=observed,process_start_ns=selected);identity=dict(stream_id=session,frame_id=fid,timestamp_ms=capture//1000000);row=dict(frame_id=fid,camera=meta,capture_select_started_ns=selected,raw_pixels_ready_ns=ns());r['rounds'].append(row)

   capture_wire_token=send_packet(rpc,key,dict(operation='capture_result',session_id=session,boot_id=boot,display_state_root=str(display.root),frame_id=fid,timestamp_us=capture//1000,camera=meta,shape=[480,800,3],dtype='uint8',source_transport='HMAC_authenticated_original_BGR800x480_native_report_inference'),pixels).hex();row['capture_reply_sent_ns']=ns();r['rounds']=r['rounds'][-8:];r['selected_frames']=ordinal+1;save()

   h,body=recv_packet(rpc,key,timeout=600,max_body=110592);assert h['operation']=='person_q' and h['session_id']==session and h['frame_id']==fid and len(h['source_pixels_sha256'])==64 and h['pixel_derivation']=='native_BGR800x480_v1' and h['shape']==[192,192,3]and h['dtype']=='int8'and len(body)==110592 and sha(body)==h['input_sha256']and observer.matches();assert h['capture_wire_token']==capture_wire_token and h['timestamp_us']==capture//1000 and len(bytes.fromhex(h['capture_pixels_sha256']))==32;capture_sha=h['capture_pixels_sha256'];digest=h['source_pixels_sha256'];assert sha(pixels)==capture_sha==digest and h['parent_size']==[800,480];source.update(capture_sha256=capture_sha,logical_sha256=digest);row.update(source_pixels_sha256=digest,capture_pixels_sha256=capture_sha,original_payload_authentication=capture_wire_token,original_SHA_computed_by_authenticated_PC=True);before=stats();assert d.yp_pl_all_layer_stats(layers_before.ctypes.data,layers_before.size)==1580;boxes=(Box*32)();heads=np.empty(d.yp_head_bytes(),np.int8);qinput=np.frombuffer(body,np.int8);start=ns();count=d.yp_infer_q(qinput.ctypes.data,110592,800,480,boxes,32);end=ns();assert count>=0,d.yp_pl_error();after=stats();assert after[1]-before[1]==79 and after[0]-before[0]==79 and after[7]-before[7]==31650912 and after[5]-before[5]==849132;assert d.yp_copy_heads(heads.ctypes.data)==heads.size

   assert d.yp_pl_all_layer_stats(layers_after.ctypes.data,layers_after.size)==1580;delta=layers_after[:,:16]-layers_before[:,:16];assert np.all(delta[:,:3]==1)and np.all(delta[:,13]==layers_after[:,19])and np.all(delta[:,14:16]==0)and np.all(delta[:,8]==0);row['all79_native_guards_and_layer_counters_pass']=True

   row.update(complete_Person_wall_ns=end-start,infer_start_ns=start,infer_end_ns=end,actual_NN_PL_RUN=79,owner_stats_delta=[b-a for a,b in zip(before,after)],six_heads_sha256=sha(heads.tobytes()),boxes_Q16=[{k:getattr(b,k)for k,_ in Box._fields_}for b in boxes[:count]],dynamic_heads_frozen_oracle_exact=None);r['actual_NN_PL_RUN']+=79

   send_packet(rpc,key,dict(operation='person_result',session_id=session,frame_id=fid,source_pixels_sha256=digest,actual_NN_PL_RUN=79,six_heads_sha256=row['six_heads_sha256'],boxes_Q16=row['boxes_Q16'],complete_Person_wall_ns=end-start));save()

   h,body=recv_packet(rpc,key,timeout=600,max_body=4+65536);assert h['operation']=='display' and h['session_id']==session and h['frame_id']==fid and h['source_pixels_sha256']==digest;n=int.from_bytes(body[:4],'big');assert 0<n<=65536 and len(body)==4+n;metadata_bytes=body[4:4+n];assert sha(metadata_bytes)==h['input_sha256'];result=json.loads(metadata_bytes);assert result['identity']==identity and result['source_pixels_sha256']==digest and len(bytes.fromhex(h['retained_capture_sha256']))==32;assert h['retained_capture_sha256']==source['capture_sha256']==sha(pixels);inferred=ns();

   messages=result.get('business_messages',[]);assert len(messages)<=3
   business_bytes=business_count=0

   with socket.socket(socket.AF_INET,socket.SOCK_DGRAM)as business:

    for message in messages:

     message['posture_age_ms']=max(0,(ns()-capture)//1000000);assert message['protocol']=='SGR1'and message['source']=='board_tcn'and message['frame_id']==fid and message['source_pixels_sha256']==digest;encoded=json.dumps(message,separators=(',',':'),ensure_ascii=True).encode();assert len(encoded)<=8192;sent=business.sendto(encoded,('127.0.0.1',5005));assert sent==len(encoded);business_bytes+=sent;business_count+=1

   result_meta=dict(overlay=result['overlay'],TCN_state=result['TCN']['state'],word_event=result['TCN'].get('event'),actual_body_RUN=result.get('actual_body_RUN',0),actual_hand_TCN_RUN=result.get('actual_hand_TCN_RUN',0));shown=display.present(original,source,identity,inferred,result_meta,validated_composite_sha256=h['retained_capture_sha256']);r['business_messages_sent']+=business_count;r['business_bytes_sent']+=business_bytes;shown.update(business_messages_sent=r['business_messages_sent'],business_bytes_sent=r['business_bytes_sent']);row.update(display=shown,capture_EOF_to_framebuffer_copy_ms=shown['capture_EOF_to_framebuffer_copy_ns']/1e6,status='DISPLAYED_CURRENT_SOURCE',TCN=result['TCN']);send_packet(rpc,key,dict(operation='display_result',session_id=session,frame_id=fid,source_pixels_sha256=digest,**shown));save();assert observer.matches();ordinal+=1

  r['status']='NAV_YOLO79_LIVE_INTEGER_SCOPE_COMPLETE'

 except BaseException as e:r['status']='FAILED_RETAINED';r['failures'].append(type(e).__name__+': '+str(e));r['traceback']=traceback.format_exc()

 finally:

  for c in (rpc,listener,key_listener):

   if c:c.close()

  if camera:

   try:camera.close()

   except BaseException as e:r['failures'].append('camera_close:'+str(e))

  if display:

   try:r['display_restore']=display.close()

   except BaseException as e:r['failures'].append('display_restore:'+str(e))

  if opened:

   try:r['owner_stats_before_close']=stats();r['actual_NN_PL_RUN']=r['owner_stats_before_close'][1];r['close_status']=d.yp_pl_close();r['owner_FDs_after_close']=owners();r['owner_closed']=r['close_status']==0 and not r['owner_FDs_after_close']

   except BaseException as e:r['failures'].append('native_close:'+str(e));r['PL_RUN_count_known']=False

  try:r['module_refs_after_close']=int(Path('/sys/module/gesture_nav_yolo_fused_v31/refcnt').read_text())

  except BaseException:r['module_refs_after_close']=None

  r['owner_closed_healthy']=r.get('owner_closed',False)and r['module_refs_after_close']==0;r['hardware_RUN']=r['actual_NN_PL_RUN'];r['quarantine_ref_present']=r['module_refs_after_close']is None or r['module_refs_after_close']>0

  if r['failures']or not r['owner_closed_healthy']:r['status']='FAILED_RETAINED'

  save()

 if r['status']!='NAV_YOLO79_LIVE_INTEGER_SCOPE_COMPLETE':raise SystemExit(1)

if __name__=='__main__':main()

