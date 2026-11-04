"""One local business state shared by the LCD and HDMI Qt processes."""
import json
import os
from pathlib import Path
import socket
import threading
import atexit
import signal

from backend_server import UiService
from b_voice_bridge import BVoiceBridge


def dispatch_a_message(service, message, address, classes, expected_pc):
    """Keep remote PC compatibility; board messages are local-process only."""
    if not isinstance(message, dict):
        return False
    if message.get('source') == 'board_tcn':
        if address[0] != '127.0.0.1':
            return False
        return service.receive_a(message, classes, trusted_board=True)
    if message.get('source') != 'pc_tcn' or address[0] != expected_pc:
        return False
    # Never mix two classifiers' frame/segment identities in one patient draft.
    if service.board_owns_input():
        return False
    return service.receive_a(message, classes)


def run():
    def terminate(signum, frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, terminate)
    clients = set()
    clients_lock = threading.Lock()
    commands_lock = threading.Lock()
    stop = threading.Event()

    def broadcast(snapshot):
        payload = (json.dumps(snapshot, ensure_ascii=False) + '\n').encode('utf-8')
        with clients_lock:
            recipients = list(clients)
        for connection in recipients:
            try:
                connection.sendall(payload)
            except OSError:
                with clients_lock:
                    clients.discard(connection)
                connection.close()

    # Production speech uses the turn-bound B TCP bridge. Keep the legacy
    # simulator's UDP socket local and ephemeral so old network senders cannot
    # bypass recording permissions on port 5000.
    service = UiService(bind_ip='127.0.0.1', bind_port=0, emitter=broadcast)
    printer = None
    if Path('/sys/class/leds/ps_led0').exists():
        try:
            from dialogue_printer import attach_board_printer
            printer = attach_board_printer(service)
            atexit.register(printer.close)
        except Exception as error:
            print('DIALOGUE_PRINT_DISABLED ' + str(error), flush=True)
    bridge = BVoiceBridge(service.receive_b_voice, service.receive_b_heartbeat,
                         get_capture_context=service.voice_capture_context,
                         bind_ip=os.getenv('MEDCOMM_B_BIND_IP', '0.0.0.0'),
                         port=int(os.getenv('MEDCOMM_B_PORT', '9000')),
                         expected_ip=os.getenv('MEDCOMM_B_IP', '192.168.2.99'))
    try:
        bridge.start()
    except Exception:
        bridge.close()
        service.close()
        if printer:
            printer.close()
        raise
    print('B_VOICE_READY TCP=%s:%d expected_B=%s' % (
        bridge.address[0], bridge.address[1], bridge.expected_ip), flush=True)
    catalog = json.loads((Path(__file__).parent / 'a_classes.json').read_text(encoding='utf-8'))
    classes = {entry['idx']: entry for entry in catalog.values()}
    expected_pc = os.getenv('MEDCOMM_PC_IP', '192.168.1.100')
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind(('0.0.0.0', 5005))
    udp.settimeout(0.5)

    def receive_a():
        while not stop.is_set():
            try:
                data, address = udp.recvfrom(8193)
                if len(data) > 8192:
                    continue
                message = json.loads(data.decode('utf-8'))
                if isinstance(message, dict):
                    with commands_lock:
                        dispatch_a_message(service, message, address, classes, expected_pc)
            except socket.timeout:
                continue
            except (ValueError, UnicodeError, OSError) as error:
                if not stop.is_set():
                    print('A_INPUT_ERROR: %s' % error, flush=True)

    def handle(connection):
        try:
            # Bound writes to a stopped UI. Explicit buffering lets an idle
            # receive timeout be retried without invalidating a makefile.
            connection.settimeout(0.5)
            with clients_lock:
                clients.add(connection)
            pending = b''
            while not stop.is_set():
                try:
                    chunk = connection.recv(4096)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                pending += chunk
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    if len(line) > 16384:
                        return
                    message = json.loads(line.decode('utf-8'))
                    if not isinstance(message, dict) or message.get('action') not in (
                        'simulate_sign', 'simulate_voice', 'select_department', 'replay_video', 'clear', 'snapshot',
                        'retry_sign', 'undo_sign', 'confirm_sign', 'retry_voice', 'confirm_voice',
                        'open_departments', 'cancel_departments',
                        'video_started', 'video_finished', 'video_failed'
                    ):
                        continue
                    with commands_lock:
                        service.handle(message)
                if len(pending) > 16384:
                    break
        except (ValueError, OSError):
            pass
        finally:
            with clients_lock:
                clients.discard(connection)
            connection.close()

    threading.Thread(target=receive_a, daemon=True, name='A-SGR1').start()
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(('127.0.0.1', 5070))
    listener.listen(4)
    print('DUAL_SERVICE_READY LCD+HDMI bridge=127.0.0.1:5070 A=UDP:5005', flush=True)
    try:
        while True:
            connection, _ = listener.accept()
            threading.Thread(target=handle, args=(connection,), daemon=True).start()
    finally:
        stop.set()
        bridge.close()
        listener.close()
        udp.close()
        service.close()
        if printer:
            printer.close()


if __name__ == '__main__':
    run()
