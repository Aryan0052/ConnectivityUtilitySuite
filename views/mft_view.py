"""MFT (Multi Function Transducer) device page - Python / PySide6 port of MFT.jsx.

Talks to the module over one serial port with its ASCII protocol
(every command ends with LF, every reply is one line):

    GETCFG                                       -> SID=..,BAUD=..  (CT_RATIO=.. / PT_RATIO=.. when sent)
    SID=<1-63>,MBD_BAUD=<baud>                   -> OK:Settings Updated
    CT_RATIO=<0-10000> / PT_RATIO=<0-10000>      -> OK CT / OK:CT   (or CT_RATIO=<value> echoed)

MFTView: RTU slave settings + CT / PT ratio.  Emits back_clicked like the other device pages.
The analog (4-20 mA) variant lives in its own file: mft_analog_view.py
"""
import os
import re

from PySide6.QtCore import Signal, Qt, QPoint, QTimer
from PySide6.QtGui import QPixmap, QPainter, QPen
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QLabel, QPushButton, QComboBox, QLineEdit,
    QFrame, QScrollArea, QPlainTextEdit, QDialog, QSizePolicy,
)

try:
    from serial.tools import list_ports
except Exception:                                    # pyserial missing: page opens, Connect reports it
    list_ports = None

try:
    from . import ui_theme as ui
except ImportError:
    import ui_theme as ui

BAUD_RATES = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 230400]
SLAVE_ID_MIN, SLAVE_ID_MAX = 1, 63
RATIO_MAX = 10000
REPLY_TIMEOUT_MS = 2000          # one attempt waits this long for the reply
MAX_ATTEMPTS = 5                 # RTU apply / refresh / channel apply are repeated up to this many times
POLL_MS = 20
DEBUG_SERIAL = True              # print every TX / RX to the Python console (VS Code terminal); set False to silence


def _dbg(direction, data, extra=""):
    """Console debug: direction TX/RX, readable text and the exact bytes (shows CR/LF)."""
    if not DEBUG_SERIAL:
        return
    import time
    raw = bytes(data)
    stamp = time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"
    print(f"[{stamp}] {direction} {raw.decode('ascii', errors='replace').strip()!r:<55} bytes={raw!r} {extra}".rstrip(),
          flush=True)
CONNECT_MUTE_MS = 4000           # replies to the warm-up GETCFG after Connect stay out of the terminal

GREEN = "#00C928"
RED = "#D00000"
BLUE = "#155B91"

def num_text(value):
    """Number as the device expects it: 0 -> '0', 0.5 -> '0.5' (no trailing .0)."""
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def normalize_ratio(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 1
    if number != number or number in (float("inf"), float("-inf")):
        return 1
    n = int(number)
    return 1 if n <= 0 else min(RATIO_MAX, n)


def ratio_error(value):
    """None if value is a valid ratio, else the error text (no clamping)."""
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return "Enter a valid number"
    if number != number or number in (float("inf"), float("-inf")):
        return "Enter a valid number"
    if number > RATIO_MAX:
        return f"cannot be greater than {RATIO_MAX}"
    return None


# ------------------------------------------------------------------ widgets
class BackButton(QPushButton):
    """White circular back button (same as the other device pages)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(58, 58)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setText("")
        self.setStyleSheet("QPushButton{background:transparent;border:none;padding:0px;margin:0px;}")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(Qt.white)
        p.drawEllipse(0, 0, 58, 58)
        pen = QPen(BLUE)
        pen.setWidth(6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawLine(QPoint(19, 29), QPoint(43, 29))
        p.drawLine(QPoint(19, 29), QPoint(31, 17))
        p.drawLine(QPoint(19, 29), QPoint(31, 41))
        p.end()




def _apply_button(text="APPLY", small=True):
    return ui.button(text, "primary", 36)


class RatioBox(QFrame):
    """CT RATIO / PT RATIO: label, number box, valid range, Apply."""
    applied = Signal(str)

    def __init__(self, kind, label, boxed=True, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setObjectName("pgBox")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(ui.label(label, "pgValue" if boxed else "pgField"), 3)
        self.edit = QLineEdit("0")
        row.addWidget(self.edit, 5)
        lay.addLayout(row)
        lay.addWidget(ui.label("Valid Range: 0 to 10000", "pgHint"))
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.button = _apply_button("Apply")
        ui.sized(self.button, "setMinimumWidth", 100)
        self.button.clicked.connect(lambda: self.applied.emit(self.kind))
        btn_row.addWidget(self.button)
        lay.addLayout(btn_row)
        self.edit.editingFinished.connect(self._clean)

    def _clean(self):
        # values above RATIO_MAX are left as typed so the error can be shown
        if ratio_error(self.edit.text()) is None:
            self.edit.setText(str(normalize_ratio(self.edit.text())))

    def value(self):
        return normalize_ratio(self.edit.text())


# ------------------------------------------------------------------ base page
class _MFTBase(QWidget):
    back_clicked = Signal()
    PROTOCOL_NAME = "Modbus RTU"

    def __init__(self):
        super().__init__()
        self._ser = None
        self._port = None
        self._buffer = bytearray()
        self._req = None                  # the one request waiting for a reply
        self._mute_until = 0.0
        self._terminal_lines = ["Device Terminal Ready"]
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(POLL_MS)
        self._monitor = QTimer(self)
        self._monitor.timeout.connect(self._check_port)
        self._monitor.start(1000)

    # ---------------------------------------------------------------- ui
    def _header(self):
        # Top bar shared with the other pages (logo, back, title, connection status, theme switch).
        self._hdr = ui.Header(self.PAGE_TITLE, root=self)
        self._hdr.back_button.clicked.connect(self.handle_back)
        return self._hdr

    def _left_panel(self):
        panel = ui.rtu_panel(self.PROTOCOL_NAME)
        self.connect_button = panel.connect
        self.status = self._hdr.status
        self._status_dot = self._hdr.status_dot
        self.status.setText("Not Connected")
        ui.set_status(self.status, self._status_dot, GREEN)
        panel.protocol.clear()
        panel.protocol.addItem(self.PROTOCOL_NAME)
        panel.protocol.setEnabled(False)
        self.slave_edit = panel.id_edit
        self.baud_box = panel.baud
        self.baud_box.clear()
        for b in BAUD_RATES:
            self.baud_box.addItem(str(b), b)
        self.baud_box.setCurrentText("9600")
        self.apply_button = panel.apply
        self.refresh_button = panel.refresh
        self.terminal = panel.terminal
        self.connect_button.clicked.connect(self.handle_connect)
        self.slave_edit.editingFinished.connect(self._clean_slave)
        self.apply_button.clicked.connect(self.handle_apply_rtu)
        self.refresh_button.clicked.connect(self.handle_refresh)
        return panel.card

    def _right_panel(self):
        raise NotImplementedError

    def _build_ui(self):
        ui.install(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._header())
        main = QWidget()
        main.setObjectName("mainArea")
        lay = QHBoxLayout(main)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(16)
        lay.addWidget(self._left_panel())
        lay.addWidget(self._right_panel(), 1)
        root.addWidget(main, 1)

    # ---------------------------------------------------------------- helpers
    def _set_status(self, text, color=GREEN):
        self.status.setText(text)
        ui.set_status(self.status, getattr(self, "_status_dot", None), color)

    def _ok(self, text):
        self._set_status(text, GREEN)

    def _err(self, text):
        self._set_status(text, RED)

    def _info(self, text):
        self._set_status(text, BLUE)

    def add_terminal_message(self, message):
        self._terminal_lines.append(str(message))
        self._terminal_lines = self._terminal_lines[-100:]
        self.terminal.setPlainText("\n".join(self._terminal_lines))
        bar = self.terminal.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _clean_slave(self):
        try:
            v = int(float(self.slave_edit.text()))
        except ValueError:
            v = SLAVE_ID_MIN
        self.slave_edit.setText(str(max(SLAVE_ID_MIN, min(SLAVE_ID_MAX, v))))

    def _connected(self):
        return self._ser is not None and self._ser.is_open

    # ---------------------------------------------------------------- connect
    def handle_connect(self):
        if self._connected():
            self._cancel_request()
            self._close_port()
            self._set_status("Not Connected", GREEN)
            self.connect_button.setText("CONNECT")
            return
        if list_ports is None:
            self._err("pyserial is not installed")
            return
        ports = [p.device for p in list_ports.comports()]
        if not ports:
            self._err("COM Port Not Found")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("COM Port")
        lay = QVBoxLayout(dialog)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)
        title = QLabel("Select COM Port")
        lay.addWidget(title)
        box = QComboBox()
        box.addItems(ports)
        lay.addWidget(box)
        row = QHBoxLayout()
        ok, cancel = QPushButton("CONNECT"), QPushButton("CANCEL")
        for b in (ok, cancel):
            row.addWidget(b)
        lay.addLayout(row)
        ui.skin_dialog(dialog, title, box, ok, cancel)
        ok.clicked.connect(lambda: self._open_port(box.currentText().strip(), dialog))
        cancel.clicked.connect(dialog.reject)
        dialog.exec()

    def _open_port(self, port, dialog=None):
        if not port:
            self._err("COM Port Not Found")
            if dialog:
                dialog.reject()
            return
        try:
            import serial
            self._ser = serial.Serial(port, int(self.baud_box.currentData() or 9600), timeout=0)
        except Exception as exc:
            self._ser = None
            self._port = None
            self._err(f"Connection Error: {exc}"[:80])
            self.connect_button.setText("CONNECT")
            if dialog:
                dialog.reject()
            return
        self._port = port
        self._buffer.clear()
        self.connect_button.setText("DISCONNECT")
        self._ok(f"Connected to {port}")
        if dialog:
            dialog.accept()
        # Warm-up: read the stored configuration once; its reply stays out of the terminal.
        import time
        self._mute_until = time.monotonic() + CONNECT_MUTE_MS / 1000.0
        self._send_line("GETCFG", kind="warmup", attempts=1)

    def _close_port(self):
        try:
            if self._ser is not None:
                self._ser.close()
        except Exception:
            pass
        self._ser = None
        self._port = None
        self._buffer.clear()

    def _check_port(self):
        if not self._connected() or self._port is None or list_ports is None:
            return
        try:
            if self._port not in {p.device for p in list_ports.comports()}:
                self._cancel_request()
                self._close_port()
                self.connect_button.setText("CONNECT")
                self._err("COM Port Disconnected")
        except Exception:
            pass

    # ---------------------------------------------------------------- request engine
    def _send_line(self, text, kind, attempts=1, timeout_ms=REPLY_TIMEOUT_MS, ctx=None):
        """Send one ASCII command and wait for its reply. `attempts` > 1 repeats it on timeout."""
        if not self._connected():
            self._err("Please connect to the COM port first")
            return False
        if self._req is not None and self._req["kind"] != "warmup":
            return False                        # one request at a time
        self._req = {"kind": kind, "text": text, "attempts": attempts, "tries": 0, "timeout": timeout_ms,
                     "ctx": ctx or {}, "waited": 0}
        return self._transmit()

    def _transmit(self):
        req = self._req
        try:
            self._ser.reset_input_buffer()
            self._buffer.clear()
            payload = (req["text"] + "\n").encode("ascii")
            self._ser.write(payload)
            self._ser.flush()
            _dbg("TX", payload, f"kind={req['kind']} try={req['tries'] + 1}/{req['attempts']}")
        except Exception:
            self._finish(req["kind"], False, req["ctx"])
            return False
        req["tries"] += 1
        req["waited"] = 0
        return True

    def _cancel_request(self):
        self._req = None
        self.apply_button.setEnabled(True)

    def _poll(self):
        if not self._connected():
            return
        try:
            waiting = self._ser.in_waiting
            if waiting:
                chunk = self._ser.read(waiting)
                _dbg("RX", chunk)
                self._buffer.extend(chunk)
            if len(self._buffer) > 4096:
                del self._buffer[:-4096]
        except Exception:
            return
        while b"\n" in self._buffer:
            raw, _, rest = bytes(self._buffer).partition(b"\n")
            self._buffer = bytearray(rest)
            line = raw.decode("ascii", errors="replace").strip()
            if line:
                self._on_line(line)
        req = self._req
        if req is not None:
            req["waited"] += POLL_MS
            if req["waited"] >= req["timeout"]:
                if req["tries"] < req["attempts"]:
                    self._transmit()                 # reply lost: send the same command again
                else:
                    self._finish(req["kind"], False, req["ctx"], timeout=True)

    def _on_line(self, line):
        import time
        req = self._req
        muted = (req is None or req["kind"] == "warmup") and time.monotonic() < self._mute_until
        if not muted:
            self.add_terminal_message(line)
        self._parse_config(line)
        if req is None:
            return
        kind = req["kind"]
        upper = re.sub(r"\s+", " ", line).strip().upper()
        is_error = bool(re.match(r"^(?:ERR|ERROR|FAIL|FAILED|NAK|INVALID)\b", upper))
        if kind == "apply":
            if "SETTINGS UPDATED" in upper:
                self._finish("apply", True, req["ctx"])
            elif is_error:
                self._finish("apply", False, req["ctx"])
        elif kind == "refresh":
            self._finish("refresh", True, req["ctx"])
        elif kind == "warmup":
            self._finish("warmup", True, req["ctx"])
        elif kind == "ratio":
            which, value = req["ctx"]["type"], req["ctx"]["value"]
            m = re.search(rf"(?:^|[,\s]){which}_RATIO\s*=\s*(\d+)", line, re.I)
            if upper in (f"OK {which}", f"OK:{which}"):
                self._finish("ratio", True, req["ctx"])
            elif m:
                self._finish("ratio", int(m.group(1)) == value, req["ctx"])
            elif is_error:
                self._finish("ratio", False, req["ctx"])
        elif kind == "channel":
            if re.match(r"^>{0,2}\s*OK\s*:?\s*A?OUT$", line, re.I):
                self._finish("channel", True, req["ctx"])
            elif is_error:
                self._finish("channel", False, req["ctx"])

    def _parse_config(self, line):
        """GETCFG style replies: SID=.. BAUD=.. CT_RATIO=.. PT_RATIO=.. fill the page."""
        m = re.search(r"(?:^|[,\s])SID\s*=\s*(\d+)", line, re.I)
        if m and SLAVE_ID_MIN <= int(m.group(1)) <= SLAVE_ID_MAX:
            self.slave_edit.setText(m.group(1))
        m = re.search(r"(?:^|[,\s])(?:MBD_)?BAUD\s*=\s*(\d+)", line, re.I)
        if m and self.baud_box.findData(int(m.group(1))) >= 0:
            self.baud_box.setCurrentIndex(self.baud_box.findData(int(m.group(1))))
        for kind, box in (("CT", self.ct_box), ("PT", self.pt_box)):
            m = re.search(rf"(?:^|[,\s]){kind}_RATIO\s*=\s*(\d+)", line, re.I)
            if m:
                box.edit.setText(str(int(m.group(1))))

    def _finish(self, kind, ok, ctx, timeout=False):
        self._req = None
        if kind == "apply":
            self.apply_button.setEnabled(True)
            if ok:
                target = ctx.get("baud")
                if target and self._connected():
                    try:
                        self._ser.baudrate = target        # the module now answers at the new baud
                    except Exception:
                        pass
                self._ok("RTU Settings Applied")
            else:
                self._err("RTU Settings Not Applied")
        elif kind == "refresh":
            if ok:
                self._ok("Configuration Loaded")
            else:
                self._err("Configuration Not Loaded")
        elif kind == "ratio":
            which = ctx["type"]
            self._ok(f"{which} Ratio Applied") if ok else self._err(f"{which} Ratio Not Applied")
        elif kind == "channel":
            n = ctx["channel"] + 1
            self._ok(f"Channel {n} Applied") if ok else self._err(f"Channel {n} Not Applied")

    # ---------------------------------------------------------------- actions
    def handle_apply_rtu(self):
        if not self._connected():
            self._err("Please connect to the COM port first")
            return
        try:
            sid = int(self.slave_edit.text().strip())
        except ValueError:
            sid = 0
        if not SLAVE_ID_MIN <= sid <= SLAVE_ID_MAX:
            self.slave_edit.setText(str(SLAVE_ID_MIN))
            self._err("RTU Settings Not Applied")
            return
        baud = int(self.baud_box.currentData())
        self.apply_button.setEnabled(False)
        self._info("Applying... waiting for device response")
        if not self._send_line(f"SID={sid},MBD_BAUD={baud}", "apply", attempts=MAX_ATTEMPTS, ctx={"baud": baud}):
            self.apply_button.setEnabled(True)

    def handle_refresh(self):
        if not self._connected():
            self._err("Please connect to the COM port first")
            return
        if self._req is not None and self._req["kind"] != "warmup":
            return
        self._send_line("GETCFG", "refresh", attempts=MAX_ATTEMPTS)

    def handle_ratio_apply(self, which):
        box = self.ct_box if which == "CT" else self.pt_box
        problem = ratio_error(box.edit.text())
        if problem:
            self._err(f"{which} Ratio {problem} (valid: 0 to {RATIO_MAX})")
            return
        value = box.value()
        box.edit.setText(str(value))
        if not self._connected():
            self._err("Please connect to the COM port first")
            return
        if not self._send_line(f"{which}_RATIO={value}", "ratio", attempts=1,
                               ctx={"type": which, "value": value}):
            self._err(f"{which} Ratio Not Applied")

    def handle_back(self):
        self._cancel_request()
        self._close_port()
        self.connect_button.setText("CONNECT")
        self._set_status("Not Connected", GREEN)
        self._terminal_lines = ["Device Terminal Ready"]
        self.terminal.setPlainText("Device Terminal Ready")
        self.back_clicked.emit()


# ------------------------------------------------------------------ MFT
class MFTView(_MFTBase):
    """MFT: RTU slave settings + CT / PT ratio."""

    PAGE_TITLE = "MFT Transducer"

    def _right_panel(self):
        panel = ui.card()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(14)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_col.addWidget(ui.label("CT / PT Ratio", "pgTitle"))
        title_col.addWidget(ui.label("Current and potential transformer ratio of the transducer", "pgSub"))
        lay.addLayout(title_col)
        self.ct_box = RatioBox("CT", "CT RATIO")
        self.pt_box = RatioBox("PT", "PT RATIO")
        row = QHBoxLayout()
        row.setSpacing(16)
        for b in (self.ct_box, self.pt_box):
            b.applied.connect(self.handle_ratio_apply)
            row.addWidget(b, 1)
        lay.addLayout(row)
        lay.addStretch(1)
        return panel