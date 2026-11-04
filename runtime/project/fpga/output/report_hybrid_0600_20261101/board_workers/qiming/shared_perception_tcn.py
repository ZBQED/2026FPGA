"""Live same-frame landmarks and latest TCN on one Q owner and shared arena."""
from pathlib import Path
import ctypes as C
import importlib.util
import os,sys,time
from resident_models import ResidentModels


def device_fds():
    return [int(p.name)for p in Path('/proc/self/fd').iterdir()if os.path.realpath(str(p))=='/dev/gesture-i8-pl0']


class SharedPerceptionTCN(ResidentModels):
    def __init__(self,root,session,person_fpga=False):
        root=Path(root);self.tcn=None;self.person=None;self.tcn_owner=None;self.session=session;self.previous=None
        assert not device_fds()
        folder=root/'tcn508a'
        self.dependency=C.CDLL(str(folder/'runtime/libgesture_tflite_pl.so'))
        self.tcn_api=C.CDLL(str(folder/'runtime/libgesture_lite_i8_v12.so'))
        self.tcn_api.gpo_owner_open.argtypes=[];self.tcn_api.gpo_owner_open.restype=C.c_void_p
        self.tcn_api.gpo_owner_close.argtypes=[C.c_void_p];self.tcn_api.gpo_owner_close.restype=C.c_int
        try:
            self.tcn_owner=self.tcn_api.gpo_owner_open();assert self.tcn_owner
            assert len(device_fds())==1;fd=device_fds()[0]
            spec=importlib.util.spec_from_file_location('live_shared_tcn',folder/'shared_tcn/shared_tcn.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            self.tcn=module.SharedTCN(self.tcn_api,self.tcn_owner,folder/'shared_tcn/assets')
            super().__init__(root,workspace=True,parent_fd=fd,selected_models={'full_hand'}if person_fpga else None)
            if person_fpga:
                from person_raw_runtime import PersonRaw
                self.person=PersonRaw(root/'person_raw',fd,base=6293376)
                assert 6293376+self.person.api.yf2_fpga_pool_used()<min(row['base']for row in self.layout)
            assert device_fds()==[fd]
            sys.path.insert(0,str(root/'wiring'))
            from word_integer import IntegerClassifier,IntegerWordSegmenter
            self.classifier=IntegerClassifier(self.tcn,root/'wiring/classes.json')
            self.segmenter=IntegerWordSegmenter(self.classifier.classify)
        except BaseException:
            self.close();raise

    def semantic_frame(self,payload,frame_id,capture_ns):
        from features_integer import make_frame,number_to_fixed,associate_current_body,rest_predicate
        start=time.monotonic_ns();assert payload['image_size']==[800,480]
        body=payload['body'];hands=payload['hands'];assert len(body)==17 and len(hands)<=2
        body_q=[[number_to_fixed(float(p[0]),16),number_to_fixed(float(p[1]),16),number_to_fixed(float(p[2]),15)]for p in body]
        hand_q=[]
        for hand in hands:
            assert len(hand['points'])==len(hand['valid'])==21
            hand_q.append(dict(side=None,identity_missing=True,
                               pixels_q16=[[number_to_fixed(float(x),16),number_to_fixed(float(y),16)]for x,y in hand['points']],
                               joint_missing=[not value for value in hand['valid']]))
        frame=make_frame(self.session,frame_id,capture_ns//1000,[800,480],body_q,[0,0],hand_q,[0,0])
        previous=self.previous
        if previous is not None and not 0<frame['timestamp_us']-previous['timestamp_us']<=1000000:previous=None
        identities=associate_current_body(frame,previous);self.previous=frame
        rest=rest_predicate(frame);event=self.segmenter.update(frame)
        if event:
            # Retain the original 80% admission gate for displayed live results.
            event['display_gesture']=event['gesture']if event.get('accepted_by_original_gate')else'未确认'
            event['live_admission_policy']='original_Q15_ge26215'
        runs=event.get('model_runs',[])if event else[]
        self.guards()
        return dict(frame_id=frame_id,capture_ns=capture_ns,state=self.segmenter.state,identity=identities,
                    event=event,last_committed_result=self.segmenter.last_result,rest_pose=rest,
                    body_missing=frame['body_missing'],body_valid=frame['body_valid'],
                    actual_PL_RUNs=sum(r['actual_PL_RUNs']for r in runs),TCN_RUN=len(runs),
                    complete_call_ns=time.monotonic_ns()-start,old_coordinate_substitution=False,
                    feature_frontend='original_integer_local_palm96_roof112',single_device_fd=len(device_fds())==1)

    def close(self):
        errors=[]
        try:
            if self.person:self.person.close();self.person=None
        except BaseException as error:errors.append(str(error))
        try:
            if hasattr(self,'models'):super().close()
        except BaseException as error:errors.append(str(error))
        try:
            if self.tcn:self.tcn.close();self.tcn=None
        except BaseException as error:errors.append(str(error))
        try:
            if self.tcn_owner:
                code=self.tcn_api.gpo_owner_close(self.tcn_owner);self.tcn_owner=None
                if code:errors.append('TCN owner close failed')
        except BaseException as error:errors.append(str(error))
        if errors:raise RuntimeError('; '.join(errors))
