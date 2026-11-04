"""Nonfatal local diagnostics. No model/RPC/board operation depends on writes."""
from pathlib import Path
import copy, ctypes, json, os, sys, threading, time

_RETRY_DELAYS = (0.002, 0.005)
_log_lock = threading.Lock()
_last_log = {}


def _report(path, exc):
    now = time.monotonic()
    name = str(path)
    with _log_lock:
        if now - _last_log.get(name, float('-inf')) < 1:
            return
        _last_log[name] = now
    try:
        print('DIAGNOSTIC_IO_NONFATAL ' + name + ': ' + type(exc).__name__ + ': ' + str(exc), file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass


def read_json_shared(path):
    """Read a whole snapshot without denying Windows rename/delete."""
    path = Path(path)
    try:
        if os.name != 'nt':
            return json.loads(path.read_text(encoding='utf-8'))
        import msvcrt
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
        create.restype = wintypes.HANDLE
        handle = create(str(path), 0x80000000, 0x1 | 0x2 | 0x4, None, 3, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel.CloseHandle(handle)
            raise
        with os.fdopen(fd, 'r', encoding='utf-8') as stream:
            return json.load(stream)
    except (OSError, ValueError):
        return {}


def _write_bytes(path, payload):
    path = Path(path)
    temp = path.with_name(path.name + '.tmp.' + str(os.getpid()) + '.' + str(threading.get_ident()))
    try:
        temp.write_bytes(payload)
        for attempt in range(len(_RETRY_DELAYS) + 1):
            try:
                os.replace(temp, path)
                return
            except OSError:
                if attempt == len(_RETRY_DELAYS):
                    raise
                time.sleep(_RETRY_DELAYS[attempt])
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _encode(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')


def write_json_diagnostic(path, value):
    """Bounded best-effort receipts for supervisor/control diagnostics only."""
    try:
        _write_bytes(path, _encode(value))
        return True
    except (OSError, TypeError, ValueError, OverflowError) as exc:
        _report(path, exc)
        return False


class AsyncDiagnosticJSON:
    """Owner encodes complete snapshots; one bounded queue coalesces old snapshots."""
    def __init__(self, path):
        self.path = Path(path)
        self._condition = threading.Condition()
        self._pending = None
        self._closing = False
        self._stats = dict(submitted=0, written=0, superseded_snapshots=0, io_failures=0,
                           serialization_failures=0, writing=False, pending=False,
                           last_write_ok=None, last_error=None)
        self._thread = threading.Thread(target=self._run, name='diagnostic-json-writer', daemon=True)
        self._thread.start()

    def status(self):
        with self._condition:
            return dict(self._stats)

    def submit(self, value):
        try:
            # Owner-thread encoding prevents nested mutable rows racing the writer.
            payload = _encode(value)
        except (TypeError, ValueError, OverflowError) as exc:
            with self._condition:
                self._stats['serialization_failures'] += 1
                self._stats['last_error'] = type(exc).__name__ + ': ' + str(exc)
            _report(self.path, exc)
            return False
        with self._condition:
            if self._closing:
                return False
            self._stats['submitted'] += 1
            if self._pending is not None:
                self._stats['superseded_snapshots'] += 1
            self._pending = payload
            self._stats['pending'] = True
            self._condition.notify()
        return True

    def submit_deferred(self, value):
        """Detach bounded latest state now; writer encodes the coalesced snapshot later."""
        try:
            detached = copy.deepcopy(value)
        except (TypeError, ValueError, OverflowError, RecursionError) as exc:
            with self._condition:
                self._stats['serialization_failures'] += 1
                self._stats['last_error'] = type(exc).__name__ + ': ' + str(exc)
            _report(self.path, exc)
            return False
        with self._condition:
            if self._closing:
                return False
            self._stats['submitted'] += 1
            if self._pending is not None:
                self._stats['superseded_snapshots'] += 1
            self._pending = detached
            self._stats['pending'] = True
            self._condition.notify()
        return True

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._pending is not None or self._closing)
                if self._pending is None:
                    return
                payload, self._pending = self._pending, None
                self._stats.update(writing=True, pending=False)
            error = None
            error_kind = "io_failures"
            try:
                if not isinstance(payload, bytes):
                    payload = _encode(payload)
                _write_bytes(self.path, payload)
            except (TypeError, ValueError, OverflowError, RecursionError) as exc:
                error_kind = "serialization_failures"
                error = type(exc).__name__ + ": " + str(exc)
                _report(self.path, exc)
            except OSError as exc:
                error = type(exc).__name__ + ': ' + str(exc)
                _report(self.path, exc)
            with self._condition:
                self._stats['writing'] = False
                self._stats['last_write_ok'] = error is None
                if error is None:
                    self._stats['written'] += 1
                else:
                    self._stats[error_kind] += 1
                    self._stats['last_error'] = error
                self._condition.notify_all()

    def flush(self, timeout=2):
        with self._condition:
            complete = self._condition.wait_for(lambda: self._pending is None and not self._stats['writing'], timeout)
            return bool(complete and self._stats['last_write_ok'])

    def close(self, timeout=2):
        with self._condition:
            self._closing = True
            self._condition.notify_all()
        self._thread.join(timeout)
        complete = not self._thread.is_alive() and self.status()['last_write_ok'] is True
        if not complete:
            _report(self.path, OSError('final diagnostic snapshot incomplete; inspect writer counters/stderr'))
        return complete
