"""TCN models preloaded once on an already-open Lite backend owner.

Pass the same backend.api and backend.owner. Never loads another owner library,
opens Device/flock, or closes the parent Hand owner. Native calls are same-thread.
"""
from pathlib import Path
import ctypes as C
import os
import threading
import time
import numpy as np


class SharedTCN:
    def __init__(self,api,owner,assets):
        self.api=api;self.owner=owner;self.assets=Path(assets)
        self.pid=os.getpid();self.thread=threading.get_ident();self.handles={};self.failed=False
        p=C.c_void_p;u=C.c_uint64;i=C.c_int
        signatures={'gtcn_shared_api_version':([],C.c_uint32),
            'gtcn_open_shared':([p,C.c_char_p,i],p),'gtcn_close':([p],i),
            'gtcn_infer':([p,p,u,p,u,p,p],i),'gtcn_stats':([p,C.POINTER(u)],i),
            'gtcn_shared_owner_stats':([p,C.POINTER(u)],i),'gtcn_error':([],C.c_char_p)}
        for name,(args,result) in signatures.items():
            f=getattr(api,name);f.argtypes=args;f.restype=result
        if not owner or api.gtcn_shared_api_version()!=0x00010000:
            raise ValueError('Explicit parent owner and shared TCN API1 required')
        start=time.monotonic_ns();self.preload_profile_ns={}
        try:
            for profile,name in enumerate(('primary','roof')):
                stamp=time.monotonic_ns()
                handle=api.gtcn_open_shared(owner,os.fsencode(self.assets),profile)
                if not handle:raise RuntimeError(api.gtcn_error().decode())
                self.handles[name]=handle;self.preload_profile_ns[name]=time.monotonic_ns()-stamp
        except Exception:
            self.close();raise
        self.preload_total_ns=time.monotonic_ns()-start

    def checked(self):
        if self.pid!=os.getpid() or self.thread!=threading.get_ident():
            raise RuntimeError('Shared TCN requires its creating process/thread')
        if self.failed or not self.handles:raise RuntimeError('Failed or closed TCN runtime; no retry')

    def stats(self,name,owner=False):
        out=(C.c_uint64*(7 if owner else 12))()
        fn=self.api.gtcn_shared_owner_stats if owner else self.api.gtcn_stats
        if fn(self.handles[name],out):raise RuntimeError(self.api.gtcn_error().decode())
        return list(out)

    def infer(self,profile,values,mask):
        self.checked();f=96 if profile=='primary' else 112
        if profile not in self.handles or values.dtype!=np.int16 or values.shape!=(32,f) or mask.dtype!=np.uint8 or mask.shape!=values.shape or np.any(mask>1):
            raise ValueError('INT16[32,F] and binary UINT8 mask required')
        if not np.any(mask[:,:84]):raise ValueError('All-invalid word rejected without PL calls')
        values=np.ascontiguousarray(values);mask=np.ascontiguousarray(mask)
        before=self.stats(profile);obefore=self.stats(profile,True)
        logits=np.empty(27,np.int16);prob=np.empty(27,np.uint16);start=time.monotonic_ns()
        best=self.api.gtcn_infer(self.handles[profile],values.ctypes.data,values.size,
                                 mask.ctypes.data,mask.size,logits.ctypes.data,prob.ctypes.data)
        elapsed=time.monotonic_ns()-start
        if best<0:
            self.failed=True;raise RuntimeError(self.api.gtcn_error().decode())
        after=self.stats(profile);oafter=self.stats(profile,True)
        delta=[b-a for a,b in zip(before,after)];od=[b-a for a,b in zip(obefore,oafter)]
        if delta[0]!=16 or delta[4]!=1 or od[0]!=16 or od[4]!=1 or oafter[5] or oafter[6]:
            self.failed=True;raise RuntimeError('Exact16 shared owner transaction/healthy-state proof failed')
        return dict(profile=profile,class_index=int(best),logits_int16=logits.tolist(),probabilities_Q15=prob.tolist(),
                    integer_model_infer_ns=elapsed,owner_open_ns=0,owner_close_ns=0,
                    per_word_device_open=False,models_reloaded_per_word=False,
                    actual_PL_RUNs=delta[0],driver_ns=delta[1],input_bytes=delta[2],output_bytes=delta[3],words=delta[4],
                    integer_im2col_ns=delta[6],device_wall_ns=delta[7],output_copy_ns=delta[8],
                    integer_boundary_ns=delta[9],core_invoke_ns=delta[10],head_invoke_ns=delta[11],
                    shared_owner_before=obefore,shared_owner_after=oafter)

    def close(self):
        if not self.handles:return
        if self.pid!=os.getpid() or self.thread!=threading.get_ident():raise RuntimeError('Close on original process/thread required')
        failed=[]
        for name,handle in list(self.handles.items()):
            if self.api.gtcn_close(handle):failed.append(name)
        self.handles.clear()
        if failed:raise RuntimeError('Shared TCN closed failed handles: '+','.join(failed))
