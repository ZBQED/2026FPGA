"""Check integer pixels against fixed digests and actual same-FB DRM receipts."""
from pathlib import Path
import argparse,ctypes as C,hashlib,json,os,random
import numpy as np

class Topology(C.Structure):
 _fields_=[(n,C.c_uint32)for n in ['crtc_id','connector_id','width','height','mode_clock_khz','htotal','vtotal','timestamp_monotonic']]
class Receipt(C.Structure):
 _fields_=[(n,C.c_uint64)for n in ['copy_fence_ns','event1_ns','event2_ns','observed1_ns','observed2_ns','irq_before','irq_after']]+[(n,C.c_uint32)for n in ['sequence1','sequence2','crtc_id','events_seen','verified']]+[('error',C.c_int32)]+[(n,C.c_uint32)for n in ['same_fb_atomic_commits','atomic_test_only']]
def load(path):
 a=C.CDLL(str(path));a.li_resize_800_640_bgr.argtypes=[C.c_void_p,C.c_uint32,C.c_void_p,C.c_uint32]
 a.li_logical_x_q20_to_capture.argtypes=[C.c_int64];a.li_logical_x_q20_to_capture.restype=C.c_int64
 a.li_draw_point_q20.argtypes=[C.c_void_p]+[C.c_uint32]*3+[C.c_int64]*2+[C.c_uint32]*2
 a.li_draw_line_q20.argtypes=[C.c_void_p]+[C.c_uint32]*3+[C.c_int64]*4+[C.c_uint32]*2
 a.li_scan_validate_fd.argtypes=[C.c_int,C.POINTER(Topology)]
 a.li_scan_after_copy.argtypes=[C.c_int,C.c_uint32,C.c_uint32,C.POINTER(Receipt)]
 return a
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--library',type=Path,required=True);parser.add_argument('--reference',type=Path);parser.add_argument('--golden',type=Path);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--drm',action='store_true');args=parser.parse_args()
api=load(args.library);reference=load(args.reference)if args.reference else None
gold=json.loads(args.golden.read_text())if args.golden else None
r=dict(status='RUNNING',library_sha256=hashlib.sha256(args.library.read_bytes()).hexdigest(),cases=[],drm=[])
if reference:
 rng=random.Random(71);cases=[]
 for i in range(900):
  kind='point'if i<450 else'line';coordinates=[rng.randint(-50*(1<<20),150*(1<<20))for _ in range(2 if kind=='point'else 4)]
  cases.append(dict(kind=kind,coordinates=coordinates,color=rng.randrange(1<<24),size=i%14 if kind=='point'else 1+i%8))
 for kind in ['point','line']:
  for edge in [-(1<<32)-1,-(1<<32),-(1<<19),-1,0,1,(1<<19),(1<<32),(1<<32)+1]:
   cases.append(dict(kind=kind,coordinates=[edge,0]if kind=='point'else[edge,0,25<<20,25<<20],color=0xff8932,size=4))
 logical=[-(1<<63),(1<<63)-1]+[rng.randint(-(1<<63),(1<<63)-1)for _ in range(200)]+[i*(1<<18)for i in range(-100,101)]
else:
 assert gold,'Provide --reference or --golden';cases=[x['spec']for x in gold['cases']];logical=[x['input']for x in gold['logical']]
for index,spec in enumerate(cases):
 a=np.full(64+64*305+64,0xa5,np.uint8);b=a.copy();offset=64
 name='li_draw_point_q20'if spec['kind']=='point'else'li_draw_line_q20';params=[96,64,305]+spec['coordinates']+[spec['color'],spec['size']]
 rc=getattr(api,name)(a.ctypes.data+offset,*params)
 if reference:
  expected=getattr(reference,name)(b.ctypes.data+offset,*params);assert rc==expected and np.array_equal(a,b),(index,spec,rc,expected,np.count_nonzero(a!=b))
 else:assert rc==gold['cases'][index]['returncode']
 digest=hashlib.sha256(a.tobytes()).hexdigest()
 if not reference:assert digest==gold['cases'][index]['sha256'],index
 assert np.all(a[:64]==0xa5)and np.all(a[-64:]==0xa5)
 r['cases'].append(dict(spec=spec,returncode=rc,sha256=digest))
r['logical']=[]
for i,value in enumerate(logical):
 result=api.li_logical_x_q20_to_capture(value);expected=reference.li_logical_x_q20_to_capture(value)if reference else gold['logical'][i]['output'];assert result==expected,(value,result,expected);r['logical'].append(dict(input=value,output=result))
r['resize']=[]
for i in range(8):
 source=((np.arange(480*2416,dtype=np.uint32)*37+(np.arange(480*2416,dtype=np.uint32)>>8)*11+i*71)&255).astype(np.uint8)
 a=np.full(480*1936+128,0xa5,np.uint8);b=a.copy();rc=api.li_resize_800_640_bgr(source.ctypes.data,2416,a.ctypes.data+64,1936)
 if reference:assert rc==reference.li_resize_800_640_bgr(source.ctypes.data,2416,b.ctypes.data+64,1936)==0 and np.array_equal(a,b),i
 digest=hashlib.sha256(a.tobytes()).hexdigest()
 if not reference:assert digest==gold['resize'][i]['sha256']and rc==0
 r['resize'].append(dict(pattern=i,sha256=digest))
if args.drm:
 fd=os.open('/dev/dri/card1',os.O_RDWR|os.O_NONBLOCK|os.O_CLOEXEC)
 try:
  before=Topology();assert api.li_scan_validate_fd(fd,C.byref(before))==0
  for publication in range(1,7):
   receipt=Receipt();rc=api.li_scan_after_copy(fd,publication,150,C.byref(receipt));row={n:int(getattr(receipt,n))for n,_ in receipt._fields_}
   assert rc==0 and row['verified']==1 and row['events_seen']==2 and row['same_fb_atomic_commits']==2 and row['atomic_test_only']==1,(rc,row)
   assert row['copy_fence_ns']<row['event1_ns']<row['event2_ns']<=row['observed2_ns']and row['irq_after']>row['irq_before']
   after=Topology();assert api.li_scan_validate_fd(fd,C.byref(after))==0 and bytes(before)==bytes(after)
   r['drm'].append(row)
 finally:os.close(fd)
r['status']='PASS';args.output.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],pixel_cases=len(r['cases']),logical_cases=len(r['logical']),resize_cases=len(r['resize']),actual_scan_receipts=len(r['drm']))))
