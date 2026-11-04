"""NDJSON backend for the dual-display Qt/QML prototype."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import socket
import math
import re
import uuid
from pathlib import Path
from typing import Any, Callable, Dict


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE2_ROOT = PROJECT_ROOT / "transport"
DEPARTMENT_CONFIG_PATH = PROJECT_ROOT / "phase1_udp" / "config" / "departments_v1.json"
VOICE_DISPLAY_TEXT_PATH = Path(__file__).with_name("voice_display_text.json")
if str(PHASE2_ROOT) not in sys.path:
    sys.path.insert(0, str(PHASE2_ROOT))

from pynq_sender import PynqUdpSender  # noqa: E402
from sign_local_demo import SignIntentMapper  # noqa: E402
from zynq_receiver import ZynqUdpReceiver  # noqa: E402
from intent_composer import OrderedIntentComposer  # noqa: E402
from protocol_runtime import with_voice_runtime_action  # noqa: E402


SnapshotEmitter = Callable[[Dict[str, Any]], None]
OVERLAY_TIMEOUT = 0.75
VIDEO_START_TIMEOUT = 10.0
VIDEO_PLAY_TIMEOUT = 65.0
DOWN_SIGN_MODE = 'down_single_v1'
A_DELIVERY_PROFILE = 'a_delivery_20261006'
POSTURE_MAX_AGE_MS = 350.0


def camera_boxes(raw_boxes, limit):
    boxes = []
    if isinstance(raw_boxes, list):
        for box in raw_boxes[:limit]:
            if (isinstance(box, list) and len(box) == 4
                    and all(isinstance(v, (float, int)) and not isinstance(v, bool)
                            and math.isfinite(v) for v in box)):
                x0, y0, x1, y1 = box
                if 0 <= x0 < x1 <= 800 and 0 <= y0 < y1 <= 480:
                    boxes.append(dict(x0=x0, y0=y0, x1=x1, y1=y1))
    return boxes


def camera_hands(raw_hands):
    hands = []
    if not isinstance(raw_hands, list):
        return hands
    for hand in raw_hands[:2]:
        if not isinstance(hand, dict):
            continue
        points = hand.get('keypoints')
        if not isinstance(points, list) or len(points) != 21:
            continue
        if all(isinstance(point, list) and len(point) == 2
               and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                       and math.isfinite(v) for v in point)
               and 0 <= point[0] < 800 and 0 <= point[1] < 480 for point in points):
            hands.append(dict(keypoints=[dict(x=x, y=y) for x, y in points]))
    return hands


def camera_body(raw_points):
    if not isinstance(raw_points, list) or len(raw_points) != 17:
        return []
    result = []
    for point in raw_points:
        if isinstance(point, dict):
            x, y = point.get('x'), point.get('y')
        elif isinstance(point, list) and len(point) in (2, 3):
            x, y = point[:2]
        else:
            return []
        if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (x, y))
                or not -800 <= x <= 1600 or not -480 <= y <= 960):
            return []
        result.append(dict(x=x, y=y))
    return result


def load_department_options() -> list[str]:
    data = json.loads(DEPARTMENT_CONFIG_PATH.read_text(encoding="utf-8"))
    options = data.get("options")
    if not isinstance(options, list) or not options:
        raise ValueError("科室配置必须包含非空 options 列表")
    normalized = [str(option).strip() for option in options]
    if any(not option for option in normalized) or len(set(normalized)) != len(normalized):
        raise ValueError("科室名称不能为空或重复")
    return normalized


def load_voice_display_config():
    """Load display wording and its explicit videos outside the frozen catalog."""
    data = json.loads(VOICE_DISPLAY_TEXT_PATH.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported voice display text schema")
    rows = data.get("display_text_by_model_class")
    if not isinstance(rows, dict):
        raise ValueError("Voice display text must map model classes to text")
    result = {}
    for key, text in rows.items():
        if (key not in {str(index) for index in range(15)}
                or not isinstance(text, str) or not text.strip()):
            raise ValueError("Invalid voice display text entry: %r" % key)
        result[int(key)] = text.strip()
    video_rows = data.get('video_by_model_class', {})
    if not isinstance(video_rows, dict):
        raise ValueError('Voice videos must map model classes to exact display sentences')
    videos = {}
    for key, row in video_rows.items():
        if key not in rows or not isinstance(row, dict):
            raise ValueError('Invalid voice video entry: %r' % key)
        text, asset = row.get('display_text'), row.get('asset')
        if (not isinstance(text, str) or not text.strip()
                or not isinstance(asset, str)
                or not re.fullmatch(r'staff_display_%02d_[a-z0-9_]+\.mp4' % int(key), asset)):
            raise ValueError('Invalid voice video binding: %r' % key)
        videos[int(key)] = dict(row)
    return result, videos


class UiService:
    def __init__(
        self,
        *,
        bind_ip: str = "0.0.0.0",
        bind_port: int = 5000,
        video_root: Path | None = None,
        emitter: SnapshotEmitter | None = None,
    ) -> None:
        configured_video_root = os.getenv('MEDCOMM_VIDEO_ROOT') or str(PROJECT_ROOT / 'videos')
        self.video_root = Path(video_root) if video_root is not None else Path(configured_video_root)
        self.emitter = emitter or self._print_snapshot
        self.output_lock = threading.Lock()
        self.state_lock = threading.RLock()
        self.sign_mapper = SignIntentMapper()
        self.sign_composer = OrderedIntentComposer()
        self.voice_display_text, self.voice_video_assets = load_voice_display_config()
        self.voice_pending = None
        self.voice_turn_token = None
        self._sign_last_received_at = None
        self.sign_neutral_gate = False
        self.sign_edited_draft = False
        self.sign_frame_floor = None
        self.sign_segment_start_floor = None
        self.a_camera_epoch = None
        self.a_retired_camera_boots = set()
        self.neutral_frames = 0
        self.last_a_frame = None
        self.last_neutral_frame = None
        self.sign_recognition_mode = 'legacy'
        self.sign_segment_state = 'waiting_neutral'
        self.sign_segment_quality = 'pose_unknown'
        self.sign_final_label = ''
        self.sign_segment_error = ''
        self.sign_pending_segments = {}
        self.down_neutral_until = 0.0
        self.video_session_id = uuid.uuid4().hex
        self.video_request_counter = 0
        self.video_deadline = None
        self.department_options = load_department_options()
        self.sign_index = 0
        self.voice_index = 0
        self.stop_event = threading.Event()
        self.last_a_seen = 0.0
        self.last_a_geometry = 0.0
        self.a_source = None
        self.board_service = None
        self.board_service_seen = None
        self.board_retired_services = set()
        self.board_status_revision = 0
        self.last_b_heartbeat = None
        self.a_sequence = None
        self.a_events = set()
        self.a_event_order = []
        self.a_segments = set()
        self.a_segment_order = []
        self.dialogue_printer = None
        self.event_log: list[str] = []
        self.state: dict[str, Any] = {
            "system_state": "STARTING",
            "conversation_turn": "patient",
            "round_number": 1,
            "sign_tokens": [],
            "sign_draft_text": "",
            "sign_match_status": "empty",
            "sign_match_hint": "请按顺序完成本次手语表达。",
            "sign_hint": "请按顺序表达手语词，匹配后确认识别",
            "sign_can_confirm": False,
            "sign_can_undo": False,
            "voice_draft_text": "",
            "voice_draft_confidence": -1.0,
            "voice_can_confirm": False,
            "status_message": "正在启动通信服务",
            "voice_online": False,
            "camera_status": "SIMULATION",
            "camera_url": "",
            "sign_online": False,
            "sign_status": "等待 A 识别服务",
            "sign_candidate_text": "",
            "sign_candidate_confidence": -1.0,
            "sign_last_word": "",
            "sign_last_confidence": -1.0,
            "sign_last_completed_at": "",
            "sign_last_reason": "",
            "sign_last_status": "empty",
            "sign_last_age_seconds": -1,
            "hand_boxes": [],
            "hand_landmarks": [],
            "body_boxes": [],
            "body_landmarks": [],
            "staff_text": "等待患者进行手语表达",
            "sign_confidence": -1.0,
            "sign_intent_code": "",
            "patient_prompt": "等待工作人员说话",
            "video_asset": "",
            "video_url": "",
            "video_available": False,
            "video_playback_state": "idle",
            "video_playback_id": self.video_session_id + ':0',
            "video_playback_error": "",
            "playback_nonce": 0,
            "department_selection_visible": False,
            "department_options": list(self.department_options),
            "selected_department": "",
            "event_log": [],
            "last_error": "",
        }

        self.receiver = ZynqUdpReceiver(
            bind_ip,
            bind_port,
            action_handler=self._on_voice_intent,
            require_ordered_voice=True,
        )
        self.receiver_thread = threading.Thread(
            target=self.receiver.serve_forever,
            args=(self.stop_event,),
            daemon=True,
            name="zynq-udp-receiver",
        )
        self.receiver_thread.start()
        self.status_thread = threading.Thread(
            target=self._status_loop,
            daemon=True,
            name="ui-status-monitor",
        )
        self.status_thread.start()
        with self.state_lock:
            self.state["system_state"] = "READY"
            self.state["status_message"] = "界面已就绪，请患者开始表达"
        self._append_event("界面与通信服务已启动")
        self.emit()

    @staticmethod
    def _print_snapshot(snapshot: dict[str, Any]) -> None:
        print(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), flush=True)

    def snapshot(self) -> dict[str, Any]:
        with self.state_lock:
            snapshot = dict(self.state)
            snapshot.update(self.dialogue_printer.snapshot() if self.dialogue_printer else dict(print_enabled=False, print_status_text="打印已关闭"))
            if self._sign_last_received_at is not None:
                snapshot['sign_last_age_seconds'] = max(
                    0, int(time.monotonic() - self._sign_last_received_at))
            self._add_board_status(snapshot, time.monotonic())
            return snapshot

    def board_owns_input(self):
        with self.state_lock:
            return (self.board_service is not None
                    and time.monotonic() - self.board_service_seen < 3.0
                    and self.board_service['service_state'] != 'stopped')

    def _add_board_status(self, snapshot, now):
        """Health is separate from fresh observations and never renews posture."""
        status = self.board_service
        if status is None:
            return
        fresh = now - self.board_service_seen < 3.0
        snapshot['board_service_online'] = fresh
        snapshot['board_service_state'] = status['service_state']
        snapshot['board_inference_ms'] = status.get('inference_ms')
        snapshot['board_frame_gap_ms'] = status.get('frame_gap_ms')
        if self.a_source == 'pc_tcn' and now - self.last_a_seen < 3.0:
            return
        phase = status['service_state']
        if phase == 'error':
            label = '板端识别服务错误'
        elif phase == 'stopped':
            label = '板端识别服务已停止'
        elif not fresh:
            label = '板端识别服务失联（超过 3 秒无状态）'
        elif (status.get('frame_gap_ms') or 0) > 1000:
            label = '板端帧间隔超过 1000 ms，动作已重置，暂不能连续识别'
        elif (status.get('inference_ms') or 0) > 1000:
            label = '板端处理超过 1000 ms，暂不能连续识别'
        elif phase == 'starting':
            label = '板端识别服务启动中'
        elif phase == 'inference':
            label = '板端正在推理，尚无新识别结果'
        elif phase == 'stalled':
            label = '板端等待新的摄像头帧'
        elif now - self.last_a_seen >= 3.0:
            label = '板端服务运行中，等待有效识别帧'
        else:
            label = snapshot['sign_status']
        if fresh and status.get('inference_ms') is not None:
            label += '（推理 %.0f ms）' % status['inference_ms']
        if fresh and status.get('frame_gap_ms') is not None:
            label += '；帧间隔 %.0f ms' % status['frame_gap_ms']
        if fresh and status.get('detail'):
            label += '；' + status['detail']
        snapshot['sign_status'] = label

    def _receive_board_status_locked(self, message):
        epoch, sequence = message.get('service_epoch'), message.get('sequence')
        if (not isinstance(epoch, str) or not re.fullmatch('[0-9a-f]{32}', epoch)
                or type(sequence) is not int or not 0 <= sequence <= 0xffffffff
                or message.get('service_state') not in
                    ('starting', 'running', 'inference', 'stalled', 'error', 'stopped')):
            return False
        detail = message.get('detail', '')
        if not isinstance(detail, str) or len(detail) > 160:
            return False
        for key in ('inference_ms', 'frame_gap_ms'):
            value = message.get(key)
            if value is not None and (isinstance(value, bool)
                    or not isinstance(value, (int, float)) or not math.isfinite(value)
                    or not 0 <= value <= 86400000):
                return False
        previous, now = self.board_service, time.monotonic()
        if previous:
            if epoch == previous['service_epoch']:
                if not 0 < (sequence - previous['sequence']) & 0xffffffff < 0x80000000:
                    return False
            elif (epoch in self.board_retired_services
                  or (now - self.board_service_seen < 3.0
                      and previous['service_state'] not in ('error', 'stopped'))):
                return False
            else:
                self.board_retired_services.add(previous['service_epoch'])
        self.board_service = {key: message.get(key) for key in
                              ('service_epoch', 'sequence', 'service_state',
                               'inference_ms', 'frame_gap_ms', 'detail')}
        self.board_service_seen = now
        self.board_status_revision += 1
        return True

    def emit(self) -> None:
        with self.output_lock:
            # Capture after ordering the outgoing writes, so concurrent voice,
            # UI and camera callbacks cannot publish an older turn last.
            self.emitter(self.snapshot())

    def _append_event(self, text: str) -> None:
        with self.state_lock:
            timestamp = time.strftime("%H:%M:%S")
            self.event_log.append(f"{timestamp}  {text}")
            self.event_log = self.event_log[-6:]
            self.state["event_log"] = list(self.event_log)

    def _asset_url(self, asset: str) -> str:
        if not asset or Path(asset).name != asset or Path(asset).suffix.lower() != '.mp4':
            return ""
        # The board decodes JPEG frames; an MP4 catalog name selects its
        # prepared frame directory. The player validates the manifest itself.
        path = (self.video_root / Path(asset).stem / 'manifest.json').resolve()
        return path.as_uri() if path.is_file() else ""

    def _video_busy(self):
        return self.state['video_playback_state'] in ('requested', 'playing')

    def _advance_video_id(self):
        self.video_request_counter += 1
        self.state['video_playback_id'] = '%s:%d' % (self.video_session_id, self.video_request_counter)

    def _end_video_locked(self, state, error=''):
        self.video_deadline = None
        self.state.update(video_playback_state=state, video_playback_error=error,
                          sign_candidate_text='', sign_candidate_confidence=-1.0)
        self._arm_sign_gate()
        self.state['status_message'] = error or '手语视频已结束，已返回摄像画面'

    def _request_video_locked(self):
        # Advance even for missing media: a new confirmed reply must cancel
        # any previous clip, and late callbacks must never affect this reply.
        self._advance_video_id()
        url = self._asset_url(self.state['video_asset'])
        self.state.update(video_url=url, video_available=bool(url),
                          sign_candidate_text='', sign_candidate_confidence=-1.0)
        if not url:
            self._end_video_locked('error', '视频暂未提供')
            self.state['status_message'] = '对应手语视频暂未提供，继续显示摄像画面'
            return False
        self.state.update(video_playback_state='requested', video_playback_error='',
                          playback_nonce=int(self.state['playback_nonce']) + 1,
                          status_message='已请求播放工作人员手语回复')
        self.video_deadline = time.monotonic() + VIDEO_START_TIMEOUT
        self._sync_sign_draft()
        return True

    def video_callback(self, action, request_id, error=''):
        with self.state_lock:
            if (not isinstance(request_id, str) or request_id != self.state['video_playback_id']
                    or not self._video_busy()):
                return False
            if action == 'video_started':
                if self.state['video_playback_state'] != 'requested':
                    return False
                self.state.update(video_playback_state='playing', video_playback_error='',
                                  status_message='正在播放工作人员手语回复')
                self.video_deadline = time.monotonic() + VIDEO_PLAY_TIMEOUT
                self._sync_sign_draft()
            elif action == 'video_finished':
                # A modal can cancel a request before its first decoded frame.
                self._end_video_locked('finished')
            elif action == 'video_failed':
                detail = ' '.join(error.split())[:160] if isinstance(error, str) else ''
                self._end_video_locked('error', '视频播放失败' + ('：' + detail if detail else ''))
            else:
                return False
        self.emit()
        return True

    def _check_video_timeout_locked(self, now):
        if not self._video_busy() or self.video_deadline is None or now < self.video_deadline:
            return False
        error = ('视频启动超时，已返回摄像画面'
                 if self.state['video_playback_state'] == 'requested'
                 else '视频播放超时，已返回摄像画面')
        self._end_video_locked('error', error)
        return True

    def _sync_sign_draft(self):
        draft = self.sign_composer.snapshot()
        self.state.update(sign_tokens=draft['tokens'], sign_draft_text=draft['text'],
                          sign_match_status=draft['status'], sign_match_hint=draft['hint'],
                          sign_hint=draft['hint'],
                          sign_can_confirm=self._can_confirm_sign(draft),
                          sign_can_undo=(bool(draft['tokens'])
                                         and self.state['conversation_turn'] == 'patient'
                                         and not self._video_busy()))
        if self.sign_neutral_gate:
            self.state['sign_hint'] = ('请先让双手自然下垂，保持上半身在画面内，再开始本轮表达'
                                       if self.sign_recognition_mode == DOWN_SIGN_MODE
                                       else '请先放下双手并移出画面，再开始本轮表达')
        if self._video_busy():
            self.state['sign_hint'] = '请观看工作人员手语回复，视频结束后继续表达'
        if self.sign_recognition_mode == DOWN_SIGN_MODE:
            self._refresh_down_sign_ui()
        if self.sign_edited_draft and self._can_confirm_sign(draft):
            self.state['sign_hint'] = '剩余词序已匹配，可直接确认；继续识别请先将双手自然放下'

    def _clear_sign_last_result(self):
        self._sign_last_received_at = None
        self.state.update(sign_last_word='', sign_last_confidence=-1.0,
                          sign_last_completed_at='', sign_last_reason='',
                          sign_last_status='empty', sign_last_age_seconds=-1)

    def _remember_sign_result(self, message, classes):
        """Display a deduplicated final A event separately from draft admission."""
        status = message.get('status')
        if status not in ('recognized', 'rejected', 'low_conf'):
            return False
        confidence = message.get('confidence')
        valid_confidence = (isinstance(confidence, (int, float))
                            and not isinstance(confidence, bool)
                            and 0 <= confidence <= 1 and math.isfinite(confidence))
        stamp = message.get('timestamp_ms')
        completed_at = ''
        if (isinstance(stamp, (int, float)) and not isinstance(stamp, bool)
                and 0 <= stamp <= 253402271999000 and math.isfinite(stamp)):
            try:
                # The sender supplies Unix time; the board's local clock/TZ
                # need not agree. Never substitute a fabricated arrival time.
                completed_at = time.strftime('%H:%M:%S', time.gmtime(stamp / 1000 + 8 * 3600))
            except (OverflowError, OSError, ValueError):
                pass
        recognized = status == 'recognized'
        class_id = message.get('class_id')
        word = (classes[class_id]['name']
                if recognized and type(class_id) is int and class_id in classes else '')
        quality = message.get('quality', message.get('reason', 'low_conf'))
        reason = '' if recognized else self._segment_rejection_hint(quality)
        # Relative age starts when this complete event reaches the backend.
        # Sender/board wall clocks can differ; neither is used for elapsed age.
        self._sign_last_received_at = time.monotonic()
        self.state.update(sign_last_word=word,
                          sign_last_confidence=float(confidence) if valid_confidence else -1.0,
                          sign_last_completed_at=completed_at, sign_last_reason=reason,
                          sign_last_status='recognized' if recognized else 'rejected',
                          sign_last_age_seconds=0)
        return True

    def _sign_result_disposition(self, reason):
        original = self.state['sign_last_reason']
        self.state['sign_last_reason'] = ((original + '；') if original and original not in reason else '') + reason

    def _can_confirm_sign(self, draft):
        return (draft['status'] == 'matched'
                and self.state['conversation_turn'] == 'patient'
                and not self._video_busy()
                and (self.sign_edited_draft or
                     (not self.sign_neutral_gate
                      and not self.sign_pending_segments
                      and self.sign_segment_state not in ('active', 'finishing'))))

    @staticmethod
    def _valid_frame(value):
        return type(value) is int and 0 <= value <= 0xffffffff

    @staticmethod
    def _frame_after(value, previous):
        return 0 < ((value - previous) & 0xffffffff) < 0x80000000

    def _arm_sign_gate(self):
        self.sign_edited_draft = False
        # The final old gesture event is emitted immediately after its state
        # packet. A frame barrier therefore remains after the neutral gate
        # opens, including when a retry happens while already neutral.
        self.sign_frame_floor = self.last_a_frame
        # Retry, undo and turn changes explicitly cancel in-flight words.
        # The frame/start barriers below also reject their later state packets.
        self.sign_pending_segments.clear()
        if self.sign_recognition_mode == DOWN_SIGN_MODE:
            self.sign_segment_start_floor = self.last_a_frame
            self.sign_neutral_gate = time.monotonic() > self.down_neutral_until or self.last_a_frame is None
        else:
            self.sign_neutral_gate = self.neutral_frames < 6 or self.last_a_frame is None
        self._sync_sign_draft()

    def _fresh_down_posture(self, message):
        frame, pose_frame, age = message.get('frame_id'), message.get('posture_frame_id'), message.get('posture_age_ms')
        return (message.get('recognition_mode') == DOWN_SIGN_MODE
                and message.get('posture_state') == 'down'
                and message.get('neutral_confirmed') is True
                and message.get('segment_state') == 'ready'
                and message.get('quality') == 'ok'
                and self._valid_frame(frame) and self._valid_frame(pose_frame)
                and (frame == pose_frame or self._frame_after(frame, pose_frame))
                and isinstance(age, (float, int)) and not isinstance(age, bool)
                and 0 <= age <= POSTURE_MAX_AGE_MS and math.isfinite(age))

    @staticmethod
    def _segment_rejection_hint(quality):
        return {
            'too_short': '这个动作太短，请完整做一个动作，结束后双手自然下垂',
            'too_long': '此前动作已重置，请双手自然下垂后重新开始',
            'tracking_lost': '本次动作跟踪中断，请保持双手和上半身在画面内，重新做这个动作',
            'pose_unknown': '姿态暂时不清楚，请保持上半身在画面内，重新做这个动作',
            'pose_stale': '姿态画面已过期，请保持上半身在画面内，重新做这个动作',
            'low_conf': '这个动作识别把握不足，请重新做这个动作',
        }.get(str(quality), '本次动作未识别清楚，请重新做这个动作')

    def _refresh_down_sign_ui(self):
        phase = self.sign_segment_state
        if self.sign_neutral_gate:
            status = '请让双手自然下垂待机'
        elif phase == 'ready' and self.sign_pending_segments:
            status = '正在接收本次动作结果'
        elif self.sign_final_label:
            status = '已识别：' + self.sign_final_label
        elif phase == 'ready' and self.sign_segment_error:
            status = '已准备好，请重新做当前动作'
        elif self.sign_segment_error:
            status = '请重新做这个动作'
        elif phase == 'active':
            status = '做完动作后，请放下双手'
        elif phase == 'finishing':
            status = '双手保持下垂，正在确认'
        elif self.sign_segment_quality in ('pose_unknown', 'pose_stale', 'tracking_lost'):
            status = '姿态不明，请保持上半身在画面内'
        elif phase == 'ready':
            status = '已准备好，请做一个动作'
        else:
            status = '请让双手自然下垂待机'
        self.state['sign_status'] = status
        # Keep posture guidance separate from sign_match_hint, which always
        # describes the complete draft's current catalog match.
        if (self.sign_neutral_gate or self._video_busy()
                or self.state['conversation_turn'] != 'patient'):
            return
        if self.sign_segment_error:
            hint = self.sign_segment_error
        elif phase == 'ready' and self.sign_pending_segments:
            hint = '动作已结束，正在接收识别结果；如连接中断，可撤回或重新识别'
        elif phase == 'active':
            hint = '一次只做一个动作；做完直接将双手自然放下，随后显示结果，无需保持手势等待'
        elif phase == 'finishing':
            hint = '已检测到双手下垂，正在确认动作结束，请保持自然放松'
        elif self.sign_segment_quality in ('pose_unknown', 'pose_stale', 'tracking_lost'):
            hint = '请保持双手和上半身在画面内，手部丢失不会作为动作结束'
        elif self.sign_final_label:
            hint = '已识别：%s。双手自然下垂待机，然后开始下一个动作' % self.sign_final_label
        elif phase == 'ready':
            hint = '已准备好，请只做一个手语动作，结束后双手自然下垂'
        else:
            hint = '请先让双手自然下垂，保持上半身在画面内'
        self.state['sign_hint'] = hint

    def _track_pending_sign_segment(self, message):
        """A ready state precedes its final packet; it cannot confirm old words."""
        segment = message.get('segment_id')
        start, frame = message.get('segment_start_frame_id'), message.get('frame_id')
        if (self.state['conversation_turn'] != 'patient' or self.sign_neutral_gate
                or self._video_busy()
                or message.get('segment_state') not in ('active', 'finishing', 'ready')
                or not isinstance(segment, str) or not 1 <= len(segment) <= 128
                or segment in self.a_segments
                or not self._valid_frame(start) or not self._valid_frame(frame)
                or (start != frame and not self._frame_after(frame, start))
                or (self.sign_frame_floor is not None
                    and not self._frame_after(frame, self.sign_frame_floor))
                or (self.sign_segment_start_floor is not None
                    and not self._frame_after(start, self.sign_segment_start_floor))):
            return
        self.sign_pending_segments[segment] = start
        self.sign_edited_draft = False

    def _observe_down_sign_state(self, message):
        frame = message.get('frame_id')
        if not self._valid_frame(frame):
            return
        self.last_a_frame = frame
        phase = message.get('segment_state')
        self.sign_segment_state = phase if phase in ('waiting_neutral', 'ready', 'active', 'finishing', 'rejected') else 'waiting_neutral'
        self.sign_segment_quality = str(message.get('quality', 'pose_unknown'))
        if phase == 'active':
            self.sign_final_label = ''
            self.sign_segment_error = ''
        if self._fresh_down_posture(message):
            self.down_neutral_until = time.monotonic() + (POSTURE_MAX_AGE_MS - message['posture_age_ms']) / 1000.0
            if self.sign_neutral_gate:
                self.sign_neutral_gate = False
                self.sign_frame_floor = frame
                # Pose runs asynchronously. Its confirmed down source frame
                # can precede this state packet's camera frame. A new action
                # after that pose is valid, unless it began before a UI retry.
                pose_frame = message['posture_frame_id']
                if (self.sign_segment_start_floor is None
                        or self._frame_after(pose_frame, self.sign_segment_start_floor)):
                    self.sign_segment_start_floor = pose_frame
        else:
            self.down_neutral_until = 0.0
        self._track_pending_sign_segment(message)
        self._sync_sign_draft()

    def _observe_sign_state(self, message, status):
        frame_id = message.get('frame_id')
        if not self._valid_frame(frame_id):
            return
        self.last_a_frame = frame_id
        if status == 'no_hand':
            if self.last_neutral_frame is None or self._frame_after(frame_id, self.last_neutral_frame):
                self.neutral_frames += 1
                self.last_neutral_frame = frame_id
            if self.sign_neutral_gate and self.neutral_frames >= 6:
                self.sign_neutral_gate = False
                self.sign_frame_floor = frame_id
                self._sync_sign_draft()
        else:
            self.neutral_frames = 0
            self.last_neutral_frame = None

    def voice_capture_context(self):
        """Receiver-issued recording permission, independent of board clocks."""
        with self.state_lock:
            token = (self.voice_turn_token
                     if self.state['conversation_turn'] == 'staff' and self.voice_pending is None
                     else None)
            return {'version': 'voice_turn_v1', 'token': token}

    def _voice_display_intent(self, intent):
        displayed = dict(intent)
        text = self.voice_display_text.get(intent['model_class'])
        displayed['display_text'] = text if text is not None else str(intent['meaning'])
        if text is not None:
            # Only an explicit video for this exact display sentence is allowed.
            # An absent or stale binding must not fall back to the frozen video.
            video = self.voice_video_assets.get(intent['model_class'], {})
            asset = video.get('asset', '') if video.get('display_text') == text else ''
            displayed['runtime_action'] = dict(intent['runtime_action'], asset=asset)
        return displayed

    def _on_voice_intent(self, intent: dict[str, Any], confidence: float,
                         *, voice_turn_token=None, require_turn_token=False):
        # The UDP receiver has already applied protocol validation and consumed
        # deduplication. A non-staff turn still ACKs, but cannot create a draft.
        if (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
                or not math.isfinite(confidence) or not 0 <= confidence <= 1):
            return 'rejected'
        with self.state_lock:
            if self.state['conversation_turn'] != 'staff' or self.voice_pending is not None:
                return 'ignored'
            if require_turn_token and (not isinstance(voice_turn_token, str)
                                       or voice_turn_token != self.voice_turn_token):
                return 'ignored'
            if intent['runtime_action']['type'] != 'play_sign_video':
                if intent['runtime_action']['type'] != 'request_repeat':
                    return 'ignored'
                self.state.update(status_message='没有识别清楚，请工作人员重新说一遍', last_error='')
                self._append_event('语音未识别，请重新表达')
                result = 'ignored'
            else:
                intent = self._voice_display_intent(intent)
                self.voice_pending = intent
                self.voice_turn_token = None
                self.state.update(voice_draft_text=intent['display_text'],
                                  voice_draft_confidence=float(confidence), voice_can_confirm=True,
                                  status_message='工作人员语音已识别，请确认识别或重新识别', last_error='')
                self._append_event('语音草稿：' + intent['display_text'])
                result = 'accepted'
        self.emit()
        return result

    def receive_b_voice(self, intent_id, confidence, voice_turn_token=None):
        intent = self.receiver.intents.get(intent_id)
        if intent is None:
            return 'rejected'
        return self._on_voice_intent(with_voice_runtime_action(intent), confidence,
                                    voice_turn_token=voice_turn_token, require_turn_token=True)

    def receive_b_heartbeat(self):
        with self.state_lock:
            self.last_b_heartbeat = time.monotonic()

    def retry_sign(self):
        with self.state_lock:
            if self.state['conversation_turn'] != 'patient':
                return
            self.sign_composer.reset()
            self._clear_sign_last_result()
            self.sign_final_label = ''
            self.sign_segment_error = ''
            self.state.update(sign_candidate_text='', sign_candidate_confidence=-1.0,
                              status_message='患者手语草稿已清空，请重新表达', last_error='')
            self._arm_sign_gate()
        self.emit()

    def confirm_sign(self):
        with self.state_lock:
            draft = self.sign_composer.snapshot()
            # Recheck authoritative phase and draft under the lock. A button's
            # earlier snapshot may predate the next action or video playback.
            if not self._can_confirm_sign(draft):
                return
            self._clear_sign_last_result()
            self.state.update(staff_text=draft['text'], sign_confidence=draft['confidence'],
                              sign_intent_code=draft['expression'], conversation_turn='staff',
                              sign_can_confirm=False, sign_can_undo=False,
                              voice_draft_text='', voice_draft_confidence=-1.0,
                              voice_can_confirm=False, status_message='患者表达已确认，请工作人员回复',
                              last_error='')
            self.voice_pending = None
            self.voice_turn_token = str(uuid.uuid4())
            if self.dialogue_printer:
                self.dialogue_printer.record('patient', draft['text'])
            self._append_event('患者已确认：' + draft['text'])
        self.emit()

    def undo_sign(self):
        with self.state_lock:
            draft = self.sign_composer.snapshot()
            if (self.state['conversation_turn'] != 'patient'
                    or self._video_busy() or not draft['tokens']):
                return
            removed = draft['tokens'][-1]
            self.sign_composer.undo()
            self._clear_sign_last_result()
            self.sign_final_label = ''
            self.sign_segment_error = ''
            self.state.update(sign_candidate_text='', sign_candidate_confidence=-1.0,
                              status_message='已撤回上一词：' + removed, last_error='')
            # Editing is allowed during an action or while waiting for neutral.
            # Keep event deduplication and require a newly started action after
            # this edit, exactly as retry does, so late completion cannot undo it.
            self._arm_sign_gate()
            # Undo explicitly cancels the in-flight gesture. The remaining
            # accepted words may be confirmed without lowering the hand used
            # to tap Undo. Keep the receive barriers for all future packets.
            self.sign_edited_draft = True
            self._sync_sign_draft()
        self.emit()

    def retry_voice(self):
        with self.state_lock:
            if self.state['conversation_turn'] != 'staff':
                return
            self.voice_pending = None
            self.voice_turn_token = str(uuid.uuid4())
            self.state.update(voice_draft_text='', voice_draft_confidence=-1.0, voice_can_confirm=False,
                              status_message='工作人员语音草稿已清空，请重新表达', last_error='')
        self.emit()

    def confirm_voice(self):
        with self.state_lock:
            if self.state['conversation_turn'] != 'staff' or self.voice_pending is None:
                return
            intent = self.voice_pending
            asset = str(intent['runtime_action'].get('asset', ''))
            self.state.update(patient_prompt=intent['display_text'], video_asset=asset,
                              conversation_turn='patient', round_number=int(self.state['round_number']) + 1,
                              voice_draft_text='', voice_draft_confidence=-1.0, voice_can_confirm=False,
                              status_message='工作人员回复已确认，请患者继续表达', last_error='')
            self.voice_pending = None
            self.voice_turn_token = None
            self.sign_composer.reset()
            self._clear_sign_last_result()
            self.sign_final_label = ''
            self.sign_segment_error = ''
            self._arm_sign_gate()
            self._request_video_locked()
            if self.dialogue_printer:
                self.dialogue_printer.record('staff', intent['display_text'])
            self._append_event('工作人员已确认：' + intent['display_text'])
        self.emit()

    def open_departments(self):
        with self.state_lock:
            self.state.update(department_selection_visible=True, last_error='')
        self.emit()

    def cancel_departments(self):
        with self.state_lock:
            self.state['department_selection_visible'] = False
        self.emit()

    def _status_loop(self) -> None:
        previous = None
        while not self.stop_event.wait(0.25):
            with self.state_lock:
                b_online = self.last_b_heartbeat is not None and time.monotonic() - self.last_b_heartbeat <= 3.0
                age = (-1 if self._sign_last_received_at is None else
                       max(0, int(time.monotonic() - self._sign_last_received_at)))
                # Keep relative labels advancing even without camera frames or
                # packets, but emit only when the displayed unit/count changes.
                age_bucket = (('empty', 0) if age < 0 else
                              ('just_now', 0) if age < 60 else
                              ('minutes', age // 60) if age < 3600 else
                              ('hours', age // 3600) if age < 86400 else
                              ('days', age // 86400))
            online = self.receiver.voice_online() or b_online
            camera_path = Path('/run/medcomm/camera.frame')
            try:
                stamp = camera_path.stat().st_mtime_ns
                camera_ready = time.time() - stamp / 1e9 < 2.0
            except OSError:
                stamp, camera_ready = 0, False
            sign_online = time.monotonic() - self.last_a_seen < 3.0
            overlay_fresh = time.monotonic() - self.last_a_geometry < OVERLAY_TIMEOUT
            board_fresh = (self.board_service_seen is not None
                           and time.monotonic() - self.board_service_seen < 3.0)
            signature = (online, stamp, camera_ready, sign_online, overlay_fresh, age_bucket,
                         self.board_status_revision, board_fresh)
            with self.state_lock:
                video_timed_out = self._check_video_timeout_locked(time.monotonic())
            if signature == previous and not video_timed_out:
                continue
            previous = signature
            with self.state_lock:
                self.state["voice_online"] = online
                self.state['camera_status'] = 'READY' if camera_ready else 'WAITING'
                self.state['camera_url'] = Path('/run/medcomm/camera.bmp').as_uri() + '?v=' + str(stamp) if camera_ready else ''
                self.state['sign_online'] = sign_online
                if not sign_online:
                    self.state['sign_status'] = '等待识别服务（板端或 PC）'
                if not sign_online or not overlay_fresh:
                    self.state['hand_boxes'] = []
                    self.state['hand_landmarks'] = []
                    self.state['body_boxes'] = []
                    self.state['body_landmarks'] = []
                    self.state['sign_candidate_text'] = ''
                    self.state['sign_candidate_confidence'] = -1.0
            self.emit()

    def receive_a(self, message, classes, *, trusted_board=False):
        with self.state_lock:
            is_board = message.get('source') == 'board_tcn'
            if is_board and not trusted_board:
                return False
            if is_board and message.get('type') == 'service_status':
                if message.get('protocol') != 'SGR1' or message.get('version') != 1:
                    return False
                accepted = self._receive_board_status_locked(message)
            else:
                accepted = self._receive_a_locked(message, classes)
        if accepted:
            self.emit()
        return accepted

    def _receive_a_locked(self, message, classes):
        source = message.get('source')
        if message.get('protocol') != 'SGR1' or message.get('version') != 1 or source not in ('pc_tcn', 'board_tcn'):
            return False
        if source == 'board_tcn' and (message.get('recognition_mode') != DOWN_SIGN_MODE
                or message.get('camera_epoch') is None
                or message.get('recognition_profile') == A_DELIVERY_PROFILE):
            return False
        if message.get('type') not in ('gesture_state', 'gesture_result'):
            return False
        sequence = message.get('sequence')
        if type(sequence) is not int or not 0 <= sequence <= 0xffffffff:
            return False
        now = time.monotonic()
        if self.a_source is not None and self.a_source != source and now - self.last_a_seen < 3.0:
            return False
        epoch = message.get('camera_epoch')
        parsed_epoch = None
        if epoch is not None:
            # PC's reassembler owns this UUID:counter. A numerical camera-frame
            # decrease by itself is never permission to clear a retry barrier.
            parts = epoch.split(':') if isinstance(epoch, str) else []
            if (len(parts) != 2 or len(parts[0]) != 32
                    or any(c not in '0123456789abcdef' for c in parts[0])
                    or not parts[1].isascii() or not parts[1].isdigit()
                    or len(parts[1]) > 19 or str(int(parts[1])) != parts[1]
                    or int(parts[1]) > 0x7fffffffffffffff):
                return False
            parsed_epoch = (parts[0], int(parts[1]))
        if self.a_camera_epoch is not None:
            if parsed_epoch is None:
                return False  # An upgraded stream cannot omit epoch metadata.
            previous_boot, previous_generation = self.a_camera_epoch
            boot, generation = parsed_epoch
            if boot == previous_boot and generation < previous_generation:
                return False
            if boot != previous_boot and (boot in self.a_retired_camera_boots
                    or now - self.last_a_seen < 3.0):
                return False
        if self.a_sequence is not None and now - self.last_a_seen >= 3.0:
            self.a_events.clear()
            self.a_event_order.clear()
            self.a_segments.clear()
            self.a_segment_order.clear()
            self.sign_pending_segments.clear()
            self.sign_frame_floor = None
            self.sign_edited_draft = False
            self.sign_segment_start_floor = None
            self.last_a_frame = None
            self.last_neutral_frame = None
            self.neutral_frames = 0
            self.down_neutral_until = 0.0
            self.sign_final_label = ''
            self.sign_segment_error = ''
            self.sign_neutral_gate = True
            self._sync_sign_draft()
        # A restarts its sequence from zero; allow this after an actual timeout.
        if self.a_sequence is not None and now - self.last_a_seen < 3.0:
            distance = (sequence - self.a_sequence) & 0xffffffff
            if not 0 < distance < 0x80000000:
                return False
        self.a_sequence, self.last_a_seen = sequence, now
        self.a_source = source
        if parsed_epoch is not None and parsed_epoch != self.a_camera_epoch:
            if self.a_camera_epoch is not None and parsed_epoch[0] != self.a_camera_epoch[0]:
                self.a_retired_camera_boots.add(self.a_camera_epoch[0])
            self.a_camera_epoch = parsed_epoch
            # Keep accepted draft words and event identities. Drop only old
            # camera-coordinate floors and require newly confirmed natural rest.
            self.sign_frame_floor = self.sign_segment_start_floor = None
            self.sign_edited_draft = False
            self.sign_pending_segments.clear()
            self.last_a_frame = self.last_neutral_frame = None
            self.neutral_frames = 0
            self.down_neutral_until = 0.0
            self.sign_neutral_gate = True
            self.sign_segment_state = 'waiting_neutral'
            self.sign_segment_quality = 'pose_unknown'
            self.sign_final_label = self.sign_segment_error = ''
            self._sync_sign_draft()
        declared_mode = message.get('recognition_mode')
        if declared_mode == DOWN_SIGN_MODE and self.sign_recognition_mode != DOWN_SIGN_MODE:
            # Latch production mode. Later legacy packets may update geometry,
            # but cannot silently restore no-hand completion or live candidates.
            self.sign_recognition_mode = DOWN_SIGN_MODE
            self.sign_edited_draft = False
            self.down_neutral_until = 0.0
            self.sign_neutral_gate = True
            self.sign_frame_floor = self.last_a_frame
            self.sign_segment_start_floor = self.last_a_frame
            self.sign_final_label = ''
            self.sign_segment_error = ''
            self._sync_sign_draft()
        down_mode = self.sign_recognition_mode == DOWN_SIGN_MODE
        status = str(message.get('status', 'waiting'))[:80]
        labels = {'waiting': '等待开始', 'watching': '请完成手语动作', 'recognized': '已识别',
                  'no_hand': '请把手放入画面', 'gesture_end': '手语动作已结束',
                  'low_conf': '请重新表达', 'no_model': '模型未加载'}
        with self.state_lock:
            self.state['sign_online'] = True
            if not down_mode:
                self.state['sign_status'] = labels.get(status, '识别中')
            # Provisional classes are separate from the draft. Final events
            # append draft words only; explicit confirmation publishes a
            # complete sentence, and department selection is always manual.
            self.state['sign_candidate_text'] = ''
            self.state['sign_candidate_confidence'] = -1.0
            candidate_id, candidate_confidence = message.get('class_id'), message.get('confidence')
            if (message['type'] == 'gesture_state' and status == 'watching'
                    and not down_mode
                    and not self._video_busy()
                    and type(candidate_id) is int and candidate_id in classes
                    and not isinstance(candidate_confidence, bool)
                    and isinstance(candidate_confidence, (int, float))
                    and math.isfinite(candidate_confidence) and 0 <= candidate_confidence <= 1):
                self.state['sign_candidate_text'] = classes[candidate_id]['name']
                self.state['sign_candidate_confidence'] = float(candidate_confidence)
            # Event geometry describes a completed segment, not the current
            # frame; accepting it would resurrect hands after they left view.
            if message['type'] == 'gesture_state':
                if down_mode:
                    if declared_mode == DOWN_SIGN_MODE:
                        self._observe_down_sign_state(message)
                    else:
                        self.down_neutral_until = 0.0
                        self.sign_segment_quality = 'pose_unknown'
                        self._sync_sign_draft()
                else:
                    self._observe_sign_state(message, status)
                self.last_a_geometry = now
                native_size = (message.get('image_width', 800) == 800
                               and message.get('image_height', 480) == 480)
                self.state['hand_boxes'] = camera_boxes(message.get('boxes'), 2) if native_size else []
                self.state['hand_landmarks'] = camera_hands(message.get('hands')) if native_size else []
                self.state['body_boxes'] = camera_boxes(message.get('body_boxes'), 6) if native_size else []
                self.state['body_landmarks'] = camera_body(message.get('body_keypoints')) if native_size else []
        if message['type'] == 'gesture_result':
            class_id, confidence = message.get('class_id'), message.get('confidence')
            rejection = down_mode and status in ('rejected', 'low_conf')
            segment_id, start_frame = message.get('segment_id'), message.get('segment_start_frame_id')
            if down_mode and (declared_mode != DOWN_SIGN_MODE
                    or not isinstance(segment_id, str) or not 1 <= len(segment_id) <= 128
                    or not isinstance(message.get('event_id'), str) or not message['event_id']
                    or not self._valid_frame(start_frame) or not self._valid_frame(message.get('frame_id'))
                    or (start_frame != message['frame_id'] and not self._frame_after(message['frame_id'], start_frame))):
                return False
            if not rejection and (type(class_id) is not int or class_id not in classes
                    or isinstance(confidence, bool) or not isinstance(confidence, (int, float))
                    or not 0 <= confidence <= 1 or not math.isfinite(confidence)):
                return False
            event_id = str(message.get('event_id') or 'frame:%s:class:%s' % (message.get('frame_id'), class_id))
            if event_id in self.a_events or (down_mode and segment_id in self.a_segments):
                return False
            self.a_events.add(event_id)
            self.a_event_order.append(event_id)
            if len(self.a_event_order) > 256:
                self.a_events.discard(self.a_event_order.pop(0))
            if down_mode:
                self.a_segments.add(segment_id)
                self.a_segment_order.append(segment_id)
                if len(self.a_segment_order) > 256:
                    self.a_segments.discard(self.a_segment_order.pop(0))
                if segment_id in self.sign_pending_segments:
                    del self.sign_pending_segments[segment_id]
                    # The state lock spans removal, validation and append, so
                    # no client can confirm the previous draft in between.
                    self._sync_sign_draft()
            remembered = self._remember_sign_result(message, classes)
            # Consume event IDs in every turn so a retransmission cannot enter
            # a later draft or restore a word the user explicitly removed.
            if (self.state['conversation_turn'] != 'patient' or self.sign_neutral_gate
                    or self._video_busy()):
                if remembered:
                    reason = ('当前是工作人员回合' if self.state['conversation_turn'] != 'patient'
                              else '正在播放手语回复' if self._video_busy()
                              else '请双手自然下垂完成回位')
                    self._sign_result_disposition(reason + '，未加入词序')
                return True
            frame_id = message.get('frame_id')
            if self.sign_frame_floor is not None and (not self._valid_frame(frame_id)
                    or not self._frame_after(frame_id, self.sign_frame_floor)):
                if remembered:
                    self._sign_result_disposition('属于重试或回合切换前的动作，未加入词序')
                return True
            if (down_mode and self.sign_segment_start_floor is not None
                    and not self._frame_after(start_frame, self.sign_segment_start_floor)):
                if remembered:
                    self._sign_result_disposition('属于重试或回合切换前的动作，未加入词序')
                return True
            # A's delivered ensemble has its own calibrated confidence and
            # top-two margin. Only an explicit posture-bounded event may use it;
            # legacy and unspecified profiles keep the established 0.80 gate.
            delivery_profile = (down_mode and declared_mode == DOWN_SIGN_MODE
                                and message.get('recognition_profile') == A_DELIVERY_PROFILE)
            confidence_policy_ok = (status == 'recognized'
                                    and confidence >= (0.65 if delivery_profile else 0.80))
            if delivery_profile:
                margin = message.get('confidence_margin')
                confidence_policy_ok = (confidence_policy_ok
                                        and isinstance(margin, (int, float))
                                        and not isinstance(margin, bool)
                                        and math.isfinite(margin) and 0.10 <= margin <= 1)
            if down_mode and (rejection or not confidence_policy_ok
                              or not self._fresh_down_posture(message)):
                quality = message.get('quality', message.get('reason', 'low_conf'))
                if not confidence_policy_ok and quality in (None, '', 'ok'):
                    quality = 'low_conf'
                self.sign_final_label = ''
                self.sign_segment_error = self._segment_rejection_hint(quality)
                self.sign_segment_state = 'rejected'
                self.sign_segment_quality = str(quality)
                self._sync_sign_draft()
                self.state['status_message'] = self.sign_segment_error
                if remembered:
                    self._sign_result_disposition('未加入词序：' + self.sign_segment_error)
                return True
            if not confidence_policy_ok:
                self.state['status_message'] = 'A 本次结果置信度不足，未纳入手语草稿'
                self.state['sign_hint'] = '这个词识别把握不足，请重新表达该词'
                if remembered:
                    self._sign_result_disposition('置信度未达到收词要求，未加入词序')
                return True
            name = classes[class_id]['name']
            self.sign_composer.append(name, float(confidence))
            self.sign_edited_draft = False
            if remembered:
                self._sign_result_disposition('已加入词序')
            if down_mode:
                self.sign_final_label = self.sign_composer.snapshot()['tokens'][-1]
                self.sign_segment_error = ''
                self.sign_segment_state = 'ready'
                self.sign_segment_quality = 'ok'
            self._sync_sign_draft()
            self.state.update(status_message=self.state['sign_hint'], last_error='')
            self._append_event('手语草稿收词：' + name)
        return True

    def simulate_sign(self) -> None:
        with self.state_lock:
            if self.state['conversation_turn'] != 'patient' or self._video_busy():
                return
            source_intent_order = self.sign_index % len(self.sign_mapper.by_source_order) + 1
            self.sign_index += 1
            intent = self.sign_mapper.by_source_order[source_intent_order]
            self.sign_composer.reset()
            self._clear_sign_last_result()
            self.sign_neutral_gate = False
            for token in intent['tokens']:
                self.sign_composer.append(token, 0.91)
            self._sync_sign_draft()
            self.state.update(status_message='模拟手语已组成草稿，请确认识别', last_error='')
            self._append_event('模拟手语草稿：' + intent['gesture_expression'])
        self.emit()

    def select_department(self, department: str) -> None:
        if department not in self.department_options:
            with self.state_lock:
                self.state["last_error"] = f"未注册的科室：{department}"
                self.state["status_message"] = "科室选择无效"
            self.emit()
            return
        with self.state_lock:
            if not self.state['department_selection_visible']:
                return
            if self.dialogue_printer:
                self.dialogue_printer.record_department(department)
            self.state.update(
                {
                    "department_selection_visible": False,
                    "selected_department": department,
                    "status_message": f"患者已选择科室：{department}",
                    "last_error": "",
                }
            )
        self._append_event(f"患者选择挂号科室：{department}")
        self.emit()

    def simulate_voice(self) -> None:
        business = [
            item
            for item in self.receiver.catalog["intents"]
            if item["type"] == "业务"
        ]
        intent = business[self.voice_index % len(business)]
        self.voice_index += 1

        def send() -> None:
            target_host = "127.0.0.1" if self.receiver.address[0] == "0.0.0.0" else self.receiver.address[0]
            sender = PynqUdpSender((target_host, self.receiver.address[1]), bind=("127.0.0.1", 0))
            try:
                sender.send_heartbeat()
                ack, attempts = sender.send_voice_result(intent["intent_id"], 0.93)
                self._append_event(
                    f"语音模拟ACK {ack['status']}，发送{attempts}次"
                )
                self.emit()
            except Exception as error:  # boundary: surface failure to the UI
                with self.state_lock:
                    self.state["last_error"] = str(error)
                    self.state["status_message"] = "语音模拟发送失败"
                self.emit()
            finally:
                sender.close()

        threading.Thread(target=send, daemon=True, name="voice-simulator").start()

    def replay_video(self) -> None:
        with self.state_lock:
            if not self.state["video_asset"]:
                return
            if self._request_video_locked():
                self.state["status_message"] = "已请求重新播放手语视频"
        self._append_event("患者端请求重新播放")
        self.emit()

    def clear(self) -> None:
        with self.state_lock:
            if self.dialogue_printer:
                try:
                    self.dialogue_printer.end_dialogue()
                except Exception as error:
                    self.state["last_error"] = str(error)
                    self.state["status_message"] = "打印队列未接受，本次对话已保留"
                    threading.Thread(target=self.emit, daemon=True).start()
                    return
            self.sign_composer.reset()
            self._clear_sign_last_result()
            self.sign_final_label = ''
            self.sign_segment_error = ''
            self.voice_pending = None
            self.voice_turn_token = None
            self.event_log = []
            self._advance_video_id()
            self.video_deadline = None
            self.state.update(
                {
                    "conversation_turn": "patient",
                    "round_number": 1,
                    "voice_draft_text": "",
                    "voice_draft_confidence": -1.0,
                    "voice_can_confirm": False,
                    "staff_text": "等待患者进行手语表达",
                    "sign_candidate_text": "",
                    "sign_candidate_confidence": -1.0,
                    "sign_confidence": -1.0,
                    "sign_intent_code": "",
                    "patient_prompt": "等待工作人员说话",
                    "video_asset": "",
                    "video_url": "",
                    "video_available": False,
                    "video_playback_state": "idle",
                    "video_playback_error": "",
                    "playback_nonce": int(self.state['playback_nonce']) + 1,
                    "department_selection_visible": False,
                    "selected_department": "",
                    "status_message": "本轮内容已清空",
                    "last_error": "",
                }
            )
            self._arm_sign_gate()
        self._append_event("清空本轮显示内容")
        self.emit()

    def handle(self, command: dict[str, Any]) -> bool:
        action = command.get("action")
        if action == "simulate_sign":
            self.simulate_sign()
        elif action == "simulate_voice":
            self.simulate_voice()
        elif action == "select_department":
            self.select_department(str(command.get("department", "")))
        elif action == "open_departments":
            self.open_departments()
        elif action == "cancel_departments":
            self.cancel_departments()
        elif action == "retry_sign":
            self.retry_sign()
        elif action == "undo_sign":
            self.undo_sign()
        elif action == "confirm_sign":
            self.confirm_sign()
        elif action == "retry_voice":
            self.retry_voice()
        elif action == "confirm_voice":
            self.confirm_voice()
        elif action == "replay_video":
            self.replay_video()
        elif action in ('video_started', 'video_finished', 'video_failed'):
            self.video_callback(action, command.get('request_id'), command.get('error', ''))
        elif action == "clear":
            self.clear()
        elif action == "snapshot":
            self.emit()
        elif action == "shutdown":
            return False
        else:
            with self.state_lock:
                self.state["last_error"] = f"未知界面命令：{action}"
            self.emit()
        return True

    def close(self) -> None:
        self.stop_event.set()
        self.receiver.close()
        self.receiver_thread.join(timeout=1.0)
        self.status_thread.join(timeout=1.0)




def main() -> None:
    parser = argparse.ArgumentParser()
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    bind_ip = os.getenv("MEDCOMM_BIND_IP", "0.0.0.0")
    bind_port = int(os.getenv("MEDCOMM_BIND_PORT", "5000"))
    video_value = os.getenv("MEDCOMM_VIDEO_ROOT", "").strip()
    video_root = Path(video_value) if video_value else None
    service = UiService(bind_ip=bind_ip, bind_port=bind_port, video_root=video_root)
    try:
        for line in sys.stdin:
            try:
                command = json.loads(line)
                if not isinstance(command, dict):
                    raise ValueError("command must be a JSON object")
                if not service.handle(command):
                    break
            except Exception as error:
                service.handle({"action": f"invalid command: {error}"})
    finally:
        service.close()


if __name__ == "__main__":
    main()
