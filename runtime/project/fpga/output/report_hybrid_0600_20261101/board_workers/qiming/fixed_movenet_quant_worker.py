"""Frozen PL convolution plus native ARM requantization against official outputs."""
import ctypes
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


def run(root,cfg):
    def stop(*unused):raise InterruptedError('Stop after current driver call')
    signal.signal(signal.SIGTERM,stop)
    result=dict(status='FIXTURE_MOVENET_QUANT_RUNNING',source_scope='fixed_fixture',fixture_kind='movenet_quant',
                model_identity='MoveNet 73 source convolutions in 75 isolated calls; Conv RAW plus ARM single rounding; not complete inference',
                boot_id=cfg['boot_id'],session_id=cfg['session_id'],rows=[],errors=[],TCN_RUN=0,
                camera_opened=False,actual_NN_PL_RUN=0,full_frame_acceptance=False)
    def save():
        p=root/'rpc_actual.json.tmp';p.write_text(json.dumps(result,separators=(',',':')));p.replace(root/'rpc_actual.json')
    fd=pool=None
    try:
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==cfg['boot_id']
        for name,digest in json.loads((root/'package_manifest.json').read_text()).items():
            assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,name
        manifest=json.loads((root/'movenet_conv.json').read_text())
        assert manifest['model_sha256']=='cd7cc22fa946e5d146a7b98d496853e1923e22828d3972d579973f27f91bb105'
        assert hashlib.sha256((root/'movenet_conv.npz').read_bytes()).hexdigest()==manifest['fixture_sha256']
        assert len(manifest['cases'])==75
        native=ctypes.CDLL(str(root/'libmovenet_requant.so'))
        native.mn_requant.argtypes=[ctypes.c_void_p]*3+[ctypes.c_int]*6
        native.mn_requant.restype=ctypes.c_int
        result['requant_library_sha256']=hashlib.sha256((root/'libmovenet_requant.so').read_bytes()).hexdigest()
        fd=os.open('/dev/gesture-i8-pl0',os.O_RDWR|os.O_CLOEXEC)
        info=bytearray(48);fcntl.ioctl(fd,0x80304982,info,True);info=list(struct.unpack('<12I',info))
        assert info[:4]==[0x3849504b,3,16*1024*1024,32]and info[8]==15
        result['driver_info']=info
        pool=mmap.mmap(fd,info[2],flags=mmap.MAP_SHARED,prot=mmap.PROT_READ|mmap.PROT_WRITE)
        job_struct=struct.Struct('<40IQ');guard=b'\xa5'*64
        with np.load(root/'movenet_conv.npz',allow_pickle=False)as fixture:
            for row in manifest['cases']:
                k=row['case'];x=fixture['x'+str(k)];weight=fixture['w'+str(k)];params=fixture['p'+str(k)];expected=fixture['y'+str(k)]
                assert x.dtype==weight.dtype==expected.dtype==np.int8 and params.dtype==np.int32
                assert hashlib.sha256(expected.tobytes()).hexdigest()==row['expected_sha256']
                config=list(row['config']);single=config[2]==0;raw=single or not config[3]
                if raw:
                    config[3]=0;config[17:20]=[0,0,0];config[22]=(expected.size*4+7)//8;config[23]=0
                assert len(config)==32 and config[:2]==[0x3849504b,2]and config[3]in(0,1)
                assert list(expected.shape)==config[7:10]
                offsets=[64,2<<20,0 if raw else 4<<20,6<<20]
                sizes=[config[20]*8,config[21]*8,0 if raw else params.nbytes,config[22]*8]
                for off,size in zip(offsets,sizes):
                    if size:
                        assert size<(2<<20)-128 or off==6<<20
                        assert off+size+64<info[2]
                        pool[off-64:off]=guard;pool[off+size:off+size+64]=guard
                started=time.monotonic_ns()
                for off,array in [(offsets[0],x),(offsets[1],weight)]+([]if raw else[(offsets[2],params)]):
                    pool[off:off+array.nbytes]=array.tobytes()
                initial_copy_ns=time.monotonic_ns()-started
                job=bytearray(job_struct.pack(*[v&0xffffffff for v in offsets+config+[10000,0,0,0]],0))
                started=time.monotonic_ns();fcntl.ioctl(fd,0xc0a84981 if raw else 0xc0a84983,job,True);ioctl_ns=time.monotonic_ns()-started
                returned=job_struct.unpack(job);assert returned[37]==0;result['actual_NN_PL_RUN']+=1
                started=time.monotonic_ns();actual=np.frombuffer(pool[offsets[3]:offsets[3]+expected.size*(4 if raw else 1)],dtype='<i4'if raw else np.int8).reshape(expected.shape)
                output_copy_ns=time.monotonic_ns()-started
                started=time.monotonic_ns()
                if raw:
                    quantized=np.empty(expected.shape,dtype=np.int8)
                    rc=native.mn_requant(actual.ctypes.data,params.ctypes.data,quantized.ctypes.data,
                        expected.shape[0]*expected.shape[1],expected.shape[2],row['output_zero'],
                        row['activation_min'],row['activation_max'],int(single))
                    assert rc==0,'Native requantization rejected input: '+str(rc)
                    actual=quantized
                ps_requant_ns=time.monotonic_ns()-started
                delta=actual.astype(np.int16)-expected.astype(np.int16);mismatches=int(np.count_nonzero(delta))
                guards=all(pool[off-64:off]==guard and pool[off+size:off+size+64]==guard for off,size in zip(offsets,sizes)if size)
                result['rows'].append(dict(case=k,source_operator=row['source_operator'],raw_ps=raw,exact=mismatches==0,
                    requant_backend='NEON_SINGLE'if single else'NEON_DOUBLE'if raw else'PL_DOUBLE',
                    mismatches=mismatches,elements=expected.size,max_abs_error=int(np.max(np.abs(delta))),guards=guards,
                    ioctl_ns=ioctl_ns,driver_transaction_ns=returned[40],initial_copy_ns=initial_copy_ns,
                    output_copy_ns=output_copy_ns,ps_requant_ns=ps_requant_ns))
                save();assert guards,'DMA guard mismatch'
        assert result['actual_NN_PL_RUN']==75
        assert all(r['exact']for r in result['rows']),'Official INT8 layer output differs; per-layer evidence retained'
        result['status']='FIXTURE_MOVENET_QUANT_PASS'
    except BaseException as error:
        result['status']='FIXTURE_MOVENET_QUANT_FAILED';result['errors'].append(type(error).__name__+': '+str(error));result['traceback']=traceback.format_exc()
    finally:
        if pool is not None:pool.close()
        if fd is not None:os.close(fd)
        result['all_device_fds_closed']=not any(p.exists()and os.path.realpath(str(p))=='/dev/gesture-i8-pl0'for p in Path('/proc/self/fd').iterdir())
        save()
    if result['errors']or not result['all_device_fds_closed']:raise SystemExit(1)
