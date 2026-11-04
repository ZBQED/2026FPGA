"""Read-only DRM vblank observations; never modesets or opens the camera."""
import ctypes as C
import os
import time
from clock_observer import Crtc


class Request(C.Structure):
    _fields_=[('type',C.c_uint),('sequence',C.c_uint),('signal',C.c_ulong)]


class Reply(C.Structure):
    _fields_=[('type',C.c_uint),('sequence',C.c_uint),('seconds',C.c_long),('microseconds',C.c_long)]


class VBlank(C.Union):
    _fields_=[('request',Request),('reply',Reply)]


class ScanoutObserver:
    def __init__(self,crtc=33,writable=False):
        self.fd=os.open('/dev/dri/card1',(os.O_RDWR if writable else os.O_RDONLY)|os.O_CLOEXEC|os.O_NONBLOCK);self.crtc=crtc
        self.lib=C.CDLL('libdrm.so.2',use_errno=True)
        self.lib.drmModeGetCrtc.argtypes=[C.c_int,C.c_uint32];self.lib.drmModeGetCrtc.restype=C.POINTER(Crtc)
        self.lib.drmModeFreeCrtc.argtypes=[C.POINTER(Crtc)]
        self.lib.drmGetCap.argtypes=[C.c_int,C.c_uint64,C.POINTER(C.c_uint64)];self.lib.drmGetCap.restype=C.c_int
        self.lib.drmWaitVBlank.argtypes=[C.c_int,C.POINTER(VBlank)];self.lib.drmWaitVBlank.restype=C.c_int
        cap=C.c_uint64()
        assert self.lib.drmGetCap(self.fd,6,C.byref(cap))==0 and cap.value==1, 'Monotonic vblank clock required'
        self.initial=self.snapshot()
        assert self.initial[0]==crtc and self.initial[2:5]==(1,1024,600)

    def snapshot(self):
        p=self.lib.drmModeGetCrtc(self.fd,self.crtc)
        if not p:raise OSError(C.get_errno(),'GetCrtc')
        try:
            c=p.contents;return(c.crtc_id,c.buffer_id,c.mode_valid,c.width,c.height,bytes(c.mode))
        finally:self.lib.drmModeFreeCrtc(p)

    def matches(self):return self.snapshot()==self.initial

    def wait(self):
        v=VBlank();v.request.type=1;v.request.sequence=1
        start=time.monotonic_ns();code=self.lib.drmWaitVBlank(self.fd,C.byref(v));end=time.monotonic_ns()
        if code:raise OSError(C.get_errno(),'DRM relative vblank wait returned '+str(code))
        stamp=v.reply.seconds*1000000000+v.reply.microseconds*1000
        assert start<=stamp<=end and self.matches(), 'Vblank identity/clock changed'
        return dict(sequence=v.reply.sequence,timestamp_ns=stamp,request_ns=start,returned_ns=end)

    def after_copy(self,copied_ns):
        assert copied_ns<=time.monotonic_ns() and self.matches()
        first=self.wait();second=self.wait()
        assert first['timestamp_ns']>copied_ns and ((second['sequence']-first['sequence'])&0xffffffff)>0
        return dict(after_copy_vblanks=[first,second],scanout_bound_ns=second['timestamp_ns'],
                    scope='two DRM vblanks after paired front-buffer copy')

    def close(self):
        if self.fd>=0:os.close(self.fd);self.fd=-1


class Topology(C.Structure):
    _fields_=[(n,C.c_uint32)for n in('crtc_id','connector_id','width','height','mode_clock_khz','htotal','vtotal','timestamp_monotonic')]


class ScanReceipt(C.Structure):
    _fields_=[(n,C.c_uint64)for n in('copy_fence_ns','event1_ns','event2_ns','observed1_ns','observed2_ns','irq_before','irq_after')]+[(n,C.c_uint32)for n in('sequence1','sequence2','crtc_id','events_seen','verified')]+[('error',C.c_int32)]+[(n,C.c_uint32)for n in('same_fb_atomic_commits','atomic_test_only')]


class NativeScanoutObserver(ScanoutObserver):
    """Two verified same-FB presentation events after the paired copy; no modeset."""
    def __init__(self,library):
        super().__init__(writable=True)
        try:
            self.native=C.CDLL(str(library),use_errno=True);self.publication=0
            self.native.li_scan_validate_fd.argtypes=[C.c_int,C.POINTER(Topology)]
            self.native.li_scan_after_copy.argtypes=[C.c_int,C.c_uint32,C.c_uint32,C.POINTER(ScanReceipt)]
            topo=Topology();assert self.native.li_scan_validate_fd(self.fd,C.byref(topo))==0 and topo.crtc_id==self.crtc and topo.timestamp_monotonic==1
            self.topology={n:getattr(topo,n)for n,_ in topo._fields_}
        except BaseException:self.close();raise

    def after_copy(self,copied_ns):
        assert copied_ns<=time.monotonic_ns()and self.matches()
        self.publication+=1;receipt=ScanReceipt();requested=time.monotonic_ns()
        rc=self.native.li_scan_after_copy(self.fd,self.publication,150,C.byref(receipt));returned=time.monotonic_ns()
        row={n:getattr(receipt,n)for n,_ in receipt._fields_}
        assert rc==0 and receipt.verified==1 and receipt.events_seen==2 and receipt.same_fb_atomic_commits==2 and receipt.atomic_test_only==1,(rc,row)
        assert copied_ns<=receipt.copy_fence_ns<receipt.event1_ns<receipt.event2_ns<=returned
        assert receipt.irq_after>receipt.irq_before and self.matches()
        return dict(receipt=row,request_ns=requested,returned_ns=returned,scanout_bound_ns=receipt.event2_ns,
                    mode_and_framebuffer_unchanged=True,scope='two verified same-FB atomic presentation events plus VDMA IRQ')
