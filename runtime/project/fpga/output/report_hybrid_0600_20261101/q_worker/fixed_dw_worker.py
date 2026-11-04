"""Finite isolated-operator test. Does not run the Full body network or TCN."""
import hashlib
import json
import os
import signal
from pathlib import Path
import traceback
import numpy as np
from pl_depthwise import DepthwisePL


def run(root, cfg):
    def stop(signum, frame):
        raise InterruptedError('Orderly stop after the current driver call')
    signal.signal(signal.SIGTERM, stop)
    r = dict(status='FIXTURE_DW_RUNNING', source_scope='fixed_fixture', fixture_kind='dw_alignment',
             model_identity='TinyPose256 isolated DW alignment; not complete NN inference', rows=[], errors=[],
             boot_id=cfg['boot_id'], session_id=cfg['session_id'], TCN_RUN=0, camera_opened=False,
             actual_NN_PL_RUN=0, full_frame_acceptance=False)
    def save():
        p = root / 'rpc_actual.json.tmp'
        p.write_text(json.dumps(r, separators=(',', ':')), encoding='utf-8')
        p.replace(root / 'rpc_actual.json')
    backend = None
    try:
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == cfg['boot_id']
        for name, digest in json.loads((root / 'package_manifest.json').read_text()).items():
            assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, name
        fixture = np.load(root / 'dw20_fixture.npz', allow_pickle=False)
        backend = DepthwisePL()
        r['driver_info'] = backend.info
        for index in range(len(fixture['weights'])):
            actual, timing = backend.run(fixture['input'], fixture['weights'][index], fixture['params'][index], -17, -3)
            exact = np.array_equal(actual, fixture['expected'][index])
            r['rows'].append(dict(index=index, exact=exact, output_sha256=hashlib.sha256(actual.tobytes()).hexdigest(), **timing))
            r['actual_NN_PL_RUN'] = backend.completed
            save()
            assert exact, 'DW20 valid-channel output differs'
        r['status'] = 'FIXTURE_DW_ALIGNMENT_PASS'
    except BaseException as error:
        r['status'] = 'FIXTURE_DW_FAILED'
        r['errors'].append(type(error).__name__ + ': ' + str(error))
        r['traceback'] = traceback.format_exc()
    finally:
        if backend is not None:
            try: backend.close()
            except BaseException as error: r['errors'].append('close: ' + str(error))
        r['all_device_fds_closed'] = not any(p.exists() and os.path.realpath(str(p)) == '/dev/gesture-i8-pl0' for p in Path('/proc/self/fd').iterdir())
        save()
    if r['errors'] or not r['all_device_fds_closed']: raise SystemExit(1)
