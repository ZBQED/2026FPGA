"""Bounded per-boot readiness for the tested Navigator v3 configuration.

No camera restart, GPIO, FPGA or boot writes. A stalled camera is reported and
left alone. Only the previously tested empty-FIFO IIC condition permits one
adapter-locked recovery. Default invocation is read-only status.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import time

HERE = Path('/opt/gesture-tcn-20261022/deployment/nav_persistent_v3')
ROOT = Path('/opt/gesture-tcn-20261022')
STATE = Path('/run/gesture-nav-ready')
LIGHT = Path('/opt/medcomm/qt_dual_display/camera_light_key.py')
LIGHT_PID = Path('/run/medcomm/camera_light_key.pid')
LIGHT_LOG = Path('/var/log/medcomm-camera_light_key.log')
MODULE = ROOT / 'deployment/camera_recovery_20261023/camera_xiic_recover.ko'
DRIVER = ROOT / 'pl_runtime/gesture_pl_driver.ko'
LIGHT_SHA = '0e6cc3f2845d15809ba766fe85c585904112cb6e98145f61a449a4bafac98f86'
MODULE_SHA = 'ebcc06f52d23a399ff45dc69f2b7d87320a0c241cc3b71a3bd83eb8212e64c58'
DRIVER_SHA = 'dc4ef9bfb68d80495129b703d072b56bc642042c9e22de86c0093a84c2ae70ac'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cmd(args, timeout=12):
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       timeout=timeout, universal_newlines=True)
    if p.returncode:
        raise RuntimeError('%s: %s' % (args[0], p.stderr or p.stdout))
    return p.stdout


def frame():
    try:
        p = Path('/run/medcomm/camera.frame')
        with p.open('rb') as f:
            h = struct.unpack('<5I', f.read(20))
            st = os.fstat(f.fileno())
        if h[0] != 0x4d43414d or h[2:] != (800, 480, 2400) or not h[1]:
            return None
        return st.st_dev, st.st_ino, h[1]
    except (OSError, struct.error):
        return None


def advanced(a, b):
    return bool(a and b and a[:2] == b[:2] and 0 < ((b[2]-a[2]) & 0xffffffff) < 0x80000000)


def wait_video(seconds):
    end = time.monotonic() + seconds
    old, advances = frame(), 0
    while time.monotonic() < end:
        time.sleep(.5)
        new = frame()
        advances = advances+1 if advanced(old, new) else 0
        if advances >= 3:
            return new
        old = new
    raise RuntimeError('Camera not advancing; no automatic sensor reset or capture restart')


def pids():
    found = []
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():
            continue
        try:
            if str(LIGHT).encode() in p.joinpath('cmdline').read_bytes().split(b'\0'):
                found.append(int(p.name))
        except OSError:
            pass
    return found


def no_i2c_users():
    users = []
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():
            continue
        try:
            for fd in p.joinpath('fd').iterdir():
                try:
                    if os.readlink(str(fd)) == '/dev/i2c-0':
                        users.append(int(p.name))
                except OSError:
                    pass
        except OSError:
            pass
    if users:
        raise RuntimeError('Another I2C user exists: %s' % users)


def registers():
    return {hex(a): int(cmd(['/sbin/devmem', hex(a), '32']).strip(), 16)
            for a in (0x4160001c, 0x41600020, 0x41600028, 0x41600100, 0x41600104)}


def identity():
    cnn = Path('/proc/device-tree/amba_pl/keypoint-conv@80000000')
    return ('cma=128M' in Path('/proc/cmdline').read_text() and cnn.is_dir()
            and cnn.joinpath('compatible').read_bytes() == b'gesture,keypoint-conv-f32-v1\0'
            and cnn.joinpath('reg').read_bytes() == bytes.fromhex('8000000000010000'))


def probe():
    # Separate child gives combined I2C ID reads a parent-side timeout.
    spec = importlib.util.spec_from_file_location('verified_lamp', str(LIGHT))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    lamp = m.CameraLamp()
    try:
        print(json.dumps({'chip_id': 0x5640, 'validated_by': 'frozen ctor',
                          'frozen_ctor_source_sha256': LIGHT_SHA}))
    finally:
        lamp.close()


def start_or_adopt_light():
    found = pids()
    if len(found) > 1:
        raise RuntimeError('Duplicate lamp processes')
    if found:
        pid = found[0]
    else:
        with LIGHT_LOG.open('ab') as f:
            p = subprocess.Popen(['/usr/bin/python3', '-B', str(LIGHT)],
                                 stdin=subprocess.DEVNULL, stdout=f, stderr=f,
                                 start_new_session=True)
        pid = p.pid
    LIGHT_PID.write_text(str(pid)+'\n')
    return pid


def execute():
    if os.geteuid() != 0:
        raise RuntimeError('Root required')
    # On the original boot do not touch IIC or create any ready marker.
    if not identity():
        print('SKIPPED_ORIGINAL_BOOT')
        return
    STATE.mkdir(exist_ok=True)
    lock = (STATE/'lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('ALREADY_RUNNING')
        return
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    attempted = STATE/'attempted.json'
    if attempted.exists():
        print('ALREADY_ATTEMPTED_THIS_BOOT')
        return
    with attempted.open('x') as f:
        json.dump({'boot_id': boot, 'time': time.time()}, f)
    report = {'boot_id': boot, 'status': 'IN_PROGRESS', 'reset_attempted': False}
    loaded = stopped = False
    try:
        for path, digest in ((LIGHT, LIGHT_SHA), (MODULE, MODULE_SHA), (DRIVER, DRIVER_SHA)):
            if sha(path) != digest:
                raise RuntimeError('Frozen artifact mismatch: '+str(path))
        if 'camera_xiic_recover ' in Path('/proc/modules').read_text():
            raise RuntimeError('Recovery helper already loaded')
        report['frame_start'] = wait_video(45)
        report['before'] = registers()
        if report['before']['0x41600104'] & 4:
            for _ in range(3):
                state = registers()
                if state['0x41600104'] != 0xc4 or state['0x41600100'] != 9:
                    raise RuntimeError('Unproven busy state; refusing reset')
                time.sleep(1)
            found = pids()
            if len(found) > 1:
                raise RuntimeError('Duplicate light processes; no reset')
            if found:
                os.kill(found[0], signal.SIGTERM)
                deadline = time.monotonic()+8
                while found[0] in pids() and time.monotonic() < deadline:
                    time.sleep(.1)
                if found[0] in pids():
                    raise RuntimeError('Light did not stop; no forced kill')
                stopped = True
            no_i2c_users()
            wait_video(3)
            # Ordinary loader checks vermagic and symbol CRCs. No force option.
            cmd(['/sbin/insmod', str(MODULE), 'recover=0'])
            loaded = True
            cmd(['/sbin/rmmod', 'camera_xiic_recover'])
            loaded = False
            report['reset_attempted'] = True
            cmd(['/sbin/insmod', str(MODULE), 'recover=1'])
            loaded = True
            cmd(['/sbin/rmmod', 'camera_xiic_recover'])
            loaded = False
            report['after_reset'] = registers()
            if report['after_reset']['0x41600104'] & 4:
                raise RuntimeError('BUS_BUSY persists; no repeated reset')
        report['sensor'] = json.loads(cmd(['/usr/bin/python3', '-B', str(__file__), '--probe'], 10))
        report['light_pid'] = start_or_adopt_light()
        stopped = False
        report['frame_final'] = wait_video(5)
        if registers()['0x41600104'] & 4:
            raise RuntimeError('Bus became busy again')
        if not Path('/sys/module/gesture_pl_driver').exists():
            cmd(['/sbin/insmod', str(DRIVER)])
        deadline = time.monotonic()+5
        while not Path('/dev/gesture-pl0').exists() and time.monotonic() < deadline:
            time.sleep(.1)
        if not Path('/dev/gesture-pl0').is_char_device():
            raise RuntimeError('CNN device missing')
        report['status'] = 'READY'
        report['cnn_node'] = '/dev/gesture-pl0'
        report['note'] = 'Readiness only; does not run model inference or prove IIC root cause'
    except Exception as e:
        report['status'] = 'DEGRADED'
        report['error'] = str(e)
    finally:
        if loaded:
            try:
                cmd(['/sbin/rmmod', 'camera_xiic_recover'])
            except Exception as e:
                report['cleanup_error'] = str(e)
        if stopped:
            try:
                report['restored_light_pid'] = start_or_adopt_light()
            except Exception as e:
                report['light_restore_error'] = str(e)
        report['finished_at'] = time.time()
        (STATE/'result.json').write_text(json.dumps(report, indent=2)+'\n')
        if report['status'] == 'READY':
            (STATE/'ready').write_text(boot+'\n')
        print(json.dumps(report), flush=True)
    if report['status'] != 'READY':
        raise SystemExit(1)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group()
    g.add_argument('--run', action='store_true')
    g.add_argument('--probe', action='store_true')
    args = p.parse_args()
    if args.run:
        execute()
    elif args.probe:
        if sha(LIGHT) != LIGHT_SHA:
            raise RuntimeError('Unverified light script')
        probe()
    else:
        path = STATE/'result.json'
        print(path.read_text() if path.exists() else 'NOT_RUN')
