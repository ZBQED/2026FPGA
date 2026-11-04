"""Resident original YOLO: 79 PL MAC calls, board requantization, no fallback."""
import ctypes as C
import json,os,threading,time
import numpy as np


class PersonRaw:
    def __init__(self,folder,parent_fd,base=0):
        self.pid=os.getpid();self.thread=threading.get_ident();self.closed=True
        self.api=C.CDLL(str(folder/'libyf2_raw_pl.so'));a=self.api
        a.yf2_fpga_open_at.argtypes=[C.c_int,C.c_uint32];a.yf2_fpga_stats.argtypes=[C.c_void_p]
        a.yf2_pc_infer_quantized.argtypes=[C.c_void_p];a.yf2_pc_copy_heads.argtypes=[C.c_void_p]
        layers=json.loads((folder/'layers.json').read_text());self.head_count=sum(int(np.prod(l['shape']))for l in layers if l['name']in('Conv_256','Conv_257','Conv_258','Conv_259','Conv_260','Conv_261'))
        rc=a.yf2_fpga_open_at(parent_fd,base);assert rc==0,('Person initialize',rc)
        self.closed=False
        assert a.yf2_fpga_pool_used()<7<<20

    def stats(self):
        v=(C.c_uint64*7)();assert self.api.yf2_fpga_stats(v)==7;return np.asarray(list(v),np.uint64)

    def infer(self,x):
        assert not self.closed and self.pid==os.getpid()and self.thread==threading.get_ident()
        assert x.shape==(192,192,3)and x.dtype==np.int8
        x=np.ascontiguousarray(x);before=self.stats();t=time.monotonic_ns()
        rc=self.api.yf2_pc_infer_quantized(x.ctypes.data);elapsed=time.monotonic_ns()-t;delta=self.stats()-before
        assert rc==0 and delta[0]==79 and self.api.yf2_fpga_guards()==0,('Person forward',rc,delta.tolist())
        out=np.empty(self.head_count,np.int8);assert self.api.yf2_pc_copy_heads(out.ctypes.data)==out.size
        return out,dict(PL_jobs=79,complete_call_ns=elapsed,native=delta.tolist(),PS_convolution_calls=0)

    def close(self):
        if not self.closed:self.api.yf2_fpga_close();self.closed=True
