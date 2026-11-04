"""Pinned Full Hand: three trace comparisons and three finite two-hand pairs."""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import signal
import time
import traceback
import numpy as np


def run(root, cfg):
    def stop(signum, frame): raise InterruptedError('Orderly stop after native model returns')
    signal.signal(signal.SIGTERM, stop)
    r = dict(status='FIXTURE_FULL_HAND_RUNNING', model_identity='approved_Full_Hand224',
             source_hand_sha256='74aa6f9a1d2834b20e289cb2ee5ccd92e555bb93425fa7db35d68d43875fef0a',
             boot_id=cfg['boot_id'], session_id=cfg['session_id'], source_scope='fixed_fixture',
             fixture_kind=cfg['fixture_kind'], camera_opened=False, TCN_RUN=0, model_warmup_RUN=0,
             rows=[], pairs=[], errors=[], actual_NN_PL_RUN=0, full_frame_acceptance=False)
    def save():
        p = root / 'rpc_actual.json.tmp';p.write_text(json.dumps(r, separators=(',', ':')), encoding='utf-8');p.replace(root/'rpc_actual.json')
    api = None; clock_before=None; clock_changed=False
    try:
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == cfg['boot_id']
        for name, digest in json.loads((root/'package_manifest.json').read_text()).items():
            assert hashlib.sha256((root/name).read_bytes()).hexdigest() == digest, name
        folder = root/'full_hand'; plan = json.loads((folder/'hand_plan.json').read_text())
        assert plan['source_hand_sha256'] == r['source_hand_sha256']
        load_started = time.monotonic_ns()
        with np.load(folder/'full_hand_fixture.npz', allow_pickle=False) as fixture:
            inputs = np.ascontiguousarray(fixture['inputs'])
            expected_heads = fixture['expected_heads'].copy()
        r['fixture_load_ns'] = time.monotonic_ns()-load_started
        hashes = json.loads((folder/'full_hand_layer_hashes.json').read_text())
        api = C.CDLL(str(folder/'libfull_hand_pl.so'))
        api.fh_open.argtypes = [C.c_char_p];api.fh_open.restype = C.c_int
        api.fh_close.argtypes = [];api.fh_close.restype = C.c_int
        api.fh_run.argtypes = [C.c_void_p,C.c_uint32,C.c_void_p,C.c_uint32,C.c_void_p];api.fh_run.restype = C.c_int
        api.fh_copy_tensor.argtypes = [C.c_uint32,C.c_void_p,C.c_uint32];api.fh_copy_tensor.restype = C.c_int
        api.fh_profile.argtypes = [C.c_void_p,C.c_uint32];api.fh_profile.restype = C.c_int
        api.fh_trace.argtypes=[C.c_int];api.fh_trace.restype=C.c_int
        started = time.monotonic_ns()
        code = api.fh_open(os.fsencode(str(folder/'hand_weights.bin')))
        assert code == 0, ('Full Hand open', code)
        r['startup_ns'] = time.monotonic_ns()-started
        def infer(sample, stage):
            x = inputs[sample];heads = np.empty(44, np.float32);stats = np.zeros(8, np.uint64)
            start = time.monotonic_ns()
            code = api.fh_run(x.ctypes.data,x.nbytes,heads.ctypes.data,heads.size,stats.ctypes.data)
            elapsed = time.monotonic_ns()-start
            r['actual_NN_PL_RUN'] += int(stats[0])
            row = dict(sample=sample,stage=stage,returncode=code,complete_call_ns=elapsed,
                       native=dict(zip(['PL_jobs','ioctl_ns','driver_ns','input_copy_ns','PS_ns','output_copy_ns','total_ns','failed_op_plus1'],map(int,stats))),
                       heads_max_abs_error=float(np.max(np.abs(heads-expected_heads[sample]))) if code == 0 else None)
            r['rows'].append(row)
            assert code == 0 and stats[0] == 50, ('Full Hand native failure', code, stats.tolist())
            np.testing.assert_allclose(heads,expected_heads[sample],rtol=0,atol=2e-6)
            if sample == 0 and stage.endswith('numerical_trace'):
                profile = np.empty((len(plan['ops']),2),np.uint64)
                assert api.fh_profile(profile.ctypes.data,profile.size) == 0
                r['layer_profile'] = [dict(index=i,name=o['name'],kind=o['kind'],wall_ns=int(profile[i,0]),driver_ns=int(profile[i,1])) for i,o in enumerate(plan['ops'])]
                r.setdefault('phase_profiles',{})[r['phase']]=r['layer_profile']
            return row
        clock_test=cfg['fixture_kind']=='full_hand_clock'
        pair_repeats=50 if clock_test else int(cfg.get('pair_repeats',3));assert 1<=pair_repeats<=200
        phases=['entry_100MHz','qualified_142MHz']if clock_test else ['entry']
        if clock_test:
            import window_state as state
            from pynq.ps import Clocks
            clock_before=state.clocks();clock0=clock_before['0x170']
            assert ((clock0>>8)&63)==5 and ((clock0>>20)&63)==2 and ((clock0>>4)&3)==0
            reference=int.from_bytes(Path('/proc/device-tree/amba/slcr@f8000000/clkc@100/ps-clk-frequency').read_bytes(),'big')
            assert reference==33333333 and not(clock_before['0x108']&0x13)
            pll_hz=reference*((clock_before['0x108']>>12)&127);assert 999000000<pll_hz<1001000000
            qualification=json.loads((root/'clock_qualification.json').read_text())
            assert qualification['bit_sha256']==hashlib.sha256((root/'candidate.bit').read_bytes()).hexdigest()
            assert qualification['route_setup_ns']>=0 and qualification['route_hold_ns']>=0 and qualification['pulse_width_ns']>=0
            assert pll_hz/7<=qualification['max_clock_hz']==150000000
            r['clock_experiment']=dict(before=clock_before,source_reference_hz=reference,PLL_hz=pll_hz,target_hz=pll_hz/7,qualification=qualification)
        for phase in phases:
            r['phase']=phase;prefix=phase+'_'if clock_test else ''
            if phase=='qualified_142MHz':
                assert state.core_idle();clock_changed=True;save()
                Clocks.set_pl_clk(0,div0=7,div1=1)
                actual=state.clocks();mask=(63<<8)|(63<<20)
                expected=dict(clock_before);expected['0x170']=(clock_before['0x170']&~mask)|(7<<8)|(1<<20)
                assert actual==expected;r['clock_experiment']['running']=actual;save()
            assert api.fh_trace(1)==0;r['numerical_trace_extra_copy_enabled']=True
            for sample in range(3):
                row=infer(sample,prefix+'numerical_trace');exact=0
                for index,digest in hashes[sample].items():
                    o=plan['ops'][int(index)];value=np.empty(o['n'],np.int8)
                    assert api.fh_copy_tensor(int(index),value.ctypes.data,value.nbytes)==0
                    assert hashlib.sha256(value.tobytes()).hexdigest()==digest,('INT8 layer differs',phase,sample,index)
                    exact+=1
                row['int8_layer_outputs_byte_exact']=exact;assert exact==47;save()
            assert api.fh_trace(0)==0
            for repeat in range(pair_repeats):
                start=time.monotonic_ns();left=infer(1,prefix+'two_hand_pair');right=infer(2,prefix+'two_hand_pair')
                r['pairs'].append(dict(phase=phase,repeat=repeat,complete_pair_ns=time.monotonic_ns()-start,
                    left_call_ns=left['complete_call_ns'],right_call_ns=right['complete_call_ns'],PL_jobs=100,
                    includes_native_inputs_and_heads=True,scope='Q fixed crops only; excludes capture,Palm,Body,TCN,HDMI'))
                save()
        r['status'] = 'FIXTURE_FULL_HAND_PASS'
    except BaseException as error:
        r['status'] = 'FIXTURE_FULL_HAND_FAILED'
        r['errors'].append(type(error).__name__+': '+str(error));r['traceback'] = traceback.format_exc()
    finally:
        if api is not None:
            try: api.fh_close()
            except BaseException as error: r['errors'].append('close: '+str(error))
        if clock_changed:
            try:
                assert state.core_idle(),'Core not idle; no clock writes'
                # Restore via 71 MHz, avoiding a transient 200 MHz intermediate divider.
                Clocks.set_pl_clk(0,div0=7,div1=2);Clocks.set_pl_clk(0,div0=5,div1=2)
                assert state.clocks()==clock_before;r['clock_experiment']['restored_exactly']=True
            except BaseException as error:r['errors'].append('clock_restore: '+str(error))
        r['all_device_fds_closed'] = not any(p.exists() and os.path.realpath(str(p)) == '/dev/gesture-i8-pl0' for p in Path('/proc/self/fd').iterdir())
        save()
    if r['errors'] or not r['all_device_fds_closed']: raise SystemExit(1)
