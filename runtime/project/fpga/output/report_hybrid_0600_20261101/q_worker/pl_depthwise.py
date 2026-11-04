"""20-channel TinyPose DW adapter for the existing guarded Linux INT8 ABI."""
import os
import struct
import time
import numpy as np

INFO = 0x80304982
RUN = 0xc0a84983
JOB = struct.Struct('<40IQ')
MAGIC = 0x3849504b


def pad_channels(x, weights, params, zero):
    assert x.dtype == weights.dtype == np.int8 and params.dtype == np.int32
    assert x.ndim == 3 and x.shape[2] == 20 and weights.shape == (3, 3, 20) and params.shape == (20, 4)
    h, w, _ = x.shape
    padded = np.full((h, w, 24), zero, dtype=np.int8)
    padded[:, :, :20] = x
    kernel = np.zeros((3, 3, 24), dtype=np.int8)
    kernel[:, :, :20] = weights
    post = np.zeros((24, 4), dtype=np.int32)
    post[:20] = params
    return padded, kernel, post


class DepthwisePL:
    def __init__(self):
        import fcntl
        import mmap
        self.fd, self.pool, self.completed = None, None, 0
        self.ioctl = fcntl.ioctl
        try:
            self.fd = os.open('/dev/gesture-i8-pl0', os.O_RDWR | os.O_CLOEXEC)
            info = bytearray(48)
            self.ioctl(self.fd, INFO, info, True)
            self.info = list(struct.unpack('<12I', info))
            assert self.info[:4] == [MAGIC, 3, 16 * 1024 * 1024, 32] and self.info[8] == 15
            self.pool = mmap.mmap(self.fd, self.info[2], flags=mmap.MAP_SHARED, prot=mmap.PROT_READ | mmap.PROT_WRITE)
        except BaseException:
            self.close()
            raise

    def run(self, x, weights, params, input_zero, output_zero):
        started = time.monotonic_ns()
        padded, kernel, post = pad_channels(x, weights, params, input_zero)
        h, w, c = padded.shape
        assert max(h, w) <= 512 and h * w * c <= 2097152
        offsets = [0, padded.nbytes, padded.nbytes + kernel.nbytes,
                   padded.nbytes + kernel.nbytes + post.nbytes]
        assert offsets[3] + padded.nbytes <= self.info[2] and all(v % 8 == 0 for v in offsets)
        cfg = [MAGIC, 2, 1, 1, h, w, c, h, w, c, 3, 3, 1, 1, 1, 1,
               input_zero, output_zero, -128, 127, padded.nbytes // 8, kernel.nbytes // 8,
               padded.nbytes // 8, post.nbytes // 8] + [0] * 8
        for offset, value in zip(offsets, (padded, kernel, post)):
            self.pool[offset:offset + value.nbytes] = value.tobytes()
        job = bytearray(JOB.pack(*[v & 0xffffffff for v in offsets + cfg + [10000, 0, 0, 0]], 0))
        submitted = time.monotonic_ns()
        self.ioctl(self.fd, RUN, job, True)
        completed = time.monotonic_ns()
        actual = JOB.unpack(job)
        assert actual[37] == 0
        self.completed += 1
        # Copy the coherent DMA region once; channel slicing then reads cached RAM.
        output = np.frombuffer(self.pool[offsets[3]:offsets[3] + padded.nbytes], dtype=np.int8).reshape(padded.shape)
        assert np.all(output[:, :, 20:] == output_zero)
        result = output[:, :, :20].copy()
        del output
        return result, dict(pack_copy_ns=submitted-started, ioctl_ns=completed-submitted,
                            driver_transaction_ns=actual[40], total_ns=time.monotonic_ns()-started)

    def close(self):
        if self.pool is not None:
            self.pool.close()
            self.pool = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
