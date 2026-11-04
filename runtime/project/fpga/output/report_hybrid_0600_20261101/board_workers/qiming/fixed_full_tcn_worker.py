"""Full Hand and latest TCN share one device lease; all inputs are frozen fixtures."""
import ctypes as C
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import time
import traceback
import numpy as np
from full_hand_runtime import FullHand


def device_fds():
    return [int(p.name) for p in Path('/proc/self/fd').iterdir() if os.path.realpath(str(p))=='/dev/gesture-i8-pl0']


def run(root,cfg):
    def stop(signum,frame):raise InterruptedError('Orderly stop after completed native call')
    signal.signal(signal.SIGTERM,stop)
    r=dict(status='FIXTURE_FULL_TCN_RUNNING',boot_id=cfg['boot_id'],session_id=cfg['session_id'],
           fixture_kind='full_hand_tcn',source_scope='fixed_fixture',camera_opened=False,
           Hand_RUN=0,TCN_RUN=0,live_TCN_RUN=0,actual_NN_PL_RUN=0,rows=[],errors=[],
           scope='Shared owner and numeric component verification; no new landmarks enter TCN; not full-frame latency')
    def save():
        p=root/'rpc_actual.json.tmp';p.write_text(json.dumps(r,separators=(',',':')));p.replace(root/'rpc_actual.json')
    api=owner=tcn=hand=memory=None
    try:
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==cfg['boot_id']
        for name,digest in json.loads((root/'package_manifest.json').read_text()).items():
            assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,name
        assert not device_fds()
        folder=root/'tcn508a';full=root/'full_hand'
        dependency=C.CDLL(str(folder/'runtime/libgesture_tflite_pl_pointwise.so'))
        api=C.CDLL(str(folder/'runtime/libgesture_lite_i8_v12.so'))
        api.gpo_owner_open.argtypes=[];api.gpo_owner_open.restype=C.c_void_p
        api.gpo_owner_close.argtypes=[C.c_void_p];api.gpo_owner_close.restype=C.c_int
        owner=api.gpo_owner_open();assert owner
        fds=device_fds();assert len(fds)==1;fd=fds[0]
        spec=importlib.util.spec_from_file_location('joint_shared_tcn',folder/'shared_tcn/shared_tcn.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        tcn=module.SharedTCN(api,owner,folder/'shared_tcn/assets')
        inputs={}
        with np.load(folder/'seven_words.npz',allow_pickle=False) as f:
            for name,width,key in [('primary',96,'primary_input'),('roof',112,'specialist_input')]:
                x=f[key][0];inputs[name]=(np.ascontiguousarray(np.clip(np.rint(x[:width].T*1024),-32768,32767),np.int16),
                                        np.ascontiguousarray(x[width:].T,np.uint8))
        def infer_tcn(name):
            value=tcn.infer(name,*inputs[name]);r['TCN_RUN']+=1;r['actual_NN_PL_RUN']+=value['actual_PL_RUNs']
            assert value['class_index']==10
            return value
        baseline={name:infer_tcn(name) for name in ('primary','roof')}
        bounds=json.loads((root/'tcn_mac/pool_bounds.json').read_text())
        assert bounds['tcn_end_exclusive']<bounds['full_hand_start']==7<<20
        assert hashlib.sha256((folder/'runtime/libgesture_lite_i8_v12.so').read_bytes()).hexdigest()==bounds['native_sha256']
        hand=FullHand(full,parent_fd=fd);assert device_fds()==[fd]
        hand.trace(True);r['numerical_trace_extra_copy_enabled']=True
        libc=C.CDLL(None)
        libc.mmap.argtypes=[C.c_void_p,C.c_size_t,C.c_int,C.c_int,C.c_int,C.c_long];libc.mmap.restype=C.c_void_p
        libc.munmap.argtypes=[C.c_void_p,C.c_size_t];libc.munmap.restype=C.c_int
        memory=libc.mmap(None,16<<20,1,1,fd,0)
        assert memory and memory!=C.c_void_p(-1).value
        def region_hash(offset,size):return hashlib.sha256(C.string_at(memory+offset,size)).hexdigest()
        with np.load(full/'full_hand_fixture.npz',allow_pickle=False) as f:
            hand_inputs=f['inputs'].copy();expected=f['expected_heads'].copy()
        hashes=json.loads((full/'full_hand_layer_hashes.json').read_text())
        plan=json.loads((full/'hand_plan.json').read_text())
        split=7<<20
        for sample in range(3):
            prefix=region_hash(0,split)
            heads,row=hand.infer(hand_inputs[sample]);r['Hand_RUN']+=1;r['actual_NN_PL_RUN']+=row['PL_jobs']
            np.testing.assert_allclose(heads,expected[sample],rtol=0,atol=2e-6)
            assert region_hash(0,split)==prefix,'Hand modified TCN arena'
            for index,digest in hashes[sample].items():
                value=hand.tensor(int(index),plan['ops'][int(index)]['n'])
                assert hashlib.sha256(value.tobytes()).hexdigest()==digest,(sample,index)
            assert len(hashes[sample])==47
            suffix=region_hash(split,(16<<20)-split);start=time.monotonic_ns()
            words={name:infer_tcn(name) for name in ('primary','roof')}
            pair=time.monotonic_ns()-start
            for name,value in words.items():
                assert all(value[k]==baseline[name][k] for k in ('class_index','logits_int16','probabilities_Q15'))
            assert region_hash(split,(16<<20)-split)==suffix,'TCN modified Full Hand arena'
            assert device_fds()==[fd]
            row.update(sample=sample,int8_layers_exact=47,TCN_pair_ns=pair,
                       opposite_arenas_unchanged=True,single_device_fd=True)
            r['rows'].append(row);save()
        assert libc.munmap(memory,16<<20)==0;memory=None;hand.close();hand=None
        assert device_fds()==[fd],'Borrowed Hand close changed parent FD'
        r['borrowed_close_preserved_parent_fd']=True;r['status']='FIXTURE_FULL_TCN_PASS'
    except BaseException as e:
        r['status']='FIXTURE_FULL_TCN_FAILED';r['errors'].append(type(e).__name__+': '+str(e));r['traceback']=traceback.format_exc()
    finally:
        if memory is not None and memory!=C.c_void_p(-1).value:libc.munmap(memory,16<<20)
        if hand is not None:hand.close()
        if tcn is not None:tcn.close()
        if owner and api.gpo_owner_close(owner):r['errors'].append('Owner close failed')
        r['all_device_fds_closed']=not device_fds();save()
    if r['errors'] or not r['all_device_fds_closed']:raise SystemExit(1)
