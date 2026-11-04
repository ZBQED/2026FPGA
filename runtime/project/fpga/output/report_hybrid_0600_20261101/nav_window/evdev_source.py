"""Read only the verified iSolution USB Mouse interface; no grab or input injection."""
try:
    import fcntl
except ImportError:  # Pure parser tests also run on the Windows development host.
    fcntl = None
import os
from pathlib import Path
import select
import stat
import struct
import time

EVENT = struct.Struct('llHHi')
EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
SYN_REPORT, SYN_DROPPED = 0, 3
ABS_X, ABS_Y, BTN_CONTACT = 0, 1, 272


class InputRejected(RuntimeError):
    pass


def bitmap(text, code, word_bits=None):
    word_bits = word_bits or struct.calcsize('P')*8
    words = [int(x, 16) for x in reversed(text.split())]
    index, shift = divmod(code, word_bits)
    return index < len(words) and bool(words[index] & (1 << shift))


def discover(root='/sys/class/input'):
    matches = []
    for node in Path(root).glob('event*'):
        dev = node/'device'
        try:
            if ('usb' not in str(node.resolve()) or
                    (dev/'id/vendor').read_text().strip().lower() != '13ff' or
                    (dev/'id/product').read_text().strip().lower() != '0008' or
                    (dev/'id/bustype').read_text().strip() != '0003' or
                    (dev/'name').read_text().strip() != 'iSolution X75W03+069 Mouse'):
                continue
            if not all(bitmap((dev/'capabilities/abs').read_text(), c) for c in (ABS_X, ABS_Y)):
                continue
            if not bitmap((dev/'capabilities/key').read_text(), BTN_CONTACT):
                continue
            matches.append('/dev/input/'+node.name)
        except (OSError, ValueError):
            continue
    if len(matches) > 1:
        raise InputRejected('More than one verified touchscreen; refusing ambiguous input')
    return matches[0] if matches else None


class PacketParser:
    """Every report comes from a real SYN_REPORT, including initial all-up."""
    def __init__(self, ranges, x, y, down):
        self.ranges = dict(ranges)
        self.x, self.y, self.down = int(x), int(y), bool(down)
        self.dropped = False
        self.changed = False

    def feed(self, kind, code, value, event_ns):
        if kind == EV_SYN and code == SYN_DROPPED:
            self.dropped = True
            self.changed = False
            return {'type': 'cancel', 'reason': 'syn_dropped'}
        if self.dropped:
            if kind == EV_SYN and code == SYN_REPORT:
                raise InputRejected('SYN_DROPPED: reopen and resynchronize from kernel')
            return None
        if kind == EV_ABS and code in (ABS_X, ABS_Y):
            axis = 'x' if code == ABS_X else 'y'
            lo, hi = self.ranges[axis]
            if not lo <= value <= hi:
                raise InputRejected('Coordinate outside verified kernel range')
            setattr(self, axis, value)
            self.changed = True
        elif kind == EV_KEY and code == BTN_CONTACT:
            if value not in (0, 1):
                raise InputRejected('Unexpected touch button value')
            self.down = bool(value)
            self.changed = True
        elif kind == EV_SYN and code == SYN_REPORT:
            if self.changed:
                self.changed = False
                return {'type': 'touch_frame', 'x': self.x, 'y': self.y,
                        'down': self.down, 'event_ns': event_ns,
                        'ranges': dict(self.ranges)}
        return None


class EvdevSource:
    def __init__(self, path):
        if fcntl is None:
            raise InputRejected('Real evdev input requires Linux')
        if path != discover():
            raise InputRejected('Device is no longer the unique verified touchscreen')
        self.path = path
        self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        self.pending = b''
        try:
            info = os.fstat(self.fd)
            if not stat.S_ISCHR(info.st_mode):
                raise InputRejected('Not an evdev character device')
            sysdev=Path('/sys/class/input')/Path(path).name
            major,minor=map(int,(sysdev/'dev').read_text().strip().split(':'))
            if (os.major(info.st_rdev),os.minor(info.st_rdev)) != (major,minor):
                raise InputRejected('Sysfs/evdev device identity changed')
            identity = bytearray(8)
            fcntl.ioctl(self.fd, 0x80084502, identity, True)
            bus, vendor, product, version = struct.unpack('4H', identity)
            if (bus, vendor, product) != (3, 0x13ff, 0x0008):
                raise InputRejected('EVIOCGID identity mismatch')
            raw_name=bytearray(128)
            fcntl.ioctl(self.fd,0x80804506,raw_name,True)
            if bytes(raw_name).split(b'\0',1)[0] != b'iSolution X75W03+069 Mouse':
                raise InputRejected('EVIOCGNAME exact interface mismatch')
            # This changes timestamps for this read-only file descriptor only.
            # Fail closed if event freshness cannot use the local monotonic clock.
            fcntl.ioctl(self.fd, 0x400445a0, struct.pack('i', 1))
            values = {}
            ranges = {}
            for code, axis in ((ABS_X, 'x'), (ABS_Y, 'y')):
                raw = bytearray(24)
                fcntl.ioctl(self.fd, 0x80184540+code, raw, True)
                current, lo, hi, fuzz, flat, resolution = struct.unpack('6i', raw)
                if not 0 < hi-lo <= 65535 or not lo <= current <= hi:
                    raise InputRejected('Invalid ABS range')
                ranges[axis] = [lo, hi]
                values[axis] = current
            keys = bytearray(96)
            fcntl.ioctl(self.fd, 0x80604518, keys, True)
            self.initial_down = bool(keys[BTN_CONTACT//8] & (1 << (BTN_CONTACT%8)))
            self.parser = PacketParser(ranges, values['x'], values['y'], self.initial_down)
            self.identity = {'vendor': vendor, 'product': product, 'bus': bus, 'version': version}
            self.ranges = ranges
            self.opened_ns = time.monotonic_ns()
        except BaseException:
            self.close()
            raise

    def initial_state(self):
        # This is an actual EVIOCGKEY/EVIOCGABS observation, never a synthetic press.
        # A held-down state only informs the receiver to remain disarmed until up.
        return {'type': 'state', 'down': self.initial_down, 'x': self.parser.x,
                'y': self.parser.y, 'ranges': dict(self.ranges),
                'event_ns': self.opened_ns, 'kernel_state': True}

    def is_up(self):
        keys = bytearray(96)
        fcntl.ioctl(self.fd, 0x80604518, keys, True)
        return not bool(keys[BTN_CONTACT//8] & (1 << (BTN_CONTACT%8)))

    def reports(self, timeout=.1):
        if not select.select([self.fd], [], [], timeout)[0]:
            return []
        data = os.read(self.fd, EVENT.size*128)
        if not data:
            raise InputRejected('Touch device disconnected')
        self.pending += data
        result = []
        now = time.monotonic_ns()
        while len(self.pending) >= EVENT.size:
            sec, usec, kind, code, value = EVENT.unpack(self.pending[:EVENT.size])
            self.pending = self.pending[EVENT.size:]
            event_ns = sec*1000000000 + usec*1000
            if event_ns > now+10000000 or now-event_ns > 250000000:
                raise InputRejected('Stale or invalid evdev timestamp; cancel instead of replay')
            report = self.parser.feed(kind, code, value, event_ns)
            if report is not None:
                result.append(report)
        return result

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

