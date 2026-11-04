"""Resident real Nav FPGA output heads; existing bit, camera and video stay loaded."""
from pathlib import Path
import ctypes as C,hashlib,json,time
import numpy as np

class NavHeads:
    def __init__(self,root):
        self.handle=None;self.params={};root=Path(root);self.manifest=json.loads((root/'head_manifest.json').read_text())
        path=Path('/opt/gesture-tcn-20261022/build_runtime/libgesture_tflite_pl.so')
        assert hashlib.sha256(path.read_bytes()).hexdigest()==self.manifest['native_library_sha256']
        self.lib=C.CDLL(str(path));a=self.lib;a.gp_backend_name.restype=C.c_char_p;a.gp_last_error.restype=C.c_char_p
        a.gp_open_device.argtypes=[C.c_char_p];a.gp_open_device.restype=C.c_void_p;a.gp_close_device.argtypes=[C.c_void_p]
        a.gp_run.argtypes=[C.c_void_p]*6;a.gp_run.restype=C.c_int;a.gp_get_stats.argtypes=[C.c_void_p,C.POINTER(C.c_uint64)]
        assert a.gp_backend_name()==b'zynq_pl_coherent_dma'
        for name,m in self.manifest['models'].items():
            self.params[name]=[]
            for j,group in enumerate(m['groups']):
                filename=name+'_0_group'+str(j)+'.npz';path=root/filename
                assert hashlib.sha256(path.read_bytes()).hexdigest()==self.manifest['files'][filename]
                with np.load(str(path),allow_pickle=False)as z:self.params[name].append(tuple(np.ascontiguousarray(z[k])for k in('weights','bias','config','output_shape')))
        self.handle=a.gp_open_device(b'/dev/gesture-pl0');assert self.handle,a.gp_last_error()

    def stats(self):
        v=(C.c_uint64*4)();self.lib.gp_get_stats(self.handle,v);return list(v)

    def infer(self,name,features):
        assert len(features)==len(self.params[name]);start=time.monotonic_ns();before=self.stats();outputs=[]
        for x,(w,b,c,expected)in zip(features,self.params[name]):
            assert x.dtype==np.float32 and x.size==int(c[2])*int(c[3])*int(c[4]);x=np.ascontiguousarray(x);y=np.empty(tuple(int(v) for v in expected),np.float32)
            rc=self.lib.gp_run(self.handle,x.ctypes.data,w.ctypes.data,b.ctypes.data,y.ctypes.data,c.ctypes.data)
            assert rc==0 and np.isfinite(y).all(),self.lib.gp_last_error();outputs.append(y.ravel())
        elapsed=time.monotonic_ns()-start;after=self.stats();delta=[a-b for a,b in zip(after,before)];assert delta[0]==len(features)
        return np.concatenate(outputs),dict(backend='Nav_FPGA_real_output_convolutions',PL_jobs=delta[0],device_ns=delta[1],complete_call_ns=elapsed,input_bytes=delta[2],output_bytes=delta[3])

    def close(self):
        if self.handle:self.lib.gp_close_device(self.handle);self.handle=None
