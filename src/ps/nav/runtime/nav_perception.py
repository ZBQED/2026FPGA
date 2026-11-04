"""Finite same-frame perception; optional Q semantic pipeline after Hand21 review."""
from pathlib import Path
import sys
sys.path.append('/opt/gesture-tcn-20261022/stdlib_compat')
import concurrent.futures,hashlib,json,socket,time,traceback
import numpy as np
import cv2
from timed_camera import TimedCameraReader
from rpc_protocol import send_packet,recv_packet
from feature_transport import unpack_features
from perception_geometry import Geometry
from drm_scanout import NativeScanoutObserver
from nav_live_display import LiveDisplay
from stable_hand_roi import StableHandROI
H=Path(__file__).resolve().parent


def main():
    cfg=json.load(sys.stdin);key=bytes.fromhex(cfg.pop('key'));session=cfg['session_id']
    semantic_enabled=bool(cfg.get('tcn_enabled'))
    offline=bool(cfg.get('offline_roi'))
    balanced=bool(cfg.get('balanced'))
    pc_front=bool(cfg.get('pc_front'));assert not pc_front or semantic_enabled
    fpga_heads=bool(cfg.get('fpga_heads'));assert not fpga_heads or pc_front
    nav_body_post=bool(cfg.get('nav_body_post'));assert not nav_body_post or fpga_heads
    late_display=bool(cfg.get('late_display'));assert not late_display or fpga_heads
    overlap_seal=bool(cfg.get('overlap_seal'));assert not overlap_seal or late_display
    pc_hands=bool(cfg.get('pc_hands'));assert not pc_hands or fpga_heads
    q_parallel=bool(cfg.get('q_parallel'));assert not q_parallel or(nav_body_post and late_display and not pc_hands)
    roi_tracker=StableHandROI()if cfg.get('reuse_roi')else None
    assert roi_tracker is None or (fpga_heads and not pc_hands)
    r=dict(status='STARTING',rows=[],errors=[],PC_core_inference=int(pc_front),PC_Hand_RUN=0,PC_TCN_RUN=0,TCN_RUN=0,
           physical_camera_opened=False,full_frame_acceptance=False,latency_target_ms=200,
           person_backend='PYNQ 79 PL convolutions, board requantization; Nav preprocessing/decoding only',other_models='Q/P PL with board PS operators')
    r['source_scope']='fixed_fixture'if offline else'live_nav_ram'
    camera=display=observer=nav_heads=geometry=None;sockets=[];indices=[0,0,0]
    try:
        geometry=Geometry(H)
        deadline=time.monotonic()+90
        for address in('192.168.1.30','192.168.1.20'):
            while True:
                try:conn=socket.create_connection((address,5115),timeout=2);break
                except OSError:
                    if time.monotonic()>deadline:raise
                    time.sleep(.2)
            conn.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1);sockets.append(conn)
            send_packet(conn,key,dict(operation='hello',session_id=session));reply,body=recv_packet(conn,key,timeout=10)
            assert reply['operation']=='ready' and not body
        if pc_front:
            with socket.socket()as listener:
                listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);listener.bind(('192.168.1.10',5116));listener.listen(1);listener.settimeout(45)
                conn,peer=listener.accept()
            conn.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1);sockets.append(conn)
            send_packet(conn,key,dict(operation='hello',session_id=session));reply,body=recv_packet(conn,key,timeout=15)
            assert reply['operation']=='ready'and not body
            r.update(person_backend='PC original YOLO-FastestV2 INT8 192; exact E:/ZYNQ_GPT_YOLO realtime source',other_models='PC full Palm/Body; Q/P FPGA full Hands and Q FPGA TCN')
        if fpga_heads:
            from nav_head_runtime import NavHeads
            nav_heads=NavHeads(H)
            r.update(person_backend='Q FPGA all 79 original YOLO convolutions; board requantization',other_models='Nav FPGA Palm/Body output convolutions; PC remaining prefixes and postprocessing; Q/P FPGA Hands; Q FPGA TCN',PC_Person_RUN=0,PC_PalmBody_output_convolutions=0)
            if pc_hands:r.update(person_backend='P FPGA all 79 original YOLO convolutions; board requantization',other_models='Nav FPGA Palm/Body output convolutions; Q FPGA TCN; PC remaining prefixes, original FullHand and postprocessing')
        observer=NativeScanoutObserver(H/'liblive_integer_frame.so');display=LiveDisplay(observer.fd,session,observer,touch_mode='inherit');r['display_start']=display.start()
        r['display_scan_topology']=observer.topology
        if offline:
            fixed_bytes=(H/'fixed_frame.bin').read_bytes()
            assert len(fixed_bytes)==1152000 and hashlib.sha256(fixed_bytes).hexdigest()==cfg['fixed_frame_sha256']
        else:camera=TimedCameraReader('/run/medcomm/camera.frame',fresh_on_open=True,stall_seconds=3.)
        def rpc(index,op,x,common):
            packing_started=time.monotonic_ns()
            semantic=op=='semantic_frame';json_result=semantic or op in('vision_jpeg','palm_heads','body_heads')
            raw=json.dumps(x,separators=(',',':'),allow_nan=False).encode()if semantic else b''if x is None else np.ascontiguousarray(x).tobytes();request=indices[index];indices[index]+=1
            head=dict(operation=op,session_id=session,request_index=request,input_sha256=hashlib.sha256(raw).hexdigest(),
                      shape=[]if x is None or semantic else list(x.shape),dtype='json'if semantic else'int8',**common)
            start=time.monotonic_ns();send_packet(sockets[index],key,head,raw);sent=time.monotonic_ns()
            reply,body=recv_packet(sockets[index],key,timeout=60,max_body=2097152 if index==2 else 300000)
            received=time.monotonic_ns();assert reply['operation']=='result' and reply['request_index']==request
            for field in('frame_id','source_identity_sha256','input_sha256'):assert reply[field]==head[field]
            assert reply['source_capture_ns']==common['capture_ns'] and reply['output_sha256']==reply['_authenticated_body_sha256']
            expected='json'if json_result else'bytes'if op=='person_hand'else'int8'if op=='person'else'float32';assert reply['output_dtype']==expected
            value=json.loads(body)if json_result else unpack_features(body,reply['feature_encoding'],sum(reply['feature_sizes']))if op=='vision_features'else np.frombuffer(body,np.int8 if op in('person','person_hand')else'<f4')
            done=time.monotonic_ns()
            return value,dict(start_after_input_ns=packing_started-common['capture_ns'],done_after_input_ns=done-common['capture_ns'],roundtrip_ns=done-start,packing_ns=start-packing_started,send_ns=sent-start,wait_receive_ns=received-sent,decode_ns=done-received,remote=reply)
        recent_person=None;body_person_prior=None
        def hand_rpc(board,original,detection,common,person_future=None,prepared=None):
            start=time.monotonic_ns();hand=geometry.hand_input(original,detection)if detection is not None and prepared is None else None
            preprocess_ns=time.monotonic_ns()-start
            if prepared is not None:hand,preprocess_ns=prepared
            if person_future is not None:person_future.result()
            values,timing=rpc(board,'hand'if detection is not None else'skip_hand',hand,common)
            timing['preprocess_ns']=preprocess_ns
            return values,timing
        def person_and_body_input(original, person_input, common, preprocess_ns, skip_body=False):
            nonlocal recent_person
            heads,timing=rpc(1,'person',person_input,common)
            start=time.monotonic_ns();boxes=geometry.person_decode(heads,original.shape)
            timing.update(preprocess_ns=preprocess_ns,decode_ns=time.monotonic_ns()-start)
            prepared=None;body_preprocess_ns=0
            box=None
            if boxes:
                box=max(boxes,key=lambda b:b[4]*(b[2]-b[0])*(b[3]-b[1]));recent_person=(list(box),dict(common))
            elif recent_person and 0<common['capture_ns']-recent_person[1]['capture_ns']<=3000000000:
                box=recent_person[0]
            timing['body_roi_source']='current_detection'if boxes else'recent_detection_current_pixels'if box is not None else'none'
            if box is not None and not skip_body:
                timing.update(body_roi_detection_frame_id=recent_person[1]['frame_id'],body_roi_age_ns=common['capture_ns']-recent_person[1]['capture_ns'])
                start=time.monotonic_ns()
                prepared=geometry.body_input(original,box);body_preprocess_ns=time.monotonic_ns()-start
                if prepared is None:recent_person=None
            return boxes,timing,prepared,body_preprocess_ns
        with concurrent.futures.ThreadPoolExecutor(max_workers=3 if overlap_seal else 2)as pool:
            last=-1
            started=time.monotonic();duration=float(cfg.get('duration_s',0));limit=1024 if duration else 48 if semantic_enabled else 8
            if offline:limit=24
            for ordinal in range(limit):
                if duration and ordinal and time.monotonic()-started>=duration:break
                if offline:
                    fid=ordinal+1;capture=time.monotonic_ns();source_bytes=fixed_bytes
                    meta=dict(source_sequence=fid,fixture_input_ready_monotonic_ns=capture,source_scope='fixed_fixture',capture_provenance_available=False,repeated_identical_fixture=True)
                else:
                    frame=camera.read(timeout=3);meta=frame.metadata;fid=int(meta['source_sequence']);capture=meta['capture_complete_monotonic_ns']
                    assert meta['capture_timestamp_tag']=='TIM9' and meta['capture_provenance_available']
                    source_bytes=frame.bgr.tobytes()
                assert fid>last;last=fid
                original=np.frombuffer(source_bytes,np.uint8).reshape(480,800,3);observed=time.monotonic_ns()
                hash_future=None if late_display else pool.submit(display.prepare,source_bytes,fid,capture);prepared_pair=None
                identity=hashlib.sha256(json.dumps([session,fid,capture],separators=(',',':')).encode()).hexdigest()
                common=dict(frame_id=fid,capture_ns=capture,source_identity_sha256=identity)
                pc_timing=None;pc_value=None
                tracked=False;roi_policy=dict(mode='current_Palm_detection',Palm_RUN=1)
                combined_future=None
                if fpga_heads:
                    prep=time.monotonic_ns();person_input=geometry.person_input(original);person_preprocess_ns=time.monotonic_ns()-prep
                    cached=None
                    if roi_tracker:cached,roi_policy=roi_tracker.select(capture)
                    tracked=cached is not None
                    person_future=None if q_parallel and tracked else pool.submit(rpc,1 if pc_hands else 0,'person',person_input,common)
                    if tracked:
                        detections=cached
                        pf=pool.submit(hand_rpc,1,original,detections[0],common)
                        q_prepared=None
                        if late_display:
                            prep=time.monotonic_ns();q_input=geometry.hand_input(original,detections[1]);q_prepared=(q_input,time.monotonic_ns()-prep)
                        if q_parallel:
                            assert q_prepared is not None
                            combined_future=pool.submit(rpc,0,'person_hand',np.concatenate((person_input.ravel(),q_input.ravel())),common);qf=None
                        else:qf=pool.submit(hand_rpc,0,original,detections[1],common,person_future,q_prepared)
                    if overlap_seal:hash_future=pool.submit(display.prepare,source_bytes,fid,capture)
                    start=time.monotonic_ns();small=cv2.resize(original,(400,240));ok,jpeg=cv2.imencode('.jpg',small,[cv2.IMWRITE_JPEG_QUALITY,95]);assert ok
                    jpeg_encode_ns=time.monotonic_ns()-start
                    features,pc_timing=rpc(2,'vision_features',jpeg,dict(common,skip_palm=tracked,body_person_prior=body_person_prior));sizes=pc_timing['remote']['feature_sizes'];palm_count=0 if tracked else len(nav_heads.params['palm']);assert len(sizes)==palm_count+1 and sum(sizes)==features.size
                    r['PC_PalmBody_output_convolutions']+=pc_timing['remote']['PC_PalmBody_output_convolutions']
                    split=np.split(features,np.cumsum(sizes)[:-1])
                    if tracked:
                        pt=dict(backend='stable_ROI_reuse_current_pixels',PL_jobs=0,complete_call_ns=0,**roi_policy);pd=dict(roundtrip_ns=0)
                    else:
                        palm,pt=nav_heads.infer('palm',split[:palm_count]);detected,pd=rpc(2,'palm_heads',palm,common)
                        detections=detected['detections']
                        for detection in detections:detection['transform']=np.asarray(detection['transform'],np.float32)
                    hands=[];hand_timing=[]
                    if pc_hands:
                        inputs=np.stack([geometry.hand_input(original,d)for d in detections])if detections else np.empty((0,224,224,3),np.int8)
                        hand_future=pool.submit(rpc,2,'hand_inputs',inputs,common)
                        heatmaps,bt=nav_heads.infer('body',split[palm_count:])
                        values,timing=hand_future.result();assert values.size==44*len(detections)
                        for j,d in enumerate(detections):
                            hands.append(geometry.hand_decode(values[j*44:(j+1)*44],d));hand_timing.append(dict(backend='PC_original_FullHand',shared_roundtrip_ns=timing['roundtrip_ns'],**timing['remote']['hand_stats'][j]))
                        r['PC_Hand_RUN']+=len(detections)
                    else:
                        if not tracked:
                            pf=pool.submit(hand_rpc,1,original,detections[0]if detections else None,common)
                            qf=pool.submit(hand_rpc,0,original,detections[1],common,person_future)if len(detections)>1 else None
                        heatmaps,bt=nav_heads.infer('body',split[palm_count:])
                    if combined_future is None:
                        person_raw,person_timing=person_future.result();boxes=geometry.person_decode(person_raw,original.shape);person_timing['preprocess_ns']=person_preprocess_ns
                    if nav_body_post:
                        post_started=time.monotonic_ns();prepared=pc_timing['remote']['body_prepared']
                        body=geometry.body_decode(heatmaps,(None,dict(im_shape=np.asarray(prepared['im_shape'],np.float32)),np.asarray(prepared['expanded'])))
                        body[:,:2]*=2;body[~np.isfinite(body).all(1)]=0
                        decoded=dict(roi_source=pc_timing['remote']['roi_source'])
                        bd=dict(roundtrip_ns=0,Nav_postprocess_ns=time.monotonic_ns()-post_started,PC_Body_postprocess_RUN=0,heatmap_bytes_not_sent=heatmaps.nbytes)
                        if combined_future is None and boxes:body_person_prior=[max(boxes,key=lambda b:b[4]*(b[2]-b[0])*(b[3]-b[1])),capture]
                    else:
                        decoded,bd=rpc(2,'body_heads',heatmaps,dict(common,person_boxes=boxes));body=np.asarray(decoded['body'],np.float32)
                    pc_timing.update(jpeg_encode_ns=jpeg_encode_ns,jpeg_bytes=jpeg.size,palm_postprocess=pd,body_postprocess=bd,source_transform='JPEG95 400x240 for PC prefixes; FPGA Hand crops and HDMI retain original 800x480 pixels')
                    pc_value=dict(model_sha256={n:v['source_sha256']for n,v in nav_heads.manifest['models'].items()})
                    if pc_hands:pc_value['model_sha256']['hand']=timing['remote']['hand_model_sha256']
                    bt['roi_source']=decoded['roi_source'];palm_decode_ns=pd['roundtrip_ns'];body_preprocess_ns=0;body_decode_ns=bd['roundtrip_ns']
                    if late_display and not overlap_seal:prepared_pair=display.prepare(source_bytes,fid,capture)
                    if combined_future is not None:
                        packet,combined_timing=combined_future.result();reply=combined_timing['remote'];stats=reply['stats'];n=stats['person_bytes']
                        assert n==17100 and stats['hand_values']==44 and packet.size==n+44*4
                        person_raw=packet[:n];values=np.frombuffer(packet[n:].tobytes(),'<f4')
                        def component_timing(name,input_array,output_array,preprocess):
                            return dict(shared_start_after_input_ns=combined_timing['start_after_input_ns'],shared_done_after_input_ns=combined_timing['done_after_input_ns'],shared_roundtrip_ns=combined_timing['roundtrip_ns'],preprocess_ns=preprocess,
                                remote=dict(frame_id=fid,source_capture_ns=capture,source_identity_sha256=identity,
                                    input_sha256=hashlib.sha256(input_array.tobytes()).hexdigest(),output_sha256=hashlib.sha256(output_array.tobytes()).hexdigest(),stats=stats[name],
                                    authenticated_compound_output_sha256=reply['output_sha256'],authenticated_compound_input_sha256=reply['input_sha256']))
                        person_timing=component_timing('Person',person_input,person_raw,person_preprocess_ns)
                        timing=component_timing('Hand',q_input,values,q_prepared[1]);timing['combined_call_ns']=stats['complete_call_ns']
                        boxes=geometry.person_decode(person_raw,original.shape)
                        if boxes:body_person_prior=[max(boxes,key=lambda b:b[4]*(b[2]-b[0])*(b[3]-b[1])),capture]
                        hands.append(geometry.hand_decode(values,detections[1]));hand_timing.append(timing)
                    if not pc_hands and qf:
                        values,timing=qf.result();hands.append(geometry.hand_decode(values,detections[1]));hand_timing.append(timing)
                    if not pc_hands:
                        values,timing=pf.result()
                        if detections:hands.append(geometry.hand_decode(values,detections[0]));hand_timing.append(timing)
                    if roi_tracker:roi_tracker.update(detections,hands,fid,capture,tracked)
                elif pc_front:
                    start=time.monotonic_ns();small=cv2.resize(original,(400,240));ok,jpeg=cv2.imencode('.jpg',small,[cv2.IMWRITE_JPEG_QUALITY,95]);assert ok
                    jpeg_encode_ns=time.monotonic_ns()-start
                    pc_value,pc_timing=rpc(2,'vision_jpeg',jpeg,common)
                    assert pc_value['PC_Hand_RUN']==pc_value['PC_TCN_RUN']==0
                    pc_timing.update(jpeg_encode_ns=jpeg_encode_ns,jpeg_bytes=jpeg.size,source_transform=pc_value['source_transform'])
                    boxes=pc_value['boxes'];body=np.asarray(pc_value['body'],np.float32);detections=pc_value['detections']
                    for detection in detections:detection['transform']=np.asarray(detection['transform'],np.float32)
                    stat=pc_value['stats'];person_timing=dict(backend='PC',complete_call_ns=stat['person_ns'])
                    pt=dict(backend='PC',complete_call_ns=stat['palm_ns']);bt=dict(backend='PC',complete_call_ns=stat['body_ns'],roi_source=pc_value['roi_source'])if pc_value['body_run']else None
                    palm_decode_ns=stat['palm_decode_ns'];body_preprocess_ns=stat['body_preprocess_ns'];body_decode_ns=stat['body_decode_ns']
                    hands=[];hand_timing=[]
                    pf=pool.submit(rpc,1,'hand'if detections else'skip_hand',geometry.hand_input(original,detections[0])if detections else None,common)
                    qf=pool.submit(rpc,0,'hand',geometry.hand_input(original,detections[1]),common)if len(detections)>1 else None
                    if qf:
                        values,timing=qf.result();hands.append(geometry.hand_decode(values,detections[1]));hand_timing.append(timing)
                    values,timing=pf.result()
                    if detections:hands.append(geometry.hand_decode(values,detections[0]));hand_timing.append(timing)
                else:
                    prep=time.monotonic_ns();person_input=geometry.person_input(original);person_preprocess_ns=time.monotonic_ns()-prep
                    cached=recent_person if balanced and recent_person and 0<capture-recent_person[1]['capture_ns']<=3000000000 else None
                    cached_prepared=None;cached_preprocess_ns=0
                    if cached:
                        prep=time.monotonic_ns();cached_prepared=geometry.body_input(original,cached[0]);cached_preprocess_ns=time.monotonic_ns()-prep
                    person_future=pool.submit(person_and_body_input,original,person_input,common,person_preprocess_ns,cached_prepared is not None)
                    body_future=None
                    if balanced:
                        if cached_prepared is not None:body_future=pool.submit(rpc,0,'body',cached_prepared[0],common)
                        boxes,person_timing,prepared,body_preprocess_ns=person_future.result()
                        if body_future is not None:
                            prepared=cached_prepared;body_preprocess_ns=cached_preprocess_ns
                            person_timing.update(body_roi_source='recent_detection_current_pixels',body_roi_detection_frame_id=cached[1]['frame_id'],body_roi_age_ns=capture-cached[1]['capture_ns'],body_started_before_person_result=True)
                        elif prepared is not None:body_future=pool.submit(rpc,0,'body',prepared[0],common)
                    prep=time.monotonic_ns();palm_input=geometry.palm_input(original);palm_preprocess_ns=time.monotonic_ns()-prep
                    palm,pt=rpc(1 if balanced else 0,'palm',palm_input,common);pt['preprocess_ns']=palm_preprocess_ns
                    prep=time.monotonic_ns();detections=geometry.palm_decode(palm,original.shape);palm_decode_ns=time.monotonic_ns()-prep;hands=[];hand_timing=[]
                    if not balanced:boxes,person_timing,prepared,body_preprocess_ns=person_future.result()
                    pf=pool.submit(rpc,1,'hand'if detections else'skip_hand',geometry.hand_input(original,detections[0])if detections else None,common)
                    qhand=geometry.hand_input(original,detections[1])if len(detections)>1 else None
                    body=np.zeros((17,3),np.float32);bt=None;body_decode_ns=0;body_heads=None
                    if prepared is not None:body_heads,bt=body_future.result()if balanced else rpc(0,'body',prepared[0],common)
                    # Only one request per board socket at a time. Decode Body on Nav
                    # while Q computes its Hand; P's Hand is already in flight.
                    qf=pool.submit(rpc,0,'hand',qhand,common)if qhand is not None else None
                    if body_heads is not None:
                        prep=time.monotonic_ns();body=geometry.body_decode(body_heads,prepared);body_decode_ns=time.monotonic_ns()-prep
                    if qf:
                        values,timing=qf.result();hands.append(geometry.hand_decode(values,detections[1]));hand_timing.append(timing)
                    values,timing=pf.result()
                    if detections:hands.append(geometry.hand_decode(values,detections[0]));hand_timing.append(timing)
                prepared_image,prepared_seal=prepared_pair if prepared_pair is not None else hash_future.result();digest=prepared_image.digest;source_hash_ns=prepared_image.hash_ns
                coordinates_done=time.monotonic_ns();semantic_result=semantic_timing=None
                if semantic_enabled:
                    body_safe=body.copy();body_safe[~np.isfinite(body_safe).all(1)]=0
                    hand_payload=[]
                    for hand in hands:
                        points=np.asarray(hand['points']);points[~np.isfinite(points).all(1)]=0
                        hand_payload.append(dict(points=points.tolist(),valid=hand['valid']))
                    semantic_result,semantic_timing=rpc(0,'semantic_frame',dict(image_size=[800,480],body=body_safe.tolist(),hands=hand_payload),common)
                    r['TCN_RUN']+=semantic_result['TCN_RUN']
                inferred=time.monotonic_ns()
                valid=(np.isfinite(body).all(1)&(body[:,2]>=.5)&(body[:,0]>=0)&(body[:,0]<800)&(body[:,1]>=0)&(body[:,1]<480)).tolist()
                hands=[h for h in hands if h['box'][2]>h['box'][0] and h['box'][3]>h['box'][1]]
                hands.sort(key=lambda h:h['points'][0][0])
                for j,h in enumerate(hands):h['color_side']='Right'if j==0 else'Left'
                tcn_state='TCN_NOT_STARTED'
                if semantic_result:
                    committed=semantic_result['last_committed_result']
                    tcn_state=committed['display_gesture']if committed else {'WAIT_REST':'请先放下双手','READY':'请做手势','ACTIVE':'识别中'}[semantic_result['state']]
                    if committed is None and semantic_result['rest_pose']is None:tcn_state='请露出双肩、髋部和双手'
                if offline:tcn_state='离线固定帧 | '+tcn_state
                overlay=dict(version=1,session_id=session,frame_id=fid,selected_ordinal=ordinal+1,source_pixels_sha256=digest,
                             body_points=body[:,:2].tolist(),body_valid=valid,body_aux=[],hands=hands,
                             person_boxes=[b[:4]for b in boxes],person_scores=[b[4]for b in boxes],tcn_state=tcn_state)
                source=dict(frame_id=fid,capture_ns=capture,observed_ns=observed,capture_sha256=digest,logical_sha256=digest)
                shown=display.present(original,source,dict(frame_id=fid,timestamp_ms=capture//1000000),inferred,
                                      dict(overlay=overlay,inference_placement='P_YOLO_Q_TCN_Nav_PalmBodyHeads_PC_FullHandsPrefixPostprocessing'if pc_hands else'Q_YOLO_Hand_TCN_P_Hand_Nav_PalmBodyHeads_PC_PrefixPostprocessing'if fpga_heads else'PC_PersonPalmBody_Q_P_Hands_Q_TCN_Nav_CameraHDMI'if pc_front else('Q_BodyHandPL_PYNQ_PersonPalmHandPL_Nav_GeometryDisplay_'if balanced else'Q_PalmBodyHandPL_PYNQ_PersonHandPL_Nav_GeometryDisplay_')+('Q_TCN'if semantic_enabled else'TCN_OFF')),digest,prepared_image=prepared_image,prepared_seal=prepared_seal)
                scan=observer.after_copy(int(shown['framebuffer_copy_ack']['framebuffer_copy_done_ns']))
                shown.update(scanout=scan,capture_EOF_to_confirmed_scanout_ns=scan['scanout_bound_ns']-capture,
                             framebuffer_copy_only=False,optical_latency_claimed=False)
                r['rows'].append(dict(frame_id=fid,camera=meta,source_sha256=digest,PC_front=pc_timing,PC_model_sha256=pc_value['model_sha256']if pc_value else None,Person=dict(boxes=boxes,**person_timing),
                                     Palm=pt,Body=bt,Hands=hand_timing,palm_detections=len(detections),body_valid=sum(valid),
                                     hand_valid=[sum(h['valid'])for h in hands],capture_EOF_to_coordinates_ns=coordinates_done-capture,
                                     hand_presence=[h['whole_hand_presence']for h in hands],body_points=body_safe.tolist()if semantic_enabled else body.tolist(),
                                     capture_EOF_to_all_inference_ns=inferred-capture,Semantic=semantic_result,semantic_timing=semantic_timing,
                                     semantic_hand_inputs=hand_payload if semantic_enabled else None,hand_presence_threshold=geometry.hand_presence_threshold,
                                     source_hash_ns=source_hash_ns,source_preparation_overlap=overlap_seal,
                                     geometry_ns=dict(palm_decode=palm_decode_ns,body_preprocess=body_preprocess_ns,body_decode=body_decode_ns),
                                     all_four_models_and_two_hands_executed=not tracked and bt is not None and len(hand_timing)==2,
                                     required_current_frame_branches_complete=bt is not None and len(hand_timing)==2,roi_policy=roi_policy,display=shown))
                if offline:
                    for obj in (r['rows'][-1],shown):
                        for name in list(obj):
                            if name.startswith('capture_EOF_'):obj[name.replace('capture_EOF_','fixture_input_ready_',1)]=obj.pop(name)
                identities=(semantic_result or{}).get('identity',[])
                telemetry_hands=[]
                for i,hand in enumerate(hand_payload if semantic_enabled else[]):
                    side=identities[i].get('side')if len(identities)==len(hand_payload)else None
                    telemetry_hands.append(dict(points=hand['points'],valid=hand['valid'],side=side,hand_presence=hands[i]['whole_hand_presence']if i<len(hands)else None))
                snapshot=dict(session_id=session,frame_id=fid,published_monotonic_ns=time.monotonic_ns(),capture_ns=capture,source_scope=r['source_scope'],
                              body_points=body_safe.tolist()if semantic_enabled else body.tolist(),body_valid=valid,hands=telemetry_hands,person_boxes=boxes,
                              Semantic=semantic_result,v4l2_driver_sequence=meta.get('v4l2_driver_sequence'),
                              PC_frontend_ms=pc_timing.get('remote',{}).get('complete_call_ns')/1e6 if pc_timing and pc_timing.get('remote',{}).get('complete_call_ns')is not None else None,
                              capture_to_scanout_ms=shown.get('capture_EOF_to_confirmed_scanout_ns')/1e6 if not offline else None)
                telemetry=H/'monitor_snapshot.json.tmp';telemetry.write_text(json.dumps(snapshot,allow_nan=False,separators=(',',':')));telemetry.replace(H/'monitor_snapshot.json')
        for conn in sockets:
            send_packet(conn,key,dict(operation='close',session_id=session));reply,body=recv_packet(conn,key,timeout=10)
            assert reply['operation']=='closed' and not body
        r['status']='THREE_BOARD_PERCEPTION_SCANOUT_PASS_TCN_ENABLED'if semantic_enabled else'THREE_BOARD_PERCEPTION_SCANOUT_PASS'
        r['full_perception_workload_frames']=sum(row['all_four_models_and_two_hands_executed']for row in r['rows'])
        r['current_geometry_frames']=sum(row['display']['framebuffer_copy_ack']['current_source_valid']and row['display']['framebuffer_copy_ack']['geometry_drawn']for row in r['rows'])
    except BaseException as error:
        r.update(status='FAILED',traceback=traceback.format_exc());r['errors'].append(str(error))
    finally:
        if geometry:r['Nav_hand_crop']=dict(native_calls=geometry.hand_native_calls,fallbacks=geometry.hand_native_fallbacks,enabled=geometry.hand_native is not None)
        for conn in sockets:conn.close()
        if nav_heads:
            try:nav_heads.close();r['Nav_FPGA_device_closed']=True
            except BaseException as error:r['errors'].append('Nav FPGA close: '+str(error))
        if camera:camera.close()
        if display:
            try:r['display_restore']=display.close()
            except BaseException as error:r['errors'].append('Display restore: '+str(error))
        if observer:observer.close()
        (H/'result.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
    if r['errors']:raise SystemExit(1)


if __name__=='__main__':
    if sys.argv[1:]in (['--check'],['--check-offline']):
        geometry=Geometry(H)
        reference=json.loads((H/'body_reference.json').read_text())
        assert reference['output_layout']=='NHWC, 64x48x17'
        with np.load(H/'body_fixture.npz',allow_pickle=False)as fixture:
            from topdown_postprocess import HRNetPostProcess
            baseline=HRNetPostProcess(use_dark=True);decode_checks=[]
            for index,heads in enumerate(fixture['expected_heads']):
                heatmaps=heads.reshape(1,64,48,17).transpose(0,3,1,2).copy()
                start=time.monotonic_ns();expected,_=baseline(heatmaps,np.array([[96.,128.]]),np.array([[.96,1.28]]));baseline_ns=time.monotonic_ns()-start
                start=time.monotonic_ns()
                points=geometry.body_decode(heads,(None,dict(im_shape=np.array([256,192])),np.array([0,0,192,256])))
                optimized_ns=time.monotonic_ns()-start
                np.testing.assert_array_equal(points,expected[0])
                np.testing.assert_allclose(points[:,2],reference['samples'][index]['candidate_peak_scores'],rtol=0,atol=1e-6)
                decode_checks.append(dict(sample=index,baseline_ns=baseline_ns,optimized_ns=optimized_ns,points_exact=True))
        if sys.argv[1:] == ['--check-offline']:
            print(json.dumps(dict(status='NAV_PERCEPTION_IMPORT_OFFLINE_PASS',body_NHWC_decode_three_frozen_heads_pass=True,body_quant_all_768_values_exact=True,sparse_DARK_comparison=decode_checks,physical_camera_opened=False,camera_RAM_read=False)))
            raise SystemExit(0)
        reader=TimedCameraReader('/run/medcomm/camera.frame',fresh_on_open=True,stall_seconds=3.)
        try:
            f=reader.read(timeout=3);assert f.metadata['capture_timestamp_tag']=='TIM9'
            print(json.dumps(dict(status='NAV_PERCEPTION_IMPORT_AND_TIM9_PASS',body_NHWC_decode_three_frozen_heads_pass=True,body_quant_all_768_values_exact=True,sparse_DARK_comparison=decode_checks,physical_camera_opened=False)))
        finally:reader.close()
    else:main()
