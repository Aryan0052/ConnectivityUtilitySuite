"""Central Modbus RTU scanner for the shared RS-485 bus.

One background thread owns the pymodbus client and runs exactly ONE
transaction at a time. Polls, retries and recoveries are all picked from
the same earliest-due-first queue, so healthy devices are never blocked by
a retrying/offline device and no job type can starve another.

Polling order (two modes, `cycle_polling`):
    cycle   (default) every cycle polls each ready device exactly ONCE in Slave-ID order, so all devices
            are read at the same rate. A new cycle starts every `cycle_ms` (auto = the longest Poll Rate
            of the polled devices); when a cycle takes longer, the next one starts right after it.
    per-device  each device keeps its own Poll Rate (earliest-due, round robin on ties).

Timing per device:
    timeout      max RX wait for one attempt (inside _perform_device_request)
    polling      Poll Rate: TX start -> next normal TX start (ONLINE devices)
    max_retries  extra attempts after a failed attempt (total = 1 + N)
    scan_rate    OFFLINE recovery interval: failed attempt end -> recovery TX

The GUI thread talks to the scanner only through the thread-safe methods
below and receives everything through the single `event` signal (queued).

Modbus TCP devices: all TCP-only logic (connections, MBAP frames, transaction ids, late / split replies,
gaps for TCP -> RTU gateways) lives in modbus_tcp.py (TcpScannerMixin); this file keeps the RTU logic
and the shared scheduling / device state machine.
"""
import threading
import time
from datetime import datetime
from types import SimpleNamespace

from PySide6.QtCore import QThread, Signal

try:
    from .device_data import process_response, AI_INPUT_TYPES, AI_CONFIG_READ, ai_unit, read_chunk
    from .modbus_tcp import TcpScannerMixin
except ImportError:
    from device_data import process_response, AI_INPUT_TYPES, AI_CONFIG_READ, ai_unit, read_chunk
    from modbus_tcp import TcpScannerMixin

PAGE_GAP_S = 0.025     # pause between the pages of one paged read (ModbusTestPanel INTER_CHUNK_GAP_MS)

ONLINE = "ONLINE"
RETRYING = "RETRYING"
OFFLINE = "OFFLINE"
DISABLED = "DISABLED"
NOT_POLLED = "NOT_POLLED"

# An OFFLINE device is probed at most once per MIN_RECOVERY_MS, so a failing slave with a
# tiny Scan Rate cannot keep occupying the shared bus and delaying the healthy ones.
MIN_RECOVERY_MS = 1000
# Modbus RTU needs a silent gap (3.5 characters) between two frames. Some slaves lose a request
# that follows the previous reply too quickly, so every transaction waits until the bus has been
# idle for at least this long (more at low baud rates).
WRITE_SETTLE_MS = 50      # quiet time after a write before polling resumes (outputs switch)
MIN_BUS_IDLE_MS = 20      # silent time on the bus before every request (slow slaves need >5 ms to be ready)

JOB_RETRY = "retry"
JOB_POLL = "poll"
JOB_RECOVERY = "recovery"
# Tie-break order when several jobs share the same due time.
_JOB_PRIORITY = {JOB_RETRY: 0, JOB_POLL: 1, JOB_RECOVERY: 2}

_CONFIG_KEYS = (
    "name", "type", "kind", "slave_id", "function", "address", "count",
    "polling", "scan_rate", "timeout", "max_retries", "data_format", "word_order",
    "host", "tcp_port", "unit",          # Modbus TCP device: its own IP / port / unit id (no host = serial bus)
)
_FUNCTION_METHODS = {
    1: "read_coils",
    2: "read_discrete_inputs",
    3: "read_holding_registers",
    4: "read_input_registers",
}


# --------------------------------------------------------------------------------------------------
# Debug prints (VS Code terminal / console): poll results and decode failures (the TCP bytes are printed by
# modbus_tcp.py). Turn off with DEBUG_PRINTS = False, or set the
# environment variable NELUMBO_MODBUS_DEBUG=0. The windowed exe has no console, so it prints nowhere.
# --------------------------------------------------------------------------------------------------
import os as _os
DEBUG_PRINTS = _os.environ.get("NELUMBO_MODBUS_DEBUG", "1") != "0"


def _dbg(*parts):
    if DEBUG_PRINTS:
        now = datetime.now()
        print(f"[{now:%H:%M:%S}.{now.microsecond // 1000:03d}] [modbus]", *parts, flush=True)


# --------------------------------------------------------------------------------------------------
# Modbus exception text (RTU; the TCP side has its own copy in modbus_tcp.py)
# --------------------------------------------------------------------------------------------------
_EXCEPTION_NAMES = {1: "illegal function", 2: "illegal data address", 3: "illegal data value",
                    4: "slave device failure", 5: "acknowledge", 6: "slave device busy",
                    10: "gateway path unavailable", 11: "gateway target device failed to respond"}


def _exception_text(response):
    """'Modbus exception response (code 0x0B: gateway target device failed to respond)'."""
    code = getattr(response, "exception_code", None)
    if code is None:
        return "Modbus exception response"
    return f"Modbus exception response (code 0x{int(code):02X}: {_EXCEPTION_NAMES.get(int(code), 'unknown')})"




class ModbusScanner(TcpScannerMixin, QThread):
    """Event dicts emitted (all carry "time" = datetime of the event):
        tx     slave_id, function, kind, frame
        rx     slave_id, function, kind, frame, elapsed_ms
        fail   slave_id, function, kind, reason(timeout|exception|error), detail, elapsed_ms
        state  slave_id, status, retry_count, next_poll, next_retry, next_recovery, last_response
        log    text
        reading  slave_id, reading (DeviceReading)
    """

    event = Signal(object)

    def __init__(self, client, parent=None):
        super().__init__(parent)
        self._serial_connection = client
        self._cond = threading.Condition()
        self._devices = {}
        self._stop_requested = False
        # Future database phase: callables receiving each DeviceReading in
        # this thread. They must be non-blocking (e.g. queue.put_nowait).
        self._reading_sinks = []
        # AI input types (for units): slave_id -> [type name per channel]; read once
        # per AI device after its first good poll and again after it recovers.
        self._ip_types = {}
        self._ip_tries = {}
        # Manual writes from the UI: executed on the bus between polls.
        self._writes = []
        self._last_bus_end = 0.0
        self.cycle_polling = True        # one poll per device per cycle (see module doc)
        self.cycle_ms = 0                # 0 = auto: longest Poll Rate among the polled devices
        self._cycle_pending = []         # slave ids still to poll in the running cycle
        self._cycle_next = 0.0           # monotonic time the next cycle may start
        self.transport = "rtu"           # "rtu" (serial, CRC frames) or "tcp" (Modbus TCP, MBAP frames)
        self._frame_tcp = False          # frame style of the transaction in progress (MBAP or RTU+CRC)
        self._tcp_init_state()           # TCP connections, transaction ids, late-reply handling (modbus_tcp.py)

    # ------------------------------------------------------------------ #
    # Thread-safe control API (called from the GUI thread)
    # ------------------------------------------------------------------ #
    def add_device(self, device):
        with self._cond:
            entry = {key: device.get(key) for key in _CONFIG_KEYS}
            entry.update(enabled=False, status=NOT_POLLED, retry_count=0,
                         next_poll=None, next_retry=None, next_recovery=None,
                         last_response=device.get("last_response", "--"), generation=0)
            self._devices[entry["slave_id"]] = entry
            if device.get("enabled", False):
                self._enable(entry)
            self._cond.notify()

    def remove_device(self, slave_id):
        with self._cond:
            self._devices.pop(slave_id, None)
            self._cond.notify()

    def set_enabled(self, slave_id, enabled):
        with self._cond:
            entry = self._devices.get(slave_id)
            if entry is None:
                return
            if enabled:
                self._enable(entry)
            else:
                entry["generation"] += 1
                entry.update(enabled=False, status=DISABLED, retry_count=0,
                             next_poll=None, next_retry=None, next_recovery=None)
            self._cond.notify()

    def update_device(self, old_slave_id, device):
        """Apply edited settings to a configured device without removing it.
        Poll/scan/timeout/retries take effect on the next cycle; a changed
        slave id or register map restarts the device's polling cleanly."""
        with self._cond:
            entry = self._devices.get(old_slave_id)
            if entry is None:
                return
            new_id = device["slave_id"]
            restart = any(entry.get(k) != device.get(k) for k in ("slave_id", "function", "address", "count", "kind",
                                                                  "host", "tcp_port", "unit"))
            if new_id != old_slave_id:
                self._devices.pop(old_slave_id, None)
                self._devices[new_id] = entry
                self._ip_types.pop(old_slave_id, None)
                self._ip_tries.pop(old_slave_id, None)
            for key in _CONFIG_KEYS:
                entry[key] = device.get(key)
            if restart:
                entry["generation"] += 1
                self._ip_types.pop(new_id, None)
                self._ip_tries.pop(new_id, None)
                if entry["enabled"]:
                    entry.update(status=NOT_POLLED, retry_count=0, next_poll=time.monotonic(),
                                 next_retry=None, next_recovery=None)
            elif entry["enabled"] and entry["status"] == ONLINE and entry["next_poll"] is not None:
                # Poll rate change: never sooner than one new interval after the last poll.
                last = entry.get("last_poll_tx") or time.monotonic()
                entry["next_poll"] = last + max(1, int(entry["polling"])) / 1000.0
            self._cond.notify()

    def set_cycle_polling(self, enabled, cycle_ms=0):
        """Switch between one-poll-per-device cycles and independent per-device Poll Rates."""
        with self._cond:
            self.cycle_polling = bool(enabled)
            self.cycle_ms = max(0, int(cycle_ms or 0))
            self._cycle_pending = []
            self._cycle_next = 0.0
            self._cond.notify()

    def poll_now(self, slave_id):
        """Kept for compatibility. The Poll Interval is a minimum: a device is
        never polled sooner than its interval, so nothing is brought forward."""
        return

    def request_write(self, request):
        """Queue a manual write: dict(slave_id, function 5/6/15/16, address,
        values (bools or ints), timeout ms). Runs on the bus between polls."""
        with self._cond:
            self._writes.append(dict(request))
            self._cond.notify()

    def add_reading_sink(self, sink):
        with self._cond:
            self._reading_sinks.append(sink)

    def request_stop(self):
        with self._cond:
            self._stop_requested = True
            self._cond.notify()

    def _enable(self, entry):
        if entry["enabled"]:
            return
        entry["generation"] += 1
        self._ip_types.pop(entry["slave_id"], None)
        self._ip_tries.pop(entry["slave_id"], None)
        entry.update(enabled=True, status=NOT_POLLED, retry_count=0,
                     next_poll=time.monotonic(), next_retry=None, next_recovery=None)
        self._cycle_next = 0.0            # cycle mode: begin a cycle at once so the new device joins

    # ------------------------------------------------------------------ #
    # Scheduler loop (scanner thread)
    # ------------------------------------------------------------------ #
    def run(self):
        try:
            while True:
                write = None
                with self._cond:
                    job = None
                    while not self._stop_requested:
                        if self._writes:
                            write = self._writes.pop(0)
                            break
                        job, wake_at = self._pick_job(time.monotonic())
                        if job is not None:
                            break
                        wait = None if wake_at is None else max(0.0, wake_at - time.monotonic())
                        self._cond.wait(wait)
                    if self._stop_requested:
                        break
                if write is not None:
                    try:
                        self._write_session(write)
                    except Exception as exc:          # never let one bad write stop the scanner
                        self._emit("log", text=f"Scanner error during write: {exc!r}")
                        time.sleep(0.05)
                    continue
                with self._cond:
                    entry, kind = job
                    self._last_served = entry["slave_id"]
                    entry["next_" + kind] = None  # consume the due time
                    config = {key: entry[key] for key in _CONFIG_KEYS}
                    generation = entry["generation"]
                try:
                    self._execute(config, kind, generation)
                except Exception as exc:
                    # An unexpected error must not silently stop this device: report it and
                    # schedule it again, otherwise it would never be polled any more.
                    self._emit("log", text=f"Scanner error (Slave {config['slave_id']}): {exc!r}")
                    with self._cond:
                        if entry.get("generation") == generation and entry.get("enabled"):
                            entry["next_" + kind] = time.monotonic() + max(0.5, int(entry.get("polling") or 1000) / 1000.0)
                    time.sleep(0.05)
        finally:
            try:
                if self._serial_connection is not None:
                    self._serial_connection.close()
            except Exception:
                pass
            self._tcp_close_all()                # modbus_tcp.py

    # ---- per-device Modbus TCP connections ------------------------------------------------
    @staticmethod
    def _unit(cfg):
        """Unit id on the wire: the serial slave id, or the TCP device's unit id (default 1)."""
        if cfg.get("host"):
            return int(cfg.get("unit") or 1)
        return int(cfg["slave_id"])

    def _client_for(self, cfg):
        """The client that talks to this device: its own TCP connection (modbus_tcp.py), or the serial bus."""
        self._frame_tcp = bool(cfg.get("host"))
        if cfg.get("host") or self.transport == "tcp":
            return self._tcp_client_for(cfg)
        return self._serial_connection

    # TCP reads / transaction ids / late replies / retries: TcpScannerMixin in modbus_tcp.py

    def _pick_job(self, now):
        """Next job among enabled devices whose time has come; also the next wake time.
        Retries go first. Otherwise devices are served in Slave-ID order, round robin
        (1, 2, 3, 4, 1, 2 ...): the next due device after the one served last. A device
        whose Poll Interval has not passed yet is skipped for that round, never polled early."""
        if self.cycle_polling:
            return self._pick_job_cycle(now)
        best = None
        best_key = None
        wake_at = None
        last = getattr(self, "_last_served", 0)
        for entry in self._devices.values():
            if not entry["enabled"]:
                continue
            status = entry["status"]
            if status == RETRYING:
                kind = JOB_RETRY
            elif status == OFFLINE:
                kind = JOB_RECOVERY
            else:
                kind = JOB_POLL
            due = entry["next_" + kind]
            if due is None:
                continue
            if due > now:
                wake_at = due if wake_at is None else min(wake_at, due)
                continue
            sid = entry["slave_id"]
            if kind == JOB_RETRY:
                key = (0, due, 0)
            else:
                key = (1, (sid - last - 1) % 256, due)   # next slave after the last one served
            if best_key is None or key < best_key:
                best, best_key = (entry, kind), key
        return best, wake_at

    def _pick_job_cycle(self, now):
        """Cycle mode: strict Slave-ID order, one turn per device, nothing in between.
        A device's own retries run in its turn (before the next device). An OFFLINE device whose recovery
        time has come takes its turn at its Slave-ID position, so no probe ever lands between two other
        devices' polls and no job type starves another."""
        for entry in self._devices.values():                      # retries belong to the device just polled
            if entry["enabled"] and entry["status"] == RETRYING and entry["next_retry"] is not None \
                    and entry["next_retry"] <= now:
                return (entry, JOB_RETRY), None

        def turn(entry):
            """Job kind this device wants in a cycle (None = skip this cycle)."""
            if not entry["enabled"]:
                return None
            if entry["status"] in (ONLINE, NOT_POLLED):
                return JOB_POLL
            if entry["status"] == OFFLINE and entry["next_recovery"] is not None and entry["next_recovery"] <= now:
                return JOB_RECOVERY
            return None

        for _ in range(2):
            while self._cycle_pending:
                entry = self._devices.get(self._cycle_pending.pop(0))
                kind = turn(entry) if entry is not None else None
                if kind is not None:
                    return (entry, kind), None
            if now < self._cycle_next:
                break
            ready = sorted((e for e in self._devices.values() if turn(e)), key=lambda e: e["slave_id"])
            if not ready:
                break
            polled = [e for e in ready if turn(e) == JOB_POLL] or ready
            period = self.cycle_ms / 1000.0 if self.cycle_ms else \
                max(max(1, int(e["polling"])) for e in polled) / 1000.0
            start = self._cycle_next if (self._cycle_next and now - self._cycle_next < period) else now
            self._cycle_next = start + period
            self._cycle_pending = [e["slave_id"] for e in ready]

        wake_at = None
        for entry in self._devices.values():
            if not entry["enabled"]:
                continue
            if entry["status"] in (ONLINE, NOT_POLLED):
                due = self._cycle_next
            elif entry["status"] == OFFLINE and entry["next_recovery"] is not None:
                due = max(entry["next_recovery"], self._cycle_next if self._cycle_next > now else 0.0)
            else:
                continue
            wake_at = due if wake_at is None else min(wake_at, due)
        return None, wake_at

    def _bus_idle_wait(self):
        """Wait until the line has been silent for the inter-frame gap."""
        if self.transport == "tcp" or self._frame_tcp:
            self._tcp_gap_wait()                 # modbus_tcp.py
            return
        gap = MIN_BUS_IDLE_MS / 1000.0
        try:
            baud = int(getattr(getattr(self._serial_connection, "comm_params", None), "baudrate", 0) or 0)
            if baud:
                gap = max(gap, min(0.030, 3.5 * 11.0 / baud))
        except Exception:
            pass
        remaining = self._last_bus_end + gap - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)

    def _execute(self, config, kind, generation):
        self._bus_idle_wait()
        slave_id = config["slave_id"]
        unit = self._unit(config)
        self._frame_tcp = bool(config.get("host"))
        self._tcp_new_request()
        function = int(config["function"])
        address = int(config.get("address") or 0)
        count = int(config.get("count") or 1)
        method = _FUNCTION_METHODS.get(function, "read_holding_registers")
        chunk = read_chunk(config)
        paged = function in (3, 4) and chunk > 0 and count > chunk      # MFT: several 20-register reads

        tx_start = time.monotonic()
        self._settle_spent = 0.0
        perf_start = time.perf_counter()
        response, reason, detail, port_lost = None, None, "", False
        rx_hex = ""
        if paged:
            response, rx_hex, reason, detail, port_lost = self._read_paged(
                config, method, slave_id, function, address, count, chunk, kind)
        else:
            tx_frame = self._build_read_frame(unit, function, address, count)
            self._emit("tx", slave_id=slave_id, function=function, kind=kind, frame=self._hex(tx_frame))
            try:
                response = self._perform_device_request(config, method, address, count)
            except Exception as exc:
                reason, port_lost = self._classify_error(exc)
                detail = str(exc)
        elapsed = int((time.perf_counter() - perf_start - self._settle_spent) * 1000)
        end = time.monotonic()
        _dbg(f"POLL slave={slave_id} kind={kind} fc={function} addr={address} count={count}: "
             f"{'OK' if reason is None else reason.upper()} {elapsed} ms{'' if reason is None else ' - ' + detail[:160]}")

        if reason is None:
            if not paged:
                rx_hex = self._hex(self._build_response_frame(unit, response))
            try:
                reading = process_response(config, response, rx_hex, datetime.now())
            except Exception as exc:
                reason, detail = "error", f"Invalid response data: {exc}"
                _dbg(f"DECODE FAILED slave={slave_id}: {exc} | RX [{rx_hex}]")
                if self._is_tcp_request(config):
                    detail += f" - RX [{rx_hex}]"
                    self._tcp_after_failure(config, detail)
            if reason is None and config.get("kind") == "AI":
                names = self._ip_types.get(slave_id)
                if names:
                    reading.units = [ai_unit(name) for name in names]
        if reason is None:
            self._emit("rx", slave_id=slave_id, function=function, kind=kind,
                       frame=rx_hex, elapsed_ms=elapsed)
            if kind == JOB_RECOVERY and not self._is_tcp_request(config):
                self._ip_types.pop(slave_id, None)   # module may have been reconfigured
                self._ip_tries.pop(slave_id, None)
            self._emit("reading", slave_id=slave_id, reading=reading)
            for sink in list(self._reading_sinks):
                try:
                    sink(reading)
                except Exception:
                    pass
            # AI input types (units only). Over a TCP gateway this extra FC03 request right after the FC04
            # poll is what collides with a late reply, so it is tried once per session there, not 3 x per recovery.
            tries = 0 if self._is_tcp_request(config) else 3   # TCP: only the selected function code goes on the wire
            if config.get("kind") == "AI" and slave_id not in self._ip_types and self._ip_tries.get(slave_id, 0) < tries:
                self._read_ip_types(config)
        else:
            if reason == "timeout" and "received instead" in detail:
                self._emit("log", text=f"Slave {slave_id}: {detail}")
            self._emit("fail", slave_id=slave_id, function=function, kind=kind,
                       reason=reason, detail=detail, elapsed_ms=elapsed)
            if port_lost:
                # The COM port itself is gone (e.g. USB-RS485 adapter unplugged).
                # Retrying cannot help: stop the scanner and let the UI disconnect.
                with self._cond:
                    self._stop_requested = True
                    self._cond.notify_all()
                self._emit("port_lost", detail=detail)
                return

        with self._cond:
            entry = self._devices.get(slave_id)
            # Device removed or stopped/restarted meanwhile: result is logged
            # (tx/rx/fail above) but must not change its new state.
            if entry is None or entry["generation"] != generation or not entry["enabled"]:
                return
            logs = self._apply_result(entry, kind, reason, elapsed, tx_start, end)
            state = {key: entry[key] for key in (
                "status", "retry_count", "next_poll", "next_retry", "next_recovery", "last_response")}
        for text in logs:
            self._emit("log", text=text)
        self._emit("state", slave_id=slave_id, **state)

    def _classify_error(self, exc):
        """(reason, port_lost) for an exception raised by one Modbus transaction."""
        text = str(exc)
        if isinstance(exc, TimeoutError) or "No response received" in text or "timeout" in text.lower():
            return "timeout", False
        if text.startswith("Modbus exception response"):
            return "exception", False
        return "error", self._is_port_lost(exc, text)

    def _read_paged(self, config, method, slave_id, function, address, count, chunk, kind):
        """Read `count` registers as several requests of `chunk` registers (the same TX / RX frames on the
        bus as any other read, just shorter) and join them in address order. To the rest of the program the
        whole thing is ONE poll: one TX event listing every page request, one RX event listing every page
        reply (events are emitted by _execute). The whole poll fails if any page fails.
        Returns (response-like with .registers, rx text, reason, detail, port_lost)."""
        unit = self._unit(config)
        pages, offset = [], 0
        while offset < count:
            page = min(chunk, count - offset)
            pages.append((address + offset, page))
            offset += page
        tx_text = " | ".join(self._hex(self._build_read_frame(unit, function, a, n)) for a, n in pages)
        self._emit("tx", slave_id=slave_id, function=function, kind=kind, frame=tx_text)
        registers, frames = [], []
        for index, (page_address, page) in enumerate(pages):
            try:
                response = self._perform_device_request(config, method, page_address, page)
            except Exception as exc:
                reason, port_lost = self._classify_error(exc)
                return None, "", reason, f"{exc} (registers {page_address}-{page_address + page - 1})", port_lost
            got = [int(reg) for reg in list(getattr(response, "registers", None) or [])]
            if len(got) < page:
                return None, "", "error", (f"Invalid response data: expected {page} registers at "
                                           f"{page_address}, received {len(got)}"), False
            frames.append(self._hex(self._build_response_frame(unit, response)))
            registers.extend(got[:page])
            if index < len(pages) - 1:
                time.sleep(PAGE_GAP_S)
        return SimpleNamespace(registers=registers), " | ".join(frames), None, "", False

    # ------------------------------------------------------------------ #
    # Manual writes (FC05 / FC06 / FC15 / FC16)
    # ------------------------------------------------------------------ #
    def _build_write_frame(self, slave_id, function, address, values):
        head = bytes([slave_id & 0xFF, function & 0xFF, (address >> 8) & 0xFF, address & 0xFF])
        if function == 5:
            body = bytes([0xFF if values[0] else 0x00, 0x00])
        elif function == 6:
            body = bytes([(values[0] >> 8) & 0xFF, values[0] & 0xFF])
        elif function == 15:
            data = bytearray((len(values) + 7) // 8)
            for index, bit in enumerate(values):
                if bit:
                    data[index // 8] |= 1 << (index % 8)
            body = bytes([(len(values) >> 8) & 0xFF, len(values) & 0xFF, len(data)]) + bytes(data)
        else:
            data = b"".join(bytes([(v >> 8) & 0xFF, v & 0xFF]) for v in values)
            body = bytes([(len(values) >> 8) & 0xFF, len(values) & 0xFF, len(data)]) + data
        return self._finish_frame(head + body, new_request=True)

    def _write_session(self, first):
        """Polling is paused while writes run: the poll in progress finishes,
        then every queued write is sent (with retries), the bus stays quiet for
        WRITE_SETTLE_MS, and only then polling resumes. Writes clicked during
        the session join it instead of waiting for another poll."""
        started = time.perf_counter()
        with self._cond:
            pending = len(self._writes) + 1
        self._emit("write_session", state="paused", pending=pending)
        done = failed = 0
        dead = set()                 # slaves that did not answer a write in this session
        write = first
        while write is not None:
            sid = int(write["slave_id"])
            if sid in dead:
                # do not hold the bus for every queued click to a device that is not answering
                self._emit("write_result", slave_id=sid, function=int(write["function"]),
                           address=int(write["address"]), ok=False, reason="skipped", detail="skipped",
                           count=len(write["values"]), elapsed_ms=0, attempts=0)
                ok, port_lost = False, False
            else:
                ok, port_lost, reason = self._execute_write(write)
                if reason == "timeout":
                    dead.add(sid)
            done += 1
            failed += 0 if ok else 1
            if port_lost:
                return
            with self._cond:
                write = self._writes.pop(0) if self._writes else None
                if write is None and not self._stop_requested:
                    # settle time: outputs switch before the next read; new writes may still join
                    self._cond.wait(WRITE_SETTLE_MS / 1000.0)
                    write = self._writes.pop(0) if self._writes else None
                if self._stop_requested:
                    break
        self._emit("write_session", state="resumed", count=done, failed=failed,
                   elapsed_ms=int((time.perf_counter() - started) * 1000))

    def _execute_write(self, request):
        """One write with up to request['retries'] retries on timeout.
        Returns (ok, port_lost)."""
        retries = max(0, int(request.get("retries", 0)))
        attempt = 0
        while True:
            reason, detail, elapsed, port_lost = self._write_once(request, attempt)
            if reason != "timeout" or attempt >= retries or self._stop_requested:
                break
            attempt += 1
        slave_id, function = int(request["slave_id"]), int(request["function"])
        values = list(request["values"])
        self._emit("write_result", slave_id=slave_id, function=function, address=int(request["address"]),
                   ok=reason is None, reason=reason, detail=detail, count=len(values), elapsed_ms=elapsed,
                   attempts=attempt + 1)
        if port_lost:
            with self._cond:
                self._stop_requested = True
                self._cond.notify_all()
            self._emit("port_lost", detail=detail)
        return reason is None, port_lost, reason

    def _write_once(self, request, attempt):
        self._bus_idle_wait()
        slave_id = int(request["slave_id"])
        unit = self._unit(request)
        client = self._client_for(request)
        function = int(request["function"])
        address = int(request["address"])
        values = list(request["values"])
        timeout = max(0.05, int(request.get("timeout", 2000)) / 1000.0)
        method = {5: "write_coil", 6: "write_register", 15: "write_coils", 16: "write_registers"}[function]
        argument = values[0] if function in (5, 6) else values
        if function in (5, 15):
            argument = bool(argument) if function == 5 else [bool(v) for v in values]
        self._tcp_new_request()
        frame = self._build_write_frame(unit, function, address, values)
        self._emit("tx", slave_id=slave_id, function=function, kind="write", attempt=attempt,
                   frame=self._hex(frame))
        perf_start = time.perf_counter()
        response, reason, detail, port_lost = None, None, "", False
        try:
            if client is None:
                raise ConnectionError("Modbus client is not connected")
            comm_params = getattr(client, "comm_params", None)
            if comm_params is not None:
                comm_params.timeout_connect = timeout
            if self._is_tcp_request(request):
                response = self._tcp_perform_write(client, request, frame, method, address, argument, unit,
                                                   timeout)   # modbus_tcp.py
            else:
                # ---- Modbus RTU (serial bus) ----
                sock = getattr(client, "socket", None)
                if sock is not None:
                    sock.timeout = timeout
                    if hasattr(sock, "reset_input_buffer"):
                        sock.reset_input_buffer()
                call = getattr(client, method)
                try:
                    response = call(address, argument, device_id=unit)
                except TypeError:
                    response = call(address, argument, slave=unit)
                if response is None:
                    raise TimeoutError("No response")
                if response.isError():
                    raise RuntimeError(_exception_text(response))
        except Exception as exc:
            text = str(exc)
            if isinstance(exc, TimeoutError) or "No response received" in text or "timeout" in text.lower():
                reason = "timeout"
            elif text.startswith("Modbus exception response"):
                reason = "exception"
                detail = text
            else:
                reason = "error"
                port_lost = self._is_port_lost(exc, text)
            detail = detail or text
        finally:
            self._last_bus_end = time.monotonic()
            try:
                sock = getattr(client, "socket", None)
                if sock is not None and hasattr(sock, "reset_input_buffer"):
                    sock.reset_input_buffer()
            except Exception:
                pass
        elapsed = int((time.perf_counter() - perf_start) * 1000)
        if reason is None:
            self._emit("rx", slave_id=slave_id, function=function, kind="write",
                       frame=self._hex(self._build_response_frame(unit, response)), elapsed_ms=elapsed)
        else:
            self._emit("fail", slave_id=slave_id, function=function, kind="write",
                       reason=reason, detail=detail, elapsed_ms=elapsed)
        return reason, detail, elapsed, port_lost

    def _apply_result(self, entry, kind, reason, elapsed, tx_start, end):
        """Device state machine. Called with the lock held. Returns log lines."""
        sid = entry["slave_id"]
        logs = []
        if reason is None:
            entry["last_poll_tx"] = tx_start
            entry.update(status=ONLINE, retry_count=0, next_retry=None, next_recovery=None,
                         last_response=f"OK ({elapsed} ms)",
                         next_poll=tx_start + max(1, int(entry["polling"])) / 1000.0)
            if kind == JOB_RECOVERY:
                logs.append(f"Slave {sid} recovered. Resuming normal polling.")
            elif kind == JOB_RETRY:
                logs.append(f"Slave {sid} retry successful. Resuming normal polling.")
            return logs

        entry["last_response"] = {"timeout": "Timeout", "exception": "Exception"}.get(reason, "Error")
        scan_ms = max(MIN_RECOVERY_MS, int(entry["scan_rate"]))
        if kind == JOB_RECOVERY:
            entry["next_recovery"] = end + scan_ms / 1000.0
            logs.append(f"Slave {sid} still OFFLINE. Next recovery attempt in {scan_ms} ms.")
            return logs

        max_retries = max(0, int(entry["max_retries"]))
        if entry["retry_count"] < max_retries:
            entry["retry_count"] += 1
            entry["status"] = RETRYING
            entry["next_retry"] = end  # next free bus slot, no artificial delay
            logs.append(f"Retry {entry['retry_count']}/{max_retries} (Slave {sid})")
        else:
            entry.update(status=OFFLINE, next_poll=None, next_retry=None,
                         next_recovery=end + scan_ms / 1000.0)
            logs.append(f"!! Slave {sid} marked OFFLINE after {entry['retry_count'] + 1} failed attempt(s). "
                        f"Recovery attempt every {scan_ms} ms.")
        return logs

    def _read_ip_types(self, config):
        """One extra transaction (FC03, address 0, 8 registers) giving each AI
        channel's input type. It never changes the device state machine."""
        self._bus_idle_wait()
        slave_id = config["slave_id"]
        unit = self._unit(config)
        self._frame_tcp = bool(config.get("host"))
        self._tcp_new_request()
        self._ip_tries[slave_id] = self._ip_tries.get(slave_id, 0) + 1
        fc, address, count = AI_CONFIG_READ["function"], AI_CONFIG_READ["address"], AI_CONFIG_READ["count"]
        tx_frame = self._build_read_frame(unit, fc, address, count)
        self._emit("tx", slave_id=slave_id, function=fc, kind="config", frame=self._hex(tx_frame))
        started = time.perf_counter()
        try:
            response = self._perform_device_request(config, _FUNCTION_METHODS[fc], address, count)
            registers = [int(r) for r in list(getattr(response, "registers", None) or [])[:count]]
            if len(registers) < count:
                raise ValueError(f"expected {count} registers, received {len(registers)}")
        except Exception as exc:
            text = str(exc)
            timed_out = isinstance(exc, TimeoutError) or "No response" in text or "timeout" in text.lower()
            self._emit("fail", slave_id=slave_id, function=fc, kind="config",
                       reason="timeout" if timed_out else "error", detail=text,
                       elapsed_ms=int((time.perf_counter() - started) * 1000))
            return
        elapsed = int((time.perf_counter() - started) * 1000)
        names = [AI_INPUT_TYPES.get(value, f"Unknown ({value})") for value in registers]
        self._ip_types[slave_id] = names
        self._emit("rx", slave_id=slave_id, function=fc, kind="config",
                   frame=self._hex(self._build_response_frame(unit, response)), elapsed_ms=elapsed)
        self._emit("config", slave_id=slave_id, ip_types=names, units=[ai_unit(n) for n in names])

    _PORT_LOST_MARKERS = (
        "ClearCommError", "Access is denied", "PermissionError", "SerialException",
        "could not open port", "device disconnected", "Input/output error",
        "Bad file descriptor", "port is closed", "not connected",
    )

    def _is_port_lost(self, exc, text):
        """True when a failure means the serial port itself is unusable (not a
        slow/silent device)."""
        if self.transport == "tcp" or self._frame_tcp:
            return False                     # TCP reconnects on the next request; devices just go OFFLINE meanwhile
        if isinstance(exc, PermissionError) or any(m.lower() in text.lower() for m in self._PORT_LOST_MARKERS):
            return True
        client = self._serial_connection
        return client is not None and getattr(client, "connected", True) is False

    def _emit(self, event_type, **data):
        data["type"] = event_type
        data["time"] = datetime.now()
        self.event.emit(data)

    # ------------------------------------------------------------------ #
    # Bus / frame functions moved unchanged from MultiDeviceView
    # ------------------------------------------------------------------ #
    def _probe_slave(self, slave_id):
        probes = [
            ("read_holding_registers", 3),
            ("read_input_registers", 4),
            ("read_coils", 1),
            ("read_discrete_inputs", 2),
        ]
        for method_name, function in probes:
            try:
                response = self._pymodbus_call(
                    method_name,
                    0,
                    count=1,
                    device_id=slave_id,
                )
                if response is not None and not response.isError():
                    return response, function
            except Exception:
                continue
        return None, None

    def _pymodbus_call(
        self, method_name, address, *, count=None, device_id=None, client=None
    ):
        client = client if client is not None else self._serial_connection
        if client is None:
            raise ConnectionError("Modbus client is not connected")
        method = getattr(client, method_name)
        kwargs = {"device_id": device_id}
        if count is not None:
            kwargs["count"] = count
        try:
            return method(address, **kwargs)
        except TypeError:
            kwargs.pop("device_id", None)
            kwargs["slave"] = device_id
            return method(address, **kwargs)

    def _perform_device_request(self, device, method, address, count):
        """Run exactly ONE Modbus transaction (no internal retries)."""
        client = self._client_for(device)
        if client is None:
            raise ConnectionError("Modbus client is not connected")
        timeout = max(0.05, int(device.get("timeout", 2000)) / 1000.0)
        # pymodbus 3.x waits for the reply using comm_params.timeout_connect, read
        # again on every request (client.timeout is not used), and pyserial's own
        # read timeout is socket.timeout. Set both so this device's Timeout is the
        # maximum RX wait of this one attempt.
        comm_params = getattr(client, "comm_params", None)
        if comm_params is not None:
            comm_params.timeout_connect = timeout
        if self._is_tcp_request(device):
            return self._tcp_perform_read(client, device, method, address, count, timeout)   # modbus_tcp.py
        # ---- Modbus RTU (serial bus) ----
        try:
            socket = getattr(client, "socket", None)
            if socket is not None:
                socket.timeout = timeout
                if hasattr(socket, "reset_input_buffer"):
                    socket.reset_input_buffer()
        except Exception:
            pass
        try:
            response = self._pymodbus_call(method, address, count=count, device_id=self._unit(device), client=client)
            if response is not None and not response.isError():
                return response
            if response is not None:
                raise RuntimeError(_exception_text(response))
            raise TimeoutError("No response")
        finally:
            self._last_bus_end = time.monotonic()
            try:
                socket = getattr(client, "socket", None)
                if socket is not None and hasattr(socket, "reset_input_buffer"):
                    socket.reset_input_buffer()
            except Exception:
                pass

    def _build_read_frame(self, slave_id, function, address, count):
        frame = bytes([
            slave_id & 0xFF,
            function & 0xFF,
            (address >> 8) & 0xFF,
            address & 0xFF,
            (count >> 8) & 0xFF,
            count & 0xFF,
        ])
        return self._finish_frame(frame, new_request=True)

    def _build_response_frame(self, slave_id, response):
        raw = getattr(response, "raw", None)
        if isinstance(raw, (bytes, bytearray)):
            return bytes(raw)                    # Modbus TCP: the frame exactly as received
        try:
            payload = response.encode()
            if not isinstance(payload, (bytes, bytearray)):
                payload = bytes(payload)
        except Exception:
            payload = b""
        function = getattr(response, "function_code", 0) & 0xFF
        return self._finish_frame(bytes([slave_id & 0xFF, function]) + payload, new_request=False)

    def _finish_frame(self, core, new_request):
        """core = unit id + function + data. RTU: append CRC16. TCP: MBAP header in front (modbus_tcp.py)."""
        if self.transport == "tcp" or self._frame_tcp:
            return self._tcp_mbap_frame(core, new_request)
        crc = self._crc16(core)
        return core + bytes([crc & 0xFF, (crc >> 8) & 0xFF])

    def _crc16(self, data):
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc & 0xFFFF

    def _hex(self, data):
        return " ".join(f"{byte:02X}" for byte in data)