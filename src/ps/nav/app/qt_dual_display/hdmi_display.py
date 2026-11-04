"""Keep the Leader Zynq7020 HDMI on its verified 1080p60 clock workaround.

The vendor clock driver can encode a divider as 4 + 1000/1000 instead of 5,
which the Clocking Wizard cannot represent. Requesting 148499 kHz selects the
correct integer divider on this board. This is a userspace workaround, not a
replacement for fixing the kernel's fractional-divider carry calculation.

Keep the card1 DRM fd AND master: lastclose restores the faulty fbdev mode,
and releasing master allows fbdev hotplug handling to restore it as well.
Qt linuxfb continues drawing the existing framebuffer. No PLL registers,
camera processes, boot files, or LCD/card0 settings are changed here.
"""
import ctypes as C
import errno
import os
import signal
import threading
import time


CARD = '/dev/dri/card1'
FRAMEBUFFER = '/dev/fb1'
LOCK = '/var/run/medcomm-hdmi-display.lock'
RETRY_SECONDS = 5
DRIVER_MODE = 1 << 6
CONNECTED = 1
HDMI_A = 11
SYNC_FLAGS = 5  # positive H sync and positive V sync
WORKAROUND_CLOCK = 148499
TIMING_FIELDS = ('hdisplay', 'hsync_start', 'hsync_end', 'htotal', 'hskew',
                 'vdisplay', 'vsync_start', 'vsync_end', 'vtotal', 'vscan')
CEA_1080P60 = (1920, 2008, 2052, 2200, 0, 1080, 1084, 1089, 1125, 0)
U = C.c_uint32
P = C.POINTER


class Mode(C.Structure):
    _fields_ = ([('clock', U)] + [(key, C.c_uint16) for key in TIMING_FIELDS] +
                [('vrefresh', U), ('flags', U), ('type', U), ('name', C.c_char * 32)])


class Resources(C.Structure):
    _fields_ = ([('count_fbs', C.c_int), ('fbs', P(U)),
                 ('count_crtcs', C.c_int), ('crtcs', P(U)),
                 ('count_connectors', C.c_int), ('connectors', P(U)),
                 ('count_encoders', C.c_int), ('encoders', P(U))] +
                [(key, U) for key in ('min_width', 'max_width', 'min_height', 'max_height')])


class Crtc(C.Structure):
    _fields_ = ([(key, U) for key in ('crtc_id', 'buffer_id', 'x', 'y', 'width', 'height')] +
                [('mode_valid', C.c_int), ('mode', Mode), ('gamma_size', C.c_int)])


class Connector(C.Structure):
    _fields_ = ([(key, U) for key in ('connector_id', 'encoder_id', 'connector_type',
                                    'connector_type_id')] +
                [('connection', C.c_int), ('mmWidth', U), ('mmHeight', U),
                 ('subpixel', C.c_int), ('count_modes', C.c_int), ('modes', P(Mode)),
                 ('count_props', C.c_int), ('props', P(U)), ('prop_values', P(C.c_uint64)),
                 ('count_encoders', C.c_int), ('encoders', P(U))])


class Framebuffer(C.Structure):
    _fields_ = [(key, U) for key in ('fb_id', 'width', 'height', 'pitch', 'bpp', 'depth', 'handle')]


class DisplayError(RuntimeError):
    pass


def _copy(value):
    return type(value).from_buffer_copy(value)


def _standard_timing(mode):
    return (tuple(getattr(mode, key) for key in TIMING_FIELDS) == CEA_1080P60 and
            mode.vrefresh == 60 and mode.clock in (148500, WORKAROUND_CLOCK) and
            bool(mode.type & DRIVER_MODE) and not (mode.flags & ~0x0f))


def target_mode(modes, current):
    """Use advertised CEA 1080p60, or an exact known current-timing fallback.

The vendor no-EDID list can omit CEA sync polarities. Only the already active
standard 1080p60 timing can supply the fallback; other resolutions, porches,
interlaced modes, and reduced-blanking modes are never invented or converted.
"""
    for candidate in modes:
        if _standard_timing(candidate) and candidate.clock == 148500 and candidate.flags == SYNC_FLAGS:
            result = _copy(candidate)
            break
    else:
        if not _standard_timing(current):
            raise DisplayError('no verified CEA 1920x1080@60 timing available')
        result = _copy(current)
    result.clock = WORKAROUND_CLOCK
    result.flags = SYNC_FLAGS
    result.type |= DRIVER_MODE
    return result


def same_output_mode(left, right):
    fields = ('clock',) + TIMING_FIELDS + ('vrefresh', 'flags')
    return all(getattr(left, key) == getattr(right, key) for key in fields)


def _libdrm():
    lib = C.CDLL('libdrm.so.2', use_errno=True)
    for name, structure, arguments in (
            ('Resources', Resources, [C.c_int]),
            ('Connector', Connector, [C.c_int, U]),
            ('Crtc', Crtc, [C.c_int, U]),
            ('FB', Framebuffer, [C.c_int, U])):
        getter = getattr(lib, 'drmModeGet' + name)
        getter.argtypes = arguments
        getter.restype = P(structure)
        release = getattr(lib, 'drmModeFree' + name)
        release.argtypes = [P(structure)]
        release.restype = None
    lib.drmModeSetCrtc.argtypes = [C.c_int, U, U, U, U, P(U), C.c_int, P(Mode)]
    lib.drmModeSetCrtc.restype = C.c_int
    lib.drmSetMaster.argtypes = [C.c_int]
    lib.drmSetMaster.restype = C.c_int
    return lib


def _check(result, operation):
    if not result:
        code = C.get_errno() or errno.EIO
        raise OSError(code, operation + ': ' + os.strerror(code))


class HdmiOutput:
    def __init__(self):
        self.lib = _libdrm()
        self.fd = os.open(CARD, os.O_RDWR | os.O_CLOEXEC)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def read_state(self):
        resources = connector = crtc = None
        try:
            resources = self.lib.drmModeGetResources(self.fd)
            _check(resources, 'get DRM resources')
            r = resources.contents
            if r.count_connectors != 1 or r.count_crtcs != 1:
                raise DisplayError('card1 is not the expected single-connector/single-CRTC device')
            connector = self.lib.drmModeGetConnector(self.fd, r.connectors[0])
            _check(connector, 'get HDMI connector')
            c = connector.contents
            if c.connector_type != HDMI_A:
                raise DisplayError('card1 connector is not HDMI-A; refusing configuration')
            if c.count_modes < 0 or c.count_modes > 512:
                raise DisplayError('invalid DRM mode count')
            crtc = self.lib.drmModeGetCrtc(self.fd, r.crtcs[0])
            _check(crtc, 'get HDMI CRTC')
            return (c.connector_id, c.connection, _copy(crtc.contents),
                    [_copy(c.modes[index]) for index in range(c.count_modes)])
        finally:
            if crtc:
                self.lib.drmModeFreeCrtc(crtc)
            if connector:
                self.lib.drmModeFreeConnector(connector)
            if resources:
                self.lib.drmModeFreeResources(resources)

    def framebuffer_fits(self, crtc):
        frame = self.lib.drmModeGetFB(self.fd, crtc.buffer_id)
        _check(frame, 'get existing HDMI framebuffer')
        try:
            return (crtc.x + 1920 <= frame.contents.width and
                    crtc.y + 1080 <= frame.contents.height)
        finally:
            self.lib.drmModeFreeFB(frame)

    def acquire_master(self):
        _check(self.lib.drmSetMaster(self.fd) == 0, 'acquire HDMI DRM master')

    def set_crtc(self, crtc, connector_id, mode):
        if mode is None:
            code = self.lib.drmModeSetCrtc(self.fd, crtc.crtc_id, 0, 0, 0, None, 0, None)
        else:
            ids = (U * 1)(connector_id)
            code = self.lib.drmModeSetCrtc(self.fd, crtc.crtc_id, crtc.buffer_id,
                                         crtc.x, crtc.y, ids, 1, C.byref(mode))
        _check(code == 0, 'set HDMI CRTC')

    def ensure_output(self):
        connector_id, connection, before, modes = self.read_state()
        if connection != CONNECTED:
            return 'WAITING_FOR_CONNECTION'
        if not before.mode_valid or not before.buffer_id:
            return 'WAITING_FOR_ACTIVE_FRAMEBUFFER'
        target = target_mode(modes, before.mode)
        if not self.framebuffer_fits(before):
            raise DisplayError('existing framebuffer is too small for verified 1080p mode')
        # Retain master even when another instance has already applied the fix.
        self.acquire_master()
        if same_output_mode(before.mode, target):
            return 'READY 1920x1080@60 clock_request_khz=148499'
        try:
            self.set_crtc(before, connector_id, None)
            time.sleep(0.3)
            self.set_crtc(before, connector_id, target)
            _, _, after, _ = self.read_state()
            if (not after.mode_valid or after.buffer_id != before.buffer_id or
                    not same_output_mode(after.mode, target)):
                raise DisplayError('HDMI CRTC readback did not match requested mode')
        except Exception as error:
            try:
                self.set_crtc(before, connector_id, before.mode)
            except Exception as restore_error:
                raise DisplayError('HDMI apply failed (%s); previous mode restore failed (%s)' %
                                   (error, restore_error)) from error
            raise
        return 'APPLIED 1920x1080@60 clock_request_khz=148499'


class StateLog:
    def __init__(self):
        self.previous = None

    def emit(self, message):
        if message != self.previous:
            print('HDMI_OUTPUT=' + message, flush=True)
            self.previous = message


def run():
    # Import only on Linux so mode selection and rollback tests also run on PC.
    import fcntl
    log = StateLog()
    lock_fd = os.open(LOCK, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
    output = None
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log.emit('ALREADY_RUNNING')
            return 0
        os.ftruncate(lock_fd, 0)
        os.write(lock_fd, str(os.getpid()).encode('ascii'))
        stop = threading.Event()
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: stop.set())
        while not stop.is_set():
            try:
                if output is None:
                    # Taking DRM master before fbdev creates fb1 can block its
                    # deferred setup when the screen is absent during boot.
                    if not os.path.exists(FRAMEBUFFER) or not os.path.exists(CARD):
                        log.emit('WAITING_FOR_DEVICE')
                        stop.wait(RETRY_SECONDS)
                        continue
                    output = HdmiOutput()
                log.emit(output.ensure_output())
            except (OSError, DisplayError) as error:
                # Keep the fd on ordinary retry (including a temporary old
                # master's EBUSY), so it never triggers lastclose between tries.
                log.emit('RETRY ' + str(error))
                if isinstance(error, OSError) and error.errno in (errno.ENODEV, errno.EBADF):
                    if output is not None:
                        output.close()
                        output = None
            stop.wait(RETRY_SECONDS)
        return 0
    finally:
        if output is not None:
            output.close()
        os.close(lock_fd)


if __name__ == '__main__':
    raise SystemExit(run())
