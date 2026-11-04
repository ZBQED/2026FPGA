"""Keep the LCD UI attached to its Goodix touchscreen, independent of event IDs."""
import os
from pathlib import Path
import signal
import subprocess
import threading
import time

TOUCH_NAME = 'Goodix Capacitive TouchScreen'
TOUCH_CLIENT = '2-0014'


def staff_touchscreen(input_root='/sys/class/input'):
    for event in sorted(Path(input_root).glob('event*')):
        try:
            if ((event / 'device/name').read_text().strip() == TOUCH_NAME
                    and 'i2c' in str((event / 'device').resolve())):
                return '/dev/input/' + event.name
        except OSError:
            continue
    return None


def reprobe_missing_touch(i2c_root='/sys/bus/i2c'):
    """Retry only the known unbound LCD touch client; never unbind a driver."""
    root = Path(i2c_root)
    client = root / 'devices' / TOUCH_CLIENT
    try:
        if (client / 'name').read_text().strip() != 'gt9xx' or (client / 'driver').exists():
            return False
        (root / 'drivers_probe').write_text(TOUCH_CLIENT)
        return True
    except OSError:
        return False


def staff_command(device):
    args = ['/opt/medcomm/medcomm_ui', '--embedded', '--dual', '--staff',
            '-platform', 'linuxfb:fb=/dev/fb0']
    if device:
        args += ['-plugin', 'evdevtouch:' + device]
    return args


def stop_child(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def run():
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    environment = os.environ.copy()
    environment['QT_QPA_FB_DISABLE_INPUT'] = '1'
    environment.pop('QT_QPA_EVDEV_TOUCHSCREEN_PARAMETERS', None)
    environment.pop('QT_QPA_EVDEV_MOUSE_PARAMETERS', None)
    process, current = None, object()
    attempts, next_probe = 0, 0.0
    try:
        while not stop.is_set():
            device = staff_touchscreen()
            # The vendor driver can fail its first boot probe with EAGAIN.
            # Bound the retries and leave every other I2C client alone.
            if device is None and attempts < 3 and time.monotonic() >= next_probe:
                attempts += 1
                attempted = reprobe_missing_touch()
                print('LCD_TOUCH_PROBE attempt=%d requested=%s' % (attempts, attempted), flush=True)
                next_probe = time.monotonic() + 5
                device = staff_touchscreen()
            if process is None or process.poll() is not None or device != current:
                stop_child(process)
                print('LCD_STAFF_TOUCH=' + (device or 'UNAVAILABLE'), flush=True)
                process = subprocess.Popen(staff_command(device), env=environment)
                current = device
            stop.wait(1)
    finally:
        stop_child(process)


if __name__ == '__main__':
    run()
