"""Toggle the Navigator OV5640 lamp on each debounced PL_KEY0 press.

Uses the existing gpio-keys input and bound camera I2C device. It neither
reprograms the FPGA nor reopens the video capture device.
"""
import ctypes as C
import errno
import glob
import json
import os
from pathlib import Path
import select
import signal
import struct
import threading
import time

KEY_CODE = 105
STROBE = 0x02
EVENT = struct.Struct('@llHHi')
CAMERA_FRAME = Path('/run/medcomm/camera.frame')
FRAME_HEADER = struct.Struct('<5I')
FRAME_MAGIC = 0x4d43414d
FRAME_BYTES = 64 + 800 * 480 * 3 * 3


def capture_sample(path=CAMERA_FRAME):
    """Read the current capture identity and completed sequence, without I2C."""
    try:
        with open(path, 'rb') as stream:
            info = os.fstat(stream.fileno())
            header = stream.read(FRAME_HEADER.size)
    except OSError:
        return None
    if len(header) != FRAME_HEADER.size or info.st_size < FRAME_BYTES:
        return None
    magic, sequence, width, height, stride = FRAME_HEADER.unpack(header)
    if magic != FRAME_MAGIC or not sequence or (width, height, stride) != (800, 480, 2400):
        return None
    return info.st_dev, info.st_ino, sequence


def wait_for_capture(stop, path=CAMERA_FRAME, interval=.25):
    """Require two fresh advances, so a leftover frame file is never readiness.

    Run this again after an I2C failure: the camera may be reinitializing.
    The stop event makes startup and reconnect waits interruptible by SIGTERM.
    """
    previous, advances = None, 0
    while not stop.is_set():
        sample = capture_sample(path)
        delta = ((sample[2] - previous[2]) & 0xffffffff) if sample and previous else 0
        if sample and previous and sample[:2] == previous[:2] and 0 < delta < 0x80000000:
            advances += 1
        else:
            advances = 0
        if advances >= 2:
            return not stop.is_set()
        previous = sample
        if stop.wait(interval):
            return False
    return False


class PressEdge:
    def __init__(self, pressed=False, debounce=0.15):
        self.pressed = pressed
        self.debounce = debounce
        self.last_press = float('-inf')

    def feed(self, event_type, code, value, now):
        if event_type != 1 or code != KEY_CODE:
            return False
        if value == 0:
            self.pressed = False
            return False
        if value != 1 or self.pressed:
            return False
        self.pressed = True
        if now - self.last_press < self.debounce:
            return False
        self.last_press = now
        return True


class I2CMessage(C.Structure):
    _fields_ = [('addr', C.c_ushort), ('flags', C.c_ushort),
                ('length', C.c_ushort), ('buf', C.POINTER(C.c_ubyte))]


class I2CTransfer(C.Structure):
    _fields_ = [('msgs', C.POINTER(I2CMessage)), ('count', C.c_uint)]


class CameraLamp:
    def __init__(self):
        devices = [p for p in Path('/sys/bus/i2c/drivers/ov5640').iterdir()
                   if p.is_symlink() and p.name.endswith('-003c')]
        if len(devices) != 1:
            raise RuntimeError('Expected exactly one bound OV5640 camera')
        bus = int(devices[0].name.split('-')[0])
        self.fd = os.open('/dev/i2c-%d' % bus, os.O_RDWR)
        self.libc = C.CDLL(None, use_errno=True)
        self.libc.ioctl.argtypes = [C.c_int, C.c_ulong, C.c_void_p]
        self.libc.ioctl.restype = C.c_int
        try:
            if (self.read(0x300a) << 8) | self.read(0x300b) != 0x5640:
                raise RuntimeError('Camera chip identity mismatch')
        except BaseException:
            self.close()
            raise

    def transfer(self, flags, buffer):
        msg = I2CMessage(0x3c, flags, len(buffer), buffer)
        transfer = I2CTransfer(C.pointer(msg), 1)
        result = self.libc.ioctl(self.fd, 0x0707, C.byref(transfer))
        if result != 1:
            error = C.get_errno() if result < 0 else errno.EIO
            raise OSError(error, 'Camera I2C transfer failed')

    def read(self, register):
        address = (C.c_ubyte * 2)(register >> 8, register & 255)
        data = (C.c_ubyte * 1)()
        # The vendor OV5640 uses separate SCCB address and data transactions.
        self.transfer(0, address)
        self.transfer(1, data)
        return data[0]

    def write(self, register, value):
        data = (C.c_ubyte * 3)(register >> 8, register & 255, value)
        self.transfer(0, data)
        if self.read(register) != value:
            raise RuntimeError('Camera lamp register readback mismatch')

    def set(self, enabled):
        if enabled:
            for register in (0x3016, 0x301c):
                old = self.read(register)
                if not old & STROBE:
                    self.write(register, old | STROBE)
        old = self.read(0x3019)
        new = (old | STROBE) if enabled else (old & ~STROBE)
        if new != old:
            self.write(0x3019, new)
        return bool(self.read(0x3019) & STROBE)

    def toggle(self):
        return self.set(not bool(self.read(0x3019) & STROBE))

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def key_device():
    tree = Path('/sys/firmware/devicetree/base/keys')
    verified = False
    for node in tree.iterdir():
        if not node.is_dir() or not (node / 'label').exists():
            continue
        if (node / 'label').read_bytes().rstrip(b'\0') == b'pl_key0':
            code = int.from_bytes((node / 'linux,code').read_bytes(), 'big')
            gpio = struct.unpack('>III', (node / 'gpios').read_bytes())
            verified = code == KEY_CODE and gpio[1:] == (55, 1)
    if not verified:
        raise RuntimeError('PL_KEY0 device tree does not match Navigator mapping')
    found = []
    for event in glob.glob('/sys/class/input/event*'):
        device = Path(event) / 'device'
        try:
            if ((device / 'phys').read_text().strip() == 'gpio-keys/input0'
                    and (device / 'device/of_node').resolve() == tree.resolve()):
                found.append('/dev/input/' + Path(event).name)
        except OSError:
            continue
    if len(found) != 1:
        raise RuntimeError('Expected one Navigator gpio-keys input device')
    return found[0]


def key_is_down(fd):
    import fcntl
    keys = bytearray(96)
    # EVIOCGKEY(sizeof(keys)); do not toggle a key already held at startup.
    fcntl.ioctl(fd, 0x80000000 | (len(keys) << 16) | (ord('E') << 8) | 0x18, keys, True)
    return bool(keys[KEY_CODE // 8] & (1 << (KEY_CODE % 8)))


def run():
    import fcntl
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    Path('/run/medcomm').mkdir(parents=True, exist_ok=True)
    with open('/run/medcomm/camera-light-key.lock', 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('CAMERA_LIGHT already running', flush=True)
            return
        initialized, last_error = False, None
        print('CAMERA_LIGHT_WAIT waiting for advancing camera frames', flush=True)
        while not stop.is_set():
            lamp, fd = None, None
            try:
                if not wait_for_capture(stop):
                    break
                device = key_device()
                fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
                edge = PressEdge(pressed=key_is_down(fd))
                lamp = CameraLamp()
                if not initialized:
                    lamp.set(False)
                    initialized = True
                print('CAMERA_LIGHT_READY ' + json.dumps({
                    'key': 'PL_KEY0', 'device': device, 'code': KEY_CODE,
                    'enabled': bool(lamp.read(0x3019) & STROBE)}), flush=True)
                last_error, dropped, pending = None, False, b''
                while not stop.is_set():
                    if not select.select([fd], [], [], .5)[0]:
                        continue
                    block = os.read(fd, EVENT.size * 32)
                    if not block:
                        raise OSError('Key input device closed')
                    pending += block
                    while len(pending) >= EVENT.size:
                        sec, usec, kind, code, value = EVENT.unpack(pending[:EVENT.size])
                        pending = pending[EVENT.size:]
                        if kind == 0 and code == 3:  # SYN_DROPPED
                            dropped = True
                        elif dropped:
                            if kind == 0 and code == 0:
                                edge = PressEdge(pressed=key_is_down(fd))
                                dropped = False
                        elif edge.feed(kind, code, value, time.monotonic()):
                            enabled = lamp.toggle()
                            print('CAMERA_LIGHT_TOGGLE ' + json.dumps({
                                'enabled': enabled, 'key': 'PL_KEY0'}), flush=True)
            except (OSError, RuntimeError, ValueError) as error:
                message = str(error)
                if message != last_error:
                    print('CAMERA_LIGHT_WAIT ' + message, flush=True)
                    last_error = message
            finally:
                if lamp is not None:
                    lamp.close()
                if fd is not None:
                    os.close(fd)
            stop.wait(3)


if __name__ == '__main__':
    run()
