"""Linux ARM32 glibc thread usage ABI; no optional Python resource extension dependency."""
import ctypes as C
FIELDS=('ru_maxrss','ru_ixrss','ru_idrss','ru_isrss','ru_minflt','ru_majflt','ru_nswap','ru_inblock','ru_oublock','ru_msgsnd','ru_msgrcv','ru_nsignals','ru_nvcsw','ru_nivcsw')
COUNTERS=('ru_minflt','ru_majflt','ru_nvcsw','ru_nivcsw')
class Timeval(C.Structure):_fields_=[('tv_sec',C.c_long),('tv_usec',C.c_long)]
class RUsage(C.Structure):_fields_=[('ru_utime',Timeval),('ru_stime',Timeval)]+[(n,C.c_long)for n in FIELDS]
def make_thread_usage(libc=None):
 assert C.sizeof(C.c_long)==4 and C.sizeof(RUsage)==72,'Requires actual verified ARM32 glibc rusage ABI'
 assert [getattr(RUsage,n).offset for n in COUNTERS]==[32,36,64,68]
 if libc is None:libc=C.CDLL(None,use_errno=True)
 call=libc.getrusage;call.argtypes=[C.c_int,C.POINTER(RUsage)];call.restype=C.c_int
 def snapshot():
  out=RUsage();C.set_errno(0);rc=call(1,C.byref(out))
  if rc:raise OSError(C.get_errno(),'libc getrusage(RUSAGE_THREAD=1) failed')
  result={n:int(getattr(out,n))for n in COUNTERS};assert all(v>=0 for v in result.values());return result
 return snapshot
