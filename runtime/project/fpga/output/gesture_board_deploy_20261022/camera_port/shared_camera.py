"""Read the existing camera bridge read-only; never opens /dev/video0.

The existing ABI has no acquisition timestamp. Every timestamp here is the
monotonic time at which the reader finished observing a stable copy, never a
fabricated camera timestamp. Importing this module does not access a camera.
"""
import argparse
import ctypes
import json
import mmap
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

WIDTH, HEIGHT, STRIDE = 800, 480, 2400
HEADER_BYTES, FRAME_BYTES = 64, 800 * 480 * 3
MAP_BYTES = HEADER_BYTES + FRAME_BYTES * 3
MAGIC = 0x4d43414d
U32_MASK = 0xffffffff


class CameraError(RuntimeError):
    pass


class FrameTimeout(CameraError):
    pass


class CameraStalled(CameraError):
    pass


class CameraFileChanged(CameraError):
    pass


@dataclass
class Frame:
    bgr: np.ndarray
    metadata: dict


class AtomicCopy:
    """Native acquire/memcpy/acquire seqlock reader; no unsafe Python fallback."""
    def __init__(self, library=None):
        path = Path(library or Path(__file__).with_name('libcamera_seqlock.so'))
        if not path.is_file():
            raise CameraError('Missing seqlock helper %s; build camera_seqlock.c first' % path)
        self.library = ctypes.CDLL(str(path.resolve()))
        self.copy = self.library.mc_camera_copy
        self.copy.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                             ctypes.c_size_t, ctypes.c_uint32,
                             ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32)]
        self.copy.restype = ctypes.c_int

    def __call__(self, mapping_view, destination, previous_sequence):
        copied, current = ctypes.c_uint32(), ctypes.c_uint32()
        code = self.copy(mapping_view.ctypes.data, mapping_view.nbytes,
            destination.ctypes.data, destination.nbytes, previous_sequence,
            ctypes.byref(copied), ctypes.byref(current))
        return code, copied.value, current.value


def sequence_change(previous, current):
    """Count intervening preview publications, handling bridge's skip-zero wrap."""
    if previous is None or previous == 0:
        return 0, False
    step = (current - previous) & U32_MASK
    if step == 0:
        return 0, False
    if step >= 0x80000000:
        return None, True
    if current < previous:  # bridge skips sequence 0 at wraparound
        step -= 1
    return max(0, step - 1), False


class SharedCameraReader:
    def __init__(self, path='/run/medcomm/camera.frame', atomic_library=None,
                 poll_seconds=.002, stall_seconds=2., fresh_on_open=True,
                 _copy_backend=None):
        if poll_seconds <= 0 or stall_seconds <= 0:
            raise ValueError('poll_seconds and stall_seconds must be positive')
        self.path = Path(path)
        self.poll_seconds = float(poll_seconds)
        self.stall_seconds = float(stall_seconds)
        self.copy_backend = _copy_backend or AtomicCopy(atomic_library)
        self.fd = os.open(str(self.path), os.O_RDONLY)
        self.mapping = None
        self.view = None
        try:
            info = os.fstat(self.fd)
            if info.st_size != MAP_BYTES:
                raise CameraError('Unexpected shared-frame size %d (expected %d)' % (info.st_size, MAP_BYTES))
            self.file_identity = (info.st_dev, info.st_ino)
            self.mapping = mmap.mmap(self.fd, MAP_BYTES, access=mmap.ACCESS_READ)
            self.view = np.frombuffer(self.mapping, dtype=np.uint8)
            # Baseline suppresses an old frame left in the file before attaching.
            scratch = np.empty((HEIGHT, WIDTH, 3), np.uint8)
            code, _, baseline = self.copy_backend(self.view, scratch, 0)
            if code < 0:
                raise CameraError('Invalid camera header, helper status %d' % code)
            self.last_sequence = baseline if fresh_on_open else None
            self.progress_sequence = baseline
            self.last_progress_ns = time.monotonic_ns()
            self.last_frame_ns = None
            self.frames_read = self.copy_retries = self.source_gaps = self.sequence_resets = 0
            self.fresh_on_open = bool(fresh_on_open)
            self.closed = False
        except Exception:
            self.close()
            raise

    def _check_file(self):
        if self.fd is None:
            raise CameraError('Reader is closed')
        info = os.fstat(self.fd)
        if info.st_size != MAP_BYTES:
            raise CameraFileChanged('Shared-frame mapping size changed; close and reconnect')
        try:
            current = os.stat(str(self.path))
        except FileNotFoundError:
            raise CameraFileChanged('Shared-frame path disappeared; close and reconnect')
        if (current.st_dev, current.st_ino) != self.file_identity:
            raise CameraFileChanged('Shared-frame file was replaced; close and reconnect')

    def read(self, timeout=1.):
        """Return one new stable BGR frame, or raise a bounded timeout/stall."""
        if timeout < 0:
            raise ValueError('timeout must not be negative')
        start = time.monotonic_ns()
        deadline = start + int(timeout * 1e9)
        destination = np.empty((HEIGHT, WIDTH, 3), np.uint8)
        while True:
            self._check_file()
            copy_started_ns = time.monotonic_ns()
            code, sequence, current = self.copy_backend(self.view, destination,
                self.last_sequence if self.last_sequence is not None else 0)
            observed_ns = time.monotonic_ns()
            if code < 0:
                raise CameraError('Invalid camera header, helper status %d' % code)
            if current and current != self.progress_sequence:
                self.progress_sequence = current
                self.last_progress_ns = observed_ns
            if code == 1:
                gaps, reset = sequence_change(self.last_sequence, sequence)
                metadata = dict(source_sequence=int(sequence),
                    source_sequence_kind='shared_preview_sequence',
                    timestamp_source='observation_monotonic',
                    timestamp_ms=observed_ns / 1e6, observed_monotonic_ns=observed_ns,
                    copy_started_monotonic_ns=copy_started_ns,
                    copy_completed_monotonic_ns=observed_ns,
                    capture_timestamp_available=False,
                    previous_observation_monotonic_ns=self.last_frame_ns,
                    observed_interval_ms=(None if self.last_frame_ns is None else
                        (observed_ns - self.last_frame_ns) / 1e6),
                    skipped_preview_frames=gaps, sequence_reset=reset,
                    width=WIDTH, height=HEIGHT, stride=STRIDE, color_order='BGR',
                    camera_path=str(self.path),
                    freshness_checked_after_attach=self.fresh_on_open)
                self.last_sequence, self.last_frame_ns = sequence, observed_ns
                self.frames_read += 1
                self.source_gaps += gaps or 0
                self.sequence_resets += int(reset)
                return Frame(destination, metadata)
            if code == 2:
                self.copy_retries += 1
            stalled_for = (observed_ns - self.last_progress_ns) / 1e9
            if stalled_for >= self.stall_seconds:
                raise CameraStalled('Preview sequence did not advance for %.3f seconds' % stalled_for)
            if observed_ns >= deadline:
                raise FrameTimeout('No new stable frame within %.3f seconds' % timeout)
            time.sleep(min(self.poll_seconds, max(0., (deadline - observed_ns) / 1e9)))

    def status(self):
        return dict(frames_read=self.frames_read, copy_retries=self.copy_retries,
                    skipped_preview_frames=self.source_gaps, sequence_resets=self.sequence_resets,
                    last_sequence=self.last_sequence,
                    seconds_without_sequence_progress=(time.monotonic_ns() - self.last_progress_ns) / 1e9)

    def close(self):
        self.view = None
        if self.mapping is not None:
            self.mapping.close()
            self.mapping = None
        if getattr(self, 'fd', None) is not None:
            os.close(self.fd)
            self.fd = None
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def save_snapshot(frame, destination):
    """Write an exclusive PNG+JSON pair, preserving the observed frame metadata."""
    import cv2
    prefix = Path(destination)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    image_path, metadata_path = prefix.with_suffix('.png'), prefix.with_suffix('.json')
    if image_path.exists() or metadata_path.exists():
        raise FileExistsError('Snapshot destination already exists: ' + str(prefix))
    ok, png = cv2.imencode('.png', frame.bgr)
    if not ok:
        raise CameraError('PNG encoding failed')
    with image_path.open('xb') as stream:
        stream.write(png.tobytes())
    metadata = dict(frame.metadata, image_file=image_path.name)
    with metadata_path.open('x', encoding='utf-8') as stream:
        json.dump(metadata, stream, ensure_ascii=False, indent=2)
    return image_path, metadata_path


def record_frames(reader, directory, max_seconds=5., max_frames=120,
                  max_bytes=128 * 1024 * 1024, reserve_disk_bytes=32 * 1024 * 1024):
    """Bounded raw BGR archive with per-frame true observation times, not CFR video.

    Stores one frame at a time on disk. Slow storage may skip preview sequences;
    every detected gap is reported, never silently labelled lossless.
    """
    if max_seconds <= 0 or max_frames <= 0 or max_bytes < FRAME_BYTES:
        raise ValueError('Positive bounds must fit at least one frame')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    if shutil.disk_usage(str(directory)).free < FRAME_BYTES + reserve_disk_bytes:
        raise CameraError('Insufficient free disk space for a bounded capture')
    started = time.monotonic_ns()
    count, payload_bytes, gaps, resets = 0, 0, 0, 0
    first_ns, last_ns, stop_reason = None, None, 'duration_limit'
    error = None
    with (directory / 'frames.bgr').open('xb') as raw, (directory / 'frames.jsonl').open('x', encoding='utf-8') as index:
        try:
            while True:
                remaining = max_seconds - (time.monotonic_ns() - started) / 1e9
                if remaining <= 0:
                    stop_reason = 'duration_limit'
                    break
                if count >= max_frames:
                    stop_reason = 'frame_limit'
                    break
                if payload_bytes + FRAME_BYTES > max_bytes:
                    stop_reason = 'byte_limit'
                    break
                if shutil.disk_usage(str(directory)).free < FRAME_BYTES + reserve_disk_bytes:
                    stop_reason = 'disk_reserve_limit'
                    break
                try:
                    frame = reader.read(timeout=min(.5, remaining))
                except FrameTimeout:
                    continue
                record = dict(frame.metadata, frame_index=count, byte_offset=payload_bytes,
                              byte_length=FRAME_BYTES)
                raw.write(frame.bgr.tobytes(order='C'))
                index.write(json.dumps(record, ensure_ascii=False, separators=(',', ':')) + '\n')
                count += 1
                payload_bytes += FRAME_BYTES
                gaps += record['skipped_preview_frames'] or 0
                resets += int(record['sequence_reset'])
                if first_ns is None:
                    first_ns = record['observed_monotonic_ns']
                last_ns = record['observed_monotonic_ns']
        except KeyboardInterrupt:
            stop_reason = 'interrupted'
        except CameraError as exc:
            stop_reason, error = type(exc).__name__, str(exc)
        finally:
            raw.flush()
            index.flush()
            os.fsync(raw.fileno())
            os.fsync(index.fileno())
    summary = dict(format='raw_bgr_frames_v1', frame_file='frames.bgr', index_file='frames.jsonl',
        frames=count, payload_bytes=payload_bytes, width=WIDTH, height=HEIGHT, stride=STRIDE,
        color_order='BGR', timestamp_source='observation_monotonic', capture_timestamp_available=False,
        started_monotonic_ns=started, first_observation_ns=first_ns, last_observation_ns=last_ns,
        elapsed_seconds=(time.monotonic_ns() - started) / 1e9,
        observed_fps=(None if count < 2 or last_ns <= first_ns else
                      (count - 1) * 1e9 / (last_ns - first_ns)),
        skipped_preview_frames=gaps, sequence_resets=resets,
        contiguous_preview_sequences=bool(count and not gaps and not resets),
        sensor_frame_loss_verified=False, stop_reason=stop_reason, error=error,
        bounds=dict(max_seconds=max_seconds, max_frames=max_frames, max_bytes=max_bytes),
        reader_status=reader.status())
    with (directory / 'capture.json').open('x', encoding='utf-8') as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2)
    return summary


def replay_frames(directory):
    """Yield stored original frames and times at any inference speed; no retiming."""
    directory = Path(directory)
    with (directory / 'frames.bgr').open('rb') as raw, (directory / 'frames.jsonl').open(encoding='utf-8') as index:
        for line in index:
            metadata = json.loads(line)
            if metadata['byte_length'] != FRAME_BYTES:
                raise CameraError('Unexpected archived frame length')
            raw.seek(metadata['byte_offset'])
            data = raw.read(FRAME_BYTES)
            if len(data) != FRAME_BYTES:
                raise CameraError('Truncated raw capture at frame %s' % metadata['frame_index'])
            yield Frame(np.frombuffer(data, dtype=np.uint8).reshape(HEIGHT, WIDTH, 3).copy(), metadata)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--camera-frame', default='/run/medcomm/camera.frame')
    parser.add_argument('--atomic-library')
    parser.add_argument('--stall-seconds', type=float, default=2.)
    commands = parser.add_subparsers(dest='command')
    snapshot = commands.add_parser('snapshot')
    snapshot.add_argument('prefix')
    snapshot.add_argument('--timeout', type=float, default=3.)
    record = commands.add_parser('record')
    record.add_argument('directory')
    record.add_argument('--seconds', type=float, default=5.)
    record.add_argument('--max-frames', type=int, default=120)
    record.add_argument('--max-mib', type=float, default=128.)
    args = parser.parse_args()
    if not args.command:
        parser.error('Choose snapshot or record')
    with SharedCameraReader(args.camera_frame, args.atomic_library, stall_seconds=args.stall_seconds) as reader:
        if args.command == 'snapshot':
            frame = reader.read(args.timeout)
            paths = save_snapshot(frame, args.prefix)
            print(json.dumps(dict(frame.metadata, files=list(map(str, paths))), ensure_ascii=False))
        else:
            print(json.dumps(record_frames(reader, args.directory, args.seconds, args.max_frames,
                int(args.max_mib * 1024 * 1024)), ensure_ascii=False))


if __name__ == '__main__':
    main()
