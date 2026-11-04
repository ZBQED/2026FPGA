"""Only owned uint8 pixels and explicit Q16/Q20 drawing enter this helper."""

from pathlib import Path

import ctypes as C

import numpy as np

HAND_EDGES=[(0,1),(1,2),(2,3),(3,4),(0,5),(5,6),(6,7),(7,8),(5,9),(9,10),(10,11),(11,12),(9,13),(13,14),(14,15),(15,16),(13,17),(0,17),(17,18),(18,19),(19,20)]

BODY_EDGES=[(5,6),(5,7),(7,9),(6,8),(8,10),(5,11),(6,12),(11,12),(11,13),(13,15),(12,14),(14,16)]

class ScanReceipt(C.Structure):

    _fields_=[(n,C.c_uint64) for n in ('copy_fence_ns','event1_ns','event2_ns','observed1_ns','observed2_ns','irq_before','irq_after')]+[(n,C.c_uint32) for n in ('sequence1','sequence2','crtc_id','events_seen','verified')]+[('error',C.c_int32)]+[(n,C.c_uint32) for n in ('same_fb_atomic_commits','atomic_test_only')]

assert C.sizeof(ScanReceipt)==88



def scan_liveness_probe(fd):

    lib=C.CDLL(str(Path(__file__).with_name('libreport_integer_image.so')))

    lib.li_scan_after_copy.argtypes=[C.c_int,C.c_uint32,C.c_uint32,C.POINTER(ScanReceipt)]

    value=ScanReceipt();rc=lib.li_scan_after_copy(fd,0x7fffff,150,C.byref(value))

    return dict(status='REAL_TWO_VBLANK_LIVENESS' if not rc else 'UNSUPPORTED_OR_FAILED_VBLANK_LIVENESS',returncode=rc,receipt={name:int(getattr(value,name)) for name,_ in ScanReceipt._fields_},source_frame_latency_claimed=False,model_RUN=0)

class IntegerImage:

    def __init__(self,path=None):

        self.lib=C.CDLL(str(path or Path(__file__).with_name('libreport_integer_image.so')))

        self.lib.li_resize_800_640_bgr.argtypes=[C.c_void_p,C.c_uint32,C.c_void_p,C.c_uint32]

        self.lib.li_draw_line_q20.argtypes=[C.c_void_p]+[C.c_uint32]*3+[C.c_int64]*4+[C.c_uint32]*2

        self.lib.li_draw_point_q20.argtypes=[C.c_void_p]+[C.c_uint32]*3+[C.c_int64]*2+[C.c_uint32]*2

    def resize(self,capture):

        if capture.dtype!=np.uint8 or capture.shape!=(480,800,3) or not capture.flags.c_contiguous:raise ValueError('Actual owned800x480 uint8 source required')

        out=np.empty((480,640,3),np.uint8)

        if self.lib.li_resize_800_640_bgr(capture.ctypes.data,2400,out.ctypes.data,1920):raise RuntimeError('Integer camera resize failed')

        return out

    def compose(self,capture,row):

        out=capture.copy();base=(out.ctypes.data,800,480,2400)

        def line(a,b,color,thickness=4):

            if self.lib.li_draw_line_q20(*(base+tuple(map(int,a))+tuple(map(int,b))+(color,thickness))):raise RuntimeError('Integer line failed')

        def point(a,color,radius):

            if self.lib.li_draw_point_q20(*(base+tuple(map(int,a))+(color,radius))):raise RuntimeError('Integer point failed')

        if row['status']!='PASS':return out

        for box in row.get('person_boxes_Q16',[]):

            x0,y0,x1,y1=[int(v)<<4 for v in box];corners=[(x0,y0),(x1,y0),(x1,y1),(x0,y1)]

            for a,b in zip(corners,corners[1:]+corners[:1]):line(a,b,0x00ff00)

        body=row['branches']['body']['reply'];xy=body['xy_q20'];missing=body['missing'];origin=body['roi']['origin']

        xy=[[int(p[0])+(origin[0]<<20),int(p[1])+(origin[1]<<20)] for p in xy]

        for a,b in BODY_EDGES:

            line(xy[a],xy[b],0x00e5ff)

        for p,absent in zip(xy,missing):

            point(p,0x102128,6);point(p,0xffeb3b,5)

        final=row['branches']['hands_finalize']['reply']['result'];origin=final['roi']['origin']

        for index,hand in enumerate(final['points']):

            xy=[[(int(p[0])<<4)+(origin[0]<<20),(int(p[1])<<4)+(origin[1]<<20)] for p in hand['pixels_Q16']];missing=hand['joint_missing'];xs=[p[0]for p in xy];ys=[p[1]for p in xy];pad=4<<20;corners=[(min(xs)-pad,min(ys)-pad),(max(xs)+pad,min(ys)-pad),(max(xs)+pad,max(ys)+pad),(min(xs)-pad,max(ys)+pad)]

            for a,b in zip(corners,corners[1:]+corners[:1]):line(a,b,0xffea00)

            color=0x00ff66 if index==0 else 0xff3dce

            for a,b in HAND_EDGES:

                line(xy[a],xy[b],color)

            for p,absent in zip(xy,missing):

                point(p,0x102128,5);point(p,0xffffff,4)

        return out

