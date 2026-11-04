"""Create this project's fixed 4-second Log-Mel feature from a WAV on PYNQ-Z2."""

import argparse
import json
import wave
from pathlib import Path

import numpy as np


SAMPLE_RATE = 16000
FRAME = 400
HOP = 160
NFFT = 512
MELS = 40
FLOOR = 1e-10
WINDOW_SECONDS = 4
WINDOW_SAMPLES = SAMPLE_RATE * WINDOW_SECONDS
EXPECTED_SHAPE = (398, MELS)


def read_pcm16(path):
    with wave.open(str(path), "rb") as wav:
        metadata = (wav.getnchannels(), wav.getsampwidth(), wav.getframerate())
        if metadata != (1, 2, SAMPLE_RATE):
            raise ValueError(
                "Expected mono, PCM16, 16000 Hz WAV; "
                f"got channels/sample_width/sample_rate={metadata}"
            )
        if wav.getcomptype() != "NONE":
            raise ValueError("Compressed WAV is not supported")
        frames = wav.getnframes()
        raw = wav.readframes(frames)
    if len(raw) != frames * 2:
        raise ValueError("Truncated WAV data")
    pcm = np.frombuffer(raw, dtype="<i2").copy()
    return pcm.astype(np.float64) / 32768.0


def mel_filterbank():
    low = 2595.0 * np.log10(1.0 + 20.0 / 700.0)
    high = 2595.0 * np.log10(1.0 + 7600.0 / 700.0)
    points = 700.0 * (10.0 ** (np.linspace(low, high, MELS + 2) / 2595.0) - 1.0)
    freqs = np.fft.rfftfreq(NFFT, d=1.0 / SAMPLE_RATE)
    left = (freqs[None, :] - points[:-2, None]) / (points[1:-1] - points[:-2])[:, None]
    right = (points[2:, None] - freqs[None, :]) / (points[2:] - points[1:-1])[:, None]
    return np.maximum(0.0, np.minimum(left, right))


def logmel(samples):
    samples = np.asarray(samples, dtype=np.float64)
    if samples.ndim != 1 or not np.all(np.isfinite(samples)):
        raise ValueError("Expected finite mono samples")
    if samples.size < FRAME:
        raise ValueError("Input is too short to form a 25 ms frame")
    frames = np.lib.stride_tricks.sliding_window_view(samples, FRAME)[::HOP]
    window = 0.54 - 0.46 * np.cos(2.0 * np.pi * np.arange(FRAME) / (FRAME - 1))
    spectrum = np.fft.rfft(frames * window, n=NFFT, axis=1)
    power = np.abs(spectrum) ** 2 / NFFT
    return np.log(np.maximum(power @ mel_filterbank().T, FLOOR))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Mono PCM16 16 kHz WAV")
    parser.add_argument("output", type=Path, help="Output Log-Mel .npy")
    parser.add_argument("--reference-npy", type=Path, help="Optional PC golden feature for comparison")
    args = parser.parse_args()

    samples = read_pcm16(args.input)
    original_samples = int(samples.size)
    if samples.size < WINDOW_SAMPLES:
        samples = np.pad(samples, (0, WINDOW_SAMPLES - samples.size))
        window_action = "zero_padded_at_end"
    else:
        samples = samples[:WINDOW_SAMPLES]
        window_action = "kept_first_4_seconds" if original_samples > WINDOW_SAMPLES else "unchanged"

    feature = logmel(samples).astype(np.float32)
    if feature.shape != EXPECTED_SHAPE:
        raise RuntimeError(f"Expected feature shape {EXPECTED_SHAPE}, got {feature.shape}")
    if not np.isfinite(feature).all():
        raise RuntimeError("Feature contains NaN or infinity")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("wb") as handle:
        np.save(handle, feature)

    result = {
        "input_wav": str(args.input),
        "output_npy": str(args.output),
        "sample_rate_hz": SAMPLE_RATE,
        "channels": 1,
        "pcm_bits": 16,
        "input_samples": original_samples,
        "fixed_window_seconds": WINDOW_SECONDS,
        "window_action": window_action,
        "feature_shape": list(feature.shape),
        "feature_dtype": str(feature.dtype),
        "feature_min": float(feature.min()),
        "feature_max": float(feature.max()),
        "feature_mean": float(feature.mean()),
    }
    if args.reference_npy:
        reference = np.asarray(np.load(args.reference_npy), dtype=np.float32)
        if reference.shape != feature.shape:
            raise ValueError(f"Reference shape {reference.shape} does not match {feature.shape}")
        delta = np.abs(feature - reference)
        result.update({
            "reference_npy": str(args.reference_npy),
            "bitwise_equal": bool(np.array_equal(feature, reference)),
            "max_abs_diff": float(delta.max()),
            "mean_abs_diff": float(delta.mean()),
            "allclose_atol_1e-6_rtol_1e-6": bool(np.allclose(feature, reference, atol=1e-6, rtol=1e-6)),
        })

    sidecar = args.output.with_suffix(".json")
    sidecar.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
