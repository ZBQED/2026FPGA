"""Original float arithmetic with native Body postprocessing on Nav."""
import ctypes as C
from pathlib import Path
import numpy as np
from perception_geometry import SparseLogDARK
from keypoint_preprocess import get_affine_transform

class NativeDARK(SparseLogDARK):
    def __init__(self,root):
        super().__init__(use_dark=True)
        self.api=C.CDLL(str(Path(root)/'libgaussian3.so'))
        self.api.body_prepare.argtypes=[C.c_void_p,C.c_void_p,C.c_void_p]
        self.api.body_finish.argtypes=[C.c_void_p,C.c_void_p,C.c_void_p]
        self.affine_key=None;self.affine=None

    def decode(self,heads,prepared):
        assert heads.dtype==np.float32 and heads.flags.c_contiguous and heads.size==64*48*17
        patch=np.empty((17,25),np.float32);points=np.empty((17,3),np.float32)
        if self.api.body_prepare(heads.ctypes.data,patch.ctypes.data,points.ctypes.data)!=0:return None
        np.log(patch,out=patch)
        _,info,expanded=prepared;key=tuple(info['im_shape'])
        if key!=self.affine_key:
            size=info['im_shape'][::-1][None]
            self.affine=get_affine_transform(np.round(size/2.)[0],(size/200.)[0]*200,0,[48,64],inv=1);self.affine_key=key
        assert self.affine.dtype==np.float64 and self.affine.flags.c_contiguous
        assert self.api.body_finish(patch.ctypes.data,points.ctypes.data,self.affine.ctypes.data)==0
        points[:,:2]+=expanded[:2]
        return points

