"""Persistent HDMI software brightness, independent of camera I2C control."""
import glob
import json
import os
from pathlib import Path
import select
import struct
import time

STATE = Path('/opt/medcomm/display_brightness.json')
EVENT = struct.Struct('@llHHi')
KEYS = {106: 10, 103: -10}  # Verified DT: PL_KEY1 / PS_KEY1


def read_level(path=STATE):
    try:
        value = json.loads(path.read_text())['percent']
        if type(value) is int and 20 <= value <= 100:
            return value
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return 100


def save_level(value, path=STATE):
    value = max(20, min(100, int(value)))
    temporary = path.with_name(path.name + '.new')
    with open(temporary, 'w') as stream:
        json.dump({'percent': value, 'mode': 'software'}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(temporary), str(path))
    directory = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def key_device():
    # Do not bind a keyboard just because it has the same arrow key codes.
    labels = {}
    for path in Path('/sys/firmware/devicetree/base/keys').glob('*/label'):
        name = path.read_bytes().rstrip(b'\0').decode()
        labels[name] = struct.unpack('>I', (path.parent / 'linux,code').read_bytes())[0]
    if labels.get('pl_key1') != 106 or labels.get('ps_key1') != 103:
        raise RuntimeError('Brightness key device-tree mapping differs')
    for event in glob.glob('/sys/class/input/event*'):
        path = Path(event)
        if (path / 'device/name').read_text().strip() == 'keys':
            return '/dev/input/' + path.name
    raise RuntimeError('gpio-keys device unavailable')


class BrightnessKeys:
    def __init__(self, percent=100):
        self.percent = percent
        self.down = set()
        self.last = {}
        self.dropped = False

    def feed(self, kind, code, value, now):
        if kind == 0 and code == 3:
            self.dropped = True
        if self.dropped:
            if kind == 0 and code == 0:
                # Require a release before accepting any post-overrun key press.
                self.down = set(KEYS)
                self.dropped = False
            return None
        if kind != 1 or code not in KEYS:
            return None
        if value == 0:
            self.down.discard(code)
            return None
        if value != 1 or code in self.down:
            return None
        self.down.add(code)
        if now - self.last.get(code, float('-inf')) < .15:
            return None
        self.last[code] = now
        updated = max(20, min(100, self.percent + KEYS[code]))
        if updated == self.percent:
            return None
        self.percent = updated
        return updated


def run_keys(stop):
    while not stop.is_set():
        fd = None
        try:
            fd = os.open(key_device(), os.O_RDONLY | os.O_NONBLOCK)
            keys = BrightnessKeys(read_level())
            print('HDMI_BRIGHTNESS_READY software percent=%d PL_KEY1=up PS_KEY1=down' % keys.percent, flush=True)
            pending = b''
            while not stop.is_set():
                if not select.select([fd], [], [], .25)[0]:
                    continue
                block = os.read(fd, EVENT.size * 32)
                if not block:
                    raise OSError('Brightness input disconnected')
                pending += block
                while len(pending) >= EVENT.size:
                    _, _, kind, code, value = EVENT.unpack(pending[:EVENT.size])
                    pending = pending[EVENT.size:]
                    level = keys.feed(kind, code, value, time.monotonic())
                    if level is not None:
                        save_level(level)
                        print('HDMI_BRIGHTNESS percent=%d' % level, flush=True)
        except (OSError, RuntimeError, ValueError) as error:
            print('HDMI_BRIGHTNESS_WAIT ' + str(error), flush=True)
        finally:
            if fd is not None:
                os.close(fd)
        stop.wait(3)


def ensure_display(profile=None):
    """Restore the selected screen's HPD workaround, using its native EDID mode."""
    path = profile or Path(__file__).with_name('display_profile.json')
    try:
        config = json.loads(path.read_text())
        if config.get('force_connected') is not True:
            return
        if (config.get('usb_vendor'), config.get('usb_product')) != ('1a86', 'e5e3'):
            return
        present = False
        for device in Path('/sys/bus/usb/devices').glob('*'):
            try:
                if ((device / 'idVendor').read_text().strip() == '1a86' and
                        (device / 'idProduct').read_text().strip() == 'e5e3'):
                    present = True
                    break
            except OSError:
                continue
        status = Path('/sys/class/drm/card1-HDMI-A-1/status')
        # The selected screen also needs video when its touch USB is unplugged.
        if (present or config.get('allow_missing_touch') is True) and status.read_text().strip() == 'disconnected':
            status.write_text('on\n')
            print('HDMI_PROFILE forced connector; preferred EDID mode', flush=True)
    except (OSError, ValueError, TypeError):
        return
