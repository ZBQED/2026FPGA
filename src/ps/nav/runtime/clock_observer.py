"""GET-only DRM software-mode observation on PID1's already held exact fd.
No new /dev open, modeset, setmaster, MMIO or frequency measurement.
The structures are the xf86drmmode.h C fields used by the frozen C helper.
"""
import ctypes as C,os,struct
from pathlib import Path
class Mode(C.Structure):
 _fields_=[('clock',C.c_uint32)]+[(n,C.c_uint16) for n in ['hdisplay','hsync_start','hsync_end','htotal','hskew','vdisplay','vsync_start','vsync_end','vtotal','vscan']]+[(n,C.c_uint32) for n in ['vrefresh','flags','type']]+[('name',C.c_char*32)]
class Crtc(C.Structure):
 _fields_=[(n,C.c_uint32) for n in ['crtc_id','buffer_id','x','y','width','height']]+[('mode_valid',C.c_int),('mode',Mode),('gamma_size',C.c_int)]
assert C.sizeof(Mode)==68 and C.sizeof(Crtc)==100 and Crtc.mode.offset==28
class ClockObserver:
 def __init__(self,owned_fd,snapshot_path):
  if type(owned_fd) is not int or owned_fd<3 or os.readlink('/proc/self/fd/'+str(owned_fd))!='/dev/dri/card1':raise RuntimeError('Exact existing HDMI DRM keeper fd required')
  raw=Path(snapshot_path).read_bytes()
  if len(raw)<32 or struct.unpack_from('<II',raw)!=(0x314d484e,1):raise RuntimeError('Frozen C capture header differs')
  self.fd=owned_fd;self.crtc=struct.unpack_from('<I',raw,8)[0]
  self.lib=C.CDLL('libdrm.so.2',use_errno=True)
  self.lib.drmModeGetCrtc.argtypes=[C.c_int,C.c_uint32];self.lib.drmModeGetCrtc.restype=C.POINTER(Crtc)
  self.lib.drmModeFreeCrtc.argtypes=[C.POINTER(Crtc)];self.lib.drmModeFreeCrtc.restype=None
 def matches(self):
  p=self.lib.drmModeGetCrtc(self.fd,self.crtc)
  if not p:return False
  try:
   r=p.contents;m=r.mode
   return bool(r.crtc_id==self.crtc and r.mode_valid==1 and r.width==1024 and r.height==600 and
    (m.clock,m.hdisplay,m.hsync_start,m.hsync_end,m.htotal,m.hskew,m.vdisplay,m.vsync_start,m.vsync_end,m.vtotal,m.vscan,m.vrefresh,m.flags,m.type)==(49499,1024,1068,1156,1344,0,600,603,609,625,0,59,9,72) and bytes(m.name)==b'1024x600')
  finally:self.lib.drmModeFreeCrtc(p)
