"""Finite frozen scenes: board-only inference, layer hashes, then uncaptured timing."""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import signal
import time
import traceback
import numpy as np


def run(root,cfg):
    def stop(signum,frame):raise InterruptedError('Orderly stop after native inference')
    signal.signal(signal.SIGTERM,stop)
    kind=cfg['fixture_kind'];assert kind in('full_palm','full_palm_clock','full_palm_add_compare','full_hand_add_compare','full_palm_ps_compare','full_body_channels','full_body_cache_compare','full_body_integer_compare','full_body_halfadd_compare','full_hand_cache_compare','full_palm_cache_compare','full_palm_fused_compare','full_palm_add32_compare','full_palm_lut_compare','full_palm_burst_compare','full_hand_mul_compare','full_palm_mul_compare','full_body_mul_compare')
    base='full_body_channels'if kind.startswith('full_body')else'full_hand'if kind.startswith('full_hand')else'full_palm'
    clock_test=kind!='full_palm';models=[base,base+('_ps_vector'if kind.endswith('_ps_compare')else'_add')]if kind.endswith('_compare')else[base]
    if kind.endswith('_mul_compare'):models=[base,base+'_mul']
    if kind in('full_palm_add_compare','full_palm_mul_compare'):models.insert(1,'full_palm_ps_vector')
    if kind=='full_body_mul_compare':models=[base+'_cached',base+'_mul_cached']
    if kind.endswith('_cache_compare'):models=[base,base+'_cached']
    if kind=='full_palm_fused_compare':models=[base+'_cached',base+'_fused_cached']
    if kind=='full_palm_add32_compare':models=[base+'_fused_cached',base+'_fused_add32_cached']
    if kind=='full_palm_lut_compare':models=[base+'_fused_cached',base+'_fused_lut_cached']
    if kind=='full_palm_burst_compare':models=[base+'_fused_cached',base+'_fused_burst_cached']
    if kind=='full_body_integer_compare':models=[base+'_cached',base+'_integer_cached']
    if kind=='full_body_halfadd_compare':models=[base+'_cached',base+'_halfadd_cached']
    status='FIXTURE_'+kind.upper()
    identity='74aa6f9a1d2834b20e289cb2ee5ccd92e555bb93425fa7db35d68d43875fef0a'if base=='full_hand'else'e30e455279e9c3df084c45b332cab1cf7f053501dfec2810df639df3bef8903a'
    if base=='full_body_channels':identity='c16f7473d4f4ef6fb2dc28d17182af0a7bda69475dcd3e9d38f0ec08544ae334'
    r=dict(status=status+'_RUNNING',fixture_kind=kind,source_model_sha256=identity,
           boot_id=cfg['boot_id'],session_id=cfg['session_id'],source_scope='fixed_fixture',
           camera_opened=False,TCN_RUN=0,model_warmup_RUN=0,full_frame_acceptance=False,
           rows=[],errors=[],actual_NN_PL_RUN=0,numerical_trace_extra_copy_enabled=True)
    def save():
        p=root/'rpc_actual.json.tmp';p.write_text(json.dumps(r,separators=(',',':')),encoding='utf-8');p.replace(root/'rpc_actual.json')
    api=None;clock_changed=False;scheduling=None
    try:
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==cfg['boot_id']
        for name,digest in json.loads((root/'package_manifest.json').read_text()).items():
            assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,name
        if kind.endswith('_compare')or kind=='full_body_channels':
            scheduling=(os.sched_getaffinity(0),os.getpriority(os.PRIO_PROCESS,0))
            assert 1 in scheduling[0]
            r['scheduling']=dict(before_cpus=sorted(scheduling[0]),before_nice=scheduling[1])
            os.sched_setaffinity(0,{1});os.setpriority(os.PRIO_PROCESS,0,-10)
            r['scheduling'].update(test_cpus=sorted(os.sched_getaffinity(0)),test_nice=os.getpriority(os.PRIO_PROCESS,0))
        if clock_test:
            import qualified_clock as clock
            r['clock_experiment']=clock.prepare(root)
        for phase in (['entry_100MHz','qualified_142MHz']if clock_test else['entry']):
            if phase=='qualified_142MHz':
                clock_changed=True;save();clock.fast(r['clock_experiment']);save()
            for model in models:
                folder=root/model;plan=json.loads((folder/'hand_plan.json').read_text());assert plan.get('source_model_sha256',plan.get('source_hand_sha256'))==identity
                jobs=sum(o['kind']==1 for o in plan['ops']);assert plan.get('PL_jobs',jobs)==jobs
                r.setdefault('artifact_sha256',{})[model]={name:hashlib.sha256((folder/name).read_bytes()).hexdigest()for name in('libfull_hand_pl.so','hand_weights.bin','hand_plan.json')}
                with np.load(root/base/('full_hand_fixture.npz'if base=='full_hand'else'fixture.npz'),allow_pickle=False)as f:inputs=f['inputs'].copy();expected=f['expected_heads'].copy()
                hashes=json.loads((folder/('full_hand_layer_hashes.json'if model=='full_hand'else'layer_hashes.json')).read_text())
                api=C.CDLL(str(folder/'libfull_hand_pl.so'))
                api.fh_open.argtypes=[C.c_char_p];api.fh_open.restype=C.c_int
                api.fh_run.argtypes=[C.c_void_p,C.c_uint32,C.c_void_p,C.c_uint32,C.c_void_p];api.fh_run.restype=C.c_int
                api.fh_trace.argtypes=[C.c_int];api.fh_trace.restype=C.c_int
                api.fh_copy_tensor.argtypes=[C.c_uint32,C.c_void_p,C.c_uint32];api.fh_copy_tensor.restype=C.c_int
                api.fh_profile.argtypes=[C.c_void_p,C.c_uint32];api.fh_profile.restype=C.c_int
                api.fh_close.argtypes=[];api.fh_close.restype=C.c_int
                if model.endswith('_halfadd_cached'):
                    assert api.fh_halfadd_selftest()==0
                    r['halfadd_all_signed_pairs_clamps_checked']=262144
                if model.endswith('_add32_cached'):
                    assert api.fh_add32_selftest()==0
                    r['add32_all_signed_byte_pairs_per_Add_pass']=True
                if model.endswith('_lut_cached'):
                    assert api.fh_lut_selftest()==0
                    r['lut_all_signed_byte_pairs_per_Add_and_inplace_pass']=True
                if model.endswith('_burst_cached'):
                    assert api.fh_burst_selftest()==0
                    r['burst_all_alignments_tails_and_canaries_pass']=True
                start=time.monotonic_ns();code=api.fh_open(os.fsencode(folder/'hand_weights.bin'));assert code==0,('open',code)
                r.setdefault('startup_ns',{})[phase+'_'+model]=time.monotonic_ns()-start
                for call in range(3+(30 if clock_test and base!='full_body_channels'else 6)):
                    sample=call%3;trace=call<3;assert api.fh_trace(int(trace))==0
                    x=inputs[sample];heads=np.empty_like(expected[sample]);stats=np.zeros(8,np.uint64)
                    start=time.monotonic_ns();code=api.fh_run(x.ctypes.data,x.nbytes,heads.ctypes.data,heads.size,stats.ctypes.data);elapsed=time.monotonic_ns()-start
                    r['actual_NN_PL_RUN']+=int(stats[0]);row=dict(model=model,phase=phase,sample=sample,stage='numerical_trace' if trace else 'timing',returncode=code,complete_call_ns=elapsed,
                        native=dict(zip(['PL_jobs','ioctl_ns','driver_ns','input_copy_ns','PS_ns','output_copy_ns','total_ns','failed_op_plus1'],map(int,stats))))
                    r['rows'].append(row);save();assert code==0 and stats[0]==jobs,('native',code,stats.tolist())
                    row['heads_max_abs_error']=float(abs(heads-expected[sample]).max());np.testing.assert_allclose(heads,expected[sample],rtol=0,atol=2e-6 if base=='full_hand'else 2e-5)
                    if trace:
                        count8=count32=0
                        for index,digest in hashes[sample].items():
                            op=plan['ops'][int(index)];is_int8=bool(op['cfg'][3]);value=np.empty(op['n'],np.int8 if is_int8 else np.int32)
                            assert api.fh_copy_tensor(int(index),value.ctypes.data,value.nbytes)==0
                            assert hashlib.sha256(value.tobytes()).hexdigest()==digest,('integer layer',sample,index)
                            count8+=is_int8;count32+=not is_int8
                        row.update(int8_layer_outputs_byte_exact=count8,raw32_layer_outputs_byte_exact=count32,integer_layer_outputs_byte_exact=len(hashes[sample]))
                    if call>=3:
                        profile=np.empty((len(plan['ops']),2),np.uint64);assert api.fh_profile(profile.ctypes.data,profile.size)==0
                        by_kind={}
                        for i,o in enumerate(plan['ops']):
                            key=('PL_mode_'+str(o['cfg'][3]))if o['kind']==1 else('PS_kind_'+str(o['kind']));entry=by_kind.setdefault(key,dict(wall_ns=0,driver_ns=0));entry['wall_ns']+=int(profile[i,0]);entry['driver_ns']+=int(profile[i,1])
                        row['operator_kind_ns']=by_kind
                        if call==3:r.setdefault('phase_profiles',{})[phase+'_'+model]=[dict(index=i,name=o['name'],kind=o['kind'],wall_ns=int(profile[i,0]),driver_ns=int(profile[i,1]))for i,o in enumerate(plan['ops'])]
                    save()
                assert api.fh_close()==0;api=None
        r['status']=status+'_PASS'
    except BaseException as e:r.update(status=status+'_FAILED',traceback=traceback.format_exc());r['errors'].append(type(e).__name__+': '+str(e))
    finally:
        if api is not None:api.fh_close()
        if clock_changed:
            try:clock.restore(r['clock_experiment'])
            except BaseException as e:r['errors'].append('clock_restore: '+str(e))
        if scheduling is not None:
            try:
                os.sched_setaffinity(0,scheduling[0]);os.setpriority(os.PRIO_PROCESS,0,scheduling[1])
                r['scheduling']['restored']=os.sched_getaffinity(0)==scheduling[0]and os.getpriority(os.PRIO_PROCESS,0)==scheduling[1]
                assert r['scheduling']['restored']
            except BaseException as e:r['errors'].append('scheduling_restore: '+str(e))
        r['all_device_fds_closed']=not any(p.exists()and os.path.realpath(str(p))=='/dev/gesture-i8-pl0'for p in Path('/proc/self/fd').iterdir());save()
    if r['errors']or not r['all_device_fds_closed']:raise SystemExit(1)
