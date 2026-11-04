"""Local patient display, using the board's existing shared conversation.

No local UiService, camera receiver or recognition model is started. A verified
SSH connection carries the board's loopback-only NDJSON UI protocol.
"""
import argparse
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import socket
import threading
import time
import urllib.request

import paramiko


FIELDS = set('''system_state conversation_turn round_number sign_tokens
sign_draft_text sign_match_status sign_hint sign_match_hint sign_can_confirm sign_can_undo status_message
voice_online camera_status sign_online sign_status sign_candidate_text
sign_candidate_confidence staff_text sign_confidence patient_prompt video_asset
video_available video_playback_state video_playback_id video_playback_error
department_selection_visible department_options selected_department last_error'''.split())
ACTIONS = {'retry_sign', 'undo_sign', 'confirm_sign', 'open_departments', 'cancel_departments',
           'select_department', 'clear', 'replay_video'}
VIDEO_ROOT = Path(__file__).resolve().parents[1] / 'assets/sign_videos'
# These are the new display-sentence recordings, not the old protocol assets.
BROWSER_VIDEO_ASSETS = frozenset((
    'staff_display_00_cards.mp4', 'staff_display_01_insurance_documents.mp4',
    'staff_display_02_register_here.mp4', 'staff_display_03_choose_department.mp4',
    'staff_display_04_payment_complete.mp4', 'staff_display_05_payment_required.mp4',
    'staff_display_06_cash_allowed.mp4',
    'staff_display_07_discharge_ready.mp4',
))


def browser_video_path(asset, video_root):
    if not isinstance(asset, str) or asset not in BROWSER_VIDEO_ASSETS:
        return None
    root = Path(video_root).resolve()
    path = (root / asset).resolve()
    return path if path.parent == root and path.is_file() else None


def video_byte_range(value, size):
    """Return one inclusive byte range; reject invalid and multi-range requests."""
    match = re.fullmatch(r'bytes=(\d*)-(\d*)', value.strip())
    if not match or not any(match.groups()) or size <= 0:
        raise ValueError('Invalid byte range')
    first, last = match.groups()
    if first:
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1
        if start >= size or end < start:
            raise ValueError('Unsatisfiable byte range')
    else:
        length = int(last)
        if length <= 0:
            raise ValueError('Unsatisfiable suffix range')
        start, end = max(0, size - length), size - 1
    return start, end


def extract_recognition(data):
    """Display the existing recognizer's output independently of intent draft.

    Never infer a word from per-frame candidates or copy words into the board's
    conversation. A new recognizer without an event clears previous results.
    """
    if not isinstance(data, dict):
        raise ValueError('Invalid recognizer state')
    result = {key: data.get(key) for key in (
        'live', 'input_live', 'frame_id', 'segment_state', 'posture_state',
        'quality', 'recognition_profile', 'camera_epoch')}
    result['last_event'] = None
    event = data.get('last_event')
    if isinstance(event, dict) and event.get('status') in ('recognized', 'rejected'):
        result['last_event'] = {key: event.get(key) for key in (
            'event_id', 'status', 'gesture_name', 'confidence', 'reason',
            'preview_received_at', 'frame_id')}
        if event.get('status') != 'recognized':
            result['last_event']['gesture_name'] = '未确认'
    return result


def validate_command(command, state):
    if (not isinstance(command, dict) or not isinstance(command.get('action'), str)
            or command['action'] not in ACTIONS):
        raise ValueError('不支持此操作')
    action = command['action']
    allowed = {'action', 'department'} if action == 'select_department' else {'action'}
    if set(command) != allowed:
        raise ValueError('操作参数无效')
    if state.get('system_state') != 'READY':
        raise ValueError('请等待界面服务恢复')
    if action in ('retry_sign', 'undo_sign', 'confirm_sign'):
        if (state.get('conversation_turn') != 'patient' or
                state.get('video_playback_state') in ('requested', 'playing')):
            raise ValueError('当前不是患者表达回合')
        if action == 'confirm_sign' and state.get('sign_can_confirm') is not True:
            raise ValueError('请先完成可确认的手语表达')
        if action == 'undo_sign' and state.get('sign_can_undo') is not True:
            raise ValueError('当前没有可撤回的手语词')
    if action == 'select_department':
        if (not state.get('department_selection_visible') or
                not isinstance(command.get('department'), str) or
                command['department'] not in state.get('department_options', [])):
            raise ValueError('请从当前科室列表选择')
    if action == 'replay_video':
        if (state.get('video_available') is not True or state.get('department_selection_visible')
                or not isinstance(state.get('video_asset'), str)
                or state.get('video_asset') not in BROWSER_VIDEO_ASSETS):
            raise ValueError('当前没有可播放的手语素材')
        # HDMI owns playback callbacks; this command requests its normal replay.
    return dict(command)


class BoardBridge:
    def __init__(self, host, username, password, known_hosts, video_root=None):
        self.host, self.username, self.password = host, username, password
        self.known_hosts = known_hosts
        self.video_root = Path(video_root) if video_root is not None else VIDEO_ROOT
        self.lock, self.send_lock = threading.Lock(), threading.Lock()
        self.stop = threading.Event()
        self.channel = None
        self.state = {}
        self.received = 0.0
        self.error = '正在连接患者端'
        self.preview = {'live': False}
        self.recognition = {'live': False, 'last_event': None}
        self.worker = threading.Thread(target=self._run, daemon=True, name='patient-board-state')
        self.camera_worker = threading.Thread(target=self._camera_status, daemon=True, name='patient-preview-status')

    def start(self):
        self.worker.start()
        self.camera_worker.start()

    def snapshot(self):
        with self.lock:
            connected = self.channel is not None and time.monotonic() - self.received <= 3.0
            asset = self.state.get('video_asset')
            video_url = '/videos/' + asset if browser_video_path(asset, self.video_root) else ''
            return dict(connected=connected, state=copy.deepcopy(self.state),
                        error='' if connected else self.error or '正在等待板端状态更新',
                        preview=dict(self.preview), recognition=copy.deepcopy(self.recognition),
                        browser_video_supported=True, browser_video_url=video_url)

    def command(self, command):
        # Never queue or replay a mutation after reconnecting. Transport failure
        # can mean that the board received it; the user must inspect new state.
        with self.send_lock:
            with self.lock:
                channel = self.channel
                if channel is None or time.monotonic() - self.received > 3.0:
                    raise ConnectionError('患者端连接中断，操作未发送')
                checked = validate_command(command, self.state)
            try:
                channel.sendall((json.dumps(checked, ensure_ascii=False) + '\n').encode('utf-8'))
            except (OSError, EOFError) as exc:
                with self.lock:
                    if self.channel is channel:
                        self.channel = None
                        self.error = '连接中断，请先核对界面状态；操作不会自动重发'
                channel.close()
                raise ConnectionError('连接中断，操作结果待核对，请勿连续重复点击') from exc

    def _run(self):
        delay = 1.0
        while not self.stop.is_set():
            client, channel = paramiko.SSHClient(), None
            try:
                client.load_host_keys(self.known_hosts)
                client.set_missing_host_key_policy(paramiko.RejectPolicy())
                client.connect(self.host, username=self.username, password=self.password,
                               timeout=5, banner_timeout=5, auth_timeout=5,
                               allow_agent=False, look_for_keys=False)
                transport = client.get_transport()
                transport.set_keepalive(10)
                channel = transport.open_channel('direct-tcpip', ('127.0.0.1', 5070),
                                                 ('127.0.0.1', 0), timeout=5)
                channel.settimeout(.5)
                channel.sendall(b'{"action":"snapshot"}\n')
                pending, last_snapshot = b'', time.monotonic()
                delay = 1.0
                while not self.stop.is_set():
                    try:
                        chunk = channel.recv(65536)
                        if not chunk:
                            raise ConnectionError('Board UI stream closed')
                        pending += chunk
                    except socket.timeout:
                        pass
                    if len(pending) > 1024 * 1024:
                        raise ValueError('Board UI frame exceeded limit')
                    while b'\n' in pending:
                        line, pending = pending.split(b'\n', 1)
                        data = json.loads(line.decode('utf-8'))
                        if not isinstance(data, dict) or 'system_state' not in data:
                            continue
                        with self.lock:
                            self.state = {k: v for k, v in data.items() if k in FIELDS}
                            self.received = time.monotonic()
                            self.channel = channel
                            self.error = ''
                    if time.monotonic() - last_snapshot >= 1.0:
                        with self.send_lock:
                            channel.sendall(b'{"action":"snapshot"}\n')
                        last_snapshot = time.monotonic()
            except Exception as exc:
                # Do not log credentials or user conversation contents.
                print('PATIENT_BRIDGE_RECONNECT ' + type(exc).__name__, flush=True)
            finally:
                with self.lock:
                    self.channel = None
                    self.error = '患者端暂时离线，正在重新连接'
                if channel is not None:
                    channel.close()
                client.close()
            self.stop.wait(delay)
            delay = min(8.0, delay * 2)

    def _camera_status(self):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        while not self.stop.is_set():
            try:
                with opener.open('http://127.0.0.1:8765/api/state', timeout=1) as response:
                    data = json.load(response)
                value = {k: data.get(k) for k in ('live', 'input_live', 'fps', 'last_frame_age_ms')}
                recognition = extract_recognition(data)
            except Exception:
                value = {'live': False}
                with self.lock:
                    recognition = copy.deepcopy(self.recognition)
                recognition.update(live=False, input_live=False)
            with self.lock:
                self.preview = value
                self.recognition = recognition
            self.stop.wait(.2)

    def close(self):
        self.stop.set()
        with self.lock:
            channel = self.channel
        if channel is not None:
            channel.close()
        self.worker.join(timeout=2)
        self.camera_worker.join(timeout=2)


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, bridge, page):
        self.bridge, self.page = bridge, page
        self.video_root = bridge.video_root
        self.slots = threading.BoundedSemaphore(12)
        super().__init__(address, Handler)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        request.settimeout(2)
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _reply(self, status, value, html=False):
        payload = value if html else json.dumps(value, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8' if html else 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.end_headers()
        if self.command == 'HEAD':
            return
        try:
            self.wfile.write(payload)
        except (OSError, TimeoutError):
            pass

    def _local_host(self):
        return self.headers.get('Host') == '127.0.0.1:%d' % self.server.server_port

    def _video(self, asset):
        path = browser_video_path(asset, self.server.video_root)
        if path is None:
            return self._reply(404, {'error': '手语视频不存在'})
        try:
            source = path.open('rb')
        except OSError:
            return self._reply(404, {'error': '手语视频不存在'})
        with source:
            size = os.fstat(source.fileno()).st_size
            start, end, status = 0, size - 1, 200
            requested = self.headers.get('Range')
            if requested is not None:
                try:
                    start, end = video_byte_range(requested, size)
                    status = 206
                except ValueError:
                    self.send_response(416)
                    self.send_header('Content-Range', 'bytes */%d' % size)
                    self.send_header('Content-Length', '0')
                    self.send_header('Accept-Ranges', 'bytes')
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    return
            self.send_response(status)
            self.send_header('Content-Type', 'video/mp4')
            self.send_header('Content-Length', str(end - start + 1))
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            if status == 206:
                self.send_header('Content-Range', 'bytes %d-%d/%d' % (start, end, size))
            self.end_headers()
            if self.command == 'HEAD':
                return
            source.seek(start)
            remaining = end - start + 1
            try:
                while remaining > 0:
                    chunk = source.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            except (OSError, TimeoutError):
                pass

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._local_host():
            return self._reply(403, {'error': '请使用本机患者端地址'})
        if self.path == '/':
            return self._reply(200, self.server.page.read_bytes(), html=True)
        if self.path == '/api/state':
            return self._reply(200, self.server.bridge.snapshot())
        if self.path.startswith('/videos/'):
            return self._video(self.path[len('/videos/'):])
        self._reply(404, {'error': '页面不存在'})

    def do_POST(self):
        origin = 'http://127.0.0.1:%d' % self.server.server_port
        if (not self._local_host() or self.path != '/api/command' or
                self.headers.get('X-Requested-With') != 'MedCommPatient' or
                self.headers.get('Origin', origin) != origin or
                self.headers.get_content_type() != 'application/json'):
            return self._reply(403, {'ok': False, 'error': '操作来源无效'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 4096:
                raise ValueError('操作大小无效')
            command = json.loads(self.rfile.read(size).decode('utf-8'))
            self.server.bridge.command(command)
            self._reply(200, {'ok': True, 'sent': True})
        except (ValueError, UnicodeError) as exc:
            self._reply(400, {'ok': False, 'error': str(exc)})
        except (OSError, EOFError) as exc:
            self._reply(503, {'ok': False, 'error': str(exc)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='192.168.1.10')
    parser.add_argument('--user', default='root')
    parser.add_argument('--known-hosts', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    password = os.environ.get('MEDCOMM_LEADER_PASSWORD')
    if not password:
        parser.error('MEDCOMM_LEADER_PASSWORD is required')
    page = Path(__file__).parent / 'web_patient/index.html'
    if not page.is_file():
        parser.error('Patient page is missing')
    bridge = BoardBridge(args.host, args.user, password, str(args.known_hosts))
    server = LocalServer(('127.0.0.1', args.port), bridge, page)
    bridge.start()
    print('PATIENT_UI_READY http://127.0.0.1:%d/' % server.server_port, flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        bridge.close()


if __name__ == '__main__':
    main()
