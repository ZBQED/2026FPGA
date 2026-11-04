"""Original full vision models on PC; authenticated current-frame JPEG only."""
from pathlib import Path
import hashlib,json,socket,sys,time,traceback
W=Path(__file__).resolve().parents[1];ROOT=W.parent
A=ROOT/'workbuddy_21/data/pp_tinypose_trial_20261024'
sys.path[:0]=[str(A/'runtime_deps'),str(A/'compat_deps'),str(A/'official'),str(ROOT),str(W/'three_board_link'),str(W/'fpga/output/report_hybrid_0600_20261101/pc_runtime')]
import cv2,numpy as np,onnxruntime as ort
from rpc_protocol import send_packet,recv_packet
from perception_geometry import Geometry,SparseLogDARK
from keypoint_preprocess import TopDownEvalAffine,expand_crop
import workbuddy_21.delivery_yolo_runtime as person_module

class Vision:
    def __init__(self):
        cv2.setNumThreads(1);person_module.ASSETS=W/'pc_accel/person';self.person=person_module.DeliveryPersonDetector()
        self.sessions={};self.model_hashes={}
        for name in ('palm','body'):
            path=W/'models'/(name+'.onnx');self.model_hashes[name]=hashlib.sha256(path.read_bytes()).hexdigest()
            options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
            options.add_session_config_entry('session.intra_op.allow_spinning','0')
            self.sessions[name]=ort.InferenceSession(str(path),sess_options=options,providers=['CPUExecutionProvider'])
        self.geometry=Geometry.__new__(Geometry)
        self.geometry.anchors=np.concatenate([np.repeat(np.array([[(x+.5)/n,(y+.5)/n]for y in range(n)for x in range(n)],np.float32),repeats,axis=0)for n,repeats in[(24,2),(12,6)]])
        self.geometry.dark=SparseLogDARK(use_dark=True);self.affine=TopDownEvalAffine(trainsize=[192,256])
        self.mean=np.array([.485,.456,.406],np.float32);self.std=np.array([.229,.224,.225],np.float32)
        self.previous_box=None

    def infer(self,name,x):
        session=self.sessions[name];start=time.perf_counter_ns()
        values=session.run(None,{session.get_inputs()[0].name:np.ascontiguousarray(x)})
        return values,time.perf_counter_ns()-start

    def frame(self,jpeg,head):
        start=time.perf_counter_ns();image=cv2.imdecode(np.frombuffer(jpeg,np.uint8),cv2.IMREAD_COLOR)
        assert image is not None and image.shape in((480,800,3),(240,400,3))
        height,width=image.shape[:2];scale=800./width
        stat=dict(jpeg_decode_ns=time.perf_counter_ns()-start)
        t=time.perf_counter_ns();boxes=self.person.detect(image);stat['person_ns']=time.perf_counter_ns()-t
        boxes=[[max(0.,b[0]),max(0.,b[1]),min(float(width),b[2]),min(float(height),b[3]),b[4]]for b in boxes]
        boxes=[b for b in boxes if b[2]>b[0]and b[3]>b[1]]
        t=time.perf_counter_ns();p=self.geometry.palm_input(image);stat['palm_preprocess_ns']=time.perf_counter_ns()-t
        values,stat['palm_ns']=self.infer('palm',((p.astype(np.float32)+128)/255.).transpose(2,0,1)[None])
        t=time.perf_counter_ns();detections=self.geometry.palm_decode(np.concatenate([x.ravel()for x in values]),image.shape);stat['palm_decode_ns']=time.perf_counter_ns()-t
        body=np.zeros((17,3),np.float32);roi=None;roi_source='none';body_run=0
        if boxes:
            roi=max(boxes,key=lambda b:b[4]*(b[2]-b[0])*(b[3]-b[1]));self.previous_box=(list(roi),head['frame_id'],head['capture_ns']);roi_source='current_detection'
        elif self.previous_box and 0<head['capture_ns']-self.previous_box[2]<=3000000000:
            roi=self.previous_box[0];roi_source='recent_detection_current_pixels'
        else:
            roi=[(width-height)/2.,0.,(width+height)/2.,float(height),1.]
            roi_source='center_full_height_crop_prior_NOT_person_detection'
        stat['body_preprocess_ns']=stat['body_ns']=stat['body_decode_ns']=0
        if roi is not None:
            t=time.perf_counter_ns();crop,expanded,_=expand_crop(image,np.asarray([0.,roi[4],*roi[:4]]))
            if crop is not None and crop.size:
                info=dict(im_shape=np.asarray(crop.shape[:2],np.float32));rgb,_=self.affine(cv2.cvtColor(crop,cv2.COLOR_BGR2RGB),info)
                tensor=((rgb.astype(np.float32)/255.-self.mean)/self.std).transpose(2,0,1)[None];stat['body_preprocess_ns']=time.perf_counter_ns()-t
                heads,stat['body_ns']=self.infer('body',tensor);t=time.perf_counter_ns()
                body=self.geometry.body_decode(heads[0].transpose(0,2,3,1).ravel(),(None,info,expanded));stat['body_decode_ns']=time.perf_counter_ns()-t;body_run=1
        body[~np.isfinite(body).all(1)]=0
        body[:,:2]*=scale
        boxes=[[*(v*scale for v in b[:4]),b[4]]for b in boxes]
        for detection in detections:
            detection['transform'][:,:2]/=scale;detection['transform']=detection['transform'].tolist()
            detection['box']=[x*scale for x in detection['box']]
        return dict(frame_id=head['frame_id'],capture_ns=head['capture_ns'],boxes=boxes,body=body.tolist(),detections=detections,
                    palm_detections=len(detections),body_run=body_run,roi_source=roi_source,stats=stat,PC_Hand_RUN=0,PC_TCN_RUN=0,
                    complete_call_ns=time.perf_counter_ns()-start,jpeg_sha256=hashlib.sha256(jpeg).hexdigest(),
                    decoded_pixels_sha256=hashlib.sha256(image.tobytes()).hexdigest(),model_sha256=self.model_hashes,
                    source_transform='JPEG95 '+str(width)+'x'+str(height)+' of the same immutable Nav frame; FPGA Hand input and display retain original pixels',PC_core_inference=True)

def main():
    cfg=json.load(sys.stdin);key=bytes.fromhex(cfg.pop('key'));run=Path(cfg['run']);r=dict(status='LOADING',rows=[],errors=[],physical_camera_opened=False)
    def save():(run/'pc_vision.json').write_text(json.dumps(r,indent=2)+'\n')
    conn=None
    try:
        vision=Vision();r.update(status='MODELS_READY',models=vision.model_hashes,onnxruntime=ort.__version__,numpy=np.__version__,opencv=cv2.__version__,python=sys.version,PC_Hand_RUN=0,PC_TCN_RUN=0);save();deadline=time.monotonic()+180
        while conn is None:
            try:conn=socket.create_connection(('192.168.1.10',5116),timeout=3)
            except OSError:
                if time.monotonic()>deadline:raise
                time.sleep(.2)
        conn.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1);hello=False;last=-1;index=0
        while True:
            h,b=recv_packet(conn,key,timeout=90,max_body=2<<20);assert h['session_id']==cfg['session_id']
            if h['operation']=='hello':
                assert not hello and not b;hello=True;send_packet(conn,key,dict(operation='ready',session_id=cfg['session_id']));continue
            assert hello
            if h['operation']=='close':send_packet(conn,key,dict(operation='closed',session_id=cfg['session_id']));break
            assert h['operation']=='vision_jpeg'and h['request_index']==index and index<cfg.get('max_frames',48)and h['frame_id']>last
            assert h['_authenticated_body_sha256']==h['input_sha256'];last=h['frame_id'];index+=1
            identity=hashlib.sha256(json.dumps([cfg['session_id'],last,h['capture_ns']],separators=(',',':')).encode()).hexdigest();assert identity==h['source_identity_sha256']
            value=vision.frame(b,h);raw=json.dumps(value,separators=(',',':'),allow_nan=False).encode()
            if index==1:(run/'first_frame_frontend_debug.jpg').write_bytes(b)
            send_packet(conn,key,dict(operation='result',session_id=cfg['session_id'],request_index=h['request_index'],frame_id=last,
                        source_capture_ns=h['capture_ns'],source_identity_sha256=identity,input_sha256=h['input_sha256'],output_dtype='json',
                        output_sha256=hashlib.sha256(raw).hexdigest(),stats=dict(PL_jobs=0,complete_call_ns=value['complete_call_ns'])),raw)
            r['rows'].append(dict(frame_id=last,stats=value['stats'],palm_detections=value['palm_detections'],PC_Hand_RUN=0,PC_TCN_RUN=0,body_run=value['body_run'],complete_call_ns=value['complete_call_ns'],jpeg_bytes=len(b)))
            if index==1 or index%16==0:r['status']='STREAMING';save()
        r['status']='PC_VISION_PASS'
    except BaseException as error:r.update(status='FAILED',traceback=traceback.format_exc());r['errors'].append(str(error));raise
    finally:
        if conn:conn.close()
        save()

if __name__=='__main__':main()
