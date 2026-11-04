"""Stable shared-frame reader with explicit kernel EOF or DQBUF provenance."""
from pathlib import Path
import ctypes as C
import mmap,os
import numpy as np
from shared_camera import SharedCameraReader,CameraError
TIM8,TIM9=0x384d4954,0x394d4954

class TimingSlot(C.Structure):
 _fields_=[(n,C.c_uint32) for n in ('guard','preview_sequence','driver_sequence','flags','kind','reason','reserved0','reserved1')]+[(n,C.c_uint64) for n in ('dequeue_ns','driver_ns','capture_ns','reserved64')]

class TimedCopy:
 def __init__(self,library,timing_path):
  self.library=C.CDLL(str(Path(library).resolve()))
  self.copy=self.library.mc_camera_copy_timed_kind
  self.copy.argtypes=[C.c_void_p,C.c_size_t,C.c_void_p,C.c_size_t,C.c_uint32,C.POINTER(C.c_uint32),C.POINTER(C.c_uint32),C.POINTER(C.c_uint64),C.POINTER(C.c_uint32)]
  self.copy.restype=C.c_int
  self.snapshot=self.library.mc_camera_timing_snapshot
  self.snapshot.argtypes=[C.c_void_p,C.c_size_t,C.c_uint32,C.POINTER(TimingSlot)];self.snapshot.restype=C.c_int
  self.capture_ns=0;self.kind=0;self.timing=None;self.mapping=None;self.view=None
  try:
   fd=os.open(str(timing_path),os.O_RDONLY)
   try:
    self.mapping=mmap.mmap(fd,256,access=mmap.ACCESS_READ)
    self.view=np.frombuffer(self.mapping,dtype=np.uint8)
   finally:os.close(fd)
  except FileNotFoundError:pass
 def __call__(self,mapping,destination,previous):
  copied,current,ns,kind=C.c_uint32(),C.c_uint32(),C.c_uint64(),C.c_uint32()
  rc=self.copy(mapping.ctypes.data,mapping.nbytes,destination.ctypes.data,destination.nbytes,previous,C.byref(copied),C.byref(current),C.byref(ns),C.byref(kind))
  if rc==1:
   self.capture_ns=ns.value;self.kind=kind.value;self.timing=None
   if self.mapping is not None:
    slot=TimingSlot()
    if self.snapshot(self.view.ctypes.data,256,copied.value,C.byref(slot))==1 and slot.kind==self.kind and slot.capture_ns==self.capture_ns:self.timing=slot
  return rc,copied.value,current.value
 def close(self):
  self.view=None
  if self.mapping is not None:self.mapping.close();self.mapping=None

class TimedCameraReader(SharedCameraReader):
 def __init__(self,*args,**kwargs):
  timing_path=kwargs.pop('timing_path','/run/medcomm/camera.timing')
  backend=TimedCopy(Path(__file__).with_name('libcamera_timed_arm.so'),timing_path)
  try:super().__init__(*args,_copy_backend=backend,**kwargs)
  except BaseException:backend.close();raise
 def read(self,*args,**kwargs):
  frame=super().read(*args,**kwargs);backend=self.copy_backend;ns=backend.capture_ns
  observed=frame.metadata['observed_monotonic_ns'];kernel=backend.kind==TIM9
  if not 0<ns<=observed:raise CameraError('Capture producer and reader monotonic clocks do not agree')
  frame.metadata.update(capture_timestamp_available=True,capture_complete_monotonic_ns=ns,capture_to_observation_ms=(observed-ns)/1e6,capture_timestamp_source='V4L2_kernel_MONOTONIC_EOF' if kernel else 'V4L2_DQBUF_observed_CLOCK_MONOTONIC_fallback',capture_timestamp_tag='TIM9' if kernel else 'TIM8',kernel_queue_delay_included=kernel,timestamp_ms=ns/1e6,timestamp_source='capture_complete_monotonic',capture_provenance_available=backend.timing is not None)
  t=backend.timing
  if t is not None:
   frame.metadata.update(v4l2_flags=t.flags,v4l2_driver_sequence=t.driver_sequence,v4l2_driver_timestamp_ns=t.driver_ns,dqbuf_observed_monotonic_ns=t.dequeue_ns,timestamp_selection_reason=t.reason,dqbuf_to_observation_ms=(observed-t.dequeue_ns)/1e6,driver_eof_to_dqbuf_ms=(t.dequeue_ns-t.driver_ns)/1e6 if kernel else None)
   if kernel and ((t.flags&0xe000)!=0x2000 or (t.flags&0x70000)!=0 or not 0<t.driver_ns<=t.dequeue_ns):raise CameraError('TIM9 provenance does not prove monotonic EOF')
  return frame
 def close(self):
  super().close()
  if hasattr(self,'copy_backend'):self.copy_backend.close()
