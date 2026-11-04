"""常驻监听所选音频输入，检测到声音后运行 B 端语音模型。

运行链路：
    PYNQ-Z2 ADAU1761/LINE IN 或 HP-MIC
    -> 48 kHz 双声道 24 bit 音频块
    -> 音量门限触发
    -> 4 秒单声道 16 kHz PCM16
    -> 398x40 Log-Mel
    -> 25 类 PS 模型
    -> speech_result.json，可选 TCP JSON Lines 发给 C

第一次验证建议使用 --once，只识别一条语音后退出；正式运行不带 --once，
程序会一直等待下一条语音。

注意：此版本使用 PYNQ base overlay 的 audio.record()，因此必须在已经能
访问 FPGA 设备的 PYNQ 环境中启动。若从 SSH 启动出现 No Devices Found，
先用 Jupyter 内核验证，之后再配置板端启动环境。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np
import board_observer as observer

import board_wav_to_logmel as feature_lib
from speech_helpers import load_labels, softmax, temporal_summary
from reliable_sender import ReliableResultSender as ResultSender


SAMPLE_RATE_IN = 48000
SAMPLE_RATE_MODEL = 16000
CHANNELS = 2
WINDOW_SECONDS = 4.0
WINDOW_SAMPLES_IN = int(SAMPLE_RATE_IN * WINDOW_SECONDS)
DEFAULT_CHUNK_SECONDS = 0.25
DEFAULT_PRE_ROLL_SECONDS = 0.50
DEFAULT_THRESHOLD_DBFS = -28.5
DEFAULT_TRIGGER_CHUNKS = 3
DEFAULT_COOLDOWN_SECONDS = 1.0
MODEL_VERSION = "staff_seven_extension_20261031_225629_024268"
INTENT_TABLE_VERSION = "2026.10.31-seven-extension-v1"
PROTOCOL_VERSION = "integration_network_v0.1"
INPUT_SOURCE_LABELS = {"line_in": "LINE IN", "microphone": "HP-MIC microphone"}
_AUDIO_METER = None


def decode_codec_buffer(buffer: np.ndarray, channels: int = CHANNELS) -> np.ndarray:
    """把 AudioADAU1761 的 24 bit 无符号打包值解码为 [-1, 1) 浮点数。"""
    packed = np.asarray(buffer, dtype=np.int64).reshape(-1)
    if packed.size % channels:
        raise ValueError(f"audio buffer length {packed.size} is not divisible by {channels}")
    values = packed & 0xFFFFFF
    values = (values ^ 0x800000) - 0x800000
    return values.reshape(-1, channels).astype(np.float64) / float(1 << 23)


def record_chunk(audio, seconds: float) -> np.ndarray:
    """同步采集一个小块并转成单声道浮点采样。"""
    audio.record(seconds)
    stereo = decode_codec_buffer(audio.buffer)
    mono = stereo.mean(axis=1)
    if _AUDIO_METER is not None:
        _AUDIO_METER.observe(stereo, mono)
    observer.level(dbfs(rms(mono)), float(np.max(np.abs(mono))) if mono.size else 0.)
    return mono


def rms(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))


def dbfs(value: float) -> float:
    return 20.0 * float(np.log10(max(value, 1e-12)))


class AudioLevelMeter:
    """Optional block-level logging; uses existing samples without changing them."""
    def __init__(self, seconds: float, clock=time.monotonic, logger=print):
        self.seconds = seconds
        self.clock, self.logger = clock, logger
        self.chunks = 0
        self.last_logged_at = None

    @classmethod
    def from_environment(cls, environ=None, clock=time.monotonic, logger=print):
        environ = os.environ if environ is None else environ
        raw = environ.get("MEDCOMM_AUDIO_METER_SECONDS", "0")
        try:
            seconds = float(raw)
            if not np.isfinite(seconds) or seconds < 0:
                raise ValueError("period must be finite and nonnegative")
        except (TypeError, ValueError, OverflowError):
            # A diagnostic setting must never prevent the real audio service
            # from starting. Invalid settings behave like the default (off).
            try:
                logger("WARN: invalid MEDCOMM_AUDIO_METER_SECONDS; audio meter disabled", flush=True)
            except Exception:
                pass
            return None
        return None if seconds == 0 else cls(seconds, clock=clock, logger=logger)

    def observe(self, stereo: np.ndarray, mono: np.ndarray) -> bool:
        self.chunks += 1
        now = self.clock()
        if self.last_logged_at is not None and now - self.last_logged_at < self.seconds:
            return False
        self.last_logged_at = now
        # Meter only the current already-captured chunk. No extra record call,
        # channel rewrite, audio file, VAD threshold or model change is involved.
        left, right = stereo[:, 0], stereo[:, 1]
        left_rms, right_rms, mono_rms = rms(left), rms(right), rms(mono)
        peak = lambda values: float(np.max(np.abs(values))) if values.size else 0.0
        record = dict(chunks=self.chunks, samples_per_channel=int(mono.size),
                      mono_rms=mono_rms, left_rms=left_rms, right_rms=right_rms,
                      mono_dbfs=dbfs(mono_rms), left_dbfs=dbfs(left_rms), right_dbfs=dbfs(right_rms),
                      mono_peak=peak(mono), left_peak=peak(left), right_peak=peak(right),
                      peak=peak(stereo))
        try:
            self.logger("AUDIO_METER " + json.dumps(record, separators=(",", ":")), flush=True)
        except Exception:
            return False  # A logging failure must not alter capture or inference.
        return True


def calculate_snr_q8(signal_rms: float, noise_rms: float) -> int | None:
    if signal_rms <= 0.0 or noise_rms <= 0.0:
        return None
    snr_db = 20.0 * np.log10(max(signal_rms / noise_rms, 1e-12))
    return int(np.clip(np.rint(snr_db * 256.0), 0, 65535))


def make_result(
    feature, model_path, intents_path, utterance_id, noise_rms, signal_rms,
    input_source="microphone", voice_turn_token=None,
):
    from model_runtime import infer_feature
    result = infer_feature(feature, model_path, intents_path, utterance_id, noise_rms, signal_rms)
    result.update(
        voice_turn_token=voice_turn_token,
        input_rms_dbfs=dbfs(signal_rms),
        noise_rms_dbfs=dbfs(noise_rms),
        input_source=input_source,
        note="PS CPU standby pipeline; microphone capture, Log-Mel, and model inference.",
    )
    return result


def save_result(result_path: Path, result: dict) -> None:
    result_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = result_path.with_suffix(result_path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(result_path)


def load_runtime_config(path: Path | None) -> dict:
    if path is None:
        return {}
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("runtime config must be a JSON object")
    return config


def capture_utterance(
    audio,
    chunk_seconds: float,
    pre_roll_seconds: float,
    threshold_rms: float,
    trigger_chunks: int,
    noise_rms: float,
    input_source: str = "line_in",
    sender: ResultSender | None = None,
    monitor_remote=None,
) -> tuple[np.ndarray, float, tuple[str, int] | None]:
    """等待门限触发，然后采集包含触发前后内容的 4 秒窗口。"""
    chunk_samples = int(round(chunk_seconds * SAMPLE_RATE_IN))
    if chunk_samples <= 0 or WINDOW_SAMPLES_IN % chunk_samples:
        raise ValueError("chunk_seconds must divide the 4-second input window exactly")
    pre_roll = deque(maxlen=max(1, int(round(pre_roll_seconds / chunk_seconds))))
    consecutive = 0
    guarded = sender is not None and sender.host is not None
    capture_context = None
    observer.publish("waiting", capture_mode="remote_turn" if guarded else "local_only")
    print(f"READY: waiting for {INPUT_SOURCE_LABELS[input_source]} audio...", flush=True)

    while True:
        if monitor_remote is not None and (monitor_remote.get_capture_context_snapshot()[0] is not None) != guarded:
            print("MODE_SWITCH: discard pre-roll and acquire a fresh authorized/local window", flush=True)
            return None, max(noise_rms, 1e-12), None
        before = sender.get_capture_context_snapshot() if guarded else None
        chunk = record_chunk(audio, chunk_seconds)
        after = sender.get_capture_context_snapshot() if guarded else None
        if guarded and (before[0] is None or before != after):
            # Keep recording/metering while waiting, but do not reuse samples
            # acquired before this staff turn or across a connection change.
            pre_roll.clear()
            consecutive = 0
            capture_context = None
            continue
        if before != capture_context:
            pre_roll.clear()
            consecutive = 0
            capture_context = before
        level = rms(chunk)
        pre_roll.append(chunk)
        if level >= threshold_rms:
            consecutive += 1
        else:
            consecutive = 0
        if consecutive >= trigger_chunks:
            observer.publish("recording", trigger_level_dbfs=dbfs(level), window_seconds=WINDOW_SECONDS)
            print(f"TRIGGER: level={dbfs(level):.1f} dBFS", flush=True)
            pieces = list(pre_roll)
            remaining = WINDOW_SAMPLES_IN - sum(part.size for part in pieces)
            interrupted = False
            while remaining > 0:
                if monitor_remote is not None and (monitor_remote.get_capture_context_snapshot()[0] is not None) != guarded:
                    print("MODE_SWITCH: discard incomplete window", flush=True)
                    return None, max(noise_rms, 1e-12), None
                if guarded and sender.get_capture_context_snapshot() != capture_context:
                    interrupted = True
                    break
                part = record_chunk(audio, min(chunk_seconds, remaining / SAMPLE_RATE_IN))
                if guarded and sender.get_capture_context_snapshot() != capture_context:
                    interrupted = True
                    break
                pieces.append(part)
                remaining -= part.size
            if interrupted:
                print("DISCARD: voice capture context changed; waiting for a fresh utterance", flush=True)
                pre_roll.clear()
                consecutive = 0
                capture_context = None
                continue
            utterance = np.concatenate(pieces)[:WINDOW_SAMPLES_IN]
            return utterance, max(noise_rms, 1e-12), capture_context


def classify_utterance(
    samples_48k: np.ndarray,
    model_path: Path,
    intents_path: Path,
    output_path: Path,
    utterance_id: int,
    noise_rms: float,
    sender: ResultSender,
    input_source: str = "line_in",
    capture_context: tuple[str, int] | None = None,
) -> dict | None:
    guarded = sender.host is not None
    if guarded and (capture_context is None or capture_context[0] is None
                    or sender.get_capture_context_snapshot() != capture_context):
        print("DISCARD: voice capture context expired before classification", flush=True)
        return None
    observer.publish("classifying")
    mono_16k = samples_48k[::3]
    if mono_16k.size < feature_lib.WINDOW_SAMPLES:
        mono_16k = np.pad(mono_16k, (0, feature_lib.WINDOW_SAMPLES - mono_16k.size))
    mono_16k = mono_16k[: feature_lib.WINDOW_SAMPLES]
    feature = feature_lib.logmel(mono_16k).astype(np.float32)
    result = make_result(
        feature,
        model_path,
        intents_path,
        utterance_id,
        noise_rms,
        rms(samples_48k),
        input_source=input_source,
        voice_turn_token=capture_context[0] if capture_context is not None else None,
    )
    if guarded and sender.get_capture_context_snapshot() != capture_context:
        print("DISCARD: voice capture context changed during classification", flush=True)
        return None
    result["delivery_mode"] = "remote_turn" if guarded else "local_only"
    result["delivery_state"] = "not_sent"
    save_result(output_path, result)
    if guarded:
        if not sender.send_result(result, capture_context=capture_context):
            print("DISCARD: voice result was not queued in its original capture context", flush=True)
            result["delivery_state"] = "discarded_context_changed"
            observer.record_result(result)
            return None
        result["delivery_state"] = "queued_not_yet_acked"
    else:
        sender.send_result(result)
    save_result(output_path, result)
    observer.record_result(result)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return result


def main() -> None:
    global _AUDIO_METER
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=Path(__file__).with_name("staff_classifier_active_speech_float32_pc_mic_selected.npz"))
    parser.add_argument("--intents", type=Path, default=Path(__file__).with_name("staff_speech_intents_v1.json"))
    parser.add_argument("--output", type=Path, default=Path("speech_result.json"))
    parser.add_argument("--config", type=Path, help="JSON runtime configuration")
    parser.add_argument("--input-source", choices=("line_in", "microphone"), default=None,
                        help="codec input; CLI overrides JSON input_source, default line_in")
    parser.add_argument("--seconds", type=float, default=None, help="one polling audio chunk")
    parser.add_argument("--pre-roll", type=float, default=None)
    parser.add_argument("--threshold-dbfs", type=float, default=None)
    parser.add_argument("--trigger-chunks", type=int, default=None)
    parser.add_argument("--cooldown", type=float, default=None)
    parser.add_argument("--host", default=None, help="optional C computer IPv4 address")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--once", action="store_true", help="classify one utterance then exit")
    args = parser.parse_args()

    _AUDIO_METER = AudioLevelMeter.from_environment()

    config = load_runtime_config(args.config)

    # Explicit command-line values take precedence; otherwise use the JSON
    # file, then the safe defaults. ``None`` is meaningful for c_host.
    def configured(argument: str, key: str, fallback):
        value = getattr(args, argument)
        if value is not None:
            return value
        return config.get(key, fallback)

    input_source = configured("input_source", "input_source", "line_in")
    if input_source not in ("line_in", "microphone"):
        parser.error("input_source must be line_in or microphone")
    input_label = INPUT_SOURCE_LABELS[input_source]
    chunk_seconds = float(configured("seconds", "chunk_seconds", DEFAULT_CHUNK_SECONDS))
    pre_roll_seconds = float(configured("pre_roll", "pre_roll_seconds", DEFAULT_PRE_ROLL_SECONDS))
    threshold_dbfs = float(configured("threshold_dbfs", "threshold_dbfs", DEFAULT_THRESHOLD_DBFS))
    trigger_chunks = int(configured("trigger_chunks", "trigger_chunks", DEFAULT_TRIGGER_CHUNKS))
    cooldown_seconds = float(configured("cooldown", "cooldown_seconds", DEFAULT_COOLDOWN_SECONDS))
    c_host = configured("host", "c_host", None)
    c_port = int(configured("port", "c_port", 9000))

    if not 0.05 <= chunk_seconds <= 1.0:
        parser.error("--seconds must be between 0.05 and 1.0")
    if trigger_chunks < 1:
        parser.error("--trigger-chunks must be positive")
    threshold_rms = 10.0 ** (threshold_dbfs / 20.0)
    output_path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    from pynq.overlays.base import BaseOverlay

    # When launched by ``%run`` inside the validated audio Notebook, reuse
    # its already initialized overlay. A normal board process creates it here.
    if "base" not in globals():
        base = BaseOverlay("base.bit")
    if getattr(base.audio, "sample_rate", None) is None:
        base.audio.configure(sample_rate=SAMPLE_RATE_IN, iic_index=1)
    if input_source == "microphone":
        base.audio.select_microphone()
    else:
        base.audio.select_line_in()
    print(f"AUDIO_INPUT source={input_source} ({input_label})", flush=True)
    sender = ResultSender(c_host, c_port)
    observer.TRANSPORT = sender
    local_monitor_enabled = bool(config.get("local_monitor_enabled", False))
    local_sender = observer.LocalOnlySender()
    observer.publish("calibrating", input_source=input_source, model_version=MODEL_VERSION,
                     intent_table_version=INTENT_TABLE_VERSION, threshold_dbfs=threshold_dbfs,
                     trigger_chunks=trigger_chunks, chunk_seconds=chunk_seconds,
                     pre_roll_seconds=pre_roll_seconds, receiver_host=c_host, receiver_port=c_port,
                     local_monitor_enabled=local_monitor_enabled)
    utterance_id = 0

    # Use a short initial calibration period. It prevents the fixed threshold
    # from being the only decision when the input floor differs between rooms.
    calibration_chunks = max(4, int(round(2.0 / chunk_seconds)))
    calibration_levels = []
    print(f"Calibrating {input_label} noise floor...", flush=True)
    for _ in range(calibration_chunks):
        calibration_levels.append(rms(record_chunk(base.audio, chunk_seconds)))
    measured_noise = float(np.percentile(calibration_levels, 80))
    noise_rms = min(measured_noise, threshold_rms * 0.8)
    print(
        f"READY input_source={input_source}, threshold={dbfs(threshold_rms):.1f} dBFS, "
        f"noise={dbfs(measured_noise):.1f} dBFS, chunk={chunk_seconds:.2f}s, "
        f"c_host={c_host or 'disabled'}:{c_port}",
        flush=True,
    )

    try:
        while True:
            context = sender.get_capture_context_snapshot() if sender.host is not None else None
            local_only = local_monitor_enabled and (context is None or context[0] is None)
            active_sender = local_sender if local_only else sender
            stats = sender.snapshot()
            observer.publish(communication_stats=stats, noise_dbfs=dbfs(noise_rms),
                             capture_mode="local_only" if local_only else "remote_turn")
            samples, noise_reference, capture_context = capture_utterance(
                base.audio,
                chunk_seconds,
                pre_roll_seconds,
                threshold_rms,
                trigger_chunks,
                noise_reference if "noise_reference" in locals() else noise_rms,
                input_source=input_source,
                sender=active_sender,
                monitor_remote=sender if local_monitor_enabled else None,
            )
            if samples is None:
                continue
            classify_utterance(
                samples,
                args.model,
                args.intents,
                output_path,
                utterance_id,
                noise_reference,
                active_sender,
                input_source=input_source,
                capture_context=capture_context,
            )
            utterance_id += 1
            if args.once:
                break
            observer.publish("cooldown")
            time.sleep(max(0.0, cooldown_seconds))
    except KeyboardInterrupt:
        print("STOP: standby listener interrupted", flush=True)
    finally:
        sender.close()


if __name__ == "__main__":
    main()

