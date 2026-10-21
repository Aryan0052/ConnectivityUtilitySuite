"""Asynchronous MongoDB writer for the Multi Device screen (Phase 4).

The scanner thread only calls ``submit(reading)``: that builds one small dict,
puts it in an in-memory buffer and returns. All database work (connect,
index creation, insert, reconnect) happens in a private background thread,
so a slow or unreachable MongoDB can never delay the Modbus bus or the UI.

* one document per reading (all channels together)
* at most one document per ``min_interval`` seconds per device
* batched ``insert_many``; failed batches stay in the buffer and are retried
* buffer is capped (``max_buffer``); when full the OLDEST records are dropped
"""
import threading
import time
from collections import deque

try:
    from .device_data import device_kind
except ImportError:
    from device_data import device_kind

COLLECTIONS = {
    "DI": "di_data",
    "DO": "do_data",
    "AI": "ai_data",
    "AO": "ao_data",
    "MFT": "mft_data",
}
DEFAULT_COLLECTION = "multi_device_data"
EXTRA_COLLECTIONS = ("alarm_events",)   # written through submit_document()


def _default_db_factory():
    """Create the project's MongoDB helper (database/mongodb.py)."""
    try:
        from database.mongodb import MongoDB
    except ImportError:
        try:
            from ..database.mongodb import MongoDB
        except ImportError:
            from mongodb import MongoDB
    return MongoDB()


def reading_to_document(reading):
    """One MongoDB document for a DeviceReading."""
    channels = {}
    for index, (name, value) in enumerate(reading.channels):
        entry = {"value": value}
        unit = reading.units[index] if index < len(reading.units) else ""
        if unit:
            entry["unit"] = unit
        channels[name] = entry
    return {
        "timestamp": reading.timestamp,
        "mode": "multi_device",
        "device_id": reading.device_id,
        "slave_id": reading.slave_id,
        "device_type": reading.device_type,
        "function": reading.function,
        "address": reading.address,
        "channels": channels,
        "quality": reading.quality,
        "raw_rx": reading.raw_response,
    }


class ReadingDatabaseWriter:
    def __init__(self, db_factory=None, min_interval=1.0, max_buffer=5000,
                 batch_size=100, flush_interval=1.0):
        self._db_factory = db_factory or _default_db_factory
        self.min_interval = float(min_interval)
        self.max_buffer = int(max_buffer)
        self.batch_size = int(batch_size)
        self.flush_interval = float(flush_interval)

        self._cond = threading.Condition()
        self._buffer = deque()          # (collection_name, document)
        self._last_saved = {}           # slave_id -> monotonic time of last accepted reading
        self._stop = False
        self._thread = None
        self._db = None
        self._connected = False
        self._saved = 0
        self._dropped = 0
        self._last_error = ""

    # ------------------------------------------------------------ public API
    def start(self):
        if self._thread is not None:
            return
        self._stop = False
        self._thread = threading.Thread(target=self._run, name="ReadingDatabaseWriter", daemon=True)
        self._thread.start()

    def stop(self, timeout=3.0):
        """Ask the thread to finish (one last flush attempt) and wait briefly."""
        with self._cond:
            self._stop = True
            self._cond.notify_all()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout)

    def submit(self, reading):
        """Reading sink for ``ModbusScanner.add_reading_sink``. Never blocks."""
        now = time.monotonic()
        with self._cond:
            last = self._last_saved.get(reading.slave_id)
            if last is not None and now - last < self.min_interval:
                return
            self._last_saved[reading.slave_id] = now
            collection = COLLECTIONS.get(device_kind(reading.device_type), DEFAULT_COLLECTION)
            self._buffer.append((collection, reading_to_document(reading)))
            while len(self._buffer) > self.max_buffer:
                self._buffer.popleft()
                self._dropped += 1
            if len(self._buffer) >= self.batch_size:
                self._cond.notify()

    def submit_document(self, collection, document):
        """Queue any document (e.g. an alarm event). Never blocks, not throttled."""
        with self._cond:
            self._buffer.append((collection, document))
            while len(self._buffer) > self.max_buffer:
                self._buffer.popleft()
                self._dropped += 1

    def status(self):
        with self._cond:
            return {
                "connected": self._connected,
                "queued": len(self._buffer),
                "saved": self._saved,
                "dropped": self._dropped,
                "last_error": self._last_error,
            }

    # ------------------------------------------------------------ worker
    def _run(self):
        backoff = 2.0
        while True:
            with self._cond:
                if not self._stop and len(self._buffer) < self.batch_size:
                    self._cond.wait(self.flush_interval)
                stopping = self._stop
                pending = bool(self._buffer)

            if stopping and not (pending and self._connected):
                break

            if not pending and not stopping:
                continue

            if self._db is None and not self._connect():
                # unreachable: wait before the next attempt, still honour stop
                with self._cond:
                    if self._stop:
                        break
                    self._cond.wait(backoff)
                backoff = min(backoff * 2, 30.0)
                continue
            backoff = 2.0

            if not self._flush_one_batch():
                self._db = None             # force reconnect on the next round
                with self._cond:
                    if self._stop:
                        break
                    self._cond.wait(2.0)
        self._close()

    def _connect(self):
        try:
            db = self._db_factory()
            for name in set(COLLECTIONS.values()) | {DEFAULT_COLLECTION} | set(EXTRA_COLLECTIONS):
                collection = db.get_collection(name)
                collection.create_index("timestamp")
                collection.create_index([("slave_id", 1), ("timestamp", -1)])
            self._db = db
            with self._cond:
                self._connected = True
                self._last_error = ""
            return True
        except Exception as exc:
            self._db = None
            with self._cond:
                self._connected = False
                self._last_error = str(exc)[:200]
            return False

    def _flush_one_batch(self):
        with self._cond:
            batch = [self._buffer.popleft()
                     for _ in range(min(self.batch_size, len(self._buffer)))]
        if not batch:
            return True
        grouped = {}
        for collection, document in batch:
            grouped.setdefault(collection, []).append(document)
        done = set()
        try:
            for collection, documents in grouped.items():
                self._db.get_collection(collection).insert_many(documents, ordered=False)
                done.add(collection)
        except Exception as exc:
            with self._cond:
                self._saved += sum(len(grouped[c]) for c in done)
                retry = [item for item in batch if item[0] not in done]
                # put the unsaved records back at the front (oldest first)
                self._buffer.extendleft(reversed(retry))
                while len(self._buffer) > self.max_buffer:
                    self._buffer.popleft()
                    self._dropped += 1
                self._connected = False
                self._last_error = str(exc)[:200]
            return False
        with self._cond:
            self._saved += len(batch)
            self._connected = True
            self._last_error = ""
        return True

    def _close(self):
        db, self._db = self._db, None
        with self._cond:
            self._connected = False
        if db is not None:
            try:
                db.close()
            except Exception:
                pass