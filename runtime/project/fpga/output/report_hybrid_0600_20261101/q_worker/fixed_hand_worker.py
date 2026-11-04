"""Finite, exact-golden Hand test using the existing Q lifecycle and owner."""
import ctypes as C
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time
import traceback
import numpy as np


def run(root, cfg):
    result = dict(status="FIXTURE_RUNNING", source_scope="fixed_fixture", rows=[], errors=[],
                  session_id=cfg['session_id'], boot_id=cfg['boot_id'], camera_opened=False,
                  TCN_RUN=0, model_warmup_RUN=0, model_identity="reference_official_Lite_INT8_not_Full",
                  actual_NN_PL_RUN=0, full_frame_acceptance=False)
    def save():
        path = root / 'rpc_actual.json.tmp'
        path.write_text(json.dumps(result, separators=(',', ':')), encoding='utf-8')
        path.replace(root / 'rpc_actual.json')
    def device_fds():
        return [p.name for p in Path('/proc/self/fd').iterdir()
                if p.exists() and os.path.realpath(str(p)) == '/dev/gesture-i8-pl0']
    backend = None
    try:
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == cfg['boot_id']
        for name, digest in json.loads((root / 'package_manifest.json').read_text()).items():
            assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, name
        spec = importlib.util.spec_from_file_location('fixture_backend', root / 'lite/lite_int8_backend.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        start = time.monotonic_ns()
        backend = module.LiteInt8Backend(root / 'lite', 'hardware', 1)
        backend.load('hand')
        result['startup_ns'] = time.monotonic_ns() - start
        def stats():
            values = (C.c_uint64 * 7)()
            assert backend.api.gpo_owner_stats(backend.owner, 4, values) == 0
            return list(values)
        owner = device_fds()
        assert len(owner) == 1 and stats()[0] == 0
        with np.load(root / 'fixed_fixture.npz', allow_pickle=False) as fixture:
            for repeat in range(3):
                for hand in (1, 2):
                    value = fixture['Hand%d_input' % hand]
                    before = stats()
                    started = time.monotonic_ns()
                    heads = backend.infer_int8('hand', value)
                    ended = time.monotonic_ns()
                    after = stats()
                    exact = [np.array_equal(head, fixture['Hand%d_head%d' % (hand, i)]) for i, head in enumerate(heads)]
                    row = dict(repeat=repeat, hand=hand, infer_start_ns=started, infer_end_ns=ended,
                               complete_ns=ended-started, heads_exact=exact,
                               input_sha256=hashlib.sha256(value.tobytes()).hexdigest(),
                               heads_sha256=[hashlib.sha256(h.tobytes()).hexdigest() for h in heads],
                               stats_before=before, stats_after=after,
                               native={k:v for k,v in backend.trace[-1].items() if not k.startswith('_')})
                    result['rows'].append(row)
                    result['actual_NN_PL_RUN'] = after[0]
                    save()
                    assert len(heads) == 4 and all(exact), 'Hand heads differ from frozen fixture'
                    assert after[0]-before[0] == 51 and after[4]-before[4] == 1 and not after[5] and not after[6]
                    assert device_fds() == owner
                    backend.trace.clear()
        result['status'] = 'FIXTURE_HAND_EXACT_PASS'
    except BaseException as error:
        result['status'] = 'FIXTURE_FAILED'
        result['errors'].append(type(error).__name__ + ': ' + str(error))
        result['traceback'] = traceback.format_exc()
    finally:
        if backend is not None:
            try: backend.close()
            except BaseException as error: result['errors'].append('close: ' + str(error))
        result['all_device_fds_closed'] = not device_fds()
        save()
    if result['errors'] or not result['all_device_fds_closed']:
        raise SystemExit(1)
