"""Approved preprocessing and output decoding on Nav; no neural backend here."""
from pathlib import Path
import ctypes as C
import json
import cv2
import numpy as np
from keypoint_preprocess import TopDownEvalAffine,expand_crop
from topdown_postprocess import HRNetPostProcess


class Box(C.Structure):
    _fields_=[(n,C.c_double)for n in('x1','y1','x2','y2','score')]+[('cate',C.c_int)]


class SparseLogDARK(HRNetPostProcess):
    def gaussian_blur(self, heatmap, kernel):
        border=(kernel-1)//2
        batch,joints,height,width=heatmap.shape
        for n in range(batch):
            origin=heatmap[n].max(axis=(1,2))
            padded=np.zeros((height+2*border,width+2*border,joints),np.float64)
            padded[border:-border,border:-border]=heatmap[n].transpose(1,2,0)
            filtered=cv2.GaussianBlur(padded,(kernel,kernel),0)
            heatmap[n]=filtered[border:-border,border:-border].transpose(2,0,1)
            heatmap[n]*=(origin/heatmap[n].max(axis=(1,2)))[:,None,None]
        return heatmap

    def dark_parse(self, hm, coord):
        height,width=hm.shape;x,y=map(int,coord)
        if 1<x<width-2 and 1<y<height-2:
            dx=.5*(hm[y,x+1]-hm[y,x-1])
            dy=.5*(hm[y+1,x]-hm[y-1,x])
            dxx=.25*(hm[y,x+2]-2*hm[y,x]+hm[y,x-2])
            dxy=.25*(hm[y+1,x+1]-hm[y-1,x+1]-hm[y+1,x-1]+hm[y-1,x-1])
            dyy=.25*(hm[y+2,x]-2*hm[y,x]+hm[y-2,x])
            determinant=dxx*dyy-dxy**2
            if determinant!=0:
                coord+=np.array([-(dyy*dx-dxy*dy)/determinant,
                                 -(dxx*dy-dxy*dx)/determinant])
        return coord

    def dark_postprocess(self, hm, coords, kernelsize):
        hm=self.gaussian_blur(hm,kernelsize)
        for n in range(coords.shape[0]):
            for p in range(coords.shape[1]):
                x,y=map(int,coords[n,p]);height,width=hm.shape[2:]
                if 1<x<width-2 and 1<y<height-2:
                    local=hm[n,p,y-2:y+3,x-2:x+3]
                    local[:]=np.log(np.maximum(local,1e-10))
                    coords[n,p]=self.dark_parse(hm[n,p],coords[n,p])
        return coords


class Geometry:
    hand_presence_threshold=.85
    def __init__(self,root):
        cv2.setNumThreads(1)
        self.hand_native=None;self.hand_native_calls=0;self.hand_native_fallbacks=0
        if (Path(root)/'libhand_crop.so').is_file():
            self.hand_native=C.CDLL(str(Path(root)/'libhand_crop.so'))
            self.hand_native.hand_crop224.argtypes=[C.c_void_p]*3
            self.hand_native.hand_crop224.restype=C.c_int
        self.api=C.CDLL(str(Path(root)/'libyf2_geometry.so'))
        self.api.yf2_pc_input_size.restype=C.c_int;self.api.yf2_pc_box_bytes.restype=C.c_int
        assert self.api.yf2_pc_input_size()==192 and self.api.yf2_pc_box_bytes()==C.sizeof(Box)
        self.api.yf2_pc_preprocess.argtypes=[C.c_void_p,C.c_int,C.c_int,C.c_void_p,C.c_void_p]
        self.api.yf2_pc_decode_heads.argtypes=[C.c_void_p,C.c_int,C.POINTER(Box),C.c_int]
        self.anchors=np.concatenate([np.repeat(np.array([[(x+.5)/n,(y+.5)/n]for y in range(n)for x in range(n)],np.float32),repeats,axis=0)for n,repeats in[(24,2),(12,6)]])
        self.affine=TopDownEvalAffine(trainsize=[192,256]);self.dark=SparseLogDARK(use_dark=True)
        if (Path(root)/'libgaussian3.so').is_file():
            from native_dark import NativeDARK
            self.dark=NativeDARK(root)
        self.mean=np.asarray([.485,.456,.406],np.float32).reshape(1,1,3)
        self.std=np.asarray([.229,.224,.225],np.float32).reshape(1,1,3)
        self.body_scales=np.asarray(json.loads((Path(root)/'body_plan.json').read_text())['input_quant'][0])
        levels=np.repeat(np.arange(256,dtype=np.uint8).reshape(256,1,1),3,axis=2)
        normalized=(levels.astype(np.float32)/255.-self.mean)/self.std
        self.body_lut=np.clip(np.rint(normalized.astype(np.float64)/self.body_scales),-128,127).astype(np.int8)
        np.testing.assert_array_equal(cv2.LUT(levels,self.body_lut),self.body_lut)

    def person_input(self,frame):
        q=np.empty((192,192,3),np.int8)
        assert self.api.yf2_pc_preprocess(frame.ctypes.data,frame.shape[1],frame.shape[0],q.ctypes.data,None)==0
        return q

    def person_decode(self,heads,shape):
        assert heads.dtype==np.int8 and heads.flags.c_contiguous
        out=(Box*32)();count=self.api.yf2_pc_decode_heads(heads.ctypes.data,heads.size,out,32)
        assert 0<=count<=32
        return [[b.x1*shape[1]/192,b.y1*shape[0]/192,b.x2*shape[1]/192,b.y2*shape[0]/192,b.score]for b in list(out)[:count]]

    def palm_input(self,frame):
        h,w=frame.shape[:2];scale=192/max(w,h);pad=np.array([(192-w*scale)*.5,(192-h*scale)*.5],np.float32)
        image=cv2.warpAffine(frame,np.array([[scale,0,pad[0]],[0,scale,pad[1]]],np.float32),(192,192),borderMode=cv2.BORDER_CONSTANT)
        return np.bitwise_xor(cv2.cvtColor(image,cv2.COLOR_BGR2RGB),np.uint8(128)).view(np.int8)

    def palm_decode(self,heads,shape):
        h,w=shape[:2];scale=192/max(w,h);pad=np.array([(192-w*scale)*.5,(192-h*scale)*.5],np.float32)
        raw=heads[:36288].reshape(2016,18);score=1/(1+np.exp(-np.clip(heads[36288:],-80,80)))
        center=(raw[:,:2]/192+self.anchors)*192;extent=raw[:,2:4]
        boxes=np.concatenate(((center-extent*.5-pad)/scale,(center+extent*.5-pad)/scale),axis=1)
        points=((raw[:,4:].reshape(-1,7,2)/192+self.anchors[:,None])*192-pad)/scale
        order=np.flatnonzero(score>=.25);order=order[np.argsort(score[order])[::-1]];detections=[]
        while len(order) and len(detections)<2:
            first=order[0];other=boxes[order]
            intersection=np.maximum(0,np.minimum(boxes[first,2:],other[:,2:])-np.maximum(boxes[first,:2],other[:,:2])).prod(1)
            area=np.maximum(0,other[:,2:]-other[:,:2]).prod(1);own=np.maximum(0,boxes[first,2:]-boxes[first,:2]).prod()
            overlap=intersection/np.maximum(1,area+own-intersection)>.3;overlap[0]=True
            ids=order[overlap];weights=score[ids]/score[ids].sum();box=(boxes[ids]*weights[:,None]).sum(0);p=(points[ids]*weights[:,None,None]).sum(0)
            up=p[2]-p[0];length=float(np.linalg.norm(up));order=order[~overlap]
            if length<1e-6:continue
            up/=length;axes=np.array([[-up[1],up[0]],[-up[0],-up[1]]],np.float32)
            size=box[2:]-box[:2];center=(box[:2]+box[2:])*.5-.5*size[1]*axes[1];side=max(2.,2.6*float(size.max()))
            transform=np.column_stack((axes/side,.5-(axes@center)/side)).astype(np.float32)
            detections.append(dict(box=box.tolist(),transform=transform,score=float(score[ids].mean())))
        return detections

    def hand_input(self,frame,detection):
        if self.hand_native is not None:
            assert frame.shape==(480,800,3)and frame.dtype==np.uint8 and frame.flags.c_contiguous
            matrix=np.ascontiguousarray(detection['transform']*224,dtype=np.float32)
            assert matrix.shape==(2,3)
            output=np.empty((224,224,3),np.int8)
            if self.hand_native.hand_crop224(frame.ctypes.data,matrix.ctypes.data,output.ctypes.data)==0:
                self.hand_native_calls+=1;return output
            self.hand_native_fallbacks+=1
        image=cv2.warpAffine(frame,detection['transform']*224,(224,224),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
        return np.bitwise_xor(cv2.cvtColor(image,cv2.COLOR_BGR2RGB),np.uint8(128)).view(np.int8)

    def hand_decode(self,heads,detection):
        transform=detection['transform'];xy=(heads[:42].reshape(21,2)-transform[:,2])@np.linalg.inv(transform[:,:2]).T
        valid=np.isfinite(xy).all(1)&(xy[:,0]>=0)&(xy[:,0]<800)&(xy[:,1]>=0)&(xy[:,1]<480)&(heads[42]>=self.hand_presence_threshold)
        box=np.array(detection['box']);box[[0,2]]=np.clip(box[[0,2]],0,800);box[[1,3]]=np.clip(box[[1,3]],0,480)
        return dict(points=xy.tolist(),valid=valid.tolist(),box=box.tolist(),whole_hand_presence=float(heads[42]),hand_presence_threshold=self.hand_presence_threshold,palm_score=float(detection['score']),handedness_probability=float(heads[43]),side=None,color_side='Left')

    def body_input(self,frame,box):
        crop,expanded,original=expand_crop(frame,np.asarray([0.,box[4],*box[:4]]))
        if crop is None or not crop.size:return None
        info=dict(im_shape=np.asarray(crop.shape[:2],np.float32));rgb=cv2.cvtColor(crop,cv2.COLOR_BGR2RGB)
        image,_=self.affine(rgb,info);q=cv2.LUT(image,self.body_lut)
        return q,info,expanded

    def body_decode(self,heads,prepared):
        if hasattr(self.dark,'decode'):
            points=self.dark.decode(heads,prepared)
            if points is not None:return points
        _,info,expanded=prepared;size=info['im_shape'][::-1][None]
        # The native graph exports NHWC; the official DARK decoder takes NCHW.
        heatmaps=heads.reshape(1,64,48,17).transpose(0,3,1,2).copy()
        points,_=self.dark(heatmaps,np.round(size/2.),size/200.)
        points[0,:,:2]+=expanded[:2];return points[0]
