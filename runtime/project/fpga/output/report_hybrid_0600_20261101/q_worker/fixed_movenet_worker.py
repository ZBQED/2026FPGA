"""Finite RAW32 probes of three split MoveNet layers, not complete inference."""
import fcntl
import hashlib
import json
import mmap
import os
from pathlib import Path
import signal
import struct
import time
import traceback
import numpy as np


def run(root, cfg):
    def stop(*unused):
        raise InterruptedError('Stop after the current driver call')
    signal.signal(signal.SIGTERM, stop)
    result=dict(status='FIXTURE_MOVENET_SPLIT_RUNNING',source_scope='fixed_fixture',
                fixture_kind='movenet_split',model_identity='MoveNet Lightning INT8 three isolated RAW32 layers',
                boot_id=cfg['boot_id'],session_id=cfg['session_id'],rows=[],errors=[],
                TCN_RUN=0,camera_opened=False,actual_NN_PL_RUN=0,full_frame_acceptance=False)
    def save():
        p=root/'rpc_actual.json.tmp';p.write_text(json.dumps(result,separators=(',',':')));p.replace(root/'rpc_actual.json')
    fd=pool=None
    try:
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==cfg['boot_id']
        for name,digest in json.loads((root/'package_manifest.json').read_text()).items():
            assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,name
        manifest=json.loads((root/'movenet_split.json').read_text())
        assert manifest['model_sha256']=='cd7cc22fa946e5d146a7b98d496853e1923e22828d3972d579973f27f91bb105'
        assert hashlib.sha256((root/'movenet_split.npz').read_bytes()).hexdigest()==manifest['fixture_sha256']
        assert len(manifest['cases'])==6
        result['source_model_sha256']=manifest['model_sha256']
        fd=os.open('/dev/gesture-i8-pl0',os.O_RDWR|os.O_CLOEXEC)
        info=bytearray(48);fcntl.ioctl(fd,0x80304980,info,True);info=list(struct.unpack('<12I',info))
        assert info[:4]==[0x3849504b,2,16*1024*1024,32] and info[8]==7
        result['driver_info']=info
        pool=mmap.mmap(fd,info[2],flags=mmap.MAP_SHARED,prot=mmap.PROT_READ|mmap.PROT_WRITE)
        layout=struct.Struct('<40IQ');guard=b'\xa5'*64
        with np.load(root/'movenet_split.npz',allow_pickle=False)as fixture:
            for row in manifest['cases']:
                k=row['case'];x=fixture['x'+str(k)];weights=fixture['w'+str(k)];expected=fixture['y'+str(k)]
                assert x.dtype==weights.dtype==np.int8 and expected.dtype==np.int32
                h,w,ci=x.shape;co=weights.shape[0]
                assert (h,w)==(6,6) and (ci,co)in((960,160),(320,640),(640,64))
                assert weights.shape==(co,ci) and expected.shape==(h,w,co) and np.any(expected)
                assert hashlib.sha256(expected.tobytes()).hexdigest()==row['expected_sha256']
                offsets=[64,2<<20,0,4<<20];sizes=[x.nbytes,weights.nbytes,0,expected.nbytes]
                for off,size in zip(offsets,sizes):
                    if size:
                        assert size%8==0 and size<(2<<20)-128
                        pool[off-64:off]=guard;pool[off+size:off+size+64]=guard
                started=time.monotonic_ns()
                pool[offsets[0]:offsets[0]+x.nbytes]=x.tobytes()
                pool[offsets[1]:offsets[1]+weights.nbytes]=weights.tobytes()
                copy_ns=time.monotonic_ns()-started
                config=[0x3849504b,2,0,0,h,w,ci,h,w,co,1,1,1,1,0,0,row['input_zero'],0,0,0,
                        x.nbytes//8,weights.nbytes//8,expected.nbytes//8,0]+[0]*8
                for repetition in range(5):
                    zero_test=repetition==4
                    if zero_test:pool[offsets[0]:offsets[0]+x.nbytes]=np.full_like(x,row['input_zero']).tobytes()
                    job=bytearray(layout.pack(*[v&0xffffffff for v in offsets+config+[10000,0,0,0]],0))
                    started=time.monotonic_ns();fcntl.ioctl(fd,0xc0a84981,job,True);elapsed=time.monotonic_ns()-started
                    returned=layout.unpack(job);assert returned[37]==0;result['actual_NN_PL_RUN']+=1
                    actual=np.frombuffer(pool[offsets[3]:offsets[3]+expected.nbytes],dtype='<i4').reshape(expected.shape)
                    exact=bool(np.all(actual==0))if zero_test else np.array_equal(actual,expected)
                    guards=all(pool[off-64:off]==guard and pool[off+size:off+size+64]==guard for off,size in zip(offsets,sizes)if size)
                    result['rows'].append(dict(case=k,source_operator=row['source_operator'],repetition=repetition,
                        warmup=repetition==0,zero_input=zero_test,exact=bool(exact),guards=guards,
                        ioctl_ns=elapsed,driver_transaction_ns=returned[40],initial_copy_ns=copy_ns))
                    save();assert exact and guards,'RAW32 output/guard mismatch'
        assert result['actual_NN_PL_RUN']==30
        result['status']='FIXTURE_MOVENET_SPLIT_PASS'
    except BaseException as error:
        result['status']='FIXTURE_MOVENET_SPLIT_FAILED';result['errors'].append(type(error).__name__+': '+str(error));result['traceback']=traceback.format_exc()
    finally:
        if pool is not None:pool.close()
        if fd is not None:os.close(fd)
        result['all_device_fds_closed']=not any(p.exists()and os.path.realpath(str(p))=='/dev/gesture-i8-pl0'for p in Path('/proc/self/fd').iterdir())
        save()
    if result['errors']or not result['all_device_fds_closed']:raise SystemExit(1)
