"""Bounded B TCP JSON Lines ingress for the existing confirmed-voice UI.

This bridge consumes recognition events, not playback commands. Reconnects and
heartbeats cannot turn an old utterance into another conversation response.
"""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import math
from pathlib import Path
import socket
import threading
import time
import uuid

PROTOCOL_VERSION = 'integration_network_v0.1'
RESULT_VERSION = 'b_speech_result_v0.1'
INTENT_VERSION = '2026.09.29'
MAX_LINE_BYTES = 16384
MAX_INTEGER = (1 << 63) - 1
INTENT_IDS = (8193, 8194, 8195, 8196, 8197, 8198, 8199, 8200, 8201,
              8202, 8208, 8209, 8211, 8212, 8213, 8432, 8433, 8434)


def integer(value, minimum=0):
    return type(value) is int and minimum <= value <= MAX_INTEGER


def valid_uuid(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


class BVoiceBridge:
    def __init__(self, on_result, on_heartbeat, *, bind_ip='0.0.0.0', port=9000,
                 expected_ip='192.168.2.99', catalog_path=None, get_capture_context=None):
        self.on_result = on_result
        self.on_heartbeat = on_heartbeat
        self.get_capture_context = get_capture_context
        self.bind_ip, self.port, self.expected_ip = bind_ip, port, expected_ip
        if not expected_ip:
            raise ValueError('B IP must be configured explicitly')
        socket.inet_pton(socket.AF_INET, expected_ip)
        path = catalog_path or Path(__file__).resolve().parents[1] / 'phase1_udp/config/voice_intents_v1.json'
        catalog = json.loads(Path(path).read_text(encoding='utf-8'))
        self.classes = {row['model_class']: row for row in catalog['intents']}
        if (set(self.classes) != set(range(18))
                or tuple(self.classes[i]['intent_id'] for i in range(18)) != INTENT_IDS):
            raise ValueError('B bridge requires the frozen 18-class voice catalog')
        self.boot_id = str(uuid.uuid4())
        self.sequence = 0
        self.lock = threading.RLock()
        self.clients_lock = threading.Lock()
        self.events = OrderedDict()
        self.highest = OrderedDict()
        self.clients = set()
        self.workers = []
        self.listener = None
        self.thread = None
        self.stop_event = threading.Event()

    def _ack(self, message, status, error=''):
        self.sequence += 1
        payload = message.get('payload') if isinstance(message.get('payload'), dict) else {}
        return dict(protocol_version=PROTOCOL_VERSION, source='A', message_type='ack',
                    boot_id=self.boot_id, sequence=self.sequence, timestamp_ms=int(time.time() * 1000),
                    payload=dict(ack_boot_id=message.get('boot_id'), ack_sequence=message.get('sequence'),
                                 utterance_id=payload.get('utterance_id'), status=status, error=error,
                                 voice_capture_context=(self.get_capture_context()
                                     if self.get_capture_context is not None
                                     else {'version': 'voice_turn_v1', 'token': None})))

    def _result_error(self, payload):
        token = payload.get('voice_turn_token')
        if token is not None and not valid_uuid(token):
            return 'invalid_voice_turn_token'
        if (payload.get('schema_version') != RESULT_VERSION or payload.get('event') != 'speech_result'
                or payload.get('intent_table_version') != INTENT_VERSION):
            return 'result_version_mismatch'
        if payload.get('status') not in ('candidate', 'rejected', 'error'):
            return 'invalid_result_status'
        if not isinstance(payload.get('model_version'), str) or not payload['model_version'].strip():
            return 'missing_model_version'
        if not integer(payload.get('error_code')):
            return 'invalid_error_code'
        if not integer(payload.get('timestamp_us')):
            return 'invalid_result_timestamp'
        top3 = payload.get('top3')
        if not isinstance(top3, list) or not 1 <= len(top3) <= 3:
            return 'invalid_top3'
        seen, previous_score = set(), 1.0
        for candidate in top3:
            if not isinstance(candidate, dict):
                return 'invalid_candidate'
            class_id = candidate.get('model_class')
            if type(class_id) is not int or class_id not in self.classes or class_id in seen:
                return 'invalid_model_class'
            seen.add(class_id)
            expected = self.classes[class_id]
            if (type(candidate.get('intent_id')) is not int
                    or candidate['intent_id'] != expected['intent_id']
                    or candidate.get('code') != expected['code']
                    or candidate.get('intent_id_hex') != expected['intent_id_hex']):
                return 'intent_mapping_mismatch'
            score = candidate.get('score')
            if (isinstance(score, bool) or not isinstance(score, (int, float))
                    or not 0 <= score <= 1 or not math.isfinite(score) or score > previous_score):
                return 'invalid_score'
            previous_score = score
        if payload['status'] == 'candidate' and (top3[0]['model_class'] >= 15 or payload['error_code'] != 0):
            return 'candidate_status_mismatch'
        if payload['status'] == 'rejected' and top3[0]['model_class'] < 15:
            return 'rejection_status_mismatch'
        return ''

    def _identity(self, message):
        payload, boot_id = message['payload'], message.get('boot_id')
        utterance_id, timestamp = payload.get('utterance_id'), payload.get('timestamp_us')
        if 'utterance_id' in payload and not integer(utterance_id):
            raise ValueError('invalid_utterance_id')
        if boot_id is not None and utterance_id is not None:
            return (boot_id, 'utterance', utterance_id), (boot_id, 'utterance'), utterance_id
        # Legacy packets lack a startup ID. Do not use connection identity or
        # sequence: watch-file reconnects assign new sequences to the old file.
        # A positive original result timestamp is mandatory in this fallback.
        if not integer(timestamp, 1):
            raise ValueError('missing_stable_event_identity')
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        digest = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
        stream = (boot_id or 'legacy', 'timestamp')
        return stream + (timestamp, digest), stream, timestamp

    def process_message(self, message):
        with self.lock:
            if not isinstance(message, dict):
                return None
            if (message.get('protocol_version') != PROTOCOL_VERSION or message.get('source') != 'B'
                    or not integer(message.get('sequence'), 1) or not integer(message.get('timestamp_ms'))
                    or not isinstance(message.get('payload'), dict)
                    or ('boot_id' in message and not valid_uuid(message['boot_id']))):
                return self._ack(message, 'rejected', 'invalid_envelope')
            kind = message.get('message_type')
            if kind == 'hello':
                return self._ack(message, 'accepted')
            if kind == 'heartbeat':
                self.on_heartbeat()
                return self._ack(message, 'accepted')
            if kind != 'speech_result':
                return self._ack(message, 'rejected', 'unsupported_message_type')
            payload = message['payload']
            error = self._result_error(payload)
            if error:
                return self._ack(message, 'rejected', error)
            try:
                key, stream, ordinal = self._identity(message)
            except (ValueError, TypeError) as error:
                return self._ack(message, 'rejected', str(error))
            if key in self.events or ordinal <= self.highest.get(stream, -1):
                return self._ack(message, 'duplicate')
            # Consume before calling business state, including wrong-turn and
            # ignored results. Heartbeats never advance this result watermark.
            self.events[key] = True
            self.highest[stream] = ordinal
            self.highest.move_to_end(stream)
            while len(self.events) > 1024:
                self.events.popitem(last=False)
            while len(self.highest) > 256:
                self.highest.popitem(last=False)
            best = payload['top3'][0]
            if payload['status'] == 'error' or payload['error_code'] != 0 or best['model_class'] in (15, 17):
                return self._ack(message, 'ignored')
            result = self.on_result(best['intent_id'], float(best['score']),
                                    payload.get('voice_turn_token'))
            status = result if result in ('accepted', 'ignored', 'rejected') else 'accepted'
            return self._ack(message, status)

    @property
    def address(self):
        return self.listener.getsockname() if self.listener is not None else (self.bind_ip, self.port)

    def start(self):
        if self.listener is not None:
            raise RuntimeError('B bridge already started')
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.listener.bind((self.bind_ip, self.port))
            self.listener.listen(4)
            self.listener.settimeout(0.25)
        except OSError:
            self.listener.close()
            self.listener = None
            raise
        self.thread = threading.Thread(target=self._accept, daemon=True, name='B-voice-TCP')
        self.thread.start()

    def _accept(self):
        while not self.stop_event.is_set():
            try:
                connection, peer = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with self.clients_lock:
                if self.stop_event.is_set() or peer[0] != self.expected_ip or len(self.clients) >= 4:
                    connection.close()
                    continue
                self.clients.add(connection)
                self.workers = [worker for worker in self.workers if worker.is_alive()]
                worker = threading.Thread(target=self._client, args=(connection,), daemon=True)
                self.workers.append(worker)
                # close() must never observe a worker that has not started.
                worker.start()

    def _client(self, connection):
        connection.settimeout(0.5)
        pending = b''
        last_received = time.monotonic()
        try:
            while not self.stop_event.is_set():
                try:
                    chunk = connection.recv(4096)
                except socket.timeout:
                    if time.monotonic() - last_received > 15.0:
                        break
                    continue
                if not chunk:
                    break
                last_received = time.monotonic()
                pending += chunk
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    if len(line) > MAX_LINE_BYTES:
                        return
                    try:
                        message = json.loads(line.decode('utf-8'))
                    except (ValueError, UnicodeError):
                        return
                    response = self.process_message(message)
                    if response is not None:
                        connection.sendall((json.dumps(response, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8'))
                if len(pending) > MAX_LINE_BYTES:
                    break
        except (OSError, ValueError, TypeError):
            pass
        finally:
            with self.clients_lock:
                self.clients.discard(connection)
            connection.close()

    def close(self):
        self.stop_event.set()
        if self.listener is not None:
            self.listener.close()
        with self.clients_lock:
            clients, workers = list(self.clients), list(self.workers)
        for connection in clients:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        if self.thread is not None:
            self.thread.join(timeout=1.0)
        for worker in workers:
            worker.join(timeout=1.0)
