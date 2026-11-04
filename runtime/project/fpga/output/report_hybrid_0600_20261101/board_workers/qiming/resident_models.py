"""Three approved models in disjoint regions of one explicitly owned DMA pool."""
from pathlib import Path
import ctypes as C
import json,hashlib
import mmap
import os
import time
import numpy as np


class ResidentModels:
    def __init__(self, root, halfadd=False, palm_lut=False, workspace=False, parent_fd=None, fast_add=False, selected_models=None):
        self.root=Path(root);self.fd=-1;self.mapping=None;self.mapping_address=0;self.models={};self.fences=[]
        self.owns_fd=parent_fd is None
        assert self.owns_fd or workspace
        area=self.root/('shared_workspace'if workspace else'resident')
        self.layout=json.loads((area/'layout.json').read_text())
        if selected_models is not None:self.layout=[row for row in self.layout if row['model']in selected_models]
        if workspace:
            proof=json.loads((area/'manifest.json').read_text())
            assert hashlib.sha256((area/'layout.json').read_bytes()).hexdigest()==proof['layout_sha256']
            assert hashlib.sha256((self.root/'tcn508a/runtime/libgesture_lite_i8_v12.so').read_bytes()).hexdigest()==proof['tcn_bounds']['native_sha256']
        try:
            self.fd=os.open('/dev/gesture-i8-pl0',os.O_RDWR|os.O_CLOEXEC)if self.owns_fd else parent_fd
            if workspace:
                # Python mmap duplicates the descriptor on this ARM runtime.
                # Borrow the TCN owner's FD without creating another descriptor.
                self.libc=C.CDLL(None,use_errno=True)
                self.libc.mmap.argtypes=[C.c_void_p,C.c_size_t,C.c_int,C.c_int,C.c_int,C.c_long];self.libc.mmap.restype=C.c_void_p
                self.libc.munmap.argtypes=[C.c_void_p,C.c_size_t];self.libc.munmap.restype=C.c_int
                address=self.libc.mmap(None,16<<20,mmap.PROT_READ|mmap.PROT_WRITE,mmap.MAP_SHARED,self.fd,0)
                if address==C.c_void_p(-1).value:raise OSError(C.get_errno(),'Workspace mmap failed')
                self.mapping_address=address
                self.mapping=memoryview((C.c_ubyte*(16<<20)).from_address(address)).cast('B')
            else:self.mapping=mmap.mmap(self.fd,16<<20,flags=mmap.MAP_SHARED,prot=mmap.PROT_READ|mmap.PROT_WRITE)
            end=proof['boundary_guard']+64 if workspace else 0
            for row in self.layout:
                base=row['base'];size=row['pool_bytes'];assert base%64==0 and base>=end and base+size+64<=16<<20
                fence=base+(row['constant_bytes']if workspace else size);end=fence+64;folder=area/row['model']
                if workspace:assert end<=proof['workspace_base']
                library=(self.root/'full_body_channels_halfadd_cached/libfull_hand_pl.so')if halfadd and row['model']=='full_body_channels_cached'else folder/'libfull_hand_pl.so'
                if workspace:library=folder/'libfull_hand_pl.so'
                if fast_add and row['model']=='full_body_channels_cached':
                    assert workspace;library=self.root/'full_body_fastadd_workspace/libfull_hand_pl.so'
                if palm_lut and not workspace and row['model']=='full_palm_fused_cached':
                    candidate=self.root/'full_palm_fused_lut_cached'
                    for name in ('hand_plan.json','hand_weights.bin'):
                        assert hashlib.sha256((candidate/name).read_bytes()).digest()==hashlib.sha256((folder/name).read_bytes()).digest(),name
                    library=candidate/'libfull_hand_pl.so'
                row['native_library_sha256']=hashlib.sha256(library.read_bytes()).hexdigest()
                row['halfadd_selected']=bool((halfadd or workspace)and row['model']=='full_body_channels_cached')
                row['palm_lut_selected']=bool((palm_lut or workspace)and row['model']=='full_palm_fused_cached')
                row['shared_activation_workspace']=workspace
                api=C.CDLL(str(library))
                if workspace:
                    api.fh_workspace_api_version.argtypes=[];api.fh_workspace_api_version.restype=C.c_uint32
                    assert api.fh_workspace_api_version()==0x00010000
                api.fh_attach_at.argtypes=[C.c_int,C.c_char_p,C.c_uint32];api.fh_attach_at.restype=C.c_int
                api.fh_run.argtypes=[C.c_void_p,C.c_uint32,C.c_void_p,C.c_uint32,C.c_void_p];api.fh_run.restype=C.c_int
                api.fh_trace.argtypes=[C.c_int];api.fh_trace.restype=C.c_int
                api.fh_copy_tensor.argtypes=[C.c_uint32,C.c_void_p,C.c_uint32];api.fh_copy_tensor.restype=C.c_int
                api.fh_close.restype=C.c_int
                weights=os.fsencode(folder/'hand_weights.bin')
                assert api.fh_attach_at(-1,weights,base)==-22
                assert api.fh_attach_at(self.fd,weights,1)==-22
                assert api.fh_attach_at(self.fd,weights,(16<<20)-64)==(-22 if workspace else-75)
                code=api.fh_attach_at(self.fd,weights,base)
                if code:raise RuntimeError((row['model'],'attach',code))
                self.models[row['model']]=(api,row)
                self.mapping[fence:fence+64]=b'\x5a'*64;self.fences.append(fence)
            if workspace:
                for fence in (proof['boundary_guard'],proof['workspace_end']):
                    self.mapping[fence:fence+64]=b'\x5a'*64;self.fences.append(fence)
            self.guards()
        except BaseException:
            self.close();raise

    def guards(self):
        assert all(self.mapping[p:p+64]==b'\x5a'*64 for p in self.fences), 'Cross-model DMA fence changed'

    def infer(self, name, x, trace=False):
        api,row=self.models[name]
        assert x.dtype==np.int8 and x.size==row['input_elements']
        x=np.ascontiguousarray(x);heads=np.empty(row['head_values'],np.float32);stats=np.zeros(8,np.uint64)
        assert api.fh_trace(int(trace))==0
        start=time.monotonic_ns();code=api.fh_run(x.ctypes.data,x.nbytes,heads.ctypes.data,heads.size,stats.ctypes.data)
        wall=time.monotonic_ns()-start;self.guards()
        assert code==0 and stats[0]==row['PL_jobs'], (name,code,stats.tolist())
        return heads,dict(complete_call_ns=wall,PL_jobs=int(stats[0]),native=list(map(int,stats)))

    def close(self):
        for api,row in self.models.values():api.fh_close()
        self.models.clear()
        if self.mapping is not None:
            if self.mapping_address:
                self.mapping.release();assert self.libc.munmap(self.mapping_address,16<<20)==0;self.mapping_address=0
            else:self.mapping.close()
            self.mapping=None
        if self.fd>=0 and self.owns_fd:os.close(self.fd)
        self.fd=-1
