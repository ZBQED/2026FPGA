#!/usr/bin/env python3
"""Prepare genuine, supplied MP4 assets for the board's JPEG sequence player.

Run on the PC with Python 3.7+ and OpenCV (cv2), for example using
LAST_PART/pc/PCRelease/.venv_gpu/Scripts/python.exe. No ffmpeg executable or
board-side video decoder is required. This tool neither downloads nor creates
sign-language content. Input names must exactly match the frozen 15-intent
catalog. Existing output assets are never overwritten.

Example: prepare_sign_videos.py --input supplied_videos --output-root sign
The JSON report lists every missing catalog asset. Exit 0 means at least one
asset was imported without errors; status=partial still means assets are
missing. Empty input exits 2; any validation/conversion error exits 1.
"""

import argparse
from contextlib import ExitStack
import json
import math
import re
import shutil
import sys
import tempfile
from pathlib import Path


DEFAULT_CATALOG = Path(__file__).resolve().parents[2] / "phase1_udp/config/voice_intents_v1.json"
WIDTH, HEIGHT = 800, 480
MAX_DURATION = 60.0
FORMAT = "medcomm-jpeg-sequence"


class VideoAssetError(ValueError):
    """The source cannot safely be published as a playable asset."""


def load_assets(catalog_path=None):
    catalog = json.loads(Path(catalog_path or DEFAULT_CATALOG).read_text(encoding="utf-8"))
    assets = {}
    for entry in catalog["intents"]:
        if entry.get("type") != "业务":
            continue
        match = re.fullmatch(r"播放 (staff_[a-z0-9_]+\.mp4)", entry.get("system_action", ""))
        if not match or match.group(1) in assets:
            raise VideoAssetError("The frozen catalog contains an invalid/duplicate asset name")
        assets[match.group(1)] = {"intent_id": entry["intent_id"], "code": entry["code"],
                                 "meaning": entry["meaning"]}
    if len(assets) != 15 or catalog.get("counts", {}).get("business_categories") != 15:
        raise VideoAssetError("Expected exactly 15 frozen business video assets")
    return assets


def _opencv():
    try:
        import cv2
    except ImportError as exc:
        raise VideoAssetError("OpenCV (cv2) is required; use the project's .venv_gpu Python") from exc
    return cv2


def _validate_settings(fps, quality):
    if isinstance(fps, bool) or not math.isfinite(fps) or not 0 < fps <= 30:
        raise VideoAssetError("Target fps must be finite and in (0, 30]")
    if isinstance(quality, bool) or not isinstance(quality, int) or not 1 <= quality <= 100:
        raise VideoAssetError("JPEG quality must be an integer from 1 to 100")


def _letterbox(cv2, frame):
    import numpy as np
    if frame is None or len(frame.shape) != 3 or frame.shape[2] != 3:
        raise VideoAssetError("Decoder did not produce a three-channel image")
    height, width = frame.shape[:2]
    if height <= 0 or width <= 0:
        raise VideoAssetError("Invalid decoded frame size")
    scale = min(WIDTH / float(width), HEIGHT / float(height))
    resized_width = max(1, min(WIDTH, round(width * scale)))
    resized_height = max(1, min(HEIGHT, round(height * scale)))
    resized = cv2.resize(frame, (resized_width, resized_height),
                         interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
    canvas = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    left, top = (WIDTH - resized_width) // 2, (HEIGHT - resized_height) // 2
    canvas[top:top + resized_height, left:left + resized_width] = resized
    return canvas


def _remove_own_stage(stage, output_root):
    # Only this invocation's mkdtemp directory may be recursively removed.
    if stage.parent.resolve() != output_root.resolve() or not stage.name.startswith(".stage-"):
        raise RuntimeError("Refusing to remove a directory outside the output staging area")
    shutil.rmtree(str(stage))


def _convert_sequence(source, output_root, asset_stem, fps=15.0, quality=85):
    """Internal decoder, also used by explicitly marked non-sign playback tests.

    Production callers must use convert_video(), which validates catalog names.
    Decode every source frame even when sampling fewer frames: early decoder
    failure, unknown frame counts, and clips longer than 60 seconds are rejected
    instead of silently publishing a shortened clip.
    """
    _validate_settings(fps, quality)
    if not re.fullmatch(r"[a-z0-9_]+", asset_stem):
        raise VideoAssetError("Asset directory must be a simple lowercase ASCII name")
    source, output_root = Path(source), Path(output_root)
    if not source.is_file() or source.suffix.lower() != ".mp4":
        raise VideoAssetError("Input must be an existing MP4 file")
    destination = output_root / asset_stem
    if destination.exists():
        raise VideoAssetError("Output already exists; choose a new output root: {}".format(destination))
    cv2 = _opencv()
    output_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".stage-{}-".format(asset_stem), dir=str(output_root)))
    capture = None
    try:
        # A Python copy into an ASCII temporary path avoids OpenCV/FFmpeg builds
        # that cannot open Chinese/other Unicode Windows input paths. Source is
        # untouched and decoder work never changes the published asset tree.
        with ExitStack() as decoder_stack:
            decode_dir = decoder_stack.enter_context(tempfile.TemporaryDirectory(prefix="medcomm-video-"))
            decoder_path = Path(decode_dir) / "source.mp4"
            shutil.copyfile(str(source), str(decoder_path))
            capture = cv2.VideoCapture(str(decoder_path))
            # Release Windows' file handle before TemporaryDirectory cleanup,
            # including on validation/encoding errors.
            decoder_stack.callback(capture.release)
            if not capture.isOpened():
                raise VideoAssetError("Cannot open/decode MP4: {}".format(source))
            source_fps = float(capture.get(cv2.CAP_PROP_FPS))
            reported_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            if not math.isfinite(source_fps) or source_fps <= 0:
                raise VideoAssetError("Source has no usable frame rate")
            if (not math.isfinite(reported_count) or reported_count < 1
                    or abs(reported_count - round(reported_count)) > 0.01):
                raise VideoAssetError("Source has no reliable frame count; duration cannot be verified")
            expected_count = int(round(reported_count))
            source_duration = expected_count / source_fps
            if source_duration > MAX_DURATION + 1e-6:
                raise VideoAssetError("Source exceeds the 60-second limit ({:.3f}s); not truncated".format(source_duration))
            output_fps = min(float(fps), source_fps)
            # At most one output-frame interval is lost to time quantization.
            # Floor avoids extending a near-60-second source beyond the limit.
            target_count = max(1, int(math.floor(source_duration * output_fps + 1e-6)))
            if target_count / output_fps > MAX_DURATION + 1e-6:
                raise VideoAssetError("Requested frame rate would make playback exceed 60 seconds")
            decoded = 0
            frames = []
            last_timestamp = -1.0
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                if frame is None or frame.size == 0:
                    raise VideoAssetError("Decoder returned an empty frame")
                timestamp = float(capture.get(cv2.CAP_PROP_POS_MSEC)) / 1000.0
                if math.isfinite(timestamp) and timestamp > 0:
                    if timestamp > MAX_DURATION + 1e-6:
                        raise VideoAssetError("Decoded timestamps exceed 60 seconds; not truncated")
                    if last_timestamp >= 0 and timestamp < last_timestamp - 1e-3:
                        raise VideoAssetError("Non-monotonic source timestamps are unsupported")
                    # This format has a single constant frame rate. Reject
                    # variable-rate sources rather than silently changing timing.
                    if abs(timestamp - decoded / source_fps) > max(0.05, 1.1 / source_fps):
                        raise VideoAssetError("Variable/inconsistent frame timing is unsupported")
                    last_timestamp = timestamp
                if (len(frames) < target_count
                        and decoded + 1e-6 >= len(frames) * source_fps / output_fps):
                    filename = "frame_{:06d}.jpg".format(len(frames))
                    canvas = _letterbox(cv2, frame)
                    encoded_ok, encoded = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, quality])
                    if not encoded_ok:
                        raise VideoAssetError("JPEG encoding failed")
                    (stage / filename).write_bytes(encoded.tobytes())
                    frames.append(filename)
                decoded += 1
                if decoded > expected_count or decoded / source_fps > MAX_DURATION + 1e-6:
                    raise VideoAssetError("Decoded length disagrees with source duration; not truncated")
            capture.release()
            capture = None
            if decoded != expected_count:
                raise VideoAssetError("Incomplete decode: {} of {} frames; nothing published".format(decoded, expected_count))
            if not frames or len(frames) != target_count:
                raise VideoAssetError("Source produced an incomplete/empty JPEG sequence")
            manifest = {"format": FORMAT, "version": 1, "width": WIDTH, "height": HEIGHT,
                        "fps": float(output_fps), "frame_count": len(frames), "frames": frames}
            (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if destination.exists():
            raise VideoAssetError("Output appeared during conversion; refusing to overwrite: {}".format(destination))
        stage.rename(destination)
        return {"asset": source.name, "directory": str(destination), "source_fps": source_fps,
                "source_frames": decoded, "duration_seconds": source_duration,
                "fps": output_fps, "frame_count": len(frames)}
    except cv2.error as exc:
        raise VideoAssetError("OpenCV decoding/encoding failed: {}".format(exc)) from exc
    finally:
        if capture is not None:
            capture.release()
        if stage.exists():
            _remove_own_stage(stage, output_root)


def convert_video(source, output_root, fps=15.0, quality=85):
    source = Path(source)
    if source.name not in load_assets():
        raise VideoAssetError("Unknown asset filename (exact frozen name required): {}".format(source.name))
    return _convert_sequence(source, output_root, source.stem, fps, quality)


def prepare_assets(input_path, output_root, fps=15.0, quality=85):
    """Import supplied assets and return a full 15-intent availability report."""
    _validate_settings(fps, quality)
    assets = load_assets()
    input_path, output_root = Path(input_path), Path(output_root)
    report = {"status": "empty", "expected_asset_count": 15, "converted": [],
              "missing": [], "errors": [], "input": str(input_path), "output_root": str(output_root)}
    if input_path.is_file():
        candidates = [input_path]
    elif input_path.is_dir():
        candidates = sorted(p for p in input_path.rglob("*") if p.is_file() and p.suffix.lower() == ".mp4")
    else:
        candidates = []
        report["errors"].append({"asset": str(input_path), "error": "Input path does not exist"})
    by_name = {}
    for source in candidates:
        if source.name not in assets:
            report["errors"].append({"asset": str(source), "error": "Unknown asset filename; exact frozen name required"})
        else:
            by_name.setdefault(source.name, []).append(source)
    for name, sources in by_name.items():
        if len(sources) != 1:
            report["errors"].append({"asset": name, "error": "Duplicate source asset names; choose one explicitly"})
            continue
        try:
            report["converted"].append(convert_video(sources[0], output_root, fps, quality))
        except (VideoAssetError, OSError) as exc:
            report["errors"].append({"asset": name, "error": str(exc)})
    # This report only claims what this invocation fully decoded/published. An
    # existing folder is not silently accepted as a verified, supplied video.
    converted = {entry["asset"] for entry in report["converted"]}
    report["missing"] = [dict(asset=name, **metadata) for name, metadata in assets.items() if name not in converted]
    report["converted_count"] = len(converted)
    report["missing_count"] = len(report["missing"])
    if report["errors"]:
        report["status"] = "failed" if not converted else "partial_with_errors"
    elif len(converted) == 15:
        report["status"] = "complete"
    elif converted:
        report["status"] = "partial"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, type=Path, help="An exact catalog-named MP4 or a directory of MP4 files")
    parser.add_argument("--output-root", required=True, type=Path, help="Destination containing asset-stem directories")
    parser.add_argument("--fps", type=float, default=15.0, help="Target frame rate in (0,30]; never upsamples (default: 15)")
    parser.add_argument("--quality", type=int, default=85, help="JPEG quality 1..100 (default: 85)")
    args = parser.parse_args(argv)
    try:
        report = prepare_assets(args.input, args.output_root, args.fps, args.quality)
    except (VideoAssetError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["errors"]:
        return 1
    return 0 if report["converted"] else 2


if __name__ == "__main__":
    sys.exit(main())
