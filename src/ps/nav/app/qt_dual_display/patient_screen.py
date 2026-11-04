"""Bind the HDMI UI only to its USB touchscreen, including hotplug."""
import glob
import os
from pathlib import Path
import signal
import struct
import subprocess
import threading


def _has_capability(text, code, word_bits):
    """Linux sysfs bitmaps print native-word hexadecimal groups, highest first."""
    if word_bits not in (32, 64):
        return False
    try:
        words = [int(word, 16) for word in reversed(text.split())]
    except ValueError:
        return False
    if not words or any(word < 0 or word >= (1 << word_bits) for word in words):
        return False
    index, offset = divmod(code, word_bits)
    return index < len(words) and bool(words[index] & (1 << offset))


def _verified_isolution_interface(path, properties, word_bits, kind):
    # On this verified controller the generic-HID Mouse interface carries actual
    # ABS_X/Y + BTN_LEFT clicks; its tablet-labelled Touchscreen can stay silent.
    # Never generalize this exception to ordinary mice or unrelated tablets.
    mouse = kind == 'evdevmouse'
    tag = 'E:ID_INPUT_MOUSE=1' if mouse else 'E:ID_INPUT_TABLET=1'
    suffix = ' Mouse' if mouse else ' Touchscreen'
    button = 0x110 if mouse else 0x14a  # BTN_LEFT / BTN_TOUCH
    if tag not in properties.splitlines():
        return False
    device = path / 'device'
    try:
        if ((device / 'id/vendor').read_text().strip().lower() != '13ff' or
                (device / 'id/product').read_text().strip().lower() != '0008' or
                not (device / 'name').read_text().strip().endswith(suffix)):
            return False
        absolute = (device / 'capabilities/abs').read_text()
        keys = (device / 'capabilities/key').read_text()
    except OSError:
        return False
    return (_has_capability(absolute, 0x00, word_bits) and  # ABS_X
            _has_capability(absolute, 0x01, word_bits) and  # ABS_Y
            _has_capability(keys, button, word_bits))


def usb_patient_input(input_root='/sys/class/input', udev_root='/run/udev/data', word_bits=None):
    if word_bits is None:
        word_bits = struct.calcsize('P') * 8
    touchscreen, tablet_fallback = None, None
    for event in sorted(glob.glob(str(Path(input_root) / 'event*'))):
        path = Path(event)
        if 'usb' not in str(path.resolve()).lower():
            continue
        try:
            major, minor = (path / 'dev').read_text().strip().split(':')
            properties = (Path(udev_root) / ('c%s:%s' % (major, minor))).read_text()
        except (OSError, ValueError):
            continue
        device = '/dev/input/' + path.name
        if _verified_isolution_interface(path, properties, word_bits, 'evdevmouse'):
            return device, 'evdevmouse'
        if 'E:ID_INPUT_TOUCHSCREEN=1' in properties.splitlines() and touchscreen is None:
            touchscreen = device, 'evdevtouch'
        elif (tablet_fallback is None and
              _verified_isolution_interface(path, properties, word_bits, 'evdevtouch')):
            tablet_fallback = device, 'evdevtouch'
    return touchscreen or tablet_fallback


def usb_touchscreen(input_root='/sys/class/input', udev_root='/run/udev/data', word_bits=None):
    """Retain the device-only diagnostic API; the supervisor also uses its kind."""
    selected = usb_patient_input(input_root, udev_root, word_bits)
    return selected[0] if selected else None


def patient_command(selected, binary='/opt/medcomm/medcomm_ui'):
    command = [binary, '--embedded', '--dual', '--patient',
               '-platform', 'linuxfb:fb=/dev/fb1']
    if selected:
        device, kind = selected
        # Qt's evdevmouse defaults to relative touchpad motion without :abs.
        parameters = device + (':abs:nocompress' if kind == 'evdevmouse' else '')
        command += ['-plugin', kind + ':' + parameters]
    return command


def run():
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    process, current = None, object()
    environment = os.environ.copy()
    if Path('/etc/gesture-touch/patient-enabled').is_file():
        os.makedirs('/run/medcomm-touch', mode=0o700, exist_ok=True)
        environment['MEDCOMM_TOUCH_SOCKET'] = '/run/medcomm-touch/patient.sock'
        environment['MEDCOMM_PATIENT_BINARY'] = '/opt/medcomm/medcomm_touch_ui'
    environment['QT_QPA_FB_DISABLE_INPUT'] = '1'
    environment['QT_QPA_FB_HIDECURSOR'] = '1'
    # Generic plugins otherwise prefer these inherited values over the explicit
    # device argument, which could route input to the other screen after hotplug.
    environment.pop('QT_QPA_EVDEV_MOUSE_PARAMETERS', None)
    environment.pop('QT_QPA_EVDEV_TOUCHSCREEN_PARAMETERS', None)
    try:
        while not stop.is_set():
            # A deployed network bridge is an explicit, exclusive input source.
            selected = None if environment.get('MEDCOMM_TOUCH_SOCKET') else usb_patient_input()
            if process is None or process.poll() is not None or selected != current:
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                device, kind = selected if selected else (
                    ('QIMING_NETWORK', 'authenticated') if environment.get('MEDCOMM_TOUCH_SOCKET')
                    else ('WAITING_FOR_USB', 'none'))
                print('HDMI_PATIENT_TOUCH=' + device + ' kind=' + kind, flush=True)
                process = subprocess.Popen(patient_command(selected, environment.get(
                    'MEDCOMM_PATIENT_BINARY', '/opt/medcomm/medcomm_ui')), env=environment)
                current = selected
            stop.wait(1)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == '__main__':
    run()
