"""Modbus TCP side of the multi-device scanner - kept apart from the RTU (serial) logic.

    TcpReply            one reply frame (MBAP + PDU) with the attributes the scanner reads (pymodbus style)
    ModbusTcpLink       one plain TCP connection to a device / TCP -> RTU gateway, used the way ModScan does:
                        send ONE request, read the reply by its MBAP length, validate it, done
    TcpScannerMixin     what ModbusScanner does for a TCP device: connections, transaction ids, one read, one write

ModbusScanner (modbus_scanner.py) inherits TcpScannerMixin and uses the same entry points as before
(_tcp_client_for, _tcp_gap_wait, _tcp_perform_read, _tcp_perform_write, _tcp_mbap_frame, _tcp_close_all,
_tcp_after_failure, _tcp_new_request, _endpoint, _is_tcp_request), each only for a TCP device.

Rules of this module (nothing else is done behind the user's back):
  * one request on the wire at a time, no hidden waits: the pace is the poll interval set in the UI
    (only a tiny TCP_MIN_GAP_S between two requests to the same gateway)
  * a reply is accepted only when MBAP header, transaction id, unit, function and byte count all fit the
    request. A reply that does not fit is an ERROR / TIMEOUT of that poll - never joined, repaired or guessed
  * no re-send inside a poll: the scanner's own Retries setting decides if a request is sent again
  * stale bytes of an earlier request are thrown away (without waiting) before a new request is sent
  * a connection is closed only when it is lost, or after TCP_RECONNECT_AFTER timeouts in a row
"""
import os as _os
import select
import socket
import struct
import time
from collections import deque
from datetime import datetime

TCP_MIN_GAP_S = 0.05        # quiet time between the end of one request and the start of the next (same gateway)
TCP_RECONNECT_AFTER = 3     # consecutive timeouts on one connection before it is closed and opened again
TCP_MAX_BACKOFF_S = 30.0    # longest wait before reconnecting to a gateway that keeps resetting us

_FUNCTION_BY_METHOD = {"read_coils": 1, "read_discrete_inputs": 2,
                       "read_holding_registers": 3, "read_input_registers": 4}

# --------------------------------------------------------------------------------------------------
# Debug prints (console): every TCP byte sent and received and what was decided about it.
# Turn off with the environment variable NELUMBO_MODBUS_DEBUG=0.
# --------------------------------------------------------------------------------------------------
DEBUG_PRINTS = _os.environ.get("NELUMBO_MODBUS_DEBUG", "1") != "0"


def _dbg(*parts):
    if DEBUG_PRINTS:
        now = datetime.now()
        print(f"[{now:%H:%M:%S}.{now.microsecond // 1000:03d}] [modbus-tcp]", *parts, flush=True)


def _hex(data):
    return " ".join(f"{byte:02X}" for byte in data)


_EXCEPTION_NAMES = {1: "illegal function", 2: "illegal data address", 3: "illegal data value",
                    4: "slave device failure", 5: "acknowledge", 6: "slave device busy",
                    10: "gateway path unavailable", 11: "gateway target device failed to respond"}


def _exception_text(response):
    """'Modbus exception response (code 0x0B: gateway target device failed to respond)'."""
    code = getattr(response, "exception_code", None)
    if code is None:
        return "Modbus exception response"
    return f"Modbus exception response (code 0x{int(code):02X}: {_EXCEPTION_NAMES.get(int(code), 'unknown')})"


# --------------------------------------------------------------------------------------------------
# Transport: one TCP connection
# --------------------------------------------------------------------------------------------------
class TcpReply:
    """Reply of one Modbus TCP transaction, with the same attributes the scanner reads from pymodbus."""

    def __init__(self, raw):
        self.raw = raw                       # the complete frame as received (MBAP + PDU)
        self.transaction_id = struct.unpack(">H", raw[:2])[0]
        self.unit = raw[6]
        self._pdu = raw[7:]
        self.function_code = self._pdu[0]
        self.registers, self.bits, self.exception_code = [], [], None
        fc = self.function_code
        if fc & 0x80:
            self.exception_code = self._pdu[1] if len(self._pdu) > 1 else None
        elif fc in (1, 2, 3, 4):
            if len(self._pdu) < 2:
                raise ValueError("Invalid response data: reply has no byte count")
            count = self._pdu[1]
            data = self._pdu[2:2 + count]
            if len(data) < count:
                raise ValueError(f"Invalid response data: byte count {count}, received {len(data)} bytes")
            if fc in (3, 4):
                self.registers = [int.from_bytes(data[i:i + 2], "big") for i in range(0, count - 1, 2)]
            else:
                self.bits = [bool((byte >> bit) & 1) for byte in data for bit in range(8)]

    def isError(self):
        return bool(self.function_code & 0x80)

    def encode(self):
        return self._pdu[1:]


class ModbusTcpLink:
    """Plain Modbus TCP master on one socket. transact() = send one request, read exactly one reply."""

    def __init__(self, host, port, connect_timeout=2.0):
        self.host, self.port = str(host), int(port)
        self.connect_timeout = connect_timeout
        self.sock = None
        self.opened_at = 0.0                 # monotonic time of the last successful connect
        self.resets = 0                      # consecutive connections reset by the gateway
        self.retry_after = 0.0               # no new connection before this time (back-off after resets)
        self.skipped = []                    # frames of other transactions skipped by the last transact (log)
        self.parts = 1                       # kept for the scanner: a reply is always ONE frame now
        self.late = False                    # kept for the scanner: late replies are never used now
        self._sent_at = 0.0

    @property
    def connected(self):
        return self.sock is not None

    # ---- connection ----
    def connect(self, timeout=None):
        self.close()
        if time.monotonic() < self.retry_after:
            return False                     # back-off: the gateway just refused / reset us
        try:
            sock = socket.create_connection((self.host, self.port), timeout or self.connect_timeout)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError as exc:
            self.sock = None
            _dbg(f"CONNECT {self.host}:{self.port} FAILED: {exc}")
            return False
        self.sock = sock
        self.opened_at = time.monotonic()
        _dbg(f"CONNECT {self.host}:{self.port} ok (local port {sock.getsockname()[1]})")
        return True

    def close(self):
        if self.sock is not None:
            _dbg(f"CLOSE {self.host}:{self.port}")
            try:
                self.sock.shutdown(socket.SHUT_RDWR)   # FIN now, so the gateway frees its connection slot at once
            except OSError:
                pass
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    def _lost(self, exc):
        """The gateway closed / reset the connection: back off a little longer each time (a new connection
        right after a reset is usually refused again - the gateway has no free slot yet)."""
        fresh = time.monotonic() - self.opened_at < 1.0
        _dbg(f"RESET by gateway {self.host}:{self.port} ({exc}); fresh connection={fresh}")
        self.close()
        self.resets += 1
        backoff = min(TCP_MAX_BACKOFF_S, 2.0 * (2 ** (self.resets - 1)))
        self.retry_after = time.monotonic() + backoff
        why = f"({exc})" if exc else "(closed by the gateway)"
        if fresh:
            raise ConnectionError(f"gateway {self.host}:{self.port} reset a new connection {why}: its connection "
                                  f"limit is probably reached - close ModScan / the Communication page / other "
                                  f"masters, or raise 'max connections' in the converter. Next try in {backoff:.0f} s")
        raise ConnectionError(f"connection lost {why}; reconnecting in {backoff:.0f} s")

    # ---- one transaction ----
    def discard_pending(self):
        """Throw away whatever is already waiting in the socket (late / broken reply of an earlier request).
        Returns the dropped bytes. Never waits."""
        dropped = b""
        while self.sock is not None:
            try:
                ready, _, _ = select.select([self.sock], [], [], 0)
            except (OSError, ValueError):
                break
            if not ready:
                break
            try:
                data = self.sock.recv(4096)
            except (BlockingIOError, InterruptedError):
                break
            except OSError as exc:
                self._lost(exc)
            if not data:
                self._lost(None)
            dropped += data
        if dropped:
            _dbg(f"DISCARDED {len(dropped)} stale bytes before the request : {_hex(dropped)}")
        return dropped

    def transact(self, unit, pdu, tid, timeout):
        """Send one request, return its TcpReply.
        TimeoutError  - no complete reply within `timeout`
        TimeoutError  - also when the reply is incomplete / not this request's answer (counted as a Timeout)
        ConnectionError - the connection is lost"""
        self.skipped = []
        if self.sock is None and not self.connect(timeout):
            wait = self.retry_after - time.monotonic()
            if wait > 0:
                raise TimeoutError(f"No response: gateway {self.host}:{self.port} reset the last connection, "
                                   f"next connect in {wait:.0f} s")
            raise TimeoutError(f"No response: cannot connect to {self.host}:{self.port}")
        stale = self.discard_pending()
        if stale:
            self.skipped.append(stale)
        unit &= 0xFF
        request = struct.pack(">HHHB", tid, 0, len(pdu) + 1, unit) + bytes(pdu)
        try:
            self.sock.sendall(request)
        except OSError as exc:
            _dbg(f"SEND FAILED tid={tid}: {exc}")
            self.close()
            raise ConnectionError(f"send failed, connection closed ({exc})")
        self._sent_at = time.monotonic()
        _dbg(f"TX  tid={tid} unit={unit} fc={pdu[0]} timeout={timeout:.3f}s : {_hex(request)}")
        deadline = self._sent_at + timeout
        buffer = b""
        while True:
            # --- take complete MBAP frames out of the buffer
            while len(buffer) >= 7:
                t_id, proto, length = struct.unpack(">HHH", buffer[:6])
                if proto != 0 or length < 2 or length > 254:
                    _dbg(f"    not an MBAP header (tid={t_id} proto={proto} len={length}) -> skip byte {buffer[0]:02X}")
                    self.skipped.append(buffer[:1])      # resynchronise byte by byte
                    buffer = buffer[1:]
                    continue
                if len(buffer) < 6 + length:
                    break                                 # frame not complete yet: read on
                frame, buffer = buffer[:6 + length], buffer[6 + length:]
                if t_id != tid:
                    _dbg(f"    SKIPPED reply of tid {t_id} (waiting for {tid}) : {_hex(frame)}")
                    self.skipped.append(frame)
                    continue
                frame = self._grace(frame, unit, pdu, deadline)
                return self._check(frame, unit, pdu)
            # --- need more bytes
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._timeout(buffer)
            try:
                self.sock.settimeout(remaining)
                data = self.sock.recv(1024)
            except socket.timeout:
                self._timeout(buffer)
            except OSError as exc:
                self._lost(exc)
            if not data:
                self._lost(None)
            self.resets = 0
            _dbg(f"RX  +{(time.monotonic() - self._sent_at) * 1000:.0f} ms  {len(data)} bytes : {_hex(data)}")
            buffer += data

    def _grace(self, frame, unit, pdu, deadline):
        """A read reply whose byte count is bigger than the data it carries may only have been sent in two
        pieces by the gateway. Wait for the rest until the request timeout ends; it is
        used only when it completes the reply EXACTLY. Otherwise the frame is returned unchanged and _check
        rejects it. Replies that are complete (or not reads) return at once."""
        if len(frame) < 9 or frame[6] != unit or frame[7] != pdu[0] or pdu[0] not in (1, 2, 3, 4):
            return frame
        expected = frame[8]
        have = len(frame) - 9
        if have >= expected:
            return frame
        until = deadline                     # the full Timeout of the device, like ModScan
        data = frame[9:]
        extra = b""
        _dbg(f"    reply has {have} of {expected} data bytes -> waiting for the rest (until the {max(0.0, deadline - time.monotonic()) * 1000:.0f} ms timeout ends)")
        while len(data) + len(extra) < expected:
            remaining = until - time.monotonic()
            if remaining <= 0:
                break
            try:
                self.sock.settimeout(remaining)
                more = self.sock.recv(1024)
            except socket.timeout:
                break
            except OSError as exc:
                self._lost(exc)
            if not more:
                self._lost(None)
            _dbg(f"RX  +{(time.monotonic() - self._sent_at) * 1000:.0f} ms  {len(more)} more bytes : {_hex(more)}")
            extra += more
        if len(data) + len(extra) != expected:
            _dbg(f"    rest did not complete the reply ({len(data) + len(extra)} of {expected}) -> rejected")
            return frame + extra if extra and len(extra) < 4 else frame
        full = frame[:9] + data + extra
        full = full[:4] + struct.pack(">H", len(full) - 6) + full[6:]
        _dbg(f"    reply completed by the late rest ({len(extra)} bytes)")
        return full

    def _timeout(self, buffer):
        _dbg(f"RX  TIMEOUT after {(time.monotonic() - self._sent_at) * 1000:.0f} ms; unparsed: [{_hex(buffer)}]")
        text = "No response received (timeout)"
        seen = [f for f in self.skipped if len(f) > 1]
        parts = [f"[{_hex(f)}]" for f in seen[:3]]
        if buffer:
            parts.append(f"incomplete [{_hex(buffer[:60])}]")
        if parts:
            text += " - received instead: " + " ".join(parts)
        raise TimeoutError(text)

    @staticmethod
    def _check(frame, unit, pdu):
        """The frame has this request's transaction id: it must also be this request's ANSWER."""
        fc = pdu[0]
        got_unit, got_fc = frame[6], frame[7]
        if got_unit != unit or (got_fc & 0x7F) != fc:
            raise TimeoutError(f"No response received (timeout) - reply is not the answer to this request "
                               f"(want unit {unit} fc {fc}) - RX [{_hex(frame)}]")
        if got_fc & 0x80:
            reply = TcpReply(frame)
            _dbg(f"    -> exception reply code {reply.exception_code}")
            return reply
        if fc in (1, 2, 3, 4):
            if len(pdu) >= 5:
                quantity = struct.unpack(">H", pdu[3:5])[0]
                want = quantity * 2 if fc in (3, 4) else (quantity + 7) // 8
            else:
                want = None
            have = len(frame) - 9
            if len(frame) < 9 or (frame[8] != have) or (want is not None and frame[8] != want):
                raise TimeoutError(f"No response received (timeout) - reply incomplete: {max(have, 0)} of "
                                   f"{want if want is not None else frame[8] if len(frame) > 8 else '?'} data bytes "
                                   f"- RX [{_hex(frame)}]")
        try:
            reply = TcpReply(frame)
        except ValueError as exc:
            raise ValueError(f"{exc} - RX [{_hex(frame)}]")
        _dbg(f"    -> ACCEPTED in {len(frame)} bytes : {_hex(frame)}")
        return reply


# --------------------------------------------------------------------------------------------------
# Scanner side: what ModbusScanner does for a TCP device
# --------------------------------------------------------------------------------------------------
class TcpScannerMixin:

    # ---- state / life cycle -----------------------------------------------------------------------
    def _tcp_init_state(self):
        self._tid = 0                    # transaction id shown in TCP frames
        self._clients = {}               # endpoint -> ModbusTcpLink, one connection per IP:port
        self._tid_queue = deque()        # transaction ids shown in the TX log, used by the next TCP request
        self._tcp_failed = {}            # unit + PDU of a request that failed -> its transaction id (re-send = same id)
        self._tcp_timeouts = {}          # endpoint -> consecutive timeouts
        self._settle_spent = 0.0         # kept for the scanner (time not counted as response time): always 0 now

    def _tcp_new_request(self):
        """A new poll / write starts: forget transaction ids queued for an earlier one."""
        self._tid_queue.clear()

    def _tcp_close_all(self):
        for client in list(self._clients.values()):
            try:
                client.close()
            except Exception:
                pass
        self._clients.clear()

    # ---- connections ------------------------------------------------------------------------------
    def _tcp_client_for(self, cfg):
        """The TCP connection of this device: its own IP:port, or the one gateway IP of the Connection panel."""
        host = cfg.get("host")
        if not host:
            shared = self._clients.get(("shared",))
            if shared is None:
                params = getattr(self._serial_connection, "comm_params", None)
                gw_host = getattr(params, "host", None) or getattr(self._serial_connection, "host", None)
                gw_port = getattr(params, "port", None) or getattr(self._serial_connection, "port", None) or 502
                if not gw_host:
                    return self._serial_connection
                try:
                    if self._serial_connection is not None:
                        self._serial_connection.close()   # free the gateway connection slot
                except Exception:
                    pass
                shared = ModbusTcpLink(gw_host, gw_port)
                self._clients[("shared",)] = shared
            return shared
        key = (str(host), int(cfg.get("tcp_port") or 502))
        client = self._clients.get(key)
        if client is None:
            client = ModbusTcpLink(key[0], key[1])
            self._clients[key] = client
        return client

    def _tcp_gap_wait(self):
        """Only a tiny quiet time after the previous request; the real pace is the poll interval."""
        remaining = self._last_bus_end + TCP_MIN_GAP_S - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)

    def _tcp_mbap_frame(self, core, new_request):
        """core = unit id + PDU -> MBAP header (transaction id, protocol 0, length) + core."""
        tid = self._tid
        if new_request:
            tid = self._tcp_failed.pop(bytes(core), None)    # the same request again after a failure: same id
            if tid is None:
                self._tid = (self._tid + 1) & 0xFFFF
                tid = self._tid
            self._tid_queue.append(tid)
        length = len(core)                      # unit id + PDU
        header = bytes([(tid >> 8) & 0xFF, tid & 0xFF, 0, 0, (length >> 8) & 0xFF, length & 0xFF])
        return header + core

    def _take_tid(self):
        """Transaction id of the next TCP request: the one already shown in its TX log line."""
        if self._tid_queue:
            return self._tid_queue.popleft()
        self._tid = (self._tid + 1) & 0xFFFF
        return self._tid

    def _tcp_connect_or_fail(self, client, cfg):
        if not getattr(client, "connected", True):
            if not client.connect():
                if isinstance(client, ModbusTcpLink) and client.retry_after > time.monotonic():
                    raise TimeoutError(f"No response: gateway {client.host}:{client.port} reset the last "
                                       f"connection, next connect in {client.retry_after - time.monotonic():.0f} s")
                raise TimeoutError(f"No response: cannot connect to {cfg.get('host') or 'gateway'}:"
                                   f"{cfg.get('tcp_port') or 502}")

    # ---- one read / one write ---------------------------------------------------------------------
    def _tcp_perform_read(self, client, device, method, address, count, timeout):
        """ONE read transaction of a TCP device. No re-send here."""
        try:
            self._tcp_connect_or_fail(client, device)
            try:
                if isinstance(client, ModbusTcpLink):
                    pdu = struct.pack(">BHH", _FUNCTION_BY_METHOD[method], address, count)
                    response = self._tcp_transact(client, device, pdu, timeout)
                    if not response.isError():
                        function = _FUNCTION_BY_METHOD[method]
                        got = len(response.registers) if function in (3, 4) else len(response.bits)
                        if got < count:
                            raise ValueError(f"Invalid response data: expected {count} values, received {got} "
                                             f"- RX [{_hex(response.raw)}]")
                else:   # no gateway IP known: the pymodbus TCP client of the Connection panel
                    response = self._pymodbus_call(method, address, count=count, device_id=self._unit(device),
                                                   client=client)
            except Exception as exc:
                self._tcp_after_failure(device, str(exc))
                raise
            if response is None:
                self._tcp_after_failure(device, "No response")
                raise TimeoutError("No response")
            if response.isError():
                raise RuntimeError(_exception_text(response))
            return response
        finally:
            self._last_bus_end = time.monotonic()

    def _tcp_perform_write(self, client, request, frame, method, address, argument, unit, timeout):
        """ONE write transaction of a TCP device. frame = the MBAP frame already shown in the TX log."""
        try:
            self._tcp_connect_or_fail(client, request)
            if isinstance(client, ModbusTcpLink):
                response = self._tcp_transact(client, request, frame[7:], timeout)   # PDU of the logged TX frame
            else:
                call = getattr(client, method)
                try:
                    response = call(address, argument, device_id=unit)
                except TypeError:
                    response = call(address, argument, slave=unit)
            if response is None:
                raise TimeoutError("No response")
            if response.isError():
                raise RuntimeError(_exception_text(response))
            return response
        except Exception as exc:
            self._tcp_after_failure(request, str(exc))
            raise
        finally:
            self._last_bus_end = time.monotonic()

    def _tcp_transact(self, client, cfg, pdu, timeout):
        tid = self._take_tid()
        unit = self._unit(cfg)
        key = bytes([unit & 0xFF]) + bytes(pdu)
        try:
            reply = client.transact(unit, pdu, tid, timeout)
        except Exception:
            self._tcp_failed[key] = tid          # the next try of this same request uses this transaction id again
            raise
        self._tcp_failed.pop(key, None)
        self._tcp_timeouts[self._endpoint(cfg)] = 0
        if client.skipped:
            frames = [f for f in client.skipped if len(f) > 1]
            junk = sum(len(f) for f in client.skipped if len(f) == 1)
            text = f"Slave {cfg.get('slave_id')}: skipped {len(frames)} stale frame(s) of earlier requests"
            if frames:
                text += ": " + " | ".join(self._hex(f) for f in frames[:3])
            if junk:
                text += f" and {junk} stray byte(s)"
            self._emit("log", text=text + ".")
        return reply

    @staticmethod
    def _endpoint(cfg):
        if not cfg.get("host"):
            return ("shared",)               # one Modbus TCP connection for all devices (gateway IP in Connection)
        return (str(cfg.get("host")), int(cfg.get("tcp_port") or 502))

    def _is_tcp_request(self, cfg):
        return bool(cfg.get("host")) or self.transport == "tcp"

    def _tcp_after_failure(self, cfg, text):
        """Only counts timeouts in a row; after TCP_RECONNECT_AFTER the connection is closed so the next request
        starts on a clean one. Nothing is waited for here."""
        if text.startswith("Modbus exception response"):
            self._tcp_timeouts[self._endpoint(cfg)] = 0       # a complete, valid reply
            return
        endpoint = self._endpoint(cfg)
        lowered = text.lower()
        if "no response" in lowered or "timeout" in lowered:
            self._tcp_timeouts[endpoint] = self._tcp_timeouts.get(endpoint, 0) + 1
        link = self._clients.get(endpoint)
        if isinstance(link, ModbusTcpLink) and link.connected and \
                self._tcp_timeouts.get(endpoint, 0) >= TCP_RECONNECT_AFTER:
            link.close()
            self._tcp_timeouts[endpoint] = 0
            self._emit("log", text=f"{link.host}:{link.port}: connection closed after {TCP_RECONNECT_AFTER} "
                                   f"timeouts in a row; it is opened again for the next request.")