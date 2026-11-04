"""Bounded ROI reuse; every landmark always comes from the current image."""
import numpy as np


class StableHandROI:
    def __init__(self):
        self.previous=None;self.source=None;self.detections=None;self.stable=False;self.reuses=0;self.reason={'reason':'need_two_valid_frames'}

    def select(self,capture_ns):
        if self.stable and self.reuses<3 and 0<capture_ns-self.source[1]<=750000000:
            self.reuses+=1
            return self.detections,dict(mode='tracked_ROI_current_image_21points',reference_frame_id=self.source[0],age_ns=capture_ns-self.source[1],reuse_index=self.reuses,Palm_RUN=0)
        return None,dict(mode='current_Palm_detection',Palm_RUN=1,reuse_rejected=self.reason)

    def update(self,detections,hands,fid,capture_ns,tracked):
        current=[]
        if len(detections)!=2 or len(hands)!=2:
            self.previous=None;self.stable=False;self.reason=dict(reason='need_two_hands',detections=len(detections),hands=len(hands));return
        # Pipeline returns Q's second detection, then P's first detection.
        for d,h in zip(detections,reversed(hands)):
            xy=np.asarray(h['points'],np.float32);transform=d['transform']
            uv=xy@transform[:,:2].T+transform[:,2]
            if not all(h['valid'])or h['whole_hand_presence']<.85 or not np.isfinite(uv).all()or uv.min()<.04 or uv.max()>.96:
                self.previous=None;self.stable=False;self.reason=dict(reason='landmark_or_ROI_boundary',valid_points=sum(h['valid']),presence=h['whole_hand_presence'],roi_min=float(uv.min()),roi_max=float(uv.max()));return
            current.append((xy,transform))
        stable=self.previous is not None
        if stable:
            old=sorted(self.previous,key=lambda v:float(v[0][0,0]));now=sorted(current,key=lambda v:float(v[0][0,0]))
            stable=all(np.max(np.linalg.norm((a[0]-b[0])@a[1][:,:2].T,axis=1))<=.10 for a,b in zip(now,old))
        self.previous=current;self.stable=stable;self.reason=dict(reason='refresh_due'if stable else'need_stable_second_frame')
        if not tracked:
            self.detections=detections;self.source=(fid,capture_ns);self.reuses=0
