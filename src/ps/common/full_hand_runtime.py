"""Approved Full Hand on PL, with one persistent native mapping and fixed weights."""
import ctypes as C
import os
import threading
import time
import numpy as np


class FullHand:
    def __init__(self, folder, parent_fd=None):
        self.pid=os.getpid();self.thread=threading.get_ident();self.closed=True;self.failed=False
        self.api=C.CDLL(str(folder/'libfull_hand_pl.so'));a=self.api
        a.fh_open.argtypes=[C.c_char_p];a.fh_open.restype=C.c_int
        a.fh_attach.argtypes=[C.c_int,C.c_char_p];a.fh_attach.restype=C.c_int
        a.fh_run.argtypes=[C.c_void_p,C.c_uint32,C.c_void_p,C.c_uint32,C.c_void_p];a.fh_run.restype=C.c_int
        a.fh_copy_tensor.argtypes=[C.c_uint32,C.c_void_p,C.c_uint32];a.fh_copy_tensor.restype=C.c_int
        a.fh_close.argtypes=[];a.fh_close.restype=C.c_int
        a.fh_trace.argtypes=[C.c_int];a.fh_trace.restype=C.c_int
        weights=os.fsencode(folder/'hand_weights.bin')
        if parent_fd is not None:
            assert os.readlink('/proc/self/fd/'+str(parent_fd))=='/dev/gesture-i8-pl0'
            code=a.fh_attach(parent_fd,weights)
        else:code=a.fh_open(weights)
        if code:raise RuntimeError('Full Hand initialization: '+str(code))
        self.closed=False

    def checked(self):
        if os.getpid()!=self.pid or threading.get_ident()!=self.thread or self.closed or self.failed:
            raise RuntimeError('Full Hand requires its healthy creating process/thread')

    def infer(self, x):
        self.checked()
        if x.dtype!=np.int8 or x.shape!=(224,224,3):raise ValueError('Pinned INT8 HWC224 RGB required')
        x=np.ascontiguousarray(x);heads=np.empty(44,np.float32);stats=np.zeros(8,np.uint64)
        start=time.monotonic_ns();code=self.api.fh_run(x.ctypes.data,x.nbytes,heads.ctypes.data,44,stats.ctypes.data)
        wall=time.monotonic_ns()-start
        if code or stats[0]!=50:
            self.failed=True;raise RuntimeError('Full Hand failed: '+str((code,stats.tolist())))
        return heads,dict(complete_call_ns=wall,PL_jobs=int(stats[0]),driver_ns=int(stats[2]),
                          PS_ns=int(stats[4]),native_ns=int(stats[6]))

    def tensor(self, index, size):
        self.checked();out=np.empty(size,np.int8)
        if self.api.fh_copy_tensor(index,out.ctypes.data,out.nbytes):raise RuntimeError('Full Hand trace copy failed')
        return out

    def trace(self,enabled):
        self.checked()
        if self.api.fh_trace(int(enabled)):raise RuntimeError('Full Hand trace setup failed')

    def close(self):
        if self.closed:return
        if os.getpid()!=self.pid or threading.get_ident()!=self.thread:raise RuntimeError('Close on original process/thread required')
        self.api.fh_close();self.closed=True
