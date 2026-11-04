"""PC model prefixes and postprocessing; YOLO/heads/Hands/TCN execute on boards."""
from pathlib import Path
import concurrent.futures,hashlib,json,socket,sys,time,traceback
W=Path(__file__).resolve().parents[1];A=W.parent/'workbuddy_21/data/pp_tinypose_trial_20261024';V=W/'fpga/output/report_hybrid_0600_20261101'
sys.path[:0]=[str(A/'runtime_deps'),str(A/'compat_deps'),str(A/'official'),str(W/'three_board_link'),str(V/'pc_runtime')]
import cv2,numpy as np,onnxruntime as ort
from perception_geometry import Geometry,SparseLogDARK
from keypoint_preprocess import TopDownEvalAffine,expand_crop
from rpc_protocol import send_packet,recv_packet
from feature_transport import pack_features

class SplitVision:
    def __init__(self,pc_hands=False,compact=False,nav_body_post=False):
        self.nav_body_post=nav_body_post
        cv2.setNumThreads(1);d=W/'nav_split'/('compact'if compact else'fused');self.manifest=json.loads((d/'manifest.json').read_text());self.sessions={};self.current=None;self.previous=None
        options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1;options.add_session_config_entry('session.intra_op.allow_spinning','0')
        for name in('palm','body'):
            for part in('prefix','suffix'):
                if nav_body_post and name=='body' and part=='suffix':continue
                filename=name+'_'+part+'.onnx';path=d/filename;assert hashlib.sha256(path.read_bytes()).hexdigest()==self.manifest['files'][filename]
                self.sessions[name,part]=ort.InferenceSession(str(path),sess_options=options,providers=['CPUExecutionProvider'])
        self.geometry=Geometry.__new__(Geometry);self.geometry.anchors=np.concatenate([np.repeat(np.array([[(x+.5)/n,(y+.5)/n]for y in range(n)for x in range(n)],np.float32),r,axis=0)for n,r in[(24,2),(12,6)]])
        self.geometry.dark=SparseLogDARK(use_dark=True);self.affine=TopDownEvalAffine(trainsize=[192,256]);self.mean=np.array([.485,.456,.406],np.float32);self.std=np.array([.229,.224,.225],np.float32)
        self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.pc_head_count=sum(len(m.get('PC_heads',[]))for m in self.manifest['models'].values())
        self.hand_session=None
        if pc_hands:
            path=W/'models/hand.onnx';self.hand_sha256=hashlib.sha256(path.read_bytes()).hexdigest()
            assert self.hand_sha256==json.loads((W/'model_contract.json').read_text())['approved_models']['hand']['sha256']
            self.hand_session=ort.InferenceSession(str(path),sess_options=options,providers=['CPUExecutionProvider'])

    def hand(self,x):
        started=time.perf_counter_ns();x=((x.astype(np.float32)+128)/255.).transpose(2,0,1)[None]
        heads=self.hand_session.run(None,{self.hand_session.get_inputs()[0].name:np.ascontiguousarray(x)})
        return np.concatenate([h.ravel()for h in heads]),dict(complete_call_ns=time.perf_counter_ns()-started,PC_Hand_RUN=1,PL_jobs=0)

    def hands(self,data,h):
        assert self.hand_session and self.current['frame_id']==h['frame_id']
        count=h['shape'][0];assert 0<=count<=2 and h['shape']==[count,224,224,3]and len(data)==count*224*224*3
        inputs=np.frombuffer(data,np.int8).reshape(count,224,224,3)
        future=self.pool.submit(self.hand,inputs[1])if count==2 else None
        values=[self.hand(inputs[0])]if count else[]
        if future:values.append(future.result())
        self.current['hand_count']=count
        return np.concatenate([v[0]for v in values]).tobytes()if values else b'',dict(output_dtype='float32',PC_Hand_RUN=count,hand_stats=[v[1]for v in values],hand_model_sha256=self.hand_sha256)

    def prefix(self,name,x):
        s=self.sessions[name,'prefix'];started=time.perf_counter_ns();cpu_started=time.process_time_ns()
        values=s.run(None,{s.get_inputs()[0].name:np.ascontiguousarray(x)})
        return values,time.perf_counter_ns()-started,time.process_time_ns()-cpu_started

    def features(self,data,h):
        started=time.perf_counter_ns();image=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR);assert image.shape==(240,400,3)
        if self.nav_body_post:self.previous=h.get('body_person_prior')
        skip_palm=bool(h.get('skip_palm'));stat={}
        if not skip_palm:
            p=self.geometry.palm_input(image);p=((p.astype(np.float32)+128)/255.).transpose(2,0,1)[None]
        roi=[80.,0.,320.,240.,1.];source='center_full_height_crop_prior_NOT_person_detection'
        if self.previous and 0<h['capture_ns']-self.previous[1]<=3000000000:
            box=self.previous[0];roi=[*(v/2 for v in box[:4]),box[4]];source='recent_YOLO_box_current_frame_pixels'
        crop,expanded,_=expand_crop(image,np.asarray([0.,roi[4],*roi[:4]]));assert crop is not None and crop.size
        info=dict(im_shape=np.asarray(crop.shape[:2],np.float32));rgb,_=self.affine(cv2.cvtColor(crop,cv2.COLOR_BGR2RGB),info)
        b=((rgb.astype(np.float32)/255.-self.mean)/self.std).transpose(2,0,1)[None]
        arrays=[];sizes=[];pending={}
        if skip_palm:computed=[('body',self.prefix('body',b))]
        else:
            body_future=self.pool.submit(self.prefix,'body',b)
            computed=[('palm',self.prefix('palm',p)),('body',body_future.result())]
        for name,(features,elapsed,cpu)in computed:
            stat[name+'_prefix_ns']=elapsed
            stat[name+'_prefix_process_cpu_ns']=cpu
            model=self.manifest['models'][name];count=len(model['features'])
            pending[name]=dict(zip(model.get('PC_heads',[]),features[count:]))
            for value in features[:count]:
                v=np.ascontiguousarray(value[0].transpose(1,2,0));arrays.append(v.ravel());sizes.append(v.size)
        self.current=dict(frame_id=h['frame_id'],capture_ns=h['capture_ns'],prepared=(None,info,expanded),image_shape=image.shape,stats=stat,roi_source=source,hand_count=0,pending_heads=pending,pc_head_count=0 if skip_palm else self.pc_head_count,skip_palm=skip_palm)
        values=np.concatenate(arrays);raw,encoding=pack_features(values)
        return raw,dict(output_dtype='float32',feature_sizes=sizes,feature_encoding=encoding,feature_raw_bytes=values.nbytes,feature_payload_bytes=len(raw),stats=stat,roi_source=source,body_prepared=dict(im_shape=info['im_shape'].tolist(),expanded=np.asarray(expanded).tolist())if self.nav_body_post else None,complete_call_ns=time.perf_counter_ns()-started,PC_Person_RUN=0,PC_PalmBody_output_convolutions=self.current['pc_head_count'],PC_designated_Nav_head_fallbacks=0,Palm_RUN=int(not skip_palm))

    def heads(self,name,data,h):
        assert self.current['frame_id']==h['frame_id'];m=self.manifest['models'][name];flat=np.frombuffer(data,'<f4');offset=0;values=dict(self.current['pending_heads'][name])
        for group in m['groups']:
            height,width,_=group['input_shape'];channels=sum(group['channels']);count=height*width*channels
            value=flat[offset:offset+count].reshape(height,width,channels);offset+=count;at=0
            for head,co in zip(group['heads'],group['channels']):values[head]=np.ascontiguousarray(value[:,:,at:at+co].transpose(2,0,1)[None]);at+=co
        assert offset==flat.size;s=self.sessions[name,'suffix'];outputs=s.run(None,values)
        if name=='palm':
            detections=self.geometry.palm_decode(np.concatenate([x.ravel()for x in outputs]),self.current['image_shape'])
            for d in detections:d['transform'][:,:2]/=2;d['transform']=d['transform'].tolist();d['box']=[x*2 for x in d['box']]
            result=dict(detections=detections)
        else:
            body=self.geometry.body_decode(outputs[0].transpose(0,2,3,1).ravel(),self.current['prepared']);body[:,:2]*=2;body[~np.isfinite(body).all(1)]=0
            boxes=h.get('person_boxes',[])
            if boxes:self.previous=(max(boxes,key=lambda b:b[4]*(b[2]-b[0])*(b[3]-b[1])),h['capture_ns'])
            result=dict(body=body.tolist(),roi_source=self.current['roi_source'],stats=self.current['stats'])
        result.update(PC_Person_RUN=0,PC_Hand_RUN=self.current['hand_count'],PC_TCN_RUN=0,PC_PalmBody_output_convolutions=self.current['pc_head_count'])
        return json.dumps(result,separators=(',',':'),allow_nan=False).encode(),dict(output_dtype='json')

def main():
    cfg=json.load(sys.stdin);key=bytes.fromhex(cfg.pop('key'));run=Path(cfg['run']);r=dict(status='LOADING',rows=[],errors=[],PC_Person_RUN=0,PC_Hand_RUN=0,PC_TCN_RUN=0,PC_PalmBody_output_convolutions=0);conn=None;engine=None
    def save():(run/'pc_vision.json').write_text(json.dumps(r,indent=2)+'\n')
    try:
        pc_hands=bool(cfg.get('pc_hands'));nav_body_post=bool(cfg.get('nav_body_post'));assert not nav_body_post or not pc_hands
        engine=SplitVision(pc_hands,bool(cfg.get('compact_nav')),nav_body_post);r.update(status='MODELS_READY',onnxruntime=ort.__version__,models=engine.manifest['models'],pc_hands_enabled=pc_hands,nav_body_post=nav_body_post);save();deadline=time.monotonic()+180
        while conn is None:
            try:conn=socket.create_connection(('192.168.1.10',5116),timeout=3)
            except OSError:
                if time.monotonic()>deadline:raise
                time.sleep(.2)
        conn.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1);hello=False;index=0;last=-1;phase=0;frames=0
        while True:
            h,b=recv_packet(conn,key,timeout=90);assert h['session_id']==cfg['session_id'];op=h['operation']
            if op=='hello':assert not hello and not b;hello=True;send_packet(conn,key,dict(operation='ready',session_id=cfg['session_id']));continue
            assert hello
            if op=='close':assert phase==0;send_packet(conn,key,dict(operation='closed',session_id=cfg['session_id']));break
            assert h['request_index']==index and index<(4 if pc_hands else 3)*cfg.get('max_frames',48);index+=1
            assert h['_authenticated_body_sha256']==h['input_sha256']
            identity=hashlib.sha256(json.dumps([cfg['session_id'],h['frame_id'],h['capture_ns']],separators=(',',':')).encode()).hexdigest();assert identity==h['source_identity_sha256']
            started=time.perf_counter_ns()
            if op=='vision_features':
                assert phase==0 and h['frame_id']>last;last=h['frame_id'];frames+=1;assert frames<=cfg.get('max_frames',48)
                raw,extra=engine.features(b,h);phase=(0 if nav_body_post else 2)if engine.current['skip_palm']else 1
            elif op=='palm_heads':assert phase==1 and h['frame_id']==last;raw,extra=engine.heads('palm',b,h);phase=0 if nav_body_post else 2
            elif op=='hand_inputs':assert pc_hands and phase==2 and h['frame_id']==last;raw,extra=engine.hands(b,h);phase=3;r['PC_Hand_RUN']+=engine.current['hand_count']
            elif op=='body_heads':assert phase==(3 if pc_hands else 2)and h['frame_id']==last;raw,extra=engine.heads('body',b,h);phase=0
            else:raise ValueError(op)
            send_packet(conn,key,dict(operation='result',session_id=cfg['session_id'],request_index=h['request_index'],frame_id=last,source_capture_ns=h['capture_ns'],source_identity_sha256=identity,input_sha256=h['input_sha256'],output_sha256=hashlib.sha256(raw).hexdigest(),**extra),raw)
            if phase==0:
                r['PC_PalmBody_output_convolutions']+=engine.current['pc_head_count']
                r['rows'].append(dict(frame_id=last,stats=engine.current['stats'],PC_Person_RUN=0,PC_Hand_RUN=engine.current['hand_count'],PC_TCN_RUN=0,PC_PalmBody_output_convolutions=engine.current['pc_head_count'],roi_source=engine.current['roi_source'],Palm_RUN=int(not engine.current['skip_palm'])));r['status']='STREAMING'
                if frames==1 or frames%16==0:save()
        r['status']='PC_VISION_PASS'
    except BaseException as e:r.update(status='FAILED',traceback=traceback.format_exc());r['errors'].append(str(e));raise
    finally:
        if conn:conn.close()
        if engine:engine.pool.shutdown(wait=True)
        save()

if __name__=='__main__':main()
