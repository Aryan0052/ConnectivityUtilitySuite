"""COM port list without waiting.

serial.tools.list_ports.comports() asks Windows for every serial device (SetupAPI). That takes 50 - 500 ms
(more with Bluetooth / virtual COM ports), and the pages call it on the screen thread: when a page is built,
from the Refresh buttons and from the 0.5 - 1 s "is my COM port still there" timers. Each call froze the
window for that long.

install() replaces comports() with a cached version:
  - the list is read once in a background thread when the application starts;
  - a call returns the last list at once; when that list is older than MAX_AGE_S, a new one is read in a
    background thread for the next call (the 0.5 - 1 s port timers keep it fresh this way);
  - when the list is older than SYNC_AGE_S (nothing asked for a while, e.g. a Refresh click after the USB
    adapter was plugged in) the call reads it directly, so a new port is never missed;
  - the very first call waits for the start-up read if it is not done yet.
"""
import threading
import time

MAX_AGE_S = 0.8
SYNC_AGE_S = 3.0

_lock = threading.Lock()
_ports = None            # last list read
_read_at = 0.0
_busy = False
_ready = threading.Event()
_real = None


def _store(ports, busy_done=False):
    global _ports, _read_at, _busy
    with _lock:
        _ports, _read_at = ports, time.monotonic()
        if busy_done:
            _busy = False
    _ready.set()


def _read():
    try:
        ports = list(_real())
    except Exception:
        ports = _ports or []
    _store(ports, busy_done=True)


def _refresh_async():
    global _busy
    with _lock:
        if _busy:
            return
        _busy = True
    threading.Thread(target=_read, name="com-port-list", daemon=True).start()


def comports(*args, **kwargs):
    if args or kwargs:                      # unusual arguments (include_links=...): ask Windows directly
        return _real(*args, **kwargs)
    if _ports is None:
        _refresh_async()
        _ready.wait(5.0)
        return list(_ports or [])
    age = time.monotonic() - _read_at
    if age > SYNC_AGE_S and not _busy:
        try:
            ports = list(_real())
        except Exception:
            return list(_ports)
        _store(ports)
        return list(ports)
    if age > MAX_AGE_S:
        _refresh_async()
    return list(_ports)


def install():
    """Call once at start-up (before the pages are built)."""
    global _real
    try:
        from serial.tools import list_ports
    except Exception:
        return
    if _real is not None:
        return
    _real = list_ports.comports
    list_ports.comports = comports
    _refresh_async()
