"""Original word policy and existing hardware-only INT8 TCN ctypes bridge."""
from collections import deque
from pathlib import Path
import ctypes as C
import hashlib
import json
import os
import time

from features_integer import prepare_word, rest_predicate, from_roi_replies, associate_current_body, cache_features

LIB_SHA='3bf63ccbe8f389e5e006f616d659f985822c64b617b279d3193f54f28fc4c253'
DEP_SHA='51451a66d5ee961f13651a8da9d3eefebb9687be5e2504b645b679d1e5d25778'
CLASSES_SHA='d163047f63455870440d44e7c0321a5d28d21c2bd39bb00026a0ead341d5709e'
PARAM_SHA={'primary':'b485dbde59199f814e2d7ef6f6de5d46b915e313a3ce76284a98573e202eb645',
           'roof':'fc3f2ad93f2d0e20f5e92ede4500e381e9bab0d7d01743b525e28dde287c87a2'}


class HardwareTCN:
    """One native PL owner at a time; hardware=1 only, no oracle fallback."""
    def __init__(self,assets,dependency='/home/xilinx/gesture-hand-palm-whole-raw-owner-v8/libgesture_tflite_pl_pointwise.so'):
        self.assets=Path(assets);dependency=Path(dependency)
        sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
        if sha(self.assets/'libtcn_integer_pl.so')!=LIB_SHA or sha(dependency)!=DEP_SHA:
            raise ValueError('Existing actual-tested integer PL library SHA mismatch')
        for profile,digest in PARAM_SHA.items():
            path=self.assets/profile/'integer_parameters.json'
            if sha(path)!=digest:raise ValueError('Frozen normalize/mirror/pool parameters differ')
            params=json.loads(path.read_text())
            for model in params['models'].values():
                if sha(self.assets/profile/model['file'])!=model['sha256']:raise ValueError('Frozen INT8 TCN model SHA differs')
        C.CDLL(str(dependency),mode=getattr(C,'RTLD_GLOBAL',0))
        self.api=C.CDLL(str(self.assets/'libtcn_integer_pl.so'))
        p=C.c_void_p;u=C.c_uint64;i=C.c_int
        for name,args,result in [('gtcn_open',[C.c_char_p,i,i],p),('gtcn_infer',[p,p,u,p,u,p,p],i),
                ('gtcn_close',[p],i),('gtcn_error',[],C.c_char_p),('gtcn_stats',[p,C.POINTER(u)],i)]:
            f=getattr(self.api,name);f.argtypes=args;f.restype=result

    def infer(self,profile,values,mask):
        import numpy as np
        f=96 if profile=='primary' else 112
        if profile not in ('primary','roof') or values.dtype!=np.int16 or values.shape!=(32,f) or mask.dtype!=np.uint8 or mask.shape!=values.shape or np.any(mask>1):
            raise ValueError('Typed INT16[32,F] / UINT8 binary-mask input required')
        if not np.any(mask[:,:84]): raise ValueError('All-invalid word rejected before PL')
        values=np.ascontiguousarray(values);mask=np.ascontiguousarray(mask)
        params=json.loads((self.assets/profile/'integer_parameters.json').read_text())
        if params['features']!=f or params['raw_input_scale'].as_integer_ratio()!=(1,1024):
            raise ValueError('Frozen temporal feature ingress contract differs')
        start=time.monotonic_ns();handle=self.api.gtcn_open(os.fsencode(self.assets),int(profile=='roof'),1)
        opened=time.monotonic_ns()
        if not handle: raise RuntimeError(self.api.gtcn_error().decode())
        row={};error=None
        try:
            logits=np.empty(27,np.int16);prob=np.empty(27,np.uint16)
            best=self.api.gtcn_infer(handle,values.ctypes.data,values.size,mask.ctypes.data,mask.size,logits.ctypes.data,prob.ctypes.data)
            done=time.monotonic_ns()
            if best<0: raise RuntimeError(self.api.gtcn_error().decode())
            stats=(C.c_uint64*12)()
            if self.api.gtcn_stats(handle,stats)!=0: raise RuntimeError('TCN stats failed')
            if stats[0]!=16 or stats[4]!=1: raise ValueError('Expected sixteen actual PL RUNs for one model/word')
            row=dict(profile=profile,class_index=int(best),logits_int16=logits.tolist(),probabilities_Q15=prob.tolist(),
                     owner_open_ns=opened-start,integer_model_infer_ns=done-opened,actual_PL_RUNs=int(stats[0]),
                     driver_ns=int(stats[1]),input_bytes=int(stats[2]),output_bytes=int(stats[3]),words=int(stats[4]),
                     integer_im2col_ns=int(stats[6]),device_wall_ns=int(stats[7]),output_copy_ns=int(stats[8]),
                     integer_boundary_ns=int(stats[9]),core_invoke_ns=int(stats[10]),head_invoke_ns=int(stats[11]))
        except Exception as exc:
            error=exc
        finally:
            close_start=time.monotonic_ns();rc=self.api.gtcn_close(handle)
            row.update(owner_close_ns=time.monotonic_ns()-close_start,owner_closed_healthy=rc==0,
                       total_owner_and_infer_ns=time.monotonic_ns()-start)
            if rc: raise RuntimeError('TCN native owner close failed; no retry')
        if error is not None: raise error
        return row


class IntegerClassifier:
    def __init__(self,runner,classes_path=None):
        self.runner=runner
        path=Path(classes_path or Path(__file__).with_name('classes.json'))
        if hashlib.sha256(path.read_bytes()).hexdigest()!=CLASSES_SHA: raise ValueError('Original 27-class label map SHA differs')
        classes=json.loads(path.read_text(encoding='utf-8-sig'))
        self.labels={v['idx']:v for v in classes.values()}

    def classify(self,frames):
        start=time.monotonic_ns();runs=[];features=[]
        def infer(profile):
            a,b,receipt=prepare_word(frames,profile=='roof');features.append(dict(profile=profile,**receipt))
            if not b[:,:84].any(): return None
            r=self.runner.infer(profile,a,b);runs.append(r);return r
        base=infer('primary')
        if base is None: return dict(label=-1,gesture='未确认',confidence_Q15=0,accepted_by_original_gate=False,accepted_by_hybrid_gate=False,actual_PL_RUNs=0)
        chosen=base;source='primary'
        if base['class_index'] in (3,23,24):
            specialist=infer('roof')
            if specialist is not None and specialist['class_index'] in (3,23,24) and specialist['class_index']!=base['class_index']:
                chosen=specialist;source='roof_specialist'
        label=chosen['class_index'];confidence=chosen['probabilities_Q15'][label];original_accepted=confidence>=26215;accepted=confidence>=19661
        return dict(label=label,gesture=self.labels[label]['name'],intents=self.labels[label].get('intents',[]),
                    display_gesture=self.labels[label]['name'] if accepted else '未确认',confidence_Q15=confidence,
                    confidence_kind='original_uncalibrated_softmax_Q15',accepted_by_original_gate=original_accepted,accepted_by_hybrid_gate=accepted,
                    prediction_source=source,base_label=base['class_index'],actual_PL_RUNs=sum(r['actual_PL_RUNs'] for r in runs),
                    model_runs=runs,features=features,classify_total_ns=time.monotonic_ns()-start,
                    semantic_policy_changed=True,word_admission_policy='Q15_ge19661_60percent',integer_feature_frontend_new_candidate=True)


class IntegerWordSegmenter:
    """Integer-us port of frozen WordSegmenter, with all timing rules retained."""
    def __init__(self,classify):
        self.classify=classify;self.last_result=None;self.event_id=0;self.stream_id=None;self.reset()

    def reset(self):
        self.state='WAIT_REST';self.rest_since=self.start_since=self.missing_since=self.previous_time=None
        self.feature_previous=None
        self.frames=[];self.preroll=deque(maxlen=16)

    def update(self,packet):
        now=packet['timestamp_us']
        if self.stream_id!=packet['stream_id']:
            self.reset();self.stream_id=packet['stream_id']
        if self.previous_time is not None and not 0<now-self.previous_time<=1000000: self.reset()
        cache_features(packet,self.feature_previous);self.feature_previous=packet
        self.previous_time=now;rest=rest_predicate(packet)
        if rest is None:
            if self.missing_since is None:self.missing_since=now
            self.rest_since=None
            if now-self.missing_since>=1000000:self.reset()
            return None
        self.missing_since=None
        if rest:
            if self.rest_since is None:self.rest_since=now
        else:self.rest_since=None
        if self.state=='WAIT_REST':
            if rest and now-self.rest_since>=650000:self.state='READY'
            return None
        if self.state=='READY':
            if rest:
                self.start_since=None;self.frames=[];self.preroll.append(packet);return None
            if self.start_since is None:
                self.start_since=now;self.frames=[p for p in self.preroll if now-p['timestamp_us']<=200000]
            self.frames.append(packet)
            if now-self.start_since>=120000:self.state='ACTIVE'
            return None
        self.frames.append(packet)
        if now-self.start_since>10000000:self.reset();return None
        if not rest or now-self.rest_since<650000:return None
        duration=self.rest_since-self.start_since;frames=self.frames;confirmation=len(frames)
        stop=next((i+1 for i,p in enumerate(frames) if p['timestamp_us']>=self.rest_since+150000),len(frames))
        frames=frames[:stop];self.state='READY';self.frames=[];self.start_since=None;self.preroll.clear();self.preroll.append(packet)
        if duration<250000:return None
        result=self.classify(frames);self.event_id+=1
        self.last_result=dict(result,event_id=self.event_id,start_us=frames[0]['timestamp_us'],end_us=self.rest_since,
                              emitted_us=now,frame_count=len(frames),confirmation_frame_count=confirmation,
                              source_frame_ids=[p['frame_id'] for p in frames],
                              processed_sequences=[p.get('processed_sequence') for p in frames])
        return self.last_result


class IntegerGesturePipeline:
    """Live connection point for same-frame Body128 + raw Hand21 replies."""
    def __init__(self,runner,classes_path=None):
        self.classifier=IntegerClassifier(runner,classes_path)
        self.segmenter=IntegerWordSegmenter(self.classifier.classify);self.previous=None

    def update_replies(self,body_context,body_reply,hand_context,hand_reply):
        started=time.monotonic_ns()
        frame=from_roi_replies(body_context,body_reply,hand_context,hand_reply)
        previous=self.previous
        if previous is not None and (frame['stream_id']!=previous['stream_id'] or not 0<frame['timestamp_us']-previous['timestamp_us']<=1000000):previous=None
        identity=associate_current_body(frame,previous)
        self.previous=frame
        event=self.segmenter.update(frame)
        return dict(frame_id=frame['frame_id'],timestamp_us=frame['timestamp_us'],state=self.segmenter.state,
                    identity=identity,integer_feature_segment_update_ns=time.monotonic_ns()-started,
                    event=event,last_committed_result=self.segmenter.last_result,
                    old_coordinate_substitution=False,YOLO_required_by_feature_or_TCN=False)
