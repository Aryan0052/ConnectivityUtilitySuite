import csv
import json
import ipaddress
import socket
import time
import os
from datetime import datetime
import html
import threading
from PySide6.QtCore import Qt, QEvent, Signal, QTimer, QPropertyAnimation, QPoint, QPointF, QRectF, QSize
from PySide6.QtGui import QPainterPath, QLinearGradient, QPixmap, QPainter, QPen, QColor, QIcon, QPolygonF, QRadialGradient, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView, QScrollArea,
    QGridLayout, QStackedWidget, QCheckBox, QPlainTextEdit, QSplitter, QGraphicsOpacityEffect, QSpinBox, QLineEdit, QMessageBox, QSizePolicy, QTabWidget,
    QFileDialog, QListView
)
try:
    from pymodbus.client import ModbusSerialClient
except ImportError:
    ModbusSerialClient = None
try:
    from pymodbus.client import ModbusTcpClient
except ImportError:
    ModbusTcpClient = None
try:
    from serial.tools import list_ports
except ImportError:
    list_ports = None
try:
    from .modbus_scanner import ModbusScanner
    from .device_data import (DEVICE_PROFILES, device_kind, ALL_FUNCTIONS,
                              is_write_function, max_count, parse_write_values,
                              DATA_FORMATS, WORD_ORDERS, WIDE_FORMATS, ENABLE_FORMATS, effective_format, format_value,
                              MFT_PARAMS)
    from .db_writer import ReadingDatabaseWriter
    from .analytics_view import DashboardTab
    from . import live_console as lc
    from . import modbus_tcp_ip as tcpip     # "Modbus TCP (IP)" connection type
    from .multi_link import ScannerGroup, LINKS, LINK_NAMES, LINK_SHORT, TYPE_TO_LINK, link_of
except ImportError:
    from modbus_scanner import ModbusScanner
    from device_data import (DEVICE_PROFILES, device_kind, ALL_FUNCTIONS,
                             is_write_function, max_count, parse_write_values,
                             DATA_FORMATS, WORD_ORDERS, WIDE_FORMATS, ENABLE_FORMATS, effective_format, format_value,
                              MFT_PARAMS)
    from db_writer import ReadingDatabaseWriter
    from analytics_view import DashboardTab
    import live_console as lc
    import modbus_tcp_ip as tcpip
    from multi_link import ScannerGroup, LINKS, LINK_NAMES, LINK_SHORT, TYPE_TO_LINK, link_of

class _NoAlarms:
    """Alarms feature removed: stand-in so the Dashboard keeps working (always 0 alarms)."""
    limits = {}
    revision = 0
    history = []

    def counts(self):
        return (0, 0)

    def active_list(self):
        return []

    def on_status(self, *a, **k):
        pass

    def on_reading(self, *a, **k):
        pass

    def clear_all(self, *a, **k):
        pass

    def clear_device(self, *a, **k):
        pass


_STATUS_TEXT = {
    "ONLINE": "ONLINE",
    "OFFLINE": "OFFLINE",
    "RETRYING": "RETRYING",
    "DISABLED": "DISABLED",
    "NOT_POLLED": "NOT POLLED",
    "WRITE": "WRITE ONLY",
}
_STATUS_COLORS = {
    "WRITE ONLY": "#C77700",
    "ONLINE": "#12A45B",
    "OFFLINE": "#E53935",
    "RETRYING": "#D88B00",
    "DISABLED": "#7A8C99",
    "NOT POLLED": "#7A8C99",
}
_STATUS_OBJECT = {
    "ONLINE": "statusOnline",
    "OFFLINE": "statusOffline",
    "RETRYING": "statusRetry",
}


def _empty_device_stats():
    return {"tx": 0, "rx": 0, "successful": 0, "timeouts": 0, "retries": 0, "errors": 0}


import re as _re

# ---- UI scale: every pixel size in the style sheets grows with the window ----
_UI_SCALE = 1.0
_PX = _re.compile(r"(\d+(?:\.\d+)?)px")


def _scaled(text, factor):
    if factor == 1.0:
        return text

    def one(m):
        v = float(m.group(1))
        return m.group(0) if v <= 1 else f"{max(2, int(round(v * factor)))}px"
    return _PX.sub(one, text)


# ---- Light / Dark theme -------------------------------------------------------
# Every style sheet is written once, in the light palette. In the dark theme the colours of
# each declaration are re-mapped by role (text / background / border) at the moment the sheet is
# applied, so one source serves both themes and a switch only re-applies the stored sheets.
import colorsys as _colorsys

_THEME = "light"
_KEEP_HEX = {"0CAFC4", "087FC8", "0759A4"}                 # header gradient: same in both themes
_RULE = _re.compile(r"([^{}]+)\{([^{}]*)\}")
_DECL = _re.compile(r"([\w-]+)\s*:\s*([^;{}]+)")
_HEX6 = _re.compile(r"#([0-9A-Fa-f]{6})")


def _dark_hex(hex6, role):
    """Light-palette colour -> the 'Test Mode' dark palette (#0d1117 / #161b22 / #262c36, blue #2f81f7)."""
    if hex6.upper() == "FFFFFF" and role == "text":
        return "#FFFFFF"
    r, g, b = (int(hex6[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    h, l, s = _colorsys.rgb_to_hls(r, g, b)
    neutral = s < 0.30 or (0.5 < h < 0.72 and s < 0.6 and l > 0.7) or (0.5 < h < 0.72 and l > 0.85)
    if role == "text":
        if l >= 0.62:
            return "#" + hex6
        if s > 0.45 and (h < 0.03 or h > 0.95):
            return "#F06A64"                                   # red
        if s > 0.45 and 0.06 < h < 0.16:
            return "#E3A33B"                                   # amber
        if s > 0.35 and 0.22 < h < 0.45:
            return "#3FB76A"                                   # green
        if s > 0.45 and l >= 0.42 and 0.5 < h < 0.72:
            return "#4C9AFF"                                   # accent blue
        if s > 0.45 and l >= 0.42:
            return "#" + hex6
        if l >= 0.42:
            return "#8B939E"                                   # muted
        return "#ECEFF3" if l < 0.30 else "#C4CAD2"            # primary / secondary text
    if role == "border":
        if l < 0.55:
            return "#" + hex6
        return "#22272F" if neutral else _dark_fill(h, s, 0.24, 0.5)
    # background
    if hex6.upper() in ("F3F8FC", "0B2239"):
        return "#0C0E12"
    if l >= 0.995:
        return "#13161B"
    if neutral:
        if l >= 0.95:
            return "#181C22"
        if l >= 0.90:
            return "#1D2229"
        if l >= 0.80:
            return "#22272F"
        if l >= 0.65:
            return "#2C323B"
        return "#" + hex6
    if l >= 0.72:
        return _dark_fill(h, s, 0.16 + (0.9 - min(l, 0.9)) * 0.3, 0.55)     # tinted pills / badges
    return "#" + hex6


def _dark_fill(h, s, l, k):
    r, g, b = _colorsys.hls_to_rgb(h, min(0.4, l), min(0.7, max(0.25, s * k)))
    return "#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))


def _role_of(prop):
    p = prop.lower()
    if "background" in p:
        return "bg"
    if p.startswith("border") or p == "outline":
        return "border"
    if p in ("color", "selection-color"):
        return "text"
    return None


def _dark_decls(body):
    def one(m):
        role = _role_of(m.group(1))
        if role is None:
            return m.group(0)
        value = _HEX6.sub(lambda h: "#" + h.group(1) if h.group(1).upper() in _KEEP_HEX
                          else _dark_hex(h.group(1), role), m.group(2))
        return f"{m.group(1)}:{value}"
    return _DECL.sub(one, body)


def _dark_qss(text):
    if "{" not in text:
        return _dark_decls(text)

    def rule(m):
        if "#header" in m.group(1) and "QFrame#header" in m.group(1):
            return "QFrame#header { background:#13161B; border:0; border-bottom:1px solid #22272F; }"
        return f"{m.group(1)}{{{_dark_decls(m.group(2))}}}"
    return _RULE.sub(rule, text)


def _themed(text):
    return text if _THEME == "light" else _dark_qss(text)


def tc(hex_, role="bg"):
    """QColor of a light-palette colour for painted widgets: re-mapped in the dark theme."""
    h = hex_.lstrip("#")
    return QColor("#" + (h if _THEME == "light" else _dark_hex(h, role).lstrip("#")))


def _ss(widget, text, k=1.0):
    """setStyleSheet that remembers the original text so it can be re-scaled / re-themed
    (k = extra local size factor, used by the big Spotlight card)."""
    widget.setProperty("_qss0", text)
    widget.setProperty("_qss_k", k)
    widget.setStyleSheet(_scaled(_themed(text), _UI_SCALE * k))


class BackButton(QPushButton):

    """White circular back button matching the reference image."""



    def __init__(self, parent=None):

        super().__init__(parent)



        self.setFixedSize(44, 44)

        self.setCursor(Qt.PointingHandCursor)

        self.setFocusPolicy(Qt.NoFocus)



        # No text: the arrow is drawn precisely below.

        self.setText("")

        _ss(self, """

            QPushButton {

                background: transparent;

                border: none;

                padding: 0px;

                margin: 0px;

            }

        """)



    def paintEvent(self, event):

        painter = QPainter(self)

        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.scale(self.width() / 58.0, self.height() / 58.0)     # artwork is drawn on a 58 px grid



        # White circular background.

        painter.setPen(Qt.NoPen)

        painter.setBrush(Qt.white)

        painter.drawEllipse(0, 0, 58, 58)



        # Thick dark-blue arrow.

        pen = QPen("#155B91")

        pen.setWidth(6)

        pen.setCapStyle(Qt.RoundCap)

        pen.setJoinStyle(Qt.RoundJoin)

        painter.setPen(pen)



        # Horizontal shaft.

        painter.drawLine(

            QPoint(19, 29),

            QPoint(43, 29)

        )



        # Large arrow head.

        painter.drawLine(

            QPoint(19, 29),

            QPoint(31, 17)

        )



        painter.drawLine(

            QPoint(19, 29),

            QPoint(31, 41)

        )



        painter.end()





class PollingDonut(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._counts = {"ONLINE": 0, "OFFLINE": 0, "RETRYING": 0, "NOT_POLLED": 0}
        self.setMinimumSize(118, 118)

    def set_counts(self, online, offline, retrying, not_polled):
        counts = {
            "ONLINE": max(0, int(online)),
            "OFFLINE": max(0, int(offline)),
            "RETRYING": max(0, int(retrying)),
            "NOT_POLLED": max(0, int(not_polled)),
        }
        if counts != self._counts:
            self._counts = counts
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        side = min(self.width(), self.height())
        rect = QRectF(
            (self.width() - side) / 2 + 9,
            (self.height() - side) / 2 + 9,
            side - 18,
            side - 18,
        )
        total = sum(self._counts.values())
        painter.setPen(QPen(tc("#E7EEF5", "border"), 12))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(rect)

        if total:
            colors = [
                ("ONLINE", "#13B86A"),
                ("OFFLINE", "#F04444"),
                ("RETRYING", "#F2A900"),
                ("NOT_POLLED", "#B5C1CC"),
            ]
            start = 90 * 16
            for key, color in colors:
                count = self._counts[key]
                if not count:
                    continue
                span = int(-360 * 16 * count / total)
                painter.setPen(QPen(QColor(color), 12, Qt.SolidLine, Qt.FlatCap))
                painter.drawArc(rect, start, span)
                start += span

        inner = QRectF(rect.left() + 14, rect.top() + 14, rect.width() - 28, rect.height() - 28)
        painter.setPen(tc("#07528A", "text"))
        font = painter.font()
        font.setFamily("Segoe UI")
        font.setPointSize(15)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(inner.left(), inner.top() + inner.height() * 0.18, inner.width(), inner.height() * 0.4),
                         Qt.AlignCenter, f"{self._counts['ONLINE']} / {total}")
        font.setPointSize(7)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(tc("#5C7A92", "text"))
        painter.drawText(QRectF(inner.left(), inner.top() + inner.height() * 0.55, inner.width(), inner.height() * 0.3),
                         Qt.AlignHCenter | Qt.AlignTop, "Devices Online")
        painter.end()


_TYPE_COLORS = {
    "DI": ("#DFF4FB", "#1383A5"), "DO": ("#E5F8EC", "#11965A"),
    "AI": ("#FFF1D7", "#C97B00"), "AO": ("#F0E7FF", "#7D46C7"),
    "MFT": ("#FFE6EF", "#C2386B"),
}
_TYPE_TITLES = {"DI": "Digital Input", "DO": "Digital Output", "AI": "Analog Input", "AO": "Analog Output",
                "MFT": "MFT Transducer"}
_PILL_COLORS = {
    "ONLINE": ("#E8F8EF", "#12A45B"), "OFFLINE": ("#FFF0F0", "#E53935"),
    "RETRYING": ("#FFF7E7", "#D88B00"),
}


def _make_icon(shape, color):
    """Small crisp icon drawn in code (no image files needed)."""
    size = 32
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(color), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    if shape == "play":
        painter.setBrush(QColor(color))
        painter.drawPolygon(QPolygonF([QPointF(10, 6), QPointF(10, 26), QPointF(26, 16)]))
    elif shape == "stop":
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(QRectF(8, 8, 16, 16), 2, 2)
    else:  # trash
        painter.setBrush(Qt.NoBrush)
        painter.drawLine(QPointF(7, 9), QPointF(25, 9))
        painter.drawLine(QPointF(13, 9), QPointF(13, 5))
        painter.drawLine(QPointF(13, 5), QPointF(19, 5))
        painter.drawLine(QPointF(19, 5), QPointF(19, 9))
        painter.drawPolyline(QPolygonF([QPointF(9, 12), QPointF(10.5, 27), QPointF(21.5, 27), QPointF(23, 12)]))
        painter.drawLine(QPointF(14, 15), QPointF(14, 23))
        painter.drawLine(QPointF(18, 15), QPointF(18, 23))
    painter.end()
    return QIcon(pixmap)


class LedDot(QWidget):
    """One channel LED: 1 = green with a soft glow, 0 = grey, None = no data."""
    def __init__(self, parent=None, on_click=None, size=16):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._state = None
        self._on_click = on_click
        if on_click is not None:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip("Click to switch this output ON / OFF")

    def mousePressEvent(self, event):
        if self._on_click is not None and event.button() == Qt.LeftButton:
            self._on_click()
            event.accept()
        else:
            super().mousePressEvent(event)

    def set_state(self, state):
        if state != self._state:
            self._state = state
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        d = float(self.width())
        s = d / 16.0
        if self._state == 1:
            glow = QRadialGradient(d / 2, d / 2, d / 2)
            glow.setColorAt(0.45, QColor(24, 196, 110, 150))
            glow.setColorAt(1.0, QColor(24, 196, 110, 0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(QRectF(0, 0, d, d))
            inset = 2.6 * s
            core = QRadialGradient(d / 2 - 1.2 * s, d / 2 - 1.2 * s, d / 2)
            core.setColorAt(0.0, QColor("#7DF0B0"))
            core.setColorAt(1.0, QColor("#18C46E"))
            painter.setPen(QPen(QColor("#0E9F55"), max(1.0, s * 0.8)))
            painter.setBrush(core)
        else:
            fill, edge = {0: ("#C9D3DC", "#B5C2CD")}.get(self._state, ("#E8EEF3", "#D5DEE6"))
            inset = 1.8 * s
            painter.setPen(QPen(tc(edge, "border"), max(1.0, s * 0.8)))
            painter.setBrush(tc(fill, "bg"))
        painter.drawEllipse(QRectF(inset, inset, d - 2 * inset, d - 2 * inset))
        painter.end()


class _Default:
    """Fixed default (replaces the removed Scan & Poll Settings spin boxes)."""
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value


def active_channels(device):
    """Names of the DI/DO channels that are 1 in the latest reading."""
    if device.get("kind") not in ("DI", "DO"):
        return []
    return [name for name, value in (device.get("latest_data") or []) if value]


_MFT_SUMMARY = (("V avg", "V"), ("I avg", "A"), ("P total", "W"), ("Q total", "var"),
                ("S total", "VA"), ("PF avg", ""), ("Freq avg", "Hz"), ("V THD avg", "%"))


def _finite(values):
    return [v for v in values if isinstance(v, (int, float)) and v == v and abs(v) != float("inf")]


def mft_summary(values):
    """The 8 summary numbers of an MFT card from {param: value} (None when not read yet)."""
    def mean(names):
        found = _finite([values.get(n) for n in names])
        return sum(found) / len(found) if found else None

    def total(names):
        found = _finite([values.get(n) for n in names])
        return sum(found) if found else None
    return [mean(("AVrms", "BVrms", "CVrms")), mean(("IA", "IB", "IC")),
            total(("P_A", "P_B", "P_C")), total(("Q_A", "Q_B", "Q_C")), total(("S_A", "S_B", "S_C")),
            mean(("PF_A", "PF_B", "PF_C")), mean(("FreqA", "FreqB", "FreqC")),
            mean(("VTHD_A", "VTHD_B", "VTHD_C"))]


def mft_text(value, unit):
    """One MFT value for a tile: '230.12 V' / '--'."""
    if not _finite([value]):
        return "--"
    magnitude = abs(value)
    text = f"{value:.0f}" if magnitude >= 10000 else (f"{value:.1f}" if magnitude >= 1000 else f"{value:.2f}")
    return f"{text} {unit}" if unit else text


WRITE_TIMEOUT_MS = 2000      # every write waits this long for the device's reply (polls keep their own timeout)

DO_WRITE_MODES = {           # first entry = default (same as the Modbus Monitor screen: FC15, one coil)
    15: "15 - Multiple Coils (one coil)",
    5: "05 - Write Single Coil",
    1500: "15 - Multiple Coils (all outputs)",
    6: "06 - Register (16 outputs as bits)",
}


class ClickLabel(QLabel):
    """Panel title that can be clicked (enlarge / restore the panel)."""
    clicked = Signal()

    def __init__(self, text=""):
        super().__init__(text)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class TerminalEdit(QPlainTextEdit):
    """Terminal whose text grows and shrinks with its own size.
    Ctrl + mouse wheel sets the size by hand (Ctrl + 0 returns to automatic)."""
    MIN_PX, MAX_PX = 9, 22

    def __init__(self):
        super().__init__()
        self._manual_px = None
        self._applied_px = None

    def _auto_px(self):
        return max(self.MIN_PX, min(self.MAX_PX, int(self.width() / 50.0)))

    def _apply_font(self):
        px = self._manual_px or self._auto_px()
        if px != self._applied_px:
            self._applied_px = px
            self.setStyleSheet(f"QPlainTextEdit#terminal {{ font-size:{px}px; }}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_font()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            base = self._manual_px or self._applied_px or self._auto_px()
            step = 1 if event.angleDelta().y() > 0 else -1
            self._manual_px = max(self.MIN_PX, min(self.MAX_PX, base + step))
            self._apply_font()
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event):
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_0:
            self._manual_px = None
            self._apply_font()
            return
        super().keyPressEvent(event)


def _id_text(device):
    """How a device is addressed: 'IP:port' for a Modbus TCP device, 'Slave N' on the serial bus."""
    if tcpip.is_device(device):
        return tcpip.id_text(device)
    if device.get("host"):
        return f"{device['host']}:{device.get('tcp_port') or 502} \u00b7 ID {device.get('unit') or 1}"
    if device.get("link") == "gateway":
        return f"TCP \u00b7 ID {device['slave_id']}"
    return f"Slave {device['slave_id']}"


def _id_line(device):
    if tcpip.is_device(device):
        return tcpip.id_line(device)
    if device.get("host"):
        return f"IP : Port     : {device['host']}:{device.get('tcp_port') or 502}\nDevice ID    : {device.get('unit') or 1}"
    return f"Slave ID     : {device['slave_id']}"


class Sparkline(QWidget):
    """Tiny live response-time trend drawn under each device card (themed, no extra libraries)."""
    def __init__(self):
        super().__init__()
        self._data = []
        self._color = "#168CF0"
        self.setFixedHeight(26)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def set_data(self, data, color):
        data = list(data)
        if data != self._data or color != self._color:
            self._data, self._color = data, color
            self.update()

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        base = tc("#D6E7F2", "border")
        p.setPen(QPen(base, 1, Qt.DotLine))
        p.drawLine(0, h - 2, w, h - 2)
        d = self._data
        if len(d) >= 2:
            lo, hi = min(d), max(d)
            span = max(1.0, hi - lo)
            step = w / (len(d) - 1)
            pts = [QPointF(i * step, h - 4 - (v - lo) / span * (h - 9)) for i, v in enumerate(d)]
            path = QPainterPath(pts[0])
            for pt in pts[1:]:
                path.lineTo(pt)
            fill = QPainterPath(path)
            fill.lineTo(w, h - 2)
            fill.lineTo(0, h - 2)
            fill.closeSubpath()
            col = QColor(self._color)
            grad = QLinearGradient(0, 0, 0, h)
            top = QColor(col); top.setAlpha(90)
            bot = QColor(col); bot.setAlpha(0)
            grad.setColorAt(0, top); grad.setColorAt(1, bot)
            p.fillPath(fill, grad)
            p.setPen(QPen(col, 1.6))
            p.drawPath(path)
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawEllipse(pts[-1], 2.6, 2.6)
        p.end()


class DeviceCard(QFrame):
    """Live status card: DI/DO = 16 LEDs (2 rows of 8), AI = 8 value tiles,
    AO = 4 value tiles. refresh() only touches widgets whose content changed."""
    def __init__(self, device, on_led_click=None, big=False, on_open=None, on_format=None):
        super().__init__()
        self.setObjectName("deviceCard")
        k = 1.8 if big else 1.0
        self._k = k
        self._big = big
        self._on_open = on_open
        self._accent = None
        if on_open is not None:
            self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred if big else QSizePolicy.Fixed)
        self._kind = device.get("kind")
        self._cache = {}
        self._leds = []
        self._tiles = []
        self._text = None
        self._mft_big, self._mft_defs, self._regs, self._mft_vals = False, [], [], {}

        root = QVBoxLayout(self)
        root.setContentsMargins(int(12 * k), int(9 * k), int(10 * k), int(9 * k))
        root.setSpacing(int(6 * k))

        head = QHBoxLayout()
        head.setSpacing(8)
        bg, fg = _TYPE_COLORS.get(self._kind, ("#EEF2F5", "#718391"))
        icon = QLabel(self._kind or "?")
        icon.setFixedSize(int(34 * k), int(34 * k))
        icon.setAlignment(Qt.AlignCenter)
        _ss(icon, f"background:{bg};color:{fg};border-radius:8px;font-size:11px;font-weight:800;", k)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        name = QLabel(device["name"])
        name.setObjectName("deviceTitle")
        sub = QLabel(_id_text(device) if device.get("host") else f'Slave ID: {device["slave_id"]}')
        sub.setObjectName("deviceType")
        titles.addWidget(name)
        titles.addWidget(sub)
        self._status = QLabel()
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setMinimumWidth(int(78 * k))
        # DI/DO: green badge with how many channels are HIGH / ON right now
        self._active = QLabel()
        self._active.setAlignment(Qt.AlignCenter)
        _ss(self._active, "background:#18C46E;color:white;border-radius:5px;"
                                   "padding:3px 8px;font-size:9px;font-weight:800;", k)
        self._active.setVisible(False)
        head.addWidget(icon)
        head.addLayout(titles, 1)
        head.addWidget(self._active, 0, Qt.AlignTop)
        head.addWidget(self._status, 0, Qt.AlignTop)
        root.addLayout(head)

        type_label = QLabel(_TYPE_TITLES.get(self._kind, device.get("type", "")))
        _ss(type_label, "color:#174F78;font-size:10px;font-weight:700;", k)
        type_row = QHBoxLayout()
        type_row.setSpacing(5)
        type_row.addWidget(type_label)
        type_row.addStretch(1)
        self._fmt_box = self._order_box = None
        if ENABLE_FORMATS and on_format is not None and int(device.get("function", 0)) in (3, 4) and self._kind in ("AI", "AO"):
            self._fmt_box = QComboBox()
            for code, text in DATA_FORMATS.items():
                self._fmt_box.addItem(text.split(" (")[0].split(" - ")[0], code)
            self._order_box = QComboBox()
            for code in WORD_ORDERS:
                self._order_box.addItem(code, code)
            for box, tip in ((self._fmt_box, "Output format of the registers"),
                             (self._order_box, "32-bit word order: MSRF = high register first, LSRF = low register first")):
                box.setView(QListView())
                box.setToolTip(tip)
                box.setCursor(Qt.PointingHandCursor)
                _ss(box, "QComboBox{min-height:20px;max-height:22px;font-size:9px;font-weight:700;padding:0 4px;"
                         "border:1px solid #A9D3F2;border-radius:4px;color:#07528A;background:#F2F8FC;}"
                         "QComboBox::drop-down{width:14px;border:0;}", k)
                type_row.addWidget(box)
            self._fmt_box.setCurrentIndex(max(0, self._fmt_box.findData(effective_format(device))))
            self._order_box.setCurrentIndex(max(0, self._order_box.findData(device.get("word_order") or "MSRF")))
            self._order_box.setVisible(self._fmt_box.currentData() in WIDE_FORMATS)

            def changed(_i=None, cb=on_format):
                fmt, order = self._fmt_box.currentData(), self._order_box.currentData()
                self._order_box.setVisible(fmt in WIDE_FORMATS)
                cb(fmt, order)
            self._fmt_box.currentIndexChanged.connect(changed)
            self._order_box.currentIndexChanged.connect(changed)
        root.addLayout(type_row)

        if self._kind in ("DI", "DO"):
            grid = QGridLayout()
            grid.setHorizontalSpacing(int(4 * k))
            grid.setVerticalSpacing(int(2 * k * (3 if big else 1)))
            for index in range(16):
                row, column = (index // 8) * 2, index % 8
                label = QLabel(f"{self._kind}{index + 1}")
                label.setObjectName("channelLabel")
                led = LedDot(on_click=(lambda i=index: on_led_click(i)) if on_led_click else None, size=int(16 * k * (1.45 if big else 1.0)))
                grid.addWidget(label, row, column, Qt.AlignHCenter)
                grid.addWidget(led, row + 1, column, Qt.AlignHCenter)
                self._leds.append(led)
            root.addLayout(grid)
        elif self._kind in ("AI", "AO"):
            grid = QGridLayout()
            grid.setHorizontalSpacing(int(6 * k))
            grid.setVerticalSpacing(int(6 * k))
            for index in range(8 if self._kind == "AI" else 4):
                tile = QFrame()
                tile.setObjectName("tile")
                tile_layout = QVBoxLayout(tile)
                tile_layout.setContentsMargins(4, 3 if not big else 10, 4, 3 if not big else 10)
                tile_layout.setSpacing(0)
                name_label = QLabel(f"{self._kind}{index + 1}")
                name_label.setObjectName("tileName")
                name_label.setAlignment(Qt.AlignCenter)
                value_label = QLabel("--")
                value_label.setObjectName("tileValue")
                value_label.setAlignment(Qt.AlignCenter)
                tile_layout.addWidget(name_label)
                tile_layout.addWidget(value_label)
                grid.addWidget(tile, index // 4, index % 4)
                self._tiles.append(value_label)
            root.addLayout(grid)
        elif self._kind == "MFT" and big:
            self._mft_big = True
            self._build_mft_panel(root, k)
        elif self._kind == "MFT":
            # small card: 8 summary tiles; detail (big) card: all 40 parameters with their units
            self._mft_big = big
            self._mft_defs = list(MFT_PARAMS) if big else list(_MFT_SUMMARY)
            columns = 6 if big else 4
            grid = QGridLayout()
            grid.setHorizontalSpacing(int(6 * k))
            grid.setVerticalSpacing(int(6 * k))
            for index, (title, _unit) in enumerate(self._mft_defs):
                tile = QFrame()
                tile.setObjectName("tile")
                tile_layout = QVBoxLayout(tile)
                tile_layout.setContentsMargins(4, 3, 4, 3)
                tile_layout.setSpacing(0)
                name_label = QLabel(title)
                name_label.setObjectName("tileName")
                name_label.setAlignment(Qt.AlignCenter)
                value_label = QLabel("--")
                value_label.setObjectName("tileValue")
                value_label.setAlignment(Qt.AlignCenter)
                _ss(name_label, "color:#35566F;font-weight:700;", k)          # explicit, dark enough on white
                _ss(value_label, "color:#0A3556;font-weight:800;", k)
                if big:
                    value_label.setObjectName("mftValue")      # sized by the big-card stylesheet below
                tile_layout.addWidget(name_label)
                tile_layout.addWidget(value_label)
                grid.addWidget(tile, index // columns, index % columns)
                self._tiles.append(value_label)
            root.addLayout(grid)
            self._regs = []
        else:
            self._text = QLabel()
            self._text.setWordWrap(True)
            self._text.setObjectName("value")
            root.addWidget(self._text)

        self._spark = Sparkline()
        root.addWidget(self._spark)
        self._footer = QLabel()
        self._footer.setObjectName("muted")
        root.addWidget(self._footer)
        if big:
            _ss(self, "QFrame#deviceCard { background:#FFFFFF; border:1px solid #CDE3F1; border-radius:14px; }"
                      "QLabel#deviceTitle { font-size:17px; } QLabel#deviceType { font-size:11px; }"
                      "QLabel#channelLabel { font-size:10px; } QLabel#tileName { font-size:10px; }"
                      "QLabel#tileValue { font-size:21px; } QLabel#muted { font-size:11px; }"
                      "QLabel#value { font-size:14px; padding:10px; } QLabel#mftValue { font-size:14px; font-weight:700; }")

    def _build_mft_panel(self, root, k):
        """Detail (Spotlight) layout of an MFT: totals strip, R / Y / B phase cards, line voltage + angles."""
        def value_label(key, size=15, color="#0A3556"):
            label = QLabel("--")
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            _ss(label, f"color:{color};font-size:{size}px;font-weight:800;", 1.0)
            self._mft_vals[key] = label
            return label

        def small(text, color="#4A6A82", bold=True):
            label = QLabel(text)
            _ss(label, f"color:{color};font-size:11px;font-weight:{700 if bold else 500};", 1.0)
            return label

        # ---- totals strip
        strip = QHBoxLayout()
        strip.setSpacing(8)
        for key, title, accent in (("T_P", "ACTIVE POWER", "#18A864"), ("T_Q", "REACTIVE POWER", "#7D46C7"),
                                   ("T_S", "APPARENT POWER", "#1383A5"), ("T_PF", "POWER FACTOR", "#C97B00"),
                                   ("T_F", "FREQUENCY", "#D9467B")):
            box = QFrame()
            box.setObjectName("kpi")
            _ss(box, f"QFrame#kpi{{background:#FFFFFF;border:1px solid #D5E5F0;border-top:3px solid {accent};"
                     "border-radius:8px;}}", 1.0)
            lay = QVBoxLayout(box)
            lay.setContentsMargins(10, 6, 10, 6)
            lay.setSpacing(0)
            lay.addWidget(small(title))
            big_value = value_label(key, 21)
            big_value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            lay.addWidget(big_value)
            strip.addWidget(box, 1)
        root.addLayout(strip)

        # ---- R / Y / B phase cards
        rows = (("Voltage", "V", "{v}"), ("Current", "I", "{i}"), ("Active power", "P", "P_{p}"),
                ("Reactive power", "Q", "Q_{p}"), ("Apparent power", "S", "S_{p}"), ("Power factor", "PF", "PF_{p}"),
                ("Frequency", "F", "Freq{p}"), ("Voltage THD", "VT", "VTHD_{p}"), ("Current THD", "IT", "ITHD_{p}"),
                ("V-I angle", "ANG", "{ang}"))
        phases = (("R", "R PHASE", "#D93F3F", "A", "AVrms", "IA", "VA_IA"),
                  ("Y", "Y PHASE", "#D99A00", "B", "BVrms", "IB", "VB_IB"),
                  ("B", "B PHASE", "#2F6FDB", "C", "CVrms", "IC", "VC_IC"))
        cards = QHBoxLayout()
        cards.setSpacing(8)
        for tag, title, color, letter, vname, iname, angle in phases:
            card = QFrame()
            card.setObjectName("phase")
            _ss(card, "QFrame#phase{background:#FFFFFF;border:1px solid #D5E5F0;border-radius:10px;}", 1.0)
            lay = QVBoxLayout(card)
            lay.setContentsMargins(0, 0, 0, 6)
            lay.setSpacing(0)
            head = QLabel(title)
            head.setAlignment(Qt.AlignCenter)
            _ss(head, f"background:{color};color:white;font-size:12px;font-weight:800;letter-spacing:1px;"
                      "border-top-left-radius:9px;border-top-right-radius:9px;padding:5px;", 1.0)
            lay.addWidget(head)
            grid = QGridLayout()
            grid.setContentsMargins(12, 8, 12, 2)
            grid.setHorizontalSpacing(8)
            grid.setVerticalSpacing(5)
            for r, (label, _code, pattern) in enumerate(rows):
                key = pattern.format(v=vname, i=iname, p=letter, ang=angle)
                grid.addWidget(small(label), r, 0)
                grid.addWidget(value_label(key, 17 if r < 2 else 14, color if r < 2 else "#0A3556"), r, 1)
            grid.setColumnStretch(1, 1)
            lay.addLayout(grid)
            cards.addWidget(card, 1)
        root.addLayout(cards)

        # ---- line voltages, neutral current, angles
        extra = QFrame()
        extra.setObjectName("extra")
        _ss(extra, "QFrame#extra{background:#F4F9FD;border:1px solid #D5E5F0;border-radius:10px;}", 1.0)
        lay = QGridLayout(extra)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setHorizontalSpacing(14)
        lay.setVerticalSpacing(4)
        groups = (("LINE VOLTAGE", (("RY", "VAB"), ("YB", "VBC"), ("BR", "VCA"))),
                  ("NEUTRAL", (("IN", "IN"),)),
                  ("VOLTAGE ANGLES", (("R-Y", "VA_VB"), ("Y-B", "VB_VC"), ("R-B", "VA_VC"))),
                  ("CURRENT ANGLES", (("R-Y", "IA_IB"), ("Y-B", "IB_IC"), ("R-B", "IA_IC"))))
        for col, (title, items) in enumerate(groups):
            lay.addWidget(small(title, "#174F78"), 0, col * 2, 1, 2)
            for r, (label, key) in enumerate(items, 1):
                lay.addWidget(small(label), r, col * 2)
                lay.addWidget(value_label(key, 13), r, col * 2 + 1)
        root.addWidget(extra)

    def _refresh_mft_panel(self, values):
        units = dict(MFT_PARAMS)

        def power(number, unit):
            if not _finite([number]):
                return "--"
            return f"{number / 1000:.2f} k{unit}" if abs(number) >= 1000 else f"{number:.1f} {unit}"
        texts = {}
        for key in self._mft_vals:
            if key in ("T_P", "T_Q", "T_S", "T_PF", "T_F"):
                continue
            number = values.get(key)
            if key[:2] in ("P_", "Q_", "S_"):
                texts[key] = power(number, units.get(key, ""))
            else:
                texts[key] = mft_text(number, units.get(key, ""))
        summary = mft_summary(values) if values else [None] * 8
        texts["T_P"], texts["T_Q"], texts["T_S"] = power(summary[2], "W"), power(summary[3], "var"), power(summary[4], "VA")
        texts["T_PF"] = mft_text(summary[5], "")
        texts["T_F"] = mft_text(summary[6], "Hz")
        for key, text in texts.items():
            label = self._mft_vals.get(key)
            if label is not None and label.text() != text:
                label.setText(text)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._accent:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(self._accent))
            painter.drawRoundedRect(QRectF(0, 10, 4, max(8, self.height() - 20)), 2, 2)
            painter.end()

    def mousePressEvent(self, event):
        if self._on_open is not None and event.button() == Qt.LeftButton:
            self._on_open()
            return
        super().mousePressEvent(event)

    def refresh(self, device, status_text):
        colors = _PILL_COLORS.get(status_text, ("#EEF2F5", "#718391"))
        if self._cache.get("status") != status_text:
            self._cache["status"] = status_text
            self._accent = {"ONLINE": "#18C46E", "OFFLINE": "#E53935", "RETRYING": "#D88B00"}.get(status_text, "#C9D3DC")
            self.update()
            self._status.setText(status_text)
            _ss(self._status, 
                f"background:{colors[0]};color:{colors[1]};border-radius:5px;"
                "padding:3px 8px;font-size:9px;font-weight:700;", self._k)
        live = status_text in ("ONLINE", "RETRYING")
        values = dict(device.get("latest_data") or []) if live else {}
        if self._leds:
            for index, led in enumerate(self._leds):
                value = values.get(f"{self._kind}{index + 1}")
                led.set_state(None if value is None else int(value))
            active = active_channels(device) if live else []
            key = tuple(active)
            if self._cache.get("active") != key:
                self._cache["active"] = key
                if active:
                    word = "HIGH" if self._kind == "DI" else "ON"
                    self._active.setText(f"\u25b2 {len(active)} {word}")
                    self._active.setToolTip(", ".join(active) + f" {word}")
                self._active.setVisible(bool(active))
        elif self._kind == "MFT" and self._mft_vals:
            self._refresh_mft_panel(values)
        elif self._tiles and self._kind == "MFT":
            numbers = ([values.get(name) for name, _unit in self._mft_defs] if self._mft_big
                       else mft_summary(values)) if values else [None] * len(self._tiles)
            for tile, number, (_title, unit) in zip(self._tiles, numbers, self._mft_defs):
                text = mft_text(number, unit)
                if tile.text() != text:
                    tile.setText(text)
        elif self._tiles:
            units = device.get("latest_units") or []
            for index, tile in enumerate(self._tiles):
                value = values.get(f"{self._kind}{index + 1}")
                if value is None:
                    text = "--"
                else:
                    fmt = effective_format(device) if self._kind in ("AI", "AO") else "raw16"
                    text = format_value(value, fmt) if fmt in ("hex16", "hex32") else (
                        f"{value:.2f}" if isinstance(value, float) else str(value))
                    if index < len(units) and units[index] and fmt not in ("hex16", "hex32"):
                        text += f" {units[index]}"
                if tile.text() != text:
                    tile.setText(text)
        elif self._text is not None:
            text = "   ".join(f"{name}={value}" for name, value in values.items()) or "--"
            if self._text.text() != text:
                self._text.setText(text)
        self._spark.set_data(device.get("resp_hist") or [], self._accent or "#168CF0")
        tip = (f'Poll: {device.get("polling", 1000)} ms   Scan: {device.get("scan_rate", 60000)} ms   '
               f'Timeout: {device.get("timeout", 2000)} ms   Retries: {device.get("retry_count", 0)}/{device.get("max_retries", 3)}')
        if self._cache.get("tip") != tip:
            self._cache["tip"] = tip
            self.setToolTip(tip)

    def refresh_footer(self, device, status_text):
        if status_text in ("OFFLINE", "RETRYING"):
            text = f"●  {device.get('last_response', 'Timeout')}"
            color = "#E53935" if status_text == "OFFLINE" else "#D88B00"
        else:
            stamp = device.get("timestamp")
            if status_text == "ONLINE" and stamp is not None:
                ms = max(0, int((datetime.now() - stamp).total_seconds() * 1000))
                age = f"{ms} ms" if ms < 1000 else (f"{ms / 1000:.1f} s" if ms < 60000 else f"{ms // 60000} min")
                text = f"Last Update: {age} ago"
            else:
                text = "Last Update: --"
            color = "#7893A8"
        if self._footer.text() != text:
            self._footer.setText(text)
        if self._cache.get("footer_color") != color:
            self._cache["footer_color"] = color
            _ss(self._footer, f"color:{color};font-size:9px;font-weight:600;", min(self._k, 1.3))


DB_SAVE_INTERVAL_S = 1.0   # at most one stored record per device per second


class WriterCard(QFrame):
    """Write device card (Point Type 05 / 06 / 15 / 16), like the Modbus Monitor
    screen: one tile per point with its address and a control.
      05  ON/OFF button per coil, sends immediately
      15  ON/OFF buttons are staged, "Write All" sends one FC15
      06  value box + Write per register
      16  value boxes, "Write All" sends one FC16
    """
    COLUMNS = 4

    def __init__(self, device, send):
        super().__init__()
        self.setObjectName("deviceCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._device = device
        self._send = send
        self._function = int(device["function"])
        self._coil = self._function in (5, 15)
        self._multi = self._function in (15, 16)
        self._tiles = []
        start = int(device["address"])

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 9, 10, 9)
        root.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        icon = QLabel("W")
        icon.setFixedSize(34, 34)
        icon.setAlignment(Qt.AlignCenter)
        _ss(icon, "background:#FFF1DC;color:#C77700;border-radius:8px;font-size:12px;font-weight:800;")
        titles = QVBoxLayout()
        titles.setSpacing(0)
        name = QLabel(device["name"])
        name.setObjectName("deviceTitle")
        sub = QLabel(f'{_id_text(device) if device.get("host") else "Slave ID: " + str(device["slave_id"])}  ·  FC{self._function:02d}  ·  '
                     f'Start {start}  ·  Length {int(device["count"])}')
        sub.setObjectName("deviceType")
        titles.addWidget(name)
        titles.addWidget(sub)
        head.addWidget(icon)
        head.addLayout(titles, 1)
        self.format_box = None
        if not self._coil:
            self.format_box = QComboBox()
            self.format_box.addItems(["UInt16", "Int16", "Hex16"])
            head.addWidget(self.format_box)
        if self._multi:
            self.write_all = QPushButton("✎  Write All")
            self.write_all.setObjectName("primaryButton")
            self.write_all.clicked.connect(self._write_all)
            head.addWidget(self.write_all)
        self._status = QLabel("WRITE ONLY")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setMinimumWidth(110)
        _ss(self._status, "background:#EEF2F5;color:#718391;border-radius:5px;padding:3px 7px;font-size:9px;font-weight:700;")
        head.addWidget(self._status, 0, Qt.AlignTop)
        root.addLayout(head)

        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        for index in range(int(device["count"])):
            address = start + index
            tile = QFrame()
            tile.setObjectName("tile")
            tl = QVBoxLayout(tile)
            tl.setContentsMargins(6, 4, 6, 5)
            tl.setSpacing(2)
            title = QLabel(f"CH-{index + 1}")
            title.setObjectName("tileName")
            addr = QLabel(f"Address: {address:05d}")
            _ss(addr, "color:#7B9AB3;font-size:8px;")
            tl.addWidget(title)
            tl.addWidget(addr)
            entry = {"address": address, "state": False}
            if self._coil:
                button = QPushButton("OFF")
                button.setCheckable(True)
                button.setCursor(Qt.PointingHandCursor)
                self._style_coil(button, False)
                button.toggled.connect(lambda on, e=entry, b=button: self._coil_toggled(e, b, on))
                entry["button"] = button
                tl.addWidget(button)
            else:
                edit = QLineEdit()
                edit.setPlaceholderText("value")
                edit.setAlignment(Qt.AlignCenter)
                entry["edit"] = edit
                tl.addWidget(edit)
                if self._function == 6:
                    go = QPushButton("Write")
                    go.setObjectName("outlineButton")
                    go.clicked.connect(lambda _=False, e=entry: self._write_register(e))
                    tl.addWidget(go)
                    edit.returnPressed.connect(lambda e=entry: self._write_register(e))
            grid.addWidget(tile, index // self.COLUMNS, index % self.COLUMNS)
            self._tiles.append(entry)
        for column in range(self.COLUMNS):
            grid.setColumnStretch(column, 1)
        root.addLayout(grid)

    @staticmethod
    def _style_coil(button, on):
        button.setText("ON" if on else "OFF")
        if on:
            _ss(button, "QPushButton{background:#12A45B;color:#FFFFFF;border:none;border-radius:4px;"
                                 "padding:4px 0;font-size:9px;font-weight:800;}")
        else:
            _ss(button, "QPushButton{background:#8A949C;color:#FFFFFF;border:none;border-radius:4px;"
                                 "padding:4px 0;font-size:9px;font-weight:800;}")

    def _set_status(self, text, good=None):
        color = {True: ("#E8F8EF", "#12A45B"), False: ("#FFF0F0", "#E53935"), None: ("#EEF2F5", "#718391")}[good]
        self._status.setText(text)
        _ss(self._status, f"background:{color[0]};color:{color[1]};border-radius:5px;padding:3px 7px;font-size:9px;font-weight:700;")

    def _coil_toggled(self, entry, button, on):
        self._style_coil(button, on)
        entry["previous"] = not on
        if self._function == 5:
            if not self._send(5, entry["address"], [bool(on)]):
                self._revert(entry)

    def _revert(self, entry):
        button = entry["button"]
        button.blockSignals(True)
        button.setChecked(entry.get("previous", False))
        self._style_coil(button, button.isChecked())
        button.blockSignals(False)

    def _parse(self, text):
        return parse_write_values(self._function, text, self.format_box.currentText() if self.format_box else "UInt16")

    def _write_register(self, entry):
        try:
            values = self._parse(entry["edit"].text())
        except ValueError as exc:
            self._set_status(str(exc)[:40], False)
            return
        self._send(6, entry["address"], values)

    def _write_all(self):
        start = int(self._device["address"])
        if self._coil:
            values = [bool(e["button"].isChecked()) for e in self._tiles]
        else:
            values = []
            for e in self._tiles:
                try:
                    values.extend(self._parse(e["edit"].text() or "0"))
                except ValueError as exc:
                    self._set_status(f"CH-{self._tiles.index(e) + 1}: {str(exc)[:30]}", False)
                    return
        self._send(self._function, start, values)

    def on_write_result(self, function, address, count, ok):
        if function != self._function:
            return
        start = int(self._device["address"])
        if not (start <= address <= start + len(self._tiles)):
            return
        if ok:
            self._set_status("WRITE OK", True)
        else:
            self._set_status("WRITE FAILED", False)
            if self._function == 5:
                for entry in self._tiles:
                    if entry["address"] == address:
                        self._revert(entry)


class RailItem(QFrame):
    """One device in the left rail: status LED, name, live summary and a response trend."""
    picked = Signal(int)

    def __init__(self, device):
        super().__init__()
        self.sid = device["slave_id"]
        self._sel = False
        self._status = "NOT POLLED"
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(78)
        grid = QGridLayout(self)
        grid.setContentsMargins(30, 8, 10, 6)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(1)
        self.name = QLabel(device["name"])
        _ss(self.name, "color:#07528A; font-size:12px; font-weight:800; background:transparent; border:0;")
        kind = device.get("kind") or device.get("type", "")
        bg, fg = _TYPE_COLORS.get(kind, ("#EEF2F5", "#718391"))
        self.pill = QLabel(kind)
        self.pill.setAlignment(Qt.AlignCenter)
        _ss(self.pill, f"background:{bg}; color:{fg}; border-radius:7px; padding:1px 8px; font-size:8px; font-weight:800; border:0;")
        self.sub = QLabel(_id_text(device))
        _ss(self.sub, "color:#5C7A92; font-size:9px; font-weight:600; background:transparent; border:0;")
        self.value = QLabel("--")
        _ss(self.value, "color:#0B3A5F; font-size:11px; font-weight:800; background:transparent; border:0;")
        self.spark = Sparkline()
        self.spark.setFixedHeight(20)
        grid.addWidget(self.name, 0, 0)
        grid.addWidget(self.pill, 0, 1, Qt.AlignRight)
        grid.addWidget(self.sub, 1, 0, 1, 2)
        grid.addWidget(self.value, 2, 0)
        grid.addWidget(self.spark, 2, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnMinimumWidth(1, 80)

    def set_selected(self, selected):
        if selected != self._sel:
            self._sel = selected
            self.update()

    def refresh(self, device, status_text, summary):
        self._status = status_text
        if self.name.text() != device["name"]:
            self.name.setText(device["name"])
        if self.value.text() != summary:
            self.value.setText(summary)
        color = _STATUS_COLORS.get(status_text, "#7A8C99")
        self.spark.set_data(device.get("resp_hist") or [], color)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.picked.emit(self.sid)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        status = QColor(_STATUS_COLORS.get(self._status, "#7A8C99"))
        p.setBrush(tc("#EAF2FB" if self._sel else "#FFFFFF", "bg"))
        p.setPen(QPen(tc("#BBD8EE" if self._sel else "#D6E7F2", "border"), 1))
        p.drawRoundedRect(r, 7, 7)
        if self._sel:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#4C9AFF"))
            p.drawRoundedRect(QRectF(0, 8, 3.5, self.height() - 16), 2, 2)
        p.setPen(Qt.NoPen)
        glow = QRadialGradient(QPointF(17, self.height() / 2), 12)
        g0 = QColor(status); g0.setAlpha(100)
        g1 = QColor(status); g1.setAlpha(0)
        glow.setColorAt(0, g0); glow.setColorAt(1, g1)
        p.setBrush(glow)
        p.drawEllipse(QPointF(17, self.height() / 2), 12, 12)
        p.setBrush(status)
        p.drawEllipse(QPointF(17, self.height() / 2), 4.5, 4.5)
        p.end()


class DeviceRail(QScrollArea):
    """Left rail listing every configured device."""
    picked = Signal(int)

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self._host = QWidget()
        self._lay = QVBoxLayout(self._host)
        self._lay.setContentsMargins(0, 0, 4, 0)
        self._lay.setSpacing(8)
        title = QLabel("DEVICES")
        _ss(title, "color:#5C7A92; font-size:9px; font-weight:800; letter-spacing:2px; background:transparent;")
        self._lay.addWidget(title)
        self._lay.addStretch(1)
        self.setWidget(self._host)
        self.items = {}
        self._selected = None

    def rebuild(self, devices):
        for item in self.items.values():
            item.setParent(None)
            item.deleteLater()
        self.items = {}
        for device in devices:
            item = RailItem(device)
            item.picked.connect(self.picked.emit)
            self._lay.insertWidget(self._lay.count() - 1, item)
            self.items[device["slave_id"]] = item
        self.select(self._selected)

    def select(self, sid):
        self._selected = sid
        for key, item in self.items.items():
            item.set_selected(key == sid)


def rail_summary(device, status_text):
    values = dict(device.get("latest_data") or []) if status_text in ("ONLINE", "RETRYING") else {}
    if not values:
        return "OFFLINE" if status_text == "OFFLINE" else "--"
    kind = device.get("kind")
    if kind in ("DI", "DO"):
        return f"\u25b2 {len(active_channels(device))} / {len(values)} active"
    if kind == "MFT":
        numbers = mft_summary(values)
        return f"{mft_text(numbers[0], 'V')}   {mft_text(numbers[1], 'A')}"
    first = next(iter(values.items()))
    value = first[1]
    return f"{first[0]} {value:.2f}" if isinstance(value, float) else f"{first[0]} {value}"


class KpiStrip(QWidget):
    """Bus-health cards (Test Mode look): small caps label, big value, one-line sub text."""
    _DEFS = (("online", "DEVICES ONLINE"), ("tx", "TX / RX"), ("rate", "SUCCESS RATE"),
             ("resp", "LAST RESPONSE"), ("port", "PORT"))

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self._v, self._sub = {}, {}
        for key, title in self._DEFS:
            box = QFrame()
            box.setObjectName("kpi")
            _ss(box, "QFrame#kpi { background:#FFFFFF; border:1px solid #CDE3F1; border-radius:8px; }")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(12, 9, 12, 9)
            bl.setSpacing(2)
            t = QLabel(title)
            _ss(t, "color:#5C7A92; font-size:9px; font-weight:600; letter-spacing:1px; background:transparent; border:0;")
            v = QLabel("--")
            _ss(v, "color:#0B3A5F; font-size:20px; font-weight:700; background:transparent; border:0;")
            sub = QLabel("")
            _ss(sub, "color:#5C7A92; font-size:10px; background:transparent; border:0;")
            bl.addWidget(t)
            bl.addWidget(v)
            bl.addWidget(sub)
            self._v[key], self._sub[key] = v, sub
            lay.addWidget(box, 1)

    def _set(self, key, value, sub, tone=None):
        if self._v[key].text() != value:
            self._v[key].setText(value)
        if self._sub[key].text() != sub:
            self._sub[key].setText(sub)
        color = {"ok": "#12A45B", "warn": "#D88B00", "bad": "#E53935"}.get(tone, "#5C7A92")
        if self._sub[key].property("_tone") != color:
            self._sub[key].setProperty("_tone", color)
            _ss(self._sub[key], f"color:{color}; font-size:10px; background:transparent; border:0;")

    def update_values(self, online, total, stats, port, baud=""):
        tx, rx, ok = stats.get("tx", 0), stats.get("rx", 0), stats.get("successful", 0)
        bad = stats.get("timeouts", 0) + stats.get("errors", 0)
        self._set("online", f"{online} / {total}",
                  "all devices healthy" if total and online == total else (f"{total - online} not responding" if total else "no devices"),
                  "ok" if total and online == total else ("warn" if total else None))
        self._set("tx", f"{tx} / {rx}", f"{stats.get('errors', 0)} errors \u00b7 {stats.get('retries', 0)} retries",
                  "bad" if stats.get("errors", 0) else None)
        self._set("rate", f"{100.0 * ok / tx:.1f} %" if tx else "--", f"{stats.get('timeouts', 0)} timeouts",
                  ("ok" if not bad else "warn") if tx else None)
        self._set("resp", str(stats.get("last_response", "--")), "latest reply")
        self._set("port", port or "Disconnected", f"{baud} baud" if port and baud else "not connected",
                  "ok" if port else "bad")


class DeviceSpotlight(QFrame):
    """Full-size view of one device: big live card, all its settings and counters,
    and a terminal that shows only this slave's TX / RX."""
    back = Signal()
    step = Signal(int)

    FIELDS = (("Status", "status"), ("Poll interval", "poll"), ("Scan rate", "scan"), ("Timeout", "timeout"),
              ("Retries", "retries"), ("Last update", "last"), ("Last response", "resp"),
              ("Requests (TX)", "tx"), ("Replies (RX)", "rx"), ("Timeouts", "timeouts"), ("Errors", "errors"))

    def __init__(self):
        super().__init__()
        self.setObjectName("spotlight")
        _ss(self, "QFrame#spotlight { background:#F7FBFE; border:1px solid #BFDDF0; border-radius:14px; }"
                  "QLabel#spotName { color:#07528A; font-size:20px; font-weight:800; background:transparent; }"
                  "QLabel#spotSub { color:#4D718B; font-size:10px; font-weight:600; background:transparent; }"
                  "QLabel#spotKey { color:#5C7A92; font-size:10px; font-weight:600; background:transparent; }"
                  "QLabel#spotVal { color:#0B3A5F; font-size:12px; font-weight:800; background:transparent; }"
                  "QFrame#spotInfo { background:#FFFFFF; border:1px solid #D6E7F2; border-radius:10px; }")
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(8)
        back = QPushButton("\u2699  Setup")
        back.setObjectName("outlineButton")
        back.setVisible(False)
        back.setToolTip("Device table, add / edit devices and the full TX / RX terminal")
        back.clicked.connect(self.back.emit)
        head.addWidget(back)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.name = QLabel("")
        self.name.setObjectName("spotName")
        self.sub = QLabel("")
        self.sub.setObjectName("spotSub")
        titles.addWidget(self.name)
        titles.addWidget(self.sub)
        head.addLayout(titles, 1)
        prev_button = QPushButton("\u25c0")
        prev_button.setObjectName("outlineButton")
        prev_button.setToolTip("Previous device")
        prev_button.clicked.connect(lambda: self.step.emit(-1))
        next_button = QPushButton("\u25b6")
        next_button.setObjectName("outlineButton")
        next_button.setToolTip("Next device")
        next_button.clicked.connect(lambda: self.step.emit(1))
        head.addWidget(prev_button)
        head.addWidget(next_button)
        root.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(12)
        left = QVBoxLayout()
        left.setSpacing(8)
        self.card_host = QVBoxLayout()
        left.addLayout(self.card_host)
        term_title = QLabel("\u25a4  THIS DEVICE  TX / RX")
        term_title.setObjectName("panelTitle")
        left.addWidget(term_title)
        self.terminal = TerminalEdit()
        self.terminal.setObjectName("terminal")
        self.terminal.setReadOnly(True)
        self.terminal.setMaximumBlockCount(600)
        left.addWidget(self.terminal, 1)
        body.addLayout(left, 5)

        right = QVBoxLayout()
        right.setSpacing(10)
        info = QFrame()
        info.setMinimumWidth(300)
        info.setObjectName("spotInfo")
        grid = QGridLayout(info)
        grid.setContentsMargins(14, 10, 14, 10)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(5)
        self._values = {}
        for index, (label, key) in enumerate(self.FIELDS):
            row, column = index, 0
            k = QLabel(label)
            k.setObjectName("spotKey")
            v = QLabel("--")
            v.setObjectName("spotVal")
            grid.addWidget(k, row, column)
            grid.addWidget(v, row, column + 1)
            self._values[key] = v
        grid.setColumnStretch(1, 1)
        right.addWidget(info)
        trend = QFrame()
        trend.setObjectName("spotInfo")
        tl = QVBoxLayout(trend)
        tl.setContentsMargins(14, 10, 14, 10)
        tl.setSpacing(4)
        ttl = QLabel("RESPONSE TIME  (last 40 replies)")
        ttl.setObjectName("spotKey")
        self._trend = Sparkline()
        self._trend.setFixedHeight(120)
        self._trend_stats = QLabel("--")
        self._trend_stats.setObjectName("spotVal")
        tl.addWidget(ttl)
        tl.addWidget(self._trend)
        tl.addWidget(self._trend_stats)
        right.addWidget(trend)
        right.addStretch(1)
        body.addLayout(right, 2)
        root.addLayout(body, 1)

    def set_card(self, card):
        while self.card_host.count():
            item = self.card_host.takeAt(0)
            old = item.widget()
            if old is not None:
                old.setParent(None)
                old.deleteLater()
        self.card_host.addWidget(card)

    def set_header(self, device):
        self.name.setText(device["name"])
        function = int(device.get("function", 0) or 0)
        self.sub.setText(f'{_id_text(device)}  \u00b7  {_TYPE_TITLES.get(device.get("kind"), device.get("type", ""))}'
                         f'  \u00b7  FC{function:02d}  \u00b7  address {device.get("address", 0)}  \u00b7  {device.get("count", 0)} points')

    def set_info(self, device, status_text, last_text):
        stats = device.get("stats") or {}
        values = {
            "status": status_text,
            "poll": f'{device.get("polling", 1000)} ms', "scan": f'{device.get("scan_rate", 60000)} ms',
            "timeout": f'{device.get("timeout", 2000)} ms',
            "retries": f'{device.get("retry_count", 0)} / {device.get("max_retries", 3)}',
            "last": last_text, "resp": str(device.get("last_response", "--")),
            "tx": str(stats.get("tx", 0)), "rx": str(stats.get("rx", 0)),
            "timeouts": str(stats.get("timeouts", 0)), "errors": str(stats.get("errors", 0)),
        }
        hist = device.get("resp_hist") or []
        self._trend.set_data(hist, {"ONLINE": "#168CF0", "OFFLINE": "#E53935", "RETRYING": "#D88B00"}.get(status_text, "#7893A8"))
        stat = (f"min {min(hist)} ms   avg {sum(hist) // len(hist)} ms   max {max(hist)} ms" if hist else "--")
        if self._trend_stats.text() != stat:
            self._trend_stats.setText(stat)
        for key, text in values.items():
            if self._values[key].text() != text:
                self._values[key].setText(text)
        color = {"ONLINE": "#12A45B", "OFFLINE": "#E53935", "RETRYING": "#D88B00"}.get(status_text, "#5C7A92")
        _ss(self._values["status"], f"color:{color};font-size:12px;font-weight:800;background:transparent;")

    def set_lines(self, lines, color_of):
        self.terminal.clear()
        self.append_lines(lines, color_of)

    def append_lines(self, lines, color_of):
        if not lines:
            return
        self.terminal.setUpdatesEnabled(False)
        for line in lines:
            self.terminal.appendHtml(f'<span style="color:{color_of(line)};white-space:pre">{html.escape(line)}</span>')
        self.terminal.setUpdatesEnabled(True)
        self.terminal.verticalScrollBar().setValue(self.terminal.verticalScrollBar().maximum())


class MultiDeviceView(QWidget):
    back_clicked = Signal()
    def __init__(self, parent=None, build_later=False):
        super().__init__(parent)
        # The page is built in pieces (_init_in_steps yields between them). Normally all pieces are built here;
        # with build_later=True the application builds one piece per idle moment (build_step) so the screen
        # never stands still for the whole build, and finish_build() completes the rest when the page is opened.
        self._init_steps = self._init_in_steps()
        if not build_later:
            self.finish_build()

    def build_step(self):
        """Build the next piece of the page; True when the page is complete."""
        if self._init_steps is None:
            return True
        try:
            next(self._init_steps)
            return False
        except StopIteration:
            self._init_steps = None
            return True

    def finish_build(self):
        while not self.build_step():
            pass

    def _init_in_steps(self):
        self._serial_connection = None
        self._connected = False
        self._devices = {}
        self._stats = {
            "tx": 0,
            "rx": 0,
            "successful": 0,
            "timeouts": 0,
            "retries": 0,
            "errors": 0,
            "last_response": "--",
        }
        # All bus traffic runs in this background scanner (one per connection).
        self._scanner = None
        self._port_lost = False
        self._db_writer = None
        self._db_state = None
        self._alarms = _NoAlarms()
        self._connected_since = None
        # GUI-side refresh state: scanner events only mark things dirty;
        # one timer repaints them in batches so the UI never lags.
        self._terminal_buffer = []
        self._writing = False          # True while polling is paused for a write
        self._pending_writes = set()   # (slave, fc, address) queued or on the bus
        self._fc05_clicks = set()      # DO LED clicks sent as FC05 (slave, address)
        self._log_file = None          # Record Log: every terminal line streamed to a file
        self._log_path = ""
        self._log_started = 0.0
        self._log_lines = 0
        self._log_pending = []
        self._dirty_devices = set()
        self._stats_dirty = False
        self._row_of = {}
        self._card_refs = {}
        self.scan_rate = _Default(60000)
        self.timeout_spin = _Default(2000)
        self.default_poll = _Default(1000)
        self.max_retries = _Default(3)
        self._csv_file = None          # Record CSV: one row per reading / timeout / write
        self._csv_writer = None
        self._csv_pending = []
        self._csv_resp = {}
        self._csv_rows = 0
        self._add_forced = False
        self._add_state = None
        self._focus = None            # 'table' | 'data' | 'terminal' | 'stats' | None
        self._spot_sid = None         # slave id shown in the Device Spotlight
        self._last_selected = None
        self._console_buffer = []
        self._resp_all = []
        self._rate_samples = []
        self._rate_hist = []
        self._rate_at = 0.0
        self._last_timeout = None
        self._mode = "console"
        self._spot_card = None
        self._focus_titles = {}
        self._editing = None          # key of the device being edited in the Add/Edit panel
        self._writers = {}            # write-only devices (Point Type 05/06/15/16), key 'W1'...
        self._writer_seq = 0
        self._writer_cards = {}
        self._loading_form = False
        self._reset_pending = False
        self._port_present = True
        self._port_check_busy = False
        self._port_seen = False
        self._port_check_at = 0.0
        self._next_poll_labels = []
        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(200)
        self._ui_timer.timeout.connect(self._refresh_ui)
        self._project_loading = False
        self._term_dirty = False
        self._tcp_active = False
        self._links = {}              # link -> open connection (None for Modbus TCP (IP)), see multi_link.py
        self._legacy_link = "rtu"     # link of devices saved without one (older versions)
        yield from self._build_ui()
        yield
        self._refresh_com_ports()
        self._update_statistics()
        yield
        self._load_project()
        yield
        for combo in (self.com_port, self.baud_rate, self.data_bits, self.parity, self.stop_bits):
            combo.currentTextChanged.connect(lambda _t: self._save_project())
        self.ip_input.editingFinished.connect(self._save_project)
        self.subnet_input.editingFinished.connect(self._save_project)
        self.tcp_port_input.valueChanged.connect(lambda _v: self._save_project())
        self._autosave_timer = QTimer(self)          # TX/RX terminal is saved with the project every 20 s
        self._autosave_timer.setInterval(20000)
        self._autosave_timer.timeout.connect(self._autosave_tick)
        self._autosave_timer.start()
        self._topbar_timer = QTimer(self)         # connection pill also follows changes made while idle
        self._topbar_timer.setInterval(500)
        self._topbar_timer.timeout.connect(self._sync_topbar)
        self._topbar_timer.start()
        self._sync_topbar()
        if not self._devices:
            self._live.detail.set_empty(True, "No devices yet \u2014 use Add device")
        if self._load_theme() == "dark":
            self.set_theme("dark", save=False)
        else:
            self.set_theme("light", save=False, restyle=False)
    def _build_ui(self):
        self.setObjectName("multiDeviceView")
        self.setMinimumSize(1050, 700)
        # The page style sheet is applied at the END of _build_ui: set first, every widget added below would
        # make Qt re-run the style sheet on the whole page (about 0.3 s more when the page is first opened).
        page_qss = ("""
            QWidget#multiDeviceView { background:#F3F8FC; color:#123B61; font-family:"Segoe UI"; }
            QFrame#header { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #0CAFC4,stop:0.55 #087FC8,stop:1 #0759A4); border:0; }
            QFrame#panel { background:#FFFFFF; border:1px solid #CFE2F0; border-radius:9px; }
            QFrame#subPanel { background:#FFFFFF; border:1px solid #D8E8F3; border-radius:8px; }
            QLabel#panelTitle { color:#07528A; font-family:"Segoe UI"; font-size:13px; font-weight:700; }
            QLabel#fieldLabel { color:#244D70; font-size:10px; font-weight:600; }
            QLabel#settingLabel { color:#123B61; font-size:10px; font-weight:600; background:transparent; }
            QLabel#muted { color:#7893A8; font-size:9px; }
            QLabel#statusValue { color:#123B61; font-size:10px; font-weight:600; }
            QComboBox,QSpinBox,QLineEdit {
                background:#FFFFFF; border:1px solid #C8DCEB; border-radius:5px;
                min-height:28px; padding:0 7px; color:#123B61; font-size:10px;
            }
            QComboBox:hover,QSpinBox:hover,QLineEdit:hover { border:1px solid #8FC6EA; }
            QComboBox:focus,QSpinBox:focus,QLineEdit:focus { border:1px solid #238EEA; }
            QComboBox::drop-down { width:22px; border:0; }
            QComboBox QAbstractItemView, QListView {
                background:#FFFFFF; color:#123B61; border:1px solid #A9D3F2; outline:0;
                selection-background-color:#DCEEFB; selection-color:#07528A; padding:2px; font-size:10px;
            }
            QComboBox QAbstractItemView::item { min-height:24px; padding:2px 8px; color:#123B61; background:#FFFFFF; }
            QComboBox QAbstractItemView::item:hover, QComboBox QAbstractItemView::item:selected { background:#DCEEFB; color:#07528A; }
            QSpinBox::up-button,QSpinBox::down-button { width:18px; border:0; }
            QPushButton {
                font-family:"Segoe UI"; font-size:10px; font-weight:700;
                border-radius:6px; padding:0 10px; min-height:30px;
            }
            QPushButton#connectButton { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #12B8C5,stop:1 #168CF0); color:white; border:0; min-height:34px; }
            QPushButton#primaryButton { background:#168CF0; color:white; border:0; }
            QPushButton#runButton { background:#12B86A; color:white; border:0; }
            QPushButton#stopButton { background:#F04444; color:white; border:0; }
            QPushButton#dangerOutline { background:#FFF7F7; color:#E53935; border:1px solid #F28B88; }
            QPushButton#outlineButton { background:#FFFFFF; color:#1764A8; border:1px solid #A9D3F2; }
            QPushButton#tableAction { background:#FFFFFF; color:#168CF0; border:1px solid #A9D3F2; min-width:28px; max-width:32px; min-height:24px; max-height:24px; padding:0; }
            QPushButton#tableDanger { background:#FFF7F7; color:#E53935; border:1px solid #F2A4A1; min-width:28px; max-width:32px; min-height:24px; max-height:24px; padding:0; }
            QPushButton:hover { border-color:#168CF0; }
            QCheckBox { color:#174F78; background:transparent; font-size:10px; font-weight:600; spacing:6px; }
            QCheckBox::indicator { width:14px; height:14px; border:1px solid #7FA6C4; border-radius:3px; background:#FFFFFF; }
            QCheckBox::indicator:hover { border-color:#168CF0; }
            QCheckBox::indicator:checked { background:#168CF0; border:1px solid #168CF0; }
            QTableView::indicator { width:14px; height:14px; border:1px solid #7FA6C4; border-radius:3px; background:#FFFFFF; }
            QTableView::indicator:checked { background:#168CF0; border:1px solid #168CF0; }
            QPushButton#runButton:hover { background:#0FA55D; }
            QPushButton#stopButton:hover { background:#D93636; }
            QTableWidget {
                background:#FFFFFF; border:1px solid #D6E6F1; border-radius:5px;
                gridline-color:#E4EEF5; color:#123B61; font-size:10px;
                selection-background-color:#EAF5FD; selection-color:#123B61;
            }
            QTableWidget::item { padding:4px; border-bottom:1px solid #E8F0F5; }
            QHeaderView { background:#EAF5FC; }
            QHeaderView::section {
                background:#EAF5FC; color:#174F78; border:0;
                border-right:1px solid #D6E6F1; border-bottom:1px solid #C7DDEB;
                padding:7px 5px; font-weight:700; font-size:9px;
            }
            QPlainTextEdit {
                background:#FFFFFF; color:#174F78; border:1px solid #C8DFEE;
                border-radius:6px; font-family:Consolas,"Courier New"; font-size:9px;
                padding:5px;
            }
            QScrollArea { background:transparent; border:0; }
            QScrollArea > QWidget > QWidget { background:transparent; }
            QScrollBar:vertical { width:10px; background:#EDF4F9; margin:2px; }
            QScrollBar::handle:vertical { background:#A9CDE7; border-radius:5px; min-height:25px; }
            QScrollBar:horizontal { height:10px; background:#EDF4F9; margin:2px; }
            QScrollBar::handle:horizontal { background:#A9CDE7; border-radius:5px; min-width:25px; }
            QFrame#deviceCard { background:#FFFFFF; border:1px solid #CDE3F1; border-radius:8px; }
            QLabel#deviceTitle { color:#07528A; font-size:11px; font-weight:700; }
            QLabel#deviceType { color:#245D84; font-size:9px; font-weight:600; }
            QLabel#value { background:#F2F8FC; border:1px solid #D6E7F2; border-radius:5px; color:#174F78; padding:5px; font-size:9px; font-weight:600; }
            QLabel#statusOnline { background:#E8F8EF; color:#12A45B; border-radius:5px; padding:3px 7px; font-size:9px; font-weight:700; }
            QLabel#statusOffline { background:#FFF0F0; color:#E53935; border-radius:5px; padding:3px 7px; font-size:9px; font-weight:700; }
            QLabel#statusRetry { background:#FFF7E7; color:#D88B00; border-radius:5px; padding:3px 7px; font-size:9px; font-weight:700; }
            QLabel#statusIdle { background:#EEF2F5; color:#718391; border-radius:5px; padding:3px 7px; font-size:9px; font-weight:700; }
            QLabel#channelLabel { color:#5C7A92; font-size:8px; font-weight:600; }
            QFrame#tile { background:#F2F8FC; border:1px solid #D6E7F2; border-radius:6px; }
            QLabel#tileName { color:#5C7A92; font-size:8px; font-weight:600; background:transparent; }
            QLabel#tileValue { color:#07528A; font-size:11px; font-weight:700; background:transparent; }
            QPlainTextEdit#terminal { background:#0B2239; color:#D6E4F0; border:1px solid #0B2239; border-radius:6px; font-family:Consolas,"Courier New"; font-size:10px; padding:6px; }
            QTabWidget::pane { border:0; background:transparent; }
            QTabBar::tab { background:#E3EFF8; color:#3B6485; padding:9px 26px; margin-right:3px; border-top-left-radius:7px; border-top-right-radius:7px; font-size:11px; font-weight:700; }
            QTabBar::tab:selected { background:#FFFFFF; color:#07528A; }
            QTabBar::tab:hover:!selected { background:#D3E6F4; }
            QLabel#metric { color:#07528A; font-size:10px; font-weight:600; }
            QLabel#metricValue { color:#07528A; font-size:12px; font-weight:700; }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # HEADER
        header = QFrame()
        self._header = header
        header.setObjectName("header")
        header.setMinimumHeight(62)
        header.setMaximumHeight(72)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 4, 20, 4)
        header_layout.setSpacing(0)
        logo = QLabel()
        logo.setFixedSize(46, 50)
        logo.setAlignment(Qt.AlignCenter)
        logo_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "assets",
            "NelumboLogo.png"
        )
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            if not pixmap.isNull():
                logo.setPixmap(pixmap.scaled(46, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        header_layout.addWidget(logo)
        title_layout = QVBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)
        title_layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        company = QLabel("Nelumbo Automation Pvt Ltd")
        self._company_label = company
        company.setFixedHeight(22)
        company.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        _ss(company, """
            QLabel {
                color: white;
                font-family: Cambria;
                font-size: 17px;
                font-weight: bold;
                padding: 0px;
                margin: 0px;
            }
        """)
        subtitle = QLabel("Connectivity Utility Suite")
        self._subtitle_label = subtitle
        subtitle.setFixedHeight(18)
        subtitle.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        _ss(subtitle, """
            QLabel {
                color: white;
                font-family: Cambria;
                font-size: 13px;
                padding: 0px;
                margin: 0px;
            }
        """)
        title_layout.addWidget(company)
        title_layout.addWidget(subtitle)
        header_layout.addLayout(title_layout)
        header_layout.addStretch()
        self.theme_button = QPushButton()
        self.theme_button.setObjectName("themeButton")
        self.theme_button.setCursor(Qt.PointingHandCursor)
        self.theme_button.setFocusPolicy(Qt.NoFocus)
        self.theme_button.setFixedSize(96, 30)
        self.theme_button.setToolTip("Switch between the light and the dark theme")
        self.theme_button.clicked.connect(self._toggle_theme)
        header_layout.addWidget(self.theme_button)
        header_layout.addSpacing(14)
        back = BackButton()
        back.setObjectName("backButton")
        back.clicked.connect(self._handle_back_from_header)
        header_layout.addWidget(back)
        root.addWidget(header)
        yield                                   # build piece done (see build_step)

        body_scroll = QScrollArea()
        self.body_scroll = body_scroll
        body_scroll.setWidgetResizable(True)
        body_scroll.setFrameShape(QFrame.NoFrame)
        body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        body_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # the page background (gutters between the panels, scroll bar lane) follows light / dark as well
        _ss(body_scroll, "QScrollArea { background:#F3F8FC; border:0; } QScrollArea > QWidget > QWidget { background:#F3F8FC; } QSplitter { background:#F3F8FC; } QSplitter::handle { background:#F3F8FC; }")

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(8, 8, 8, 8)
        body_layout.setSpacing(8)

        self._connection_widget = self._connection_panel()
        yield                                   # build piece done (see build_step)
        body_layout.addWidget(self._connection_widget, 0)

        # Resizable layout: drag the handles (or enlarge the window) and every
        # panel grows with it. "Expand" on the terminal gives it the whole tab.
        self._manager_widget = self._manager_panel()
        yield                                   # build piece done (see build_step)
        self._data_widget = self._data_panel()
        yield                                   # build piece done (see build_step)
        terminal_widget = self._terminal_panel()
        yield                                   # build piece done (see build_step)
        self._stats_column = QWidget()
        lower_right = QVBoxLayout(self._stats_column)
        lower_right.setContentsMargins(0, 0, 0, 0)
        lower_right.setSpacing(8)
        self._next_poll_panel()

        self._lower_split = QSplitter(Qt.Horizontal)
        self._lower_split.setChildrenCollapsible(False)
        self._lower_split.setHandleWidth(8)
        for widget, stretch in ((self._data_widget, 6), (terminal_widget, 8)):
            widget.setMinimumWidth(150)
            self._lower_split.addWidget(widget)
            self._lower_split.setStretchFactor(self._lower_split.count() - 1, stretch)
        self._lower_split.setSizes([600, 820])

        self._right_split = QSplitter(Qt.Vertical)
        self._right_split.setChildrenCollapsible(False)
        self._right_split.setHandleWidth(8)
        self._manager_widget.setMinimumHeight(260)
        self._lower_split.setMinimumHeight(400)     # terminal / statistics never get squeezed; the page scrolls instead
        self._right_split.addWidget(self._manager_widget)
        self._right_split.addWidget(self._lower_split)
        self._focus_widgets = {"table": self._table_panel, "data": self._data_widget,
                               "terminal": terminal_widget}
        esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        esc.activated.connect(self._escape_pressed)
        self._right_split.setStretchFactor(0, 1)
        self._right_split.setStretchFactor(1, 2)
        self._right_split.setSizes([420, 560])

        self._body_layout = body_layout
        yield                                   # build piece done (see build_step)
        self._live = lc.LivePage()
        self._live.devices.picked.connect(self._open_spotlight)
        detail = self._live.detail
        detail.pause_clicked.connect(self._toggle_pause)
        detail.edit_clicked.connect(self._edit_from_console)
        detail.do_toggle.connect(lambda sid, i: sid in self._devices and self._toggle_do(self._devices[sid], i))
        detail.format_changed.connect(
            lambda sid, f, o: sid in self._devices and self._quick_format(self._devices[sid], f, o))
        detail.tabs.changed.connect(lambda _k: self._spot_sid in self._devices
                                    and self._refresh_spotlight(self._devices[self._spot_sid]))
        self._live.console.record_clicked.connect(self._toggle_log)
        self._stack = QStackedWidget()
        self._stack.addWidget(self._live)
        self._stack.addWidget(self._right_split)
        body_layout.addWidget(self._stack, 1)
        body_scroll.setWidget(body)
        yield                                   # build piece done (see build_step)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        # page background and date boxes follow light / dark like the other pages
        _ss(self.tabs, """
            QTabWidget, QTabWidget > QStackedWidget { background:#F3F8FC; }
            QTabWidget::pane { background:#F3F8FC; border:0; }
            QWidget#histTab, QWidget#trendsTab { background:#F3F8FC; }
            QDateTimeEdit { background:#FFFFFF; border:1px solid #C8DCEB; border-radius:5px;
                min-height:28px; padding:0 7px; color:#123B61; font-size:10px; }
            QDateTimeEdit:focus { border:1px solid #238EEA; }
            QDateTimeEdit::drop-down { width:22px; border:0; }
        """)
        self.dashboard_tab = DashboardTab(
            self._alarms, lambda: list(self._devices.values()), lambda: self._stats, self._dashboard_runtime)
        yield                                   # build piece done (see build_step)
        self.tabs.addTab(self.dashboard_tab, "Dashboard")
        yield                                   # build piece done (see build_step)
        self.tabs.addTab(body_scroll, "Live")
        yield                                   # build piece done (see build_step)
        self.tabs.tabBar().hide()
        self._header.hide()
        self._nav = lc.NavRail()
        self._nav.picked.connect(self._nav_to)
        self._top = lc.TopBar()
        self._top.back_btn.clicked.connect(self._handle_back_from_header)
        self._top.connect_btn.clicked.connect(self._toggle_connection)
        self._top.rescan_btn.clicked.connect(self._start_scan)
        self._top.add_btn.clicked.connect(self._add_from_console)
        self._top.stop_btn.clicked.connect(self._stop_all)
        self._top.start_btn.clicked.connect(self._run_all)
        self._top.theme_btn.clicked.connect(self._toggle_theme)
        self.theme_button = self._top.theme_btn
        yield                                   # build piece done (see build_step)
        shell = QWidget()
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        shell_layout.addWidget(self._nav)
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._top)
        column.addWidget(self.tabs, 1)
        shell_layout.addLayout(column, 1)
        yield                                   # build piece done (see build_step)
        root.addWidget(shell, 1)
        yield                                   # build piece done (see build_step)
        self.tabs.setCurrentIndex(1)
        self.tabs.currentChanged.connect(lambda _i: self._sync_nav())
        self._sync_mode()
        for _combo in self.findChildren(QComboBox):      # styled list so drop-downs stay readable on dark Windows themes
            _combo.setView(QListView())
        yield                                   # build piece done (see build_step)
        _ss(self, page_qss)
    def _handle_back_from_header(self):
        """Back only leaves the page. Connection, devices, polling and recording keep running
        exactly as they are; nothing is reset or disconnected."""
        self.back_clicked.emit()

    # ---------------------------------------------------------------- #
    # Project save / restore: devices + communication settings are kept in a
    # JSON file and loaded again the next time the page opens.
    # ---------------------------------------------------------------- #
    _PROJECT_FIELDS = ("name", "type", "slave_id", "function", "address", "count",
                       "polling", "scan_rate", "timeout", "max_retries", "do_write", "data_format", "word_order",
                       "host", "tcp_port", "subnet", "unit", "link")

    @staticmethod
    def project_path():
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "NelumboConnectivityUtility", "multi_device_project.json")

    def _autosave_tick(self):
        if self._term_dirty:
            self._save_project()

    def _save_project(self, path=None):
        if self._project_loading:
            return False
        try:
            self._term_dirty = False
            if self._terminal_buffer:
                self._flush_terminal()
            data = {
                "version": 1,
                "comm": {"type": self.connection_type.currentText(), "ip": self.ip_input.text().strip(), "subnet": self.subnet_input.text().strip(),
                         "tcp_port": self.tcp_port_input.value(),
                         "port": self.com_port.currentText(), "baud": self.baud_rate.currentText(),
                         "data_bits": self.data_bits.currentText(), "parity": self.parity.currentText(),
                         "stop_bits": self.stop_bits.currentText()},
                "devices": [{k: d.get(k) for k in self._PROJECT_FIELDS if k in d}
                            for d in self._all_device_rows()],
                "terminal": self.terminal.toPlainText().splitlines()[-1000:],
            }
            path = path or self.project_path()
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
            os.replace(tmp, path)
            return True
        except Exception:
            return False          # saving must never disturb polling or the UI

    def _save_project_as(self):
        default_dir = os.path.join(os.path.expanduser("~"), "Documents")
        if not os.path.isdir(default_dir):
            default_dir = os.path.expanduser("~")
        path, _ = QFileDialog.getSaveFileName(self, "Save project", os.path.join(default_dir, "my_project.mdproj"),
                                              "Project files (*.mdproj);;JSON files (*.json)")
        if not path:
            return
        if self._save_project(path):
            self._terminal(f"Project saved: {path}")
        else:
            self._terminal(f"Unable to save project to {path}")

    def _open_project(self):
        default_dir = os.path.join(os.path.expanduser("~"), "Documents")
        if not os.path.isdir(default_dir):
            default_dir = os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(self, "Open project", default_dir,
                                              "Project files (*.mdproj *.json);;All files (*)")
        if not path:
            return
        if self._devices or self._writers:
            answer = QMessageBox.question(
                self, "Open project",
                "Opening a project replaces the devices that are configured now (running devices are stopped). Continue?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        self._load_project(path, replace=True)

    def _load_project(self, path=None, replace=False):
        path = path or self.project_path()
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError("not a project file")
        except (OSError, ValueError):
            if replace:
                self._terminal(f"Unable to read project file: {path}")
            return
        if replace:
            if self._editing is not None:
                self._cancel_edit()
            self._stop_all()
            for key in list(self._devices) + list(self._writers):
                self._drop_device(key)
        self._project_loading = True
        try:
            comm = data.get("comm") or {}
            if comm.get("type") in ("Modbus RTU", "Modbus TCP", tcpip.MODE_NAME):
                self.connection_type.setCurrentText(comm["type"])
            if comm.get("ip"):
                self.ip_input.setText(str(comm["ip"]))
            if comm.get("subnet"):
                self.subnet_input.setText(str(comm["subnet"]))
            if comm.get("tcp_port"):
                try:
                    self.tcp_port_input.setValue(int(comm["tcp_port"]))
                except (TypeError, ValueError):
                    pass
            for combo, key in ((self.baud_rate, "baud"), (self.data_bits, "data_bits"),
                               (self.parity, "parity"), (self.stop_bits, "stop_bits"),
                               (self.com_port, "port")):
                value = comm.get(key)
                if value and combo.findText(value) >= 0:
                    combo.setCurrentText(value)
            loaded = 0
            comm_type = (comm or {}).get("type") if isinstance(comm, dict) else None
            self._legacy_link = ("rtu" if comm_type == "Modbus RTU" else
                                 "gateway" if comm_type == "Modbus TCP" or (comm or {}).get("ip") else "rtu")
            guessed = 0
            for item in data.get("devices") or []:
                try:
                    register = {"function": int(item["function"]), "address": int(item["address"]),
                                "count": int(item["count"])}
                    device = self._new_device(
                        int(item["slave_id"]), item.get("name") or f"Slave {item['slave_id']}",
                        item["type"], int(item.get("polling", 1000)), int(item.get("scan_rate", 60000)),
                        int(item.get("timeout", 2000)), int(item.get("max_retries", 3)), "Not tested",
                        register=register)
                    if is_write_function(device["function"]):
                        device.update(mode="write", status="WRITE", last_response="--")
                    device["do_write"] = int(item.get("do_write") or 15)
                    if item.get("host"):
                        device.update(host=str(item["host"]), tcp_port=int(item.get("tcp_port") or 502),
                                      subnet=str(item.get("subnet") or "255.255.255.0"), unit=int(item.get("unit") or 1))
                        if item.get("link") == tcpip.LINK_KEY:
                            device.update(tcpip.device_fields(str(item["host"])))
                    if item.get("link") in LINKS:
                        device["link"] = item["link"]
                    elif not device.get("host"):
                        device["link"] = self._legacy_link       # saved by an older version: best guess
                        guessed += 1
                    else:
                        device["link"] = "tcp_ip"
                    if item.get("data_format") in DATA_FORMATS:
                        device["data_format"] = item["data_format"]
                    if item.get("word_order") in WORD_ORDERS:
                        device["word_order"] = item["word_order"]
                    if device["mode"] != "write" and device["slave_id"] in self._devices:
                        continue
                    self._register_device(device)
                    loaded += 1
                except (KeyError, ValueError, TypeError):
                    continue
            if guessed:
                self._terminal(f"{guessed} device(s) were saved by an older version without a link; they are set to "
                               f"{LINK_NAMES[self._legacy_link]}. If that is wrong: Edit the device, choose the right "
                               "Connection Type and press Save Changes.")
        finally:
            self._project_loading = False
        if replace:
            self._rebuild_device_table(); self._rebuild_data_cards(); self._update_statistics()
        saved_lines = [str(x) for x in (data.get("terminal") or [])][-1000:]
        if replace:
            self.terminal.clear()
        if saved_lines:
            self.terminal.setUpdatesEnabled(False)
            for line in saved_lines:
                self.terminal.appendHtml(
                    f'<span style="color:{self._terminal_color(line)};white-space:pre">{html.escape(line)}</span>')
            self.terminal.setUpdatesEnabled(True)
            self.terminal.verticalScrollBar().setValue(self.terminal.verticalScrollBar().maximum())
            self._terminal(f"---- {len(saved_lines)} saved TX/RX line(s) above are from the previous session ----")
        if loaded:
            self._terminal(f"Project {'opened' if replace else 'restored'}: {loaded} device(s) loaded. "
                           + ("Press Run All." if self._connected else "Connect and press Run All."))

    def _reset_to_initial(self):
        """Back to the state of a freshly opened page (communication settings are kept)."""
        self._reset_pending = False
        self._stop_log("page reset")
        self._stop_csv("page reset")
        self._spot_sid = None
        self._spot_card = None
        self._focus = None
        self._apply_layout()
        if self._editing is not None:
            self._cancel_edit()
        self._devices.clear()
        self._writers.clear()
        self._alarms.clear_all("reset")
        self._clear_terminal_and_statistics()
        self._clear_add_form()
        self._rebuild_device_table(); self._rebuild_data_cards()
        self.dashboard_tab.reset_session()
        self.tabs.setCurrentWidget(self.dashboard_tab)
        self.body_scroll.verticalScrollBar().setValue(0)
        self.body_scroll.horizontalScrollBar().setValue(0)
        self._refresh_com_ports()
        self._stats_dirty = True
        self._refresh_ui()

    def _connection_panel(self):
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setMinimumWidth(238)
        panel.setMaximumWidth(270)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(7)

        title = QLabel("⚙  COMMUNICATION SETTINGS")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        self.connection_type = self._combo(["Modbus RTU", "Modbus TCP", tcpip.MODE_NAME])
        layout.addWidget(self._field("Connection Type", self.connection_type))

        row = QHBoxLayout()
        row.setSpacing(5)
        self.com_port = self._combo([])
        refresh = QPushButton("↻")
        refresh.setObjectName("outlineButton")
        refresh.setFixedWidth(34)
        refresh.clicked.connect(self._refresh_com_ports)
        row.addWidget(self.com_port, 1)
        row.addWidget(refresh)
        self._serial_fields = [self._field("COM Port", row)]
        layout.addWidget(self._serial_fields[0])

        # Modbus TCP: gateway / device IP and port (the slave IDs of the devices become unit IDs)
        self.ip_input = QLineEdit("192.168.1.10")
        self.ip_input.setPlaceholderText("e.g. 192.168.1.10")
        self.tcp_port_input = QSpinBox()
        self.tcp_port_input.setRange(1, 65535)
        self.tcp_port_input.setValue(502)
        self.subnet_input = QLineEdit("255.255.255.0")
        self.subnet_input.setPlaceholderText("e.g. 255.255.255.0")
        self.subnet_input.setToolTip("Used to check that the device IP is on the same network as this PC. "
                                     "It is not sent to the device.")
        # Modbus TCP: one gateway IP / subnet / port here, devices by Device ID (Unit ID).
        # Modbus TCP (IP): every device has its own IP (Add New Device) - only a hint is shown here.
        self._gw_fields = [self._field("IP Address", self.ip_input), self._field("Subnet Mask", self.subnet_input),
                           self._field("TCP Port", self.tcp_port_input)]
        hint = QLabel(tcpip.HINT)
        self._tcp_hint = hint
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        self._tcp_fields = self._gw_fields + [hint]
        for widget in self._tcp_fields:
            layout.addWidget(widget)
            widget.hide()

        self.baud_rate = self._combo(["9600", "19200", "38400", "57600", "115200"])
        self.baud_rate.setCurrentText("9600")
        self._serial_fields.append(self._field("Baud Rate", self.baud_rate))
        layout.addWidget(self._serial_fields[-1])

        self.data_bits = self._combo(["7", "8"])
        self.data_bits.setCurrentText("8")
        self._serial_fields.append(self._field("Data Bits", self.data_bits))
        layout.addWidget(self._serial_fields[-1])

        self.parity = self._combo(["None", "Even", "Odd"])
        self._serial_fields.append(self._field("Parity", self.parity))
        layout.addWidget(self._serial_fields[-1])

        self.stop_bits = self._combo(["1", "2"])
        self.stop_bits.setCurrentText("1")
        self._serial_fields.append(self._field("Stop Bits", self.stop_bits))
        layout.addWidget(self._serial_fields[-1])
        self.connection_type.currentIndexChanged.connect(self._on_connection_type)

        self.cycle_check = QCheckBox("Cycle polling (all devices once)")
        self.cycle_check.setToolTip(
            "ON: each cycle reads every device exactly once in Slave-ID order, so all devices are sampled together.\n"
            "The cycle repeats every (longest Poll Rate), or right after the previous one if that takes longer.\n"
            "OFF: every device keeps its own Poll Rate independently.")
        try:
            from PySide6.QtCore import QSettings
            self.cycle_check.setChecked(
                str(QSettings("Nelumbo", "ConnectivityUtility").value("multi_device/cycle_polling", "true")).lower() != "false")
        except Exception:
            self.cycle_check.setChecked(True)
        self.cycle_check.toggled.connect(self._cycle_toggled)
        layout.addWidget(self.cycle_check)

        self.connect_button = QPushButton("🔌  CONNECT")
        self.connect_button.setObjectName("connectButton")
        self.connect_button.clicked.connect(self._toggle_connection)
        layout.addWidget(self.connect_button)

        status = QFrame()
        status.setObjectName("subPanel")
        sl = QVBoxLayout(status)
        sl.setContentsMargins(9, 8, 9, 8)
        sl.setSpacing(5)
        st = QLabel("●  CONNECTION STATUS")
        st.setObjectName("panelTitle")
        sl.addWidget(st)
        self.status_indicator = QLabel("●  Disconnected")
        self.status_indicator.setObjectName("statusOffline")
        self.status_indicator.setAlignment(Qt.AlignCenter)
        sl.addWidget(self.status_indicator)
        self.status_text = QLabel(
            "PORT          :  --\n"
            "BAUD RATE     :  9600\n"
            "DATA BITS     :  8\n"
            "PARITY        :  None\n"
            "STOP BITS     :  1\n"
            "CONNECTION    :  Modbus RTU"
        )
        self.status_text.setObjectName("statusValue")
        sl.addWidget(self.status_text)
        layout.addWidget(status)
        status.hide()          # Connection Status panel removed from the screen (widgets stay for the handlers)

        stats = QFrame()
        stats.setObjectName("subPanel")
        ssl = QVBoxLayout(stats)
        ssl.setContentsMargins(9, 8, 9, 8)
        ssl.setSpacing(4)
        stitle = QLabel("▥  STATISTICS (SESSION)")
        stitle.setObjectName("panelTitle")
        ssl.addWidget(stitle)
        self.session_summary = QLabel()
        self.session_summary.setObjectName("statusValue")
        ssl.addWidget(self.session_summary)
        layout.addWidget(stats)
        layout.addWidget(self._polling_cycle_panel())
        self._stats_panel_widget = self._statistics_panel()   # per-device statistics, now in the left column
        self._stats_panel_widget.setMinimumHeight(260)
        layout.addWidget(self._stats_panel_widget, 1)
        layout.addStretch()
        return panel
    def _manager_panel(self):
        wrapper = QWidget()
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        def setting_label(text):
            label = QLabel(text)
            label.setObjectName("settingLabel")
            return label

        def spin(lo, hi, value, suffix=""):
            box = QSpinBox()
            box.setRange(lo, hi)
            box.setValue(value)
            if suffix:
                box.setSuffix(suffix)
            return box

        add = QFrame()
        self._add_panel = add
        add.setObjectName("panel")
        al = QGridLayout(add)
        al.setContentsMargins(11, 9, 11, 9)
        al.setHorizontalSpacing(8)
        al.setVerticalSpacing(6)

        self.add_title = QLabel("＋  ADD NEW DEVICE")
        self.add_title.setObjectName("panelTitle")
        al.addWidget(self.add_title, 0, 0, 1, 4)
        self.write_confirm = QCheckBox("Confirm before write")
        self.addr_hex = QCheckBox("Hex address")
        # How a click on a DO LED is written (modules differ in what they accept)
        self.do_write_label = QLabel("DO write:")
        _ss(self.do_write_label, "color:#174F78;font-size:9px;font-weight:600;")
        self.do_write_input = QComboBox()
        for code, text in DO_WRITE_MODES.items():
            self.do_write_input.addItem(text, code)
        self.do_write_input.setToolTip(
            "Function used when you click a DO LED.\n"
            "If the module does not answer 05, try 15 (one coil), then 15 (all coils), then 06.")
        options = QHBoxLayout()
        options.setSpacing(18)
        options.addStretch()
        options.addWidget(self.do_write_label)
        options.addWidget(self.do_write_input)
        options.addWidget(self.write_confirm)
        options.addWidget(self.addr_hex)
        al.addLayout(options, 0, 4, 1, 2)
        al.setColumnStretch(1, 3)
        al.setColumnStretch(3, 2)
        al.setColumnStretch(5, 1)

        self.device_name_input = QLineEdit()
        self.device_name_input.setPlaceholderText("e.g. DI-Panel-1")
        self.device_type_input = self._combo([
            "Digital Input (DI)",
            "Digital Output (DO)",
            "Analog Input (AI)",
            "Analog Output (AO)",
            "MFT (Multi Function Transducer)",
        ])
        self.slave_input = spin(1, 247, 1)
        self.function_input = QComboBox()
        for code, text in ALL_FUNCTIONS.items():
            self.function_input.addItem(text, code)
        self.address_input = spin(0, 65535, 0)
        self.count_input = spin(1, 2000, 16)
        self.poll_input = spin(50, 60000, 1000, " ms")
        self.add_scan_display = spin(10, 60000, 60000, " ms")
        self.add_timeout_display = spin(50, 60000, 2000, " ms")
        self.add_retry_display = spin(0, 10, 3)
        self.data_format_input = QComboBox()
        for code, text in DATA_FORMATS.items():
            self.data_format_input.addItem(text, code)
        self.word_order_input = QComboBox()
        for code, text in WORD_ORDERS.items():
            self.word_order_input.addItem(text, code)
        self.data_format_input.setToolTip("How the registers are read: 16-bit raw, or 32-bit (2 registers per channel).")
        self.word_order_input.setToolTip("32-bit values only.\nMSRF: first register = high word (Modbus default).\n"
                                         "LSRF: first register = low word (word-swapped).")
        self.format_label = setting_label("Data Format")
        self.order_label = setting_label("Word Order")

        al.addWidget(setting_label("Device Name"), 1, 0)
        al.addWidget(self.device_name_input, 1, 1)
        al.addWidget(setting_label("Device Type"), 1, 2)
        al.addWidget(self.device_type_input, 1, 3)
        self.slave_label = setting_label("Device ID")
        al.addWidget(self.slave_label, 1, 4)
        al.addWidget(self.slave_input, 1, 5)
        self.dev_ip_input = QLineEdit("192.168.1.10")
        self.dev_ip_input.setPlaceholderText("e.g. 192.168.1.10")
        self.dev_subnet_input = QLineEdit("255.255.255.0")
        self.dev_subnet_input.setPlaceholderText("e.g. 255.255.255.0")
        self.dev_subnet_input.setToolTip("Checked against this PC's network (device and PC must be on the same "
                                         "subnet). It is not sent to the device.")
        self.dev_port_input = spin(1, 65535, 502)
        self._tcp_form_widgets = []
        for column, (text, widget) in enumerate((("IP Address", self.dev_ip_input), ("Subnet Mask", self.dev_subnet_input),
                                                 ("TCP Port", self.dev_port_input))):
            label = setting_label(text)
            al.addWidget(label, 6, column * 2)
            al.addWidget(widget, 6, column * 2 + 1)
            self._tcp_form_widgets += [label, widget]
        al.addWidget(setting_label("Point Type"), 2, 0)
        al.addWidget(self.function_input, 2, 1)
        al.addWidget(setting_label("Start Address"), 2, 2)
        al.addWidget(self.address_input, 2, 3)
        self.length_label = setting_label("Length")
        al.addWidget(self.length_label, 2, 4)
        al.addWidget(self.count_input, 2, 5)
        al.addWidget(setting_label("Poll Interval (ms)"), 3, 0)
        al.addWidget(self.poll_input, 3, 1)
        al.addWidget(setting_label("Timeout (ms)"), 3, 2)
        al.addWidget(self.add_timeout_display, 3, 3)
        al.addWidget(setting_label("Scan Rate (ms)"), 3, 4)
        al.addWidget(self.add_scan_display, 3, 5)
        al.addWidget(setting_label("Max Retries"), 4, 0)
        al.addWidget(self.add_retry_display, 4, 1)
        al.addWidget(self.format_label, 5, 0)
        al.addWidget(self.data_format_input, 5, 1)
        al.addWidget(self.order_label, 5, 2)
        al.addWidget(self.word_order_input, 5, 3)
        self.data_format_input.currentIndexChanged.connect(self._on_format_changed)

        self.add_device_button = QPushButton("＋  Add Device")
        self.add_device_button.setObjectName("primaryButton")
        self.add_device_button.clicked.connect(self._manual_add_device)
        self.clear_form_button = QPushButton("↻  Clear")
        self.clear_form_button.setObjectName("outlineButton")
        self.clear_form_button.clicked.connect(self._clear_add_form)
        al.addWidget(self.add_device_button, 4, 2, 1, 2)
        al.addWidget(self.clear_form_button, 4, 4, 1, 2)

        self._sync_add_mode()
        self.device_type_input.currentIndexChanged.connect(self._on_type_changed)
        self.function_input.currentIndexChanged.connect(self._on_function_changed)
        self.addr_hex.toggled.connect(self._on_addr_hex)
        self._apply_profile(0)
        outer.addWidget(add)

        panel = QFrame()
        self._table_panel = panel
        panel.setObjectName("panel")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(10, 8, 10, 8)
        pl.setSpacing(6)

        head = QHBoxLayout()
        t = self._focus_title("table", "▦  CONFIGURED DEVICES")
        t.setObjectName("panelTitle")
        head.addWidget(t)
        self.device_count_label = QLabel("(0)")
        self.device_count_label.setObjectName("muted")
        head.addWidget(self.device_count_label)
        head.addStretch()

        self.scan_button = QPushButton("⟳  Rescan Devices")
        self.scan_button.setObjectName("primaryButton")
        self.scan_button.clicked.connect(self._start_scan)
        self.run_all_button = QPushButton("▶  Run All")
        self.run_all_button.setObjectName("runButton")
        self.run_all_button.clicked.connect(self._run_all)
        self.stop_all_button = QPushButton("■  Stop All")
        self.stop_all_button.setObjectName("stopButton")
        self.stop_all_button.clicked.connect(self._stop_all)
        self.remove_selected_button = QPushButton("♲  Remove Selected")
        self.remove_selected_button.setObjectName("dangerOutline")
        self.remove_selected_button.clicked.connect(self._remove_selected_devices)
        self.add_toggle_button = QPushButton("\uff0b  Add Device")
        self.add_toggle_button.setObjectName("primaryButton")
        self.add_toggle_button.setToolTip("Show / hide the Add New Device panel while devices are running")
        self.add_toggle_button.clicked.connect(self._toggle_add_panel)
        self.add_toggle_button.setVisible(False)
        self.open_project_button = QPushButton("\U0001F4C2  Open")
        self.open_project_button.setObjectName("outlineButton")
        self.open_project_button.setToolTip("Open a saved project (devices + communication settings)")
        self.open_project_button.clicked.connect(self._open_project)
        self.save_project_button = QPushButton("\U0001F4BE  Save")
        self.save_project_button.setObjectName("outlineButton")
        self.save_project_button.setToolTip("Save this project to a file. The project is also saved automatically "
                                            "and reopens next time.")
        self.save_project_button.clicked.connect(self._save_project_as)
        for button in (self.add_toggle_button, self.open_project_button, self.save_project_button,
                       self.scan_button, self.run_all_button, self.stop_all_button,
                       self.remove_selected_button):
            head.addWidget(button)
        pl.addLayout(head)

        self.device_table = QTableWidget(0, 12)
        self.device_table.setHorizontalHeaderLabels([
            "", "No.", "Device Name", "Type", "Slave ID / IP", "Function",
            "Poll Rate (ms)", "Scan Rate (ms)", "Timeout (ms)",
            "Retries", "Status", "Actions"
        ])
        self.device_table.verticalHeader().setVisible(False)
        self.device_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.device_table.setSelectionMode(QTableWidget.NoSelection)
        self.device_table.setAlternatingRowColors(False)
        self.device_table.setMinimumHeight(120)
        self.device_table.cellDoubleClicked.connect(self._row_double_clicked)
        self.device_table.verticalHeader().setDefaultSectionSize(34)
        header = self.device_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setStretchLastSection(True)
        header.setMinimumSectionSize(42)
        header.setSectionResizeMode(0, QHeaderView.Fixed)       # checkbox column
        header.setSectionResizeMode(11, QHeaderView.Fixed)      # Actions column: always wide enough for 3 buttons
        header.setStretchLastSection(False)
        self._fix_table_columns()
        self.device_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        pl.addWidget(self.device_table)

        self.no_device_label = QLabel("No devices configured")
        self.no_device_label.setAlignment(Qt.AlignCenter)
        _ss(self.no_device_label, "color:#7B9AB3;font-size:11px;padding:12px;")
        pl.addWidget(self.no_device_label)
        outer.addWidget(panel, 1)
        return wrapper
    def _data_panel(self):
        panel = QFrame()
        panel.setObjectName("panel")
        l = QVBoxLayout(panel)
        l.setContentsMargins(9, 8, 9, 8)
        l.setSpacing(6)
        title = self._focus_title("data", "▣  LIVE DEVICE STATUS")
        title.setObjectName("panelTitle")
        l.addWidget(title)

        self.data_scroll = QScrollArea()
        self.data_scroll.setWidgetResizable(True)
        self.data_scroll.setFrameShape(QFrame.NoFrame)
        self.data_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.data_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.data_container = QWidget()
        self.data_layout = QGridLayout(self.data_container)
        self.data_layout.setContentsMargins(0, 0, 0, 0)
        self.data_layout.setHorizontalSpacing(7)
        self.data_layout.setVerticalSpacing(7)
        self.data_scroll.setWidget(self.data_container)
        self.data_scroll.viewport().installEventFilter(self)

        self.no_data_label = QLabel("No devices configured")
        self.no_data_label.setAlignment(Qt.AlignCenter)
        _ss(self.no_data_label, "color:#7B9AB3;font-size:11px;padding:20px;")
        self.data_layout.addWidget(self.no_data_label, 0, 0)
        l.addWidget(self.data_scroll, 1)
        return panel
    def _terminal_panel(self):
        panel = QFrame()
        panel.setObjectName("panel")
        l = QVBoxLayout(panel)
        l.setContentsMargins(9, 8, 9, 8)
        l.setSpacing(6)
        tr = QHBoxLayout()
        title = self._focus_title("terminal", "▤  TX / RX TERMINAL")
        title.setObjectName("panelTitle")
        tr.addWidget(title)
        tr.addStretch()
        tr2 = QHBoxLayout()
        tr2.setSpacing(6)

        clear = QPushButton("Clear")
        clear.setObjectName("outlineButton")
        clear.clicked.connect(self._clear_terminal_and_statistics)
        tr.addWidget(clear)

        self.log_duration = QComboBox()
        for text, minutes in (("Until stop", 0), ("5 min", 5), ("10 min", 10), ("20 min", 20),
                              ("30 min", 30), ("60 min", 60)):
            self.log_duration.addItem(text, minutes)
        self.log_duration.setCurrentIndex(3)
        self.log_duration.setToolTip("Record Log stops by itself after this time")
        self.log_duration.setMinimumWidth(96)
        tr2.addWidget(self.log_duration)

        self.log_button = QPushButton("\u25cf  Record Log")
        self.log_button.setObjectName("outlineButton")
        self.log_button.setToolTip("Save every TX/RX line to a .txt file (all lines, with time), for analysis")
        self.log_button.clicked.connect(self._toggle_log)
        tr2.addWidget(self.log_button)

        self.csv_button = QPushButton("\u25cf  Record CSV")
        self.csv_button.setObjectName("outlineButton")
        self.csv_button.setToolTip("Save every reading (time, device, all channels, status, response time), "
                                   "timeouts and writes to a .csv file that opens in Excel")
        self.csv_button.clicked.connect(self._toggle_csv)
        tr2.addWidget(self.csv_button)

        self.auto_scroll = QCheckBox("Auto Scroll")
        self.auto_scroll.setChecked(True)
        _ss(self.auto_scroll, "color:#174F78;font-size:9px;font-weight:600;")
        tr2.addWidget(self.auto_scroll)

        self.show_timestamps = QCheckBox("Show Timestamps")
        self.show_timestamps.setChecked(True)
        _ss(self.show_timestamps, "color:#174F78;font-size:9px;font-weight:600;")
        tr2.addWidget(self.show_timestamps)
        tr2.addStretch()

        self.expand_button = QPushButton("\u2922  Expand")
        self.expand_button.setObjectName("outlineButton")
        self.expand_button.setToolTip("Give the terminal the whole Live tab (click again to restore). "
                                      "Ctrl + mouse wheel changes the text size.")
        self.expand_button.clicked.connect(lambda: self._toggle_focus("terminal"))
        tr.addWidget(self.expand_button)
        l.addLayout(tr)
        l.addLayout(tr2)

        self.terminal = TerminalEdit()
        self.terminal.setObjectName("terminal")
        self.terminal.setReadOnly(True)
        self.terminal.setMaximumBlockCount(1000)
        l.addWidget(self.terminal, 1)
        return panel
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "_scale_timer"):
            self._scale_timer = QTimer(self)
            self._scale_timer.setSingleShot(True)
            self._scale_timer.timeout.connect(self._auto_scale)
        self._scale_timer.start(120)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._auto_scale)

    def _auto_scale(self):
        """Whole UI follows the window: text, inputs, buttons, rows and header."""
        global _UI_SCALE
        width = self.window().width() or self.width()
        height = self.window().height() or self.height()
        factor = max(1.0, min(1.8, round(min(width / 1250.0, height / 800.0) * 10) / 10.0))
        if factor == _UI_SCALE:
            return
        _UI_SCALE = factor
        self._restyle_async()

    # ---- restyle in small slices ------------------------------------------------
    # A change of window size / theme re-applies ~360 style sheets. Done in one go that freezes the window
    # for a moment; here it is done in slices of ~10 ms, so the window keeps answering all the time.
    def _restyle_widget(self, widget, factor):
        text = widget.property("_qss0")
        if text:
            widget.setStyleSheet(_scaled(_themed(text), factor * (widget.property("_qss_k") or 1.0)))
        template = widget.property("_lc_qss")
        if template:
            widget.setStyleSheet(lc._render(template, widget.property("_lc_k") or 1.0))
        if hasattr(widget, "retheme"):
            widget.retheme()

    def _restyle_async(self, theme_changed=False):
        self._theme_tail = getattr(self, "_theme_tail", False) or theme_changed
        factor = _UI_SCALE
        lc.THEME, lc.SCALE = ("dark" if _THEME == "dark" else "light"), factor
        self._restyle_gen = getattr(self, "_restyle_gen", 0) + 1
        gen = self._restyle_gen
        widgets = iter([self] + self.findChildren(QWidget))
        if not getattr(self, "_restyle_busy", False):
            self._restyle_busy = True
            self.setUpdatesEnabled(False)

        def step():
            if gen != self._restyle_gen:
                return                      # a newer restyle has started
            started = time.perf_counter()
            for widget in widgets:
                try:
                    self._restyle_widget(widget, factor)
                except RuntimeError:
                    pass                    # widget deleted meanwhile
                if time.perf_counter() - started > 0.010:
                    QTimer.singleShot(0, step)
                    return
            self._restyle_busy = False
            self.setUpdatesEnabled(True)
            self._restyle_done()
        QTimer.singleShot(0, step)

    def _restyle_done(self):
        self._apply_scale_tail(_UI_SCALE)
        if getattr(self, "_theme_tail", False):
            self._theme_tail = False
            self._apply_theme_tail()

    def _apply_scale_tail(self, factor):
        hs = 1.0 + (factor - 1.0) * 0.45          # the header grows much less than the rest of the UI
        self._header.setMinimumHeight(int(62 * hs))
        self._header.setMaximumHeight(int(72 * hs))
        self._company_label.setFixedHeight(int(22 * hs))
        self._subtitle_label.setFixedHeight(int(18 * hs))
        self.device_table.verticalHeader().setDefaultSectionSize(int(34 * factor))
        self._fix_table_columns()
        for _row in range(self.device_table.rowCount()):
            self.device_table.setRowHeight(_row, int(40 * factor))
        self._connection_widget.setMinimumWidth(int(238 * factor))
        self._connection_widget.setMaximumWidth(int(270 * factor))
        self._stats_column.setMinimumWidth(int(200 * factor))
        self._lower_split.setMinimumHeight(int(400 * max(1.0, factor * 0.9)))
        self._fit_manager()
        self._card_cols = 0
        self._reflow_cards()

    # ---- theme ------------------------------------------------------------------
    def _load_theme(self):
        try:
            from PySide6.QtCore import QSettings
            return "dark" if QSettings("Nelumbo", "ConnectivityUtility").value("multi_device/theme", "light") == "dark" else "light"
        except Exception:
            return "light"

    def _update_status_bar(self):
        st = self._stats
        if self._connected:
            head = (f"\u25cf Connected   {self.com_port.currentText()} \u00b7 {self.baud_rate.currentText()} "
                    f"{self.data_bits.currentText()}{self.parity.currentText()[:1]}{self.stop_bits.currentText()}")
            tone = "ok"
        else:
            head, tone = "\u25cf Disconnected", "off"
        last = st.get("last_response", "--")
        text = (f"  {head}      TX {st['tx']:,}  \u00b7  RX {st['rx']:,}  \u00b7  Err {st['errors']:,}      "
                f"Last response {last}      Devices {len(self._devices)}")
        if self._status_bar.text() != text:
            self._status_bar.setText(text)
        if tone != self._status_tone:
            self._status_tone = tone
            color = "#1F6FEB" if tone == "ok" else "#B62324"
            self._status_bar.setStyleSheet(f"background:{color}; color:#FFFFFF; font-size:11px; font-weight:600;")

    def _cycle_toggled(self, on):
        try:
            from PySide6.QtCore import QSettings
            QSettings("Nelumbo", "ConnectivityUtility").setValue("multi_device/cycle_polling", "true" if on else "false")
        except Exception:
            pass
        scanner = getattr(self, "_scanner", None)
        if scanner is not None:
            scanner.set_cycle_polling(on)

    def _toggle_theme(self):
        self.set_theme("light" if _THEME == "dark" else "dark")

    def set_theme(self, name, save=True, restyle=True):
        """Light / dark: re-apply every stored style sheet in the new palette and repaint."""
        global _THEME
        name = "dark" if name == "dark" else "light"
        _THEME = name
        if save:
            try:
                from PySide6.QtCore import QSettings
                QSettings("Nelumbo", "ConnectivityUtility").setValue("multi_device/theme", name)
            except Exception:
                pass
        if restyle:
            self._restyle_async(theme_changed=True)
        else:
            self._apply_theme_tail()          # the sheets are already in this theme and scale (start-up, light)

    def _apply_theme_tail(self):
        try:
            from . import history_views as _hv
        except ImportError:
            import history_views as _hv
        _hv.set_theme(_THEME)                 # the hand-painted trend chart
        for _chart in self.findChildren(QWidget):
            if type(_chart).__name__ == "TrendChart":
                _chart.update()
        self.dashboard_tab.apply_theme(_THEME)
        for card in list(self._card_refs.values()):
            card._cache.clear()
        self._dirty_devices.update(self._devices)
        self._rebuild_device_table()

    def _fix_table_columns(self):
        self.device_table.setColumnWidth(0, int(40 * _UI_SCALE))
        self.device_table.setColumnWidth(11, int(124 * _UI_SCALE))

    def _toggle_add_panel(self):
        self._add_forced = not self._add_forced
        self._sync_add_panel()

    def _fit_manager(self):
        """Give the device table only the height it needs; the rest goes to the lower row (terminal)."""
        if self._focus is not None or self._spot_sid is not None:
            return
        mgr = self._manager_widget
        mgr.setMinimumHeight(0)
        mgr.layout().invalidate()
        mgr.layout().activate()
        need = mgr.minimumSizeHint().height()
        mgr.setMinimumHeight(need)
        total = max(1, sum(self._right_split.sizes()))
        if self._add_panel.isVisible():
            want = max(need, int(total * 0.42))
        else:
            rows = min(self.device_table.rowCount(), 8)      # up to 8 devices fully visible, then the table scrolls
            want = max(need, rows * self.device_table.verticalHeader().defaultSectionSize()
                       + int(110 * _UI_SCALE))
            mgr.setMinimumHeight(want)        # page scrolls instead of cutting the table / terminal
        self._right_split.setSizes([want, max(1, total - want)])

    def _sync_add_panel(self):
        """Devices running: hide the Add New Device panel so everything moves up
        and the terminal gets the space. Stopped / editing: show it again."""
        if self._focus is not None or self._spot_sid is not None:
            return
        running = any(d.get("enabled") for d in self._devices.values())
        if not running:
            self._add_forced = False
        show = (not running) or self._add_forced or self._editing is not None
        state = (show, running, self._add_forced)
        if state == getattr(self, "_add_state", None):
            return
        self._add_state = state
        self._add_panel.setVisible(show)
        self.add_toggle_button.setVisible(running)
        self.add_toggle_button.setText("\u25b2  Hide Add" if (running and show) else "\uff0b  Add Device")
        self._fit_manager()

    # ------------------------------------------------------------------ #
    # Focus mode (click a panel title) and Device Spotlight (click a card)
    # ------------------------------------------------------------------ #
    def _focus_title(self, name, text):
        label = ClickLabel(text + "   \u2922")
        label.setToolTip("Click to enlarge this panel  (Esc or click again to restore)")
        label.clicked.connect(lambda n=name: self._toggle_focus(n))
        self._focus_titles[name] = (label, text)
        return label

    def _toggle_focus(self, name):
        self._focus = None if self._focus == name else name
        self._apply_layout()

    def _escape_pressed(self):
        if self._focus is not None:
            self._focus = None
            self._apply_layout()

    def _fade_in(self, widget):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", widget)
        anim.setDuration(220)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.finished.connect(lambda w=widget: w.setGraphicsEffect(None))
        widget._fade = anim
        anim.start()

    def _apply_layout(self):
        """One place that decides what is visible: normal / focused panel / spotlight."""
        spot = self._spot_sid is not None
        focus = self._focus
        console = getattr(self, "_mode", "setup") == "console"
        self._connection_widget.setVisible(not focus and not console)

        target = None
        if spot:
            self._manager_widget.setVisible(False)
            self._lower_split.setVisible(False)
            target = None
        elif focus == "table":
            self._manager_widget.setVisible(True)
            self._add_panel.setVisible(False)
            self._lower_split.setVisible(False)
            target = self._manager_widget
        elif focus in ("data", "terminal", "stats"):
            self._manager_widget.setVisible(False)
            self._lower_split.setVisible(True)
            for name, widget in self._focus_widgets.items():
                if name != "table":
                    widget.setVisible(name == focus)
            target = self._focus_widgets[focus]
        else:
            self._manager_widget.setVisible(True)
            self._lower_split.setVisible(True)
            for name, widget in self._focus_widgets.items():
                if name != "table":
                    widget.setVisible(True)
            self._add_state = None
            self._sync_add_panel()
            self._fit_manager()
        for name, (label, text) in self._focus_titles.items():
            label.setText(text + ("   \u2921" if focus == name and not spot else "   \u2922"))
        self.expand_button.setText("\u2921  Restore" if focus == "terminal" and not spot else "\u2922  Expand")
        if target is not None:
            self._fade_in(target)
        self._card_cols = 0
        self._reflow_cards()

    def _open_spotlight(self, slave_id):
        """Select a device in the Live console (from the list, a card or the table)."""
        device = self._devices.get(slave_id)
        if device is None:
            return
        if self._mode != "console" or self.tabs.currentIndex() != 1:
            self._mode = "console"
            self.tabs.setCurrentIndex(1)
            self._sync_mode()
        self._spot_sid = slave_id
        self._last_selected = slave_id
        self._live.devices.select(slave_id)
        self._live.console.set_device(slave_id)
        detail = self._live.detail
        detail.sid = slave_id
        detail.show_device(device)
        detail.traffic.clear()
        for line in self._live.console.lines_for(slave_id):
            detail.traffic.appendHtml(f'<div style="white-space:pre">{line}</div>')
        self._apply_layout()
        self._refresh_spotlight(device)

    def _close_spotlight(self):
        """The selected device was removed: pick another one (or show the empty state)."""
        if self._spot_sid is None:
            return
        self._spot_sid = None
        self._live.devices.select(None)
        if self._mode == "console" and self._devices:
            self._open_spotlight(sorted(self._devices)[0])
            return
        self._live.detail.set_empty(True, "No devices yet \u2014 use Add device")
        self._apply_layout()

    def _sync_mode(self):
        console = self._mode == "console"
        self._stack.setCurrentIndex(0 if console else 1)
        self._body_layout.setContentsMargins(*((0, 0, 0, 0) if console else (8, 8, 8, 8)))
        self._body_layout.setSpacing(0 if console else 8)
        if not console:
            self._spot_sid = None
            self._live.devices.select(None)
        self._apply_layout()
        self._sync_nav()

    def _set_mode(self, mode):
        if mode == self._mode:
            self._sync_nav()
            return
        self._mode = mode
        self._sync_mode()
        if mode == "console" and self._devices:
            self._open_spotlight(self._last_selected if self._last_selected in self._devices
                                 else sorted(self._devices)[0])

    _NAV_PAGES = ("dashboard", "live")
    _NAV_TITLES = {"dashboard": "Dashboard", "live": "Live", "setup": "Setup"}

    def _nav_to(self, key):
        if key == "setup":
            self.tabs.setCurrentIndex(1)
            self._set_mode("setup")
        elif key == "live":
            self.tabs.setCurrentIndex(1)
            self._set_mode("console")
        else:
            self.tabs.setCurrentIndex(self._NAV_PAGES.index(key))
        self._sync_nav()

    def _sync_nav(self):
        if not hasattr(self, "_nav"):
            return
        index = self.tabs.currentIndex()
        key = self._NAV_PAGES[index] if 0 <= index < len(self._NAV_PAGES) else "live"
        if key == "live" and self._mode == "setup":
            key = "setup"
        self._nav.set_current(key)
        self._top.set_page(self._NAV_TITLES[key])

    def _add_from_console(self):
        self._nav_to("setup")
        self._add_forced = True
        self._add_state = None
        self._sync_add_panel()
        self.device_name_input.setFocus()

    def _toggle_pause(self, slave_id):
        device = self._devices.get(slave_id)
        if device is None:
            return
        if device.get("enabled"):
            self._stop_device(slave_id)
        else:
            self._run_device(slave_id)

    def _edit_from_console(self, slave_id):
        device = self._devices.get(slave_id)
        if device is None:
            return
        self._nav_to("setup")
        self._edit_device(device.get("key", slave_id))

    def _row_value(self, device, status):
        if status not in ("ONLINE", "RETRYING"):
            return {"OFFLINE": "Timeout", "DISABLED": "Paused"}.get(status, "Not polled")
        values = list(device.get("latest_data") or [])
        if not values:
            return "--"
        kind = device.get("kind")
        if kind in ("DI", "DO"):
            on = sum(1 for _n, v in values if v)
            return f"{on} / {len(values)} " + ("high" if kind == "DI" else "on")
        if kind == "MFT":
            data = dict(values)
            volts = [data.get(k) for k in ("AVrms", "BVrms", "CVrms") if lc.finite(data.get(k))]
            return f"{sum(volts) / len(volts):.1f} V" if volts else "--"
        name, value = values[0]
        fmt = effective_format(device) if kind in ("AI", "AO") else "raw16"
        if fmt in ("hex16", "hex32"):
            return format_value(value, fmt)
        units = device.get("latest_units") or []
        unit = units[0] if units and units[0] else ""
        text = f"{value:.2f}" if isinstance(value, float) else str(value)
        return f"{text} {unit}".strip()

    def _row_meta(self, device):
        function = int(device.get("function", 0) or 0)
        count = device.get("count", 0)
        what = {1: "coils", 2: "inputs"}.get(function, "regs")
        meta = f"{_id_text(device)} \u00b7 FC{function:02d} \u00b7 {count} {what}"
        if function in (3, 4) and device.get("kind") in ("AI", "AO") and ENABLE_FORMATS:
            fmt = effective_format(device)
            if fmt != "raw16":
                meta += f" \u00b7 {fmt.capitalize()}" + (f" {device.get('word_order') or 'MSRF'}" if fmt in WIDE_FORMATS else "")
        return meta

    def _refresh_live_row(self, device):
        row = self._live.devices.rows.get(device["slave_id"])
        if row is None:
            return
        status = self._status_text(device)
        row.refresh(device, status, self._row_value(device, status), self._row_meta(device),
                    device.get("resp_hist") or [])

    def _sync_topbar(self):
        tcp = self._is_tcp()
        if self._connected and len(self._links) > 1:
            tone = "warn" if getattr(self, "_writing", False) else "ok"
            parts = ["Writing\u2026" if tone == "warn" else "Connected", self._link_text(),
                     " + ".join(LINK_SHORT[l] for l in LINKS if l in self._links)]
            raw = _re.sub(r"[^A-Za-z .]", "", self.connect_button.text()).strip()
            link = {"CONNECT": "Connect", "DISCONNECT": "Disconnect"}.get(raw.upper(), raw.title())
            self._top.set_connection(tone, parts, link, self.connect_button.isEnabled())
            self._live.console.set_recording(self._log_file is not None)
            return
        if self._connected:
            tone = "warn" if getattr(self, "_writing", False) else "ok"
            parts = ["Writing\u2026" if tone == "warn" else "Connected", self._link_text()]
        else:
            tone = "bad" if self._port_lost else "idle"
            parts = ["Disconnected", self._link_text() or "No port"]
        if not tcp:
            parts.append(f"{self.baud_rate.currentText()} \u00b7 {self.data_bits.currentText()}"
                         f"{self.parity.currentText()[:1]}{self.stop_bits.currentText()}")
        parts.append(self.connection_type.currentText() if tcp else "Modbus RTU")
        raw = _re.sub(r"[^A-Za-z .]", "", self.connect_button.text()).strip()
        link = {"CONNECT": "Connect", "DISCONNECT": "Disconnect"}.get(raw.upper(), raw.title())
        self._top.set_connection(tone, parts, link, self.connect_button.isEnabled())
        self._live.console.set_recording(self._log_file is not None)

    def _update_live_stats(self, online, total):
        st = self._stats
        now = time.monotonic()
        self._rate_samples.append((now, st["tx"]))
        self._rate_samples = [s for s in self._rate_samples if now - s[0] <= 10.0]
        t0, tx0 = self._rate_samples[0]
        rate = (st["tx"] - tx0) / (now - t0) if now - t0 > 0.5 else 0.0
        if now - self._rate_at >= 1.0:
            self._rate_at = now
            self._rate_hist.append(rate)
            del self._rate_hist[:-40]
        cells = self._live.stats.cells
        devices = sorted(self._devices.values(), key=lambda d: d["slave_id"])
        cells["online"].set(str(online), f"/ {total}" if total else "")
        self._live.stats.meter.set_tones([lc.STATUS_TONE.get(self._status_text(d), "idle") for d in devices])
        cells["req"].set(f"{st['tx']:,}", "", f"{rate:.1f} req/s")
        self._live.stats.req_spark.set_data(self._rate_hist, "accent")
        if st["tx"]:
            success = 100.0 * st["successful"] / st["tx"]
            cells["rate"].set(f"{min(100.0, success):.1f}", "%",
                              f"{st['timeouts']} timeouts \u00b7 {st['errors']} errors",
                              "ok" if success >= 99.0 else "warn")
        else:
            cells["rate"].set("--", "", "no requests yet")
        resp = self._resp_all
        if resp:
            ordered = sorted(resp)
            p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
            cells["resp"].set(f"{sum(resp) / len(resp):.0f}", "ms", f"p95 {p95} ms")
            self._live.stats.resp_spark.set_data(resp[-40:], "ok")
        else:
            cells["resp"].set("--", "", "waiting for replies")
        if self._last_timeout:
            name, at = self._last_timeout
            age = now - at
            ago = f"{age:.0f} s ago" if age < 60 else f"{age / 60:.0f} min ago"
            cells["to"].set(f"{st['timeouts']:,}", "", f"{name} \u00b7 {ago}", "bad" if age < 30 else None)
        else:
            cells["to"].set(f"{st['timeouts']:,}", "", "none this session")

    def _spot_step(self, direction):
        sids = sorted(self._devices)
        if not sids or self._spot_sid not in sids:
            return
        self._open_spotlight(sids[(sids.index(self._spot_sid) + direction) % len(sids)])

    def _refresh_spotlight(self, device):
        if device["slave_id"] != self._spot_sid:
            return
        self._live.detail.refresh(device, self._status_text(device))

    def _statistics_panel(self):
        panel = QFrame()
        panel.setObjectName("panel")
        l = QVBoxLayout(panel)
        l.setContentsMargins(9, 8, 9, 8)
        l.setSpacing(5)
        title = QLabel("▥  SESSION STATISTICS")
        title.setObjectName("panelTitle")
        l.addWidget(title)
        self.statistics = QPlainTextEdit()
        self.statistics.setObjectName("statusValue")
        self.statistics.setReadOnly(True)
        self.statistics.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.statistics.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.statistics.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.statistics.setPlainText(
            "Total Devices   :   0\n"
            "Running Devices :   0\n"
            "Total TX        :   0\n"
            "Total RX        :   0\n"
            "Successful      :   0\n"
            "Timeouts        :   0\n"
            "Retries         :   0\n"
            "Errors          :   0"
        )
        l.addWidget(self.statistics, 1)
        return panel
    def _polling_cycle_panel(self):
        panel = QFrame()
        panel.setObjectName("panel")
        l = QVBoxLayout(panel)
        l.setContentsMargins(9, 8, 9, 8)
        l.setSpacing(5)
        title = QLabel("◌  POLLING CYCLE")
        title.setObjectName("panelTitle")
        l.addWidget(title)

        row = QHBoxLayout()
        self.polling_donut = PollingDonut()
        row.addWidget(self.polling_donut, 0, Qt.AlignCenter)

        legend = QVBoxLayout()
        self.poll_online = QLabel("●  Online   0")
        _ss(self.poll_online, "color:#12A45B;font-size:9px;font-weight:600;")
        self.poll_offline = QLabel("●  Offline   0")
        _ss(self.poll_offline, "color:#E53935;font-size:9px;font-weight:600;")
        self.poll_retry = QLabel("●  Retrying   0")
        _ss(self.poll_retry, "color:#D88B00;font-size:9px;font-weight:600;")
        self.poll_idle = QLabel("●  Not Polled   0")
        _ss(self.poll_idle, "color:#8798A6;font-size:9px;font-weight:600;")
        for label in (self.poll_online, self.poll_offline, self.poll_retry, self.poll_idle):
            legend.addWidget(label)
        legend.addStretch()
        row.addLayout(legend)
        l.addLayout(row)
        return panel

    def _next_poll_panel(self):
        panel = QFrame()
        self._next_poll_frame = panel
        panel.hide()           # Next Poll panel removed from the screen
        panel.setObjectName("panel")
        l = QVBoxLayout(panel)
        l.setContentsMargins(9, 8, 9, 8)
        l.setSpacing(5)
        title = QLabel("◷  NEXT POLL")
        title.setObjectName("panelTitle")
        l.addWidget(title)
        self.next_poll_list = QVBoxLayout()
        self.next_poll_list.setSpacing(4)
        l.addLayout(self.next_poll_list)
        l.addStretch()
        return panel

    def _combo(self, values):
        combo = QComboBox()
        combo.addItems(values)
        return combo
    def _field(self, label_text, widget):
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        label = QLabel(label_text)
        label.setObjectName("fieldLabel")
        layout.addWidget(label)
        if isinstance(widget, QHBoxLayout):
            layout.addLayout(widget)
        else:
            layout.addWidget(widget)
        return box
    def _is_tcp(self):
        return self.connection_type.currentText() in ("Modbus TCP", tcpip.MODE_NAME)

    def _is_ip_mode(self):
        """Connection type "Modbus TCP (IP)": devices by IP address only (modbus_tcp_ip.py)."""
        return tcpip.is_mode(self.connection_type.currentText())

    def _on_connection_type(self, _index=None):
        tcp = self._is_tcp()
        ip_mode = self._is_ip_mode()
        for widget in self._serial_fields:
            widget.setVisible(not tcp)
        for widget in self._gw_fields:
            widget.setVisible(tcp and not ip_mode)
        self._tcp_hint.setVisible(ip_mode)
        self._sync_add_mode()
        self._save_project()

    def _sync_add_mode(self):
        """Add New Device: Device ID for the serial bus, IP / subnet / port for Modbus TCP."""
        if not hasattr(self, "dev_ip_input"):
            return
        tcp = self._is_tcp()
        ip_mode = self._is_ip_mode()
        self.slave_label.setText("Device ID (Unit)" if tcp else "Device ID")
        # Modbus TCP (IP): IP address only - no Device ID, subnet mask or port.
        # Modbus RTU / Modbus TCP: Device ID only (the gateway IP is in Communication Settings).
        self.slave_label.setVisible(not ip_mode)
        self.slave_input.setVisible(not ip_mode)
        for widget in self._tcp_form_widgets[:2]:
            widget.setVisible(ip_mode)
        for widget in self._tcp_form_widgets[2:]:
            widget.setVisible(False)

    def _free_sid(self):
        """Internal device number for a TCP device (it has no Device ID): the lowest unused one."""
        used = {d["slave_id"] for d in self._devices.values()} | {d["slave_id"] for d in self._writers.values()}
        return next((n for n in range(1, 248) if n not in used), None)

    def _tcp_form(self):
        """Validated IP / subnet / port of the Add form as device fields, or None (reason in the terminal)."""
        if self._is_ip_mode():
            host, error = tcpip.check_ip(self.dev_ip_input.text())
            if error:
                self._terminal(error)
                return None
            return tcpip.device_fields(host)
        host = self.dev_ip_input.text().strip()
        mask = self.dev_subnet_input.text().strip() or "255.255.255.0"
        try:
            ipaddress.IPv4Address(host)
        except ValueError:
            self._terminal(f"'{host}' is not a valid IPv4 address.")
            return None
        try:
            network = ipaddress.IPv4Network(f"{host}/{mask}", strict=False)
        except ValueError:
            self._terminal(f"'{mask}' is not a valid subnet mask (example: 255.255.255.0).")
            return None
        self._check_subnet(host, mask, network)
        return {"host": host, "tcp_port": self.dev_port_input.value(), "subnet": mask, "unit": self.slave_input.value()}

    def _mode_ok(self, device):
        """A device runs when ITS link (Modbus RTU / Modbus TCP / Modbus TCP (IP)) is connected - all links
        can be connected and run at the same time."""
        return self._scanner is not None and self._scanner.has_link(link_of(device, self._legacy_link))

    def _link_text(self):
        """Short description of the current link(s), for the top bar / Dashboard / logs."""
        if self._connected and len(self._links) > 1:
            parts = []
            for link in LINKS:
                if link == "rtu" and link in self._links:
                    parts.append(self.com_port.currentText())
                elif link == "gateway" and link in self._links:
                    parts.append(f"{self.ip_input.text().strip()}:{self.tcp_port_input.value()}")
                elif link == "tcp_ip" and link in self._links:
                    parts.append("IP devices")
            return " + ".join(parts)
        if self._is_ip_mode():
            return f"IP only \u00b7 port {tcpip.TCP_PORT}"
        if self._is_tcp():
            return f"{self.ip_input.text().strip()}:{self.tcp_port_input.value()}"
        return self.com_port.currentText()

    def _refresh_com_ports(self):
        current = self.com_port.currentText() if self.com_port.count() else ""
        self.com_port.blockSignals(True)
        self.com_port.clear()
        if list_ports is not None:
            ports = [port.device for port in list_ports.comports()]
        else:
            ports = []
        self.com_port.addItems(ports)
        if current in ports:
            self.com_port.setCurrentText(current)
        elif ports:
            self.com_port.setCurrentIndex(0)
        self.com_port.blockSignals(False)
    def _toggle_connection(self):
        if self._connected:
            self._disconnect()
        else:
            self._connect()
    @staticmethod
    def _local_ip_for(host):
        """IP address of this PC on the interface that would reach `host` (no packet is sent)."""
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.connect((host, 9))
            address = probe.getsockname()[0]
            probe.close()
            return address
        except OSError:
            return None

    def _check_subnet(self, host, mask, network):
        local = self._local_ip_for(host)
        if local is None:
            self._terminal(f"Network {network}: no route to {host} from this PC - check the cable / Wi-Fi / PC IP.")
        elif ipaddress.IPv4Address(local) in network:
            self._terminal(f"Network check OK: PC {local} and device {host} are on the same subnet {network}.")
        else:
            self._terminal(f"Warning: PC IP {local} is NOT in {network} (device {host}, mask {mask}). "
                           "Change the PC IP / mask, or use a router/gateway.")

    def _current_link(self):
        """Link of the Connection Type selected at the top (new devices get this link)."""
        return TYPE_TO_LINK.get(self.connection_type.currentText(), "rtu")

    def _needed_links(self):
        """The links Connect opens: those of all configured devices + the selected Connection Type."""
        wanted = {link_of(d, self._legacy_link) for d in list(self._devices.values()) + list(self._writers.values())}
        wanted.add(self._current_link())
        return [link for link in LINKS if link in wanted]

    def _open_serial(self):
        """Modbus RTU: open the COM port of Communication Settings. Returns the client or None."""
        if ModbusSerialClient is None:
            self._terminal("PyModbus is not installed.")
            return None
        port = self.com_port.currentText().strip()
        if not port:
            self._terminal("Modbus RTU: no COM port selected.")
            return None
        try:
            client = ModbusSerialClient(
                port=port,
                baudrate=int(self.baud_rate.currentText()),
                bytesize=int(self.data_bits.currentText()),
                parity=self.parity.currentText()[0],
                stopbits=int(self.stop_bits.currentText()),
                timeout=max(0.05, self.timeout_spin.value() / 1000.0) if hasattr(self, "timeout_spin") else 0.10,
                retries=0,
            )
            if not client.connect():
                self._terminal(f"Modbus RTU: unable to open {port}.")
                return None
            return client
        except Exception as exc:
            self._terminal(f"Modbus RTU: connection error on {port}: {exc}")
            return None

    def _open_gateway(self):
        """Modbus TCP: connect to the gateway IP / port of Communication Settings. Returns the client or None."""
        if ModbusTcpClient is None:
            self._terminal("PyModbus is not installed.")
            return None
        host = self.ip_input.text().strip()
        if not host:
            self._terminal("Modbus TCP: enter the gateway IP address first.")
            return None
        port = self.tcp_port_input.value()
        mask = self.subnet_input.text().strip() or "255.255.255.0"
        try:
            ipaddress.IPv4Address(host)
            network = ipaddress.IPv4Network(f"{host}/{mask}", strict=False)
        except ValueError:
            self._terminal(f"Modbus TCP: '{host}' / '{mask}' is not a valid IP address / subnet mask.")
            return None
        self._check_subnet(host, mask, network)
        try:
            client = ModbusTcpClient(host=host, port=port, timeout=max(0.05, self.timeout_spin.value() / 1000.0),
                                     retries=0)
            if not client.connect():
                self._terminal(f"Modbus TCP: unable to connect to {host}:{port}.")
                return None
            return client
        except Exception as exc:
            self._terminal(f"Modbus TCP: connection error {host}:{port}: {exc}")
            return None

    def _link_line(self, link):
        if link == "rtu":
            return (f"Modbus RTU   {self.com_port.currentText()}  {self.baud_rate.currentText()} "
                    f"{self.data_bits.currentText()}{self.parity.currentText()[:1]}{self.stop_bits.currentText()}")
        if link == "gateway":
            return f"Modbus TCP   {self.ip_input.text().strip()}:{self.tcp_port_input.value()}"
        return f"TCP (IP)     IP per device, port {tcpip.TCP_PORT}"

    def _connect(self):
        """Open every link the configured devices need (Modbus RTU, Modbus TCP gateway, Modbus TCP (IP)) - they
        run at the same time, each in its own scanner (multi_link.py). A link that cannot be opened is reported;
        the others still connect."""
        opened, failed = {}, []
        for link in self._needed_links():
            if link == "tcp_ip":
                opened[link] = None             # nothing to open: each device connects to its own IP when polled
                continue
            client = self._open_serial() if link == "rtu" else self._open_gateway()
            if client is None:
                failed.append(link)
            else:
                opened[link] = client
        if not opened:
            return
        self._links = opened
        self._serial_connection = opened.get("rtu") or opened.get("gateway")
        self._connected = True
        self._tcp_active = "rtu" not in opened
        self._ip_active = "tcp_ip" in opened
        self._start_scanner()
        self.connect_button.setText("DISCONNECT")
        self.status_indicator.setText("●  Connected")
        self.status_indicator.setObjectName("statusOnline")
        _ss(self.status_indicator, "background:#E8F8EF;color:#12A45B;border-radius:5px;padding:3px 7px;font-size:9px;font-weight:700;")
        lines = ["Port Status   :   Connected"] + [self._link_line(link) for link in LINKS if link in opened]
        lines += [f"NOT connected:  {LINK_NAMES[link]}" for link in failed]
        self.status_text.setText("\n".join(lines))
        names = ", ".join(LINK_NAMES[link] for link in LINKS if link in opened)
        self._terminal(f"Connected: {names}. All devices of these links can run together - press Run All.")
        if failed:
            self._terminal(f"Not connected: {', '.join(LINK_NAMES[l] for l in failed)} - the devices of "
                           f"{'this link' if len(failed) == 1 else 'these links'} cannot run. Check the settings, "
                           "then Disconnect and Connect again.")

    def _start_scanner(self):
        self._port_lost = False
        self._connected_since = datetime.now()
        self.dashboard_tab.reset_session()
        self._port_present = True
        self._port_seen = False
        self._port_check_at = time.monotonic()
        self._pending_writes = set()
        # one scanner per link (multi_link.ScannerGroup): the serial bus keeps its own single-transaction
        # timing and frames; TCP links never wait for it
        group = ScannerGroup(self)
        for link in LINKS:
            if link in self._links:
                scanner = ModbusScanner(self._links[link])
                scanner.transport = "rtu" if link == "rtu" else "tcp"
                group.add_link(link, scanner)
        self._scanner = group
        self._scanner.set_cycle_polling(self.cycle_check.isChecked())
        self._scanner.event.connect(self._on_scanner_event)
        self._scanner.finished.connect(self._on_scanner_finished)
        for device in self._devices.values():
            self._scanner.add_device(device)
        # Phase 4: asynchronous MongoDB storage (never blocks the bus or the UI)
        self._scanner.add_reading_sink(self._ensure_db_writer().submit)
        self._scanner.start()
        self._ui_timer.start()

    def _disconnect(self):
        """Stop the scanner; the port is closed by the scanner thread only
        after the in-flight transaction (if any) has completed."""
        self._connected = False
        if self._scanner is not None and self._scanner.isRunning():
            self.connect_button.setEnabled(False)
            self.connect_button.setText("DISCONNECTING...")
            self._scanner.request_stop()
            return
        self._finish_disconnect()

    def _on_scanner_finished(self):
        if self.sender() is self._scanner:
            self._finish_disconnect()

    def _dashboard_runtime(self):
        return {
            "connected": self._connected,
            "port": self._link_text() if hasattr(self, "com_port") else "--",
            "baud": (self.connection_type.currentText() if self._is_tcp() else
                     f"{self.baud_rate.currentText()} · {self.data_bits.currentText()}{self.parity.currentText()[:1]}{self.stop_bits.currentText()}")
                    if hasattr(self, "baud_rate") else "",
            "since": self._connected_since,
            "db": self._db_writer.status() if self._db_writer is not None else None,
        }

    def _ensure_db_writer(self):
        if self._db_writer is None:
            self._db_writer = ReadingDatabaseWriter(min_interval=DB_SAVE_INTERVAL_S)
            self._db_state = None
            self._db_writer.start()
        return self._db_writer

    def _stop_db_writer(self):
        writer = getattr(self, "_db_writer", None)
        self._db_writer = None
        if writer is not None:
            writer.stop()

    def _check_db_status(self):
        """Log database connect / disconnect changes (runs on the UI timer)."""
        writer = getattr(self, "_db_writer", None)
        if writer is None:
            return
        status = writer.status()
        state = status["connected"]
        if state != self._db_state and (state or status["last_error"]):
            if state:
                self._terminal(f"Database connected. Saved {status['saved']} records.")
            else:
                self._terminal(f"Database error: {status['last_error'] or 'not reachable'} "
                               f"- buffering {status['queued']} records, retrying.")
            self._db_state = state

    def _finish_disconnect(self):
        self._alarms.clear_all("disconnected")
        self._connected_since = None
        if self._scanner is not None:
            self._scanner.deleteLater()       # every scanner closes its own connection when its thread ends
            self._scanner = None
        else:
            for client in self._links.values():
                try:
                    if client is not None:
                        client.close()
                except Exception:
                    pass
        self._links = {}
        self._serial_connection = None
        self._ui_timer.stop()
        self.connect_button.setEnabled(True)
        self.connect_button.setText("CONNECT")
        self.status_indicator.setText("●  COM Port Lost" if self._port_lost else "●  Disconnected")
        self.status_indicator.setObjectName("statusOffline")
        _ss(self.status_indicator, "background:#FFF0F0;color:#E53935;border-radius:5px;padding:3px 7px;font-size:9px;font-weight:700;")
        self.status_text.setText(
            f"Port Status   :   {'COM Port Lost' if self._port_lost else 'Disconnected'}\n"
            "COM Port      :   --\n"
            f"Baud Rate     :   {self.baud_rate.currentText()}\n"
            f"Data Bits     :   {self.data_bits.currentText()}\n"
            f"Parity        :   {self.parity.currentText()}\n"
            f"Stop Bits     :   {self.stop_bits.currentText()}"
        )
        # Keep configured devices; reset them to the stopped / not polled state.
        for device in self._devices.values():
            device.update(enabled=False, status="NOT_POLLED", retry_count=0,
                          next_poll=None, next_retry=None, next_recovery=None,
                          latest_data=None, latest_units=None, ip_types=None, quality=None, timestamp=None)
        self._rebuild_device_table()
        self._rebuild_data_cards()
        self._rebuild_data_cards()
        self._stats_dirty = True
        self._terminal("Disconnected.")
        self._refresh_ui()
        if self._reset_pending:
            self._reset_to_initial()
    def _start_scan(self):
        if not self._connected:
            self._terminal("Connect first (COM port or TCP).")
            return
        self._terminal("Devices are manually configured. Add or edit devices, then press Run All.")
    def _new_device(self, sid, name, type_text, polling, scan_rate, timeout, max_retries, last_response, function=None, register=None):
        # function/address/count come from the register profile of the device type
        # (device_data.DEVICE_PROFILES); `function` is only used for untyped devices.
        kind = device_kind(type_text)
        profile = DEVICE_PROFILES.get(kind) or {"function": function or 3, "address": 0, "count": 1}
        if register:   # explicit function / start address / quantity from the Add / Edit form
            profile = dict(profile, **register)
        return {
            "name": name, "type": type_text, "kind": kind, "slave_id": sid, "function": profile["function"],
            "polling": polling, "scan_rate": scan_rate, "timeout": timeout, "max_retries": max_retries,
            "address": profile["address"], "count": profile["count"],
            "mode": "read", "enabled": False, "status": "NOT_POLLED", "retry_count": 0, "last_response": last_response,
            "next_poll": None, "next_retry": None, "next_recovery": None,
            "latest_data": None, "latest_units": None, "ip_types": None, "quality": None, "timestamp": None,
            "stats": _empty_device_stats(),
        }
    def _add_detected_device(self, slave_id, function, response):
        if len(self._devices) >= 32 or slave_id in self._devices:
            return
        device_type={1:"Digital / Coil",2:"Digital Input",3:"Register Device",4:"Analog / Register"}.get(function,"Unknown")
        device = self._new_device(
            slave_id, f"Slave {slave_id}", device_type,
            self.default_poll.value(), self.scan_rate.value(), self.timeout_spin.value(), self.max_retries.value(), "--",
            function=function)
        self._terminal(f"Detected Slave ID {slave_id} using Function {function:02d}.")
        self._register_device(device)
    # ---- Add / Edit device form ------------------------------------------------
    def _form_register(self):
        return {"function": int(self.function_input.currentData()),
                "address": self.address_input.value(), "count": self.count_input.value()}

    def _apply_profile(self, _index=None):
        """Fill Point Type / Start Address / Length from the register profile of the
        device type (only while a read Point Type is selected)."""
        profile = DEVICE_PROFILES.get(device_kind(self.device_type_input.currentText()))
        if not profile:
            return
        if self.function_input.currentData() is not None and is_write_function(self.function_input.currentData()):
            return
        self._loading_form = True
        try:
            self._set_function(profile["function"])
            self.address_input.setValue(profile["address"])
            self.count_input.setValue(profile["count"])
            if profile.get("word_order"):          # MFT: Float32 + CD AB (LSRF)
                self.data_format_input.setCurrentIndex(max(0, self.data_format_input.findData(profile.get("data_format", "float32"))))
                self.word_order_input.setCurrentIndex(max(0, self.word_order_input.findData(profile["word_order"])))
        finally:
            self._loading_form = False

    def _set_function(self, code):
        index = self.function_input.findData(int(code))
        self.function_input.setCurrentIndex(max(0, index))
        self._on_function_changed()

    def _on_type_changed(self, _index=None):
        kind = device_kind(self.device_type_input.currentText())
        if getattr(self, "_last_form_kind", None) == "MFT" and kind != "MFT" and not self._loading_form:
            self.word_order_input.setCurrentIndex(max(0, self.word_order_input.findData("MSRF")))   # MFT's LSRF must not leak
        self._last_form_kind = kind
        if not self._loading_form:
            self._apply_profile()
            self._default_format()
            self._on_format_changed()
        self._update_length_hint()
        self._update_do_write_visible()

    def _update_do_write_visible(self):
        show = device_kind(self.device_type_input.currentText()) == "DO" and \
            self.function_input.currentData() == 1
        self.do_write_label.setVisible(show)
        self.do_write_input.setVisible(show)

    def _on_function_changed(self, _index=None):
        code = self.function_input.currentData()
        if code is None:
            return
        self.count_input.setMaximum(max_count(code))
        write = is_write_function(code)
        for box in (self.poll_input, self.add_scan_display, self.add_retry_display):
            box.setEnabled(not write)
        if not self._loading_form:
            self._default_format()
        self._on_format_changed()
        self._update_do_write_visible()

    def _default_format(self):
        """AI input registers default to Float32, everything else to 16-bit raw."""
        code = self.function_input.currentData()
        kind = device_kind(self.device_type_input.currentText())
        default = "float32" if ((kind == "AI" and code == 4) or (kind == "MFT" and code in (3, 4))) else "raw16"
        self.data_format_input.blockSignals(True)
        self.data_format_input.setCurrentIndex(max(0, self.data_format_input.findData(default)))
        self.data_format_input.blockSignals(False)

    def _on_format_changed(self, _index=None):
        code = self.function_input.currentData()
        register_read = code in (3, 4) and ENABLE_FORMATS
        if device_kind(self.device_type_input.currentText()) == "MFT":
            register_read = False                  # MFT is fixed: Float32, LSRF (CD AB)
        for widget in (self.format_label, self.data_format_input):
            widget.setVisible(register_read)
        wide = register_read and self.data_format_input.currentData() in WIDE_FORMATS
        for widget in (self.order_label, self.word_order_input):
            widget.setVisible(bool(wide))
        self._update_length_hint()

    def _update_length_hint(self):
        analog = ENABLE_FORMATS and self.function_input.currentData() in (3, 4) and self.data_format_input.currentData() in WIDE_FORMATS
        self.length_label.setText("Length (2 regs = 1 ch)" if analog else "Length")
        self.count_input.setToolTip(
            "32-bit format: every channel is 2 registers.\n"
            "Length 16 = 8 channels (CH1..CH8), Length 8 = 4 channels. Start Address normally 0.\n"
            "MFT: Length 80 = 40 parameters (Float32, LSRF), read in pages of 20 registers."
            if analog else "Number of coils / registers to read or write.")

    def _on_addr_hex(self, on):
        self.address_input.setDisplayIntegerBase(16 if on else 10)
        self.address_input.setPrefix("0x" if on else "")

    def _form_device(self, sid):
        name = self.device_name_input.text().strip() or f"Slave {sid}"
        device = self._new_device(
            sid, name, self.device_type_input.currentText(), self.poll_input.value(),
            self.add_scan_display.value(), self.add_timeout_display.value(),
            self.add_retry_display.value(), "Not tested", register=self._form_register())
        if is_write_function(device["function"]):
            device.update(mode="write", status="WRITE", last_response="--")
        device["do_write"] = int(self.do_write_input.currentData() or 15)
        device.update(host=None, tcp_port=None, subnet=None, unit=None)       # serial device unless the caller adds a TCP address
        device["link"] = self._current_link()        # Modbus TCP (IP) devices get "tcp_ip" from tcpip.device_fields
        if device.get("kind") == "MFT":
            device["data_format"], device["word_order"] = "float32", "LSRF"
        elif device["function"] in (3, 4) and device["mode"] != "write":
            device["data_format"] = self.data_format_input.currentData() or "raw16"
            device["word_order"] = self.word_order_input.currentData() or "MSRF"
        else:
            device["data_format"], device["word_order"] = "raw16", "MSRF"
        return device

    def _next_writer_key(self):
        self._writer_seq += 1
        return f"W{self._writer_seq}"

    def _lookup(self, key):
        return self._devices.get(key) if isinstance(key, int) else self._writers.get(key)

    def _manual_add_device(self):
        if self._editing is not None:
            self._save_device_edit()
            return
        if len(self._devices) + len(self._writers) >= 32:
            self._terminal("Maximum 32 devices can be configured."); return
        tcp = self._is_ip_mode()           # per-device IP only for Modbus TCP (IP)
        extra = None
        if tcp:
            extra = self._tcp_form()
            if extra is None:
                return
            sid = self._free_sid()
            if sid is None:
                self._terminal("No free device number left."); return
        else:
            sid = self.slave_input.value()
        device = self._form_device(sid)
        if tcp and tcpip.is_device(extra):
            device.update(extra)
            if not self.device_name_input.text().strip():
                device["name"] = tcpip.default_name(extra["host"])
            if tcpip.same_reading(self._devices, device):
                self._terminal(f"Note: another device on {extra['host']} already reads FC{device['function']:02d} "
                               f"address {device['address']} length {device['count']} - both will show the same data. "
                               f"Check the Point Type / Start Address.")
        elif tcp:
            device.update(extra)
            if not self.device_name_input.text().strip():
                device["name"] = f"Device {extra['host']} ID {extra['unit']}"
            if device["mode"] != "write" and any(
                    (d.get("host"), d.get("tcp_port"), d.get("unit")) == (extra["host"], extra["tcp_port"], extra["unit"])
                    for d in self._devices.values()):
                self._terminal(f"Device ID {extra['unit']} on {extra['host']}:{extra['tcp_port']} is already configured."); return
        if device["mode"] != "write" and sid in self._devices:
            self._terminal(f"Slave ID {sid} is already configured."); return
        name = device["name"]
        self._terminal(f"Added {name} ({_id_text(device)}): FC{device['function']:02d}, address {device['address']}, length {device['count']}.")
        if device["mode"] != "write" and not DEVICE_PROFILES.get(device["kind"], {}).get("verified", True):
            self._terminal(
                f"Note: no live-value register map is defined for {device['kind']} yet; reading "
                f"FC{device['function']:02d} address {device['address']} count {device['count']} (placeholder).")
        self._register_device(device)
        self._clear_add_form()

    def _register_device(self, device):
        if device.get("mode") == "write":
            device["key"] = self._next_writer_key()
            self._writers[device["key"]] = device
        else:
            self._devices[device["slave_id"]] = device
            if self._scanner is not None and not self._scanner.add_device(device) and not self._project_loading:
                self._terminal(f"{device['name']}: {LINK_NAMES[link_of(device, self._legacy_link)]} is not connected "
                               "yet - Disconnect and Connect again to run this device.")
        self._rebuild_device_table(); self._rebuild_data_cards(); self._update_statistics()

    def _drop_device(self, key):
        device = self._lookup(key)
        if device is None:
            return
        if device.get("mode") == "write":
            self._writers.pop(key, None)
        else:
            self._devices.pop(key, None)
            self._alarms.clear_device(key)
            if self._scanner is not None:
                self._scanner.remove_device(key)

    def _edit_device(self, key):
        device = self._lookup(key)
        if device is None:
            return
        self._editing = key
        link_name = LINK_NAMES[link_of(device, self._legacy_link)]
        if self.connection_type.currentText() != link_name:
            self.connection_type.setCurrentText(link_name)     # form fields of the device's own link
        self._sync_add_panel()
        self._loading_form = True
        try:
            self.device_name_input.setText(device["name"])
            self.slave_input.setValue(int(device["slave_id"]))
            if device.get("host"):
                self.slave_input.setValue(int(device.get("unit") or 1))
                self.dev_ip_input.setText(str(device["host"]))
                self.dev_subnet_input.setText(str(device.get("subnet") or "255.255.255.0"))
                self.dev_port_input.setValue(int(device.get("tcp_port") or 502))
            index = self.device_type_input.findText(device["type"])
            if index >= 0:
                self.device_type_input.setCurrentIndex(index)
            self._set_function(device["function"])
            self.address_input.setValue(int(device["address"]))
            self.count_input.setValue(int(device["count"]))
            self.poll_input.setValue(int(device["polling"]))
            self.add_scan_display.setValue(int(device["scan_rate"]))
            self.add_timeout_display.setValue(int(device["timeout"]))
            self.add_retry_display.setValue(int(device["max_retries"]))
            self.do_write_input.setCurrentIndex(max(0, self.do_write_input.findData(int(device.get("do_write", 15)))))
            self.data_format_input.setCurrentIndex(max(0, self.data_format_input.findData(effective_format(device))))
            self.word_order_input.setCurrentIndex(max(0, self.word_order_input.findData(device.get("word_order") or "MSRF")))
        finally:
            self._loading_form = False
        self._update_do_write_visible()
        self.add_title.setText(f"✎  EDIT DEVICE  -  {device['name']} (Slave {device['slave_id']})")
        self.add_device_button.setText("✔  Save Changes")
        self.clear_form_button.setText("✕  Cancel")
        self.device_name_input.setFocus()
        self._terminal(f"Editing {device['name']} (Slave {device['slave_id']}). Change the settings and press Save Changes.")

    def _save_device_edit(self):
        key = self._editing
        device = self._lookup(key)
        if device is None:
            self._cancel_edit(); return
        tcp = self._is_ip_mode()           # per-device IP only for Modbus TCP (IP)
        extra = None
        if tcp:
            extra = self._tcp_form()
            if extra is None:
                return
            sid = device["slave_id"] if device.get("host") else self._free_sid()
            if sid is None:
                self._terminal("No free device number left."); return
        else:
            sid = self.slave_input.value()
        fresh = self._form_device(sid)
        if tcp and tcpip.is_device(extra):
            fresh.update(extra)
            if tcpip.same_reading(self._devices, fresh, skip_key=key):
                self._terminal(f"Note: another device on {extra['host']} already reads FC{fresh['function']:02d} "
                               f"address {fresh['address']} length {fresh['count']} - both will show the same data. "
                               f"Check the Point Type / Start Address.")
        elif tcp:
            fresh.update(extra)
            if any((d.get("host"), d.get("tcp_port"), d.get("unit")) == (extra["host"], extra["tcp_port"], extra["unit"])
                   and k != key for k, d in self._devices.items()) and fresh["mode"] != "write":
                self._terminal(f"Device ID {extra['unit']} on {extra['host']}:{extra['tcp_port']} is already configured."); return
        new_write = fresh["mode"] == "write"
        old_write = device.get("mode") == "write"
        if not new_write and sid in self._devices and sid != key:
            self._terminal(f"Slave ID {sid} is already configured."); return
        if new_write != old_write:
            # Read <-> write: the device becomes the other kind (settings are the new ones).
            self._drop_device(key)
            fresh["stats"] = device.get("stats", fresh["stats"])
            self._register_device(fresh)
            device = fresh
        elif new_write:
            for k in ("name", "type", "kind", "slave_id", "function", "address", "count", "timeout",
                      "host", "tcp_port", "subnet", "unit", "link"):
                device[k] = fresh[k]
        else:
            remap = any(device.get(k) != fresh.get(k) for k in ("slave_id", "kind", "function", "address", "count",
                                                                 "data_format", "word_order", "host", "tcp_port"))
            for k in ("name", "type", "kind", "slave_id", "function", "address", "count",
                      "polling", "scan_rate", "timeout", "max_retries", "do_write", "data_format", "word_order",
                      "host", "tcp_port", "subnet", "unit", "link"):
                device[k] = fresh.get(k)
            if sid != key:
                self._devices.pop(key, None)
                self._devices[sid] = device
                self._alarms.clear_device(key)
            if remap:
                device.update(latest_data=None, latest_units=None, ip_types=None, quality=None, timestamp=None)
                if device.get("enabled"):
                    device.update(status="NOT_POLLED", retry_count=0, next_poll=time.monotonic(),
                                  next_retry=None, next_recovery=None)
            if self._scanner is not None:
                self._scanner.update_device(key, device)
        self._terminal(f"Updated {device['name']} ({_id_text(device)}): FC{device['function']:02d}, "
                       f"address {device['address']}, length {device['count']}.")
        self._cancel_edit()
        self._rebuild_device_table(); self._rebuild_data_cards(); self._update_statistics()
        self._stats_dirty = True

    def _cancel_edit(self):
        self._editing = None
        self.add_title.setText("＋  ADD NEW DEVICE")
        self.add_device_button.setText("＋  Add Device")
        self.clear_form_button.setText("↻  Clear")
        self._clear_add_form(keep_edit=True)

    def _clear_add_form(self, _checked=False, keep_edit=False):
        if self._editing is not None and not keep_edit:
            self._cancel_edit()
            return
        self._loading_form = True
        try:
            self.device_name_input.clear()
            self.slave_input.setValue(1)
            self.device_type_input.setCurrentIndex(0)
            self.function_input.setCurrentIndex(0)
            self.poll_input.setValue(self.default_poll.value())
            self.add_scan_display.setValue(self.scan_rate.value())
            self.add_timeout_display.setValue(self.timeout_spin.value())
            self.add_retry_display.setValue(self.max_retries.value())
            self.do_write_input.setCurrentIndex(0)
            self.word_order_input.setCurrentIndex(0)
        finally:
            self._loading_form = False
        self._on_function_changed()
        self._apply_profile()

    def _toggle_do(self, device, index):
        """Click on a DO LED: switch that output (FC05) to the opposite of its current state."""
        if device.get("status") != "ONLINE" or not device.get("latest_data"):
            self._terminal(f"{device['name']}: run the device and wait until it is ONLINE before switching outputs.")
            return
        current = dict(device["latest_data"]).get(f"DO{index + 1}")
        if current is None:
            return
        sid = int(device["slave_id"])
        new = not bool(current)
        base = int(device["address"])
        mode = int(device.get("do_write", 15))
        # whole-image writes must not overlap (each one carries all 16 outputs);
        # single-coil writes are only blocked for the same output (in _do_write)
        if mode in (1500, 6) and any(k[0] == sid for k in self._pending_writes):
            self._terminal(f"{device['name']}: previous write still running - click ignored.")
            return
        if mode == 15:                       # FC15 with a single coil
            self._do_write(device, 15, base + index, [new])
        elif mode == 1500:                   # FC15 with the whole output image
            bits = [bool(v) for _, v in device["latest_data"]][:int(device["count"])]
            bits[index] = new
            self._do_write(device, 15, base, bits)
        elif mode == 6:                      # FC06: all 16 outputs as bits of one register
            bits = [bool(v) for _, v in device["latest_data"]][:16]
            bits[index] = new
            self._do_write(device, 6, base, [sum(1 << i for i, b in enumerate(bits) if b)])
        else:                                # FC05 write single coil
            if self._do_write(device, 5, base + index, [new]):
                self._fc05_clicks.add((sid, base + index))

    # ---- Write (called by the write device cards) --------------------------------
    def _do_write(self, device, function, address, values):
        """Queue one write on the bus. Returns False when it was not sent."""
        if not self._connected or self._scanner is None:
            self._terminal("Connect first (COM port or TCP).")
            return False
        if address + len(values) > 65536:
            self._terminal("Write rejected: address range goes past 65535.")
            return False
        if self.write_confirm.isChecked():
            shown = ", ".join(str(int(v)) if isinstance(v, bool) else str(v) for v in values[:8])
            if len(values) > 8:
                shown += ", ..."
            answer = QMessageBox.question(
                self, "Confirm write",
                f"Write to {device['name']} (Slave {device['slave_id']})?\n\n"
                f"Function {function:02d}   Address {address}\nValue(s): {shown}",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return False
        key = (int(device["slave_id"]), int(function), int(address))
        if key in self._pending_writes:
            self._terminal(f"Same write to Slave {key[0]} is already waiting - not queued again.")
            return False
        self._pending_writes.add(key)
        self._scanner.request_write({
            "slave_id": int(device["slave_id"]), "function": function, "address": address,
            "host": device.get("host"), "tcp_port": device.get("tcp_port"), "unit": device.get("unit"),
            "link": link_of(device, self._legacy_link),
            "values": values, "timeout": WRITE_TIMEOUT_MS,   # a write waits up to 2 s for its reply
            "retries": 0})                      # a write is sent once, never repeated
        self._terminal(f"Write queued: Slave {device['slave_id']} FC{function:02d} address {address} ({len(values)} value(s)).")
        return True

    def _remove_selected_devices(self):
        keys = []
        for row in range(self.device_table.rowCount()):
            item = self.device_table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                keys.append(item.data(Qt.UserRole))
        for key in keys:
            if self._editing == key:
                self._cancel_edit()
            self._drop_device(key)
        if keys:
            self._terminal(f"Removed {len(keys)} selected device(s).")
        self._rebuild_device_table(); self._rebuild_data_cards(); self._update_statistics()

    def _all_device_rows(self):
        readers = sorted(self._devices.values(), key=lambda x: x["slave_id"])
        writers = sorted(self._writers.values(), key=lambda x: (x["slave_id"], x["key"]))
        return readers + writers

    def _rebuild_device_table(self):
        """Structural rebuild (add / remove / run / stop only). Live status
        changes go through _refresh_device_row so checkboxes are kept."""
        checked = set()
        for row in range(self.device_table.rowCount()):
            item = self.device_table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                checked.add(item.data(Qt.UserRole))
        self.device_table.setRowCount(0)
        self._row_of = {}
        devices = self._all_device_rows()
        self.device_count_label.setText(f"({len(devices)})")
        for row, device in enumerate(devices):
            self.device_table.insertRow(row)
            sid = int(device["slave_id"])
            key = device.get("key", sid)
            writer = device.get("mode") == "write"

            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check.setCheckState(Qt.Checked if key in checked else Qt.Unchecked)
            check.setData(Qt.UserRole, key)
            self.device_table.setItem(row, 0, check)

            na = "--"
            values = [
                str(row + 1),
                device["name"],
                device["type"],
                (tcpip.id_text(device) if tcpip.is_device(device) else
                 f"{device['host']}:{device.get('tcp_port') or 502}  #{device.get('unit') or 1}" if device.get("host") else str(sid)),
                f"{ALL_FUNCTIONS.get(int(device['function']), 'FC' + str(device['function']))}  @{device['address']}  x{device['count']}"
                + (f"  ({int(device['count']) // 2} ch)" if ENABLE_FORMATS and device.get("kind") in ("AI", "MFT") and int(device["function"]) in (3, 4) and effective_format(device) in WIDE_FORMATS else "")
                + (f"  | {effective_format(device).upper()}{' ' + (device.get('word_order') or 'MSRF') if effective_format(device) in WIDE_FORMATS else ''}"
                   if int(device["function"]) in (3, 4) and not writer and effective_format(device) != "raw16" else "")
                + (f"  | write {({5: 'FC05', 15: 'FC15', 1500: 'FC15 all', 6: 'FC06'}).get(int(device.get('do_write', 15)), 'FC15')}"
                   if device.get("kind") == "DO" and int(device["function"]) == 1 and not writer else ""),
                na if writer else str(device.get("polling", 1000)),
                na if writer else str(device.get("scan_rate", 60000)),
                str(device.get("timeout", 2000)),
                na if writer else str(device.get("max_retries", 3)),
            ]
            for col, value in enumerate(values, 1):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter if col not in (2, 5) else Qt.AlignLeft | Qt.AlignVCenter)
                self.device_table.setItem(row, col, item)

            kind = device.get("kind")
            bg, fg = _TYPE_COLORS.get(kind, ("#EEF2F5", "#718391"))
            pill = QLabel(kind or device.get("type", ""))
            pill.setAlignment(Qt.AlignCenter)
            _ss(pill, f"background:{bg};color:{fg};border-radius:9px;padding:2px 12px;font-size:9px;font-weight:800;")
            holder = QWidget()
            holder_layout = QHBoxLayout(holder)
            holder_layout.setContentsMargins(0, 0, 0, 0)
            holder_layout.addStretch()
            holder_layout.addWidget(pill)
            holder_layout.addStretch()
            self.device_table.setCellWidget(row, 3, holder)
            type_item = self.device_table.item(row, 3)
            if type_item:
                type_item.setText(kind or device.get("type", ""))

            self._row_of[key] = row
            self._refresh_device_row(key)

            actions = QWidget()
            action_layout = QHBoxLayout(actions)
            action_layout.setContentsMargins(2, 0, 2, 0)
            action_layout.setSpacing(4)
            action_layout.addStretch()

            if not writer:
                run_stop = QPushButton()
                run_stop.setIcon(_make_icon("stop", "#E53935") if device.get("enabled", False) else _make_icon("play", "#168CF0"))
                run_stop.setIconSize(QSize(16, 16))
                run_stop.setObjectName("tableAction" if not device.get("enabled", False) else "tableDanger")
                run_stop.setToolTip("Stop device" if device.get("enabled", False) else "Run device")
                if device.get("enabled", False):
                    run_stop.clicked.connect(lambda checked=False, device_id=sid: self._stop_device(device_id))
                else:
                    run_stop.clicked.connect(lambda checked=False, device_id=sid: self._run_device(device_id))
                action_layout.addWidget(run_stop)

            edit = QPushButton("✎")
            edit.setObjectName("tableAction")
            edit.setToolTip("Edit device settings")
            edit.clicked.connect(lambda checked=False, k=key: self._edit_device(k))

            remove = QPushButton()
            remove.setIcon(_make_icon("trash", "#E53935"))
            remove.setIconSize(QSize(16, 16))
            remove.setObjectName("tableDanger")
            remove.setToolTip("Remove device")
            remove.clicked.connect(lambda checked=False, k=key: self._remove_device_from_table(k))

            action_layout.addWidget(edit)
            action_layout.addWidget(remove)
            action_layout.addStretch()
            self.device_table.setCellWidget(row, 11, actions)

            self.device_table.setRowHeight(row, int(40 * _UI_SCALE))

        has_devices = bool(devices)
        self.no_device_label.setVisible(not has_devices)
        self.device_table.setVisible(has_devices)
        self._fit_manager()
        self._save_project()

    def _row_double_clicked(self, row, _col):
        item = self.device_table.item(row, 0)
        if item is not None:
            self._edit_device(item.data(Qt.UserRole))

    def _status_text(self, device):
        return _STATUS_TEXT.get(str(device.get("status", "NOT_POLLED")).upper(), "NOT POLLED")

    def _refresh_device_row(self, key):
        row = self._row_of.get(key)
        device = self._lookup(key)
        if row is None or device is None:
            return
        status_text = self._status_text(device)
        item = self.device_table.item(row, 10)
        if item is None:
            item = QTableWidgetItem()
            item.setTextAlignment(Qt.AlignCenter)
            self.device_table.setItem(row, 10, item)
        label = f"●  {status_text}"          # status column shows only ONLINE / OFFLINE (etc.), no HIGH / ON counts
        if item.text() != label:
            item.setText(label)
            item.setForeground(tc(_STATUS_COLORS.get(status_text, "#7A8C99"), "text"))

    def _remove_device_from_table(self, key):
        device = self._lookup(key)
        if device is not None:
            if self._editing == key:
                self._cancel_edit()
            name = device.get("name", f"Slave {device['slave_id']}")
            self._drop_device(key)
            self._terminal(f"Removed {name} (Slave {device['slave_id']}).")
            self._rebuild_device_table()
            self._rebuild_data_cards()
            self._update_statistics()

    def _rebuild_data_cards(self):
        self._card_refs = {}
        self._grid_cards = None
        if self._spot_sid is not None and self._spot_sid not in self._devices:
            self._close_spotlight()
        self._writer_cards = {}
        devices_now = list(self._devices.values())
        self._live.devices.set_devices(sorted(devices_now, key=lambda item: item["slave_id"]))
        for _d in devices_now:
            self._refresh_live_row(_d)
        if not devices_now:
            self._live.detail.set_empty(True, "No devices yet \u2014 use Add device")
        if self._mode == "console" and self._spot_sid is None and devices_now:
            QTimer.singleShot(0, lambda: self._spot_sid is None and self._devices
                              and self._open_spotlight(self._last_selected if self._last_selected in self._devices
                                                       else sorted(self._devices)[0]))
        self.dashboard_tab.set_devices(devices_now)
        while self.data_layout.count():
            item = self.data_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        devices = sorted(self._devices.values(), key=lambda item: item["slave_id"])
        writers = sorted(self._writers.values(), key=lambda item: (item["slave_id"], item["key"]))
        if not devices and not writers:
            self.no_data_label = QLabel("No devices configured")
            self.no_data_label.setAlignment(Qt.AlignCenter)
            _ss(self.no_data_label, "color:#718991;font-size:11px;padding:20px;")
            self.data_layout.addWidget(self.no_data_label, 0, 0, 1, 2)
            return

        self._grid_cards = [self._create_device_card(device) for device in devices]
        self._grid_writers = []
        for device in writers:
            card = WriterCard(device, lambda fn, addr, vals, d=device: self._do_write(d, fn, addr, vals))
            self._writer_cards[device["key"]] = card
            self._grid_writers.append(card)
        self._card_cols = 0
        self._reflow_cards()

    def _card_columns(self):
        width = self.data_scroll.viewport().width()
        return max(1, min(4, width // 330))

    def _reflow_cards(self):
        """Lay the device cards out in as many columns as the panel is wide."""
        cards = getattr(self, "_grid_cards", None)
        if cards is None:
            return
        cols = self._card_columns()
        if cols == getattr(self, "_card_cols", 0):
            return
        self._card_cols = cols
        while self.data_layout.count():
            self.data_layout.takeAt(0)
        for column in range(5):
            self.data_layout.setColumnStretch(column, 0)
        for index, card in enumerate(cards):
            self.data_layout.addWidget(card, index // cols, index % cols, Qt.AlignTop)
        row = (len(cards) + cols - 1) // cols
        for card in self._grid_writers:
            self.data_layout.addWidget(card, row, 0, 1, cols, Qt.AlignTop)
            row += 1
        for column in range(cols):
            self.data_layout.setColumnStretch(column, 1)
        self.data_layout.setRowStretch(row + 1, 1)

    def eventFilter(self, obj, event):
        if obj is self.data_scroll.viewport() and event.type() == QEvent.Resize:
            self._reflow_cards()
        return super().eventFilter(obj, event)
    def _create_device_card(self, device):
        clickable = device.get("kind") == "DO" and int(device.get("function", 0)) == 1
        card = DeviceCard(device, (lambda i, d=device: self._toggle_do(d, i)) if clickable else None,
                          on_open=lambda sid=device["slave_id"]: self._open_spotlight(sid),
                          on_format=lambda fmt, order, d=device: self._quick_format(d, fmt, order))
        self._card_refs[device["slave_id"]] = card
        self._refresh_device_card(device["slave_id"])
        return card

    def _refresh_device_card(self, slave_id):
        card = self._card_refs.get(slave_id)
        device = self._devices.get(slave_id)
        if card is None or device is None:
            return
        status_text = self._status_text(device)
        card.refresh(device, status_text)
        card.refresh_footer(device, status_text)
        self._refresh_live_row(device)
        if slave_id == self._spot_sid:
            self._refresh_spotlight(device)

    def _quick_format(self, device, fmt, order):
        """Data Format / Word Order picked directly on a Live card: applies from the next reading."""
        if device.get("data_format") == fmt and (device.get("word_order") or "MSRF") == order:
            return
        device["data_format"], device["word_order"] = fmt, order
        device.update(latest_data=None, quality=None, timestamp=None)
        if self._scanner is not None:
            self._scanner.update_device(device["slave_id"], device)
        self._rebuild_device_table()                     # also saves the project
        self._dirty_devices.add(device["slave_id"])
        self._terminal(f"{device['name']} (Slave {device['slave_id']}): output "
                       f"{DATA_FORMATS.get(fmt, fmt)}" + (f", {order}" if fmt in WIDE_FORMATS else "") + ".")

    def _set_device_enabled(self, device, enabled):
        if bool(device.get("enabled", False)) == enabled:
            return
        device.update(enabled=enabled, status="NOT_POLLED" if enabled else "DISABLED", retry_count=0,
                      next_poll=time.monotonic() if enabled else None, next_retry=None, next_recovery=None)
        if self._scanner is not None:
            self._scanner.set_enabled(device["slave_id"], enabled)

    def _after_run_state_change(self):
        self._rebuild_device_table()
        for sid in self._devices:
            self._refresh_device_card(sid)
        self._stats_dirty = True
        self._refresh_ui()

    def _run_device(self, slave_id):
        device = self._devices.get(slave_id)
        if device is None:
            return
        if not self._connected or self._scanner is None:
            self._terminal("Connect first (COM port or TCP).")
            return
        if not self._mode_ok(device):
            self._terminal(f"{device['name']}: its link ({LINK_NAMES[link_of(device, self._legacy_link)]}) is not "
                           "connected. Check its settings, then Disconnect and Connect again.")
            return
        self._set_device_enabled(device, True)
        self._after_run_state_change()
    def _stop_device(self, slave_id):
        device = self._devices.get(slave_id)
        if device is None:
            return
        self._set_device_enabled(device, False)
        self._after_run_state_change()
    def _run_all(self):
        if not self._connected or self._scanner is None or not self._devices:
            return
        # Devices already running (ONLINE / RETRYING / OFFLINE) keep their state.
        skipped = 0
        for device in self._devices.values():
            if not self._mode_ok(device):
                skipped += 1
                continue
            self._set_device_enabled(device, True)
        if skipped:
            self._terminal(f"{skipped} device(s) were not started: their link is not connected "
                           "(see 'Not connected' above). Disconnect and Connect again after fixing it.")
        self._after_run_state_change()
    def _stop_all(self):
        for device in self._devices.values():
            self._set_device_enabled(device, False)
        self._after_run_state_change()

    # ------------------------------------------------------------------ #
    # Scanner events (GUI thread, queued). Only update the model and mark
    # things dirty; _refresh_ui repaints in batches every 200 ms.
    # ------------------------------------------------------------------ #
    def _on_scanner_event(self, event):
        if self.sender() is not self._scanner:
            return
        kind = event["type"]
        sid = event.get("slave_id")
        device = self._devices.get(sid)
        device_stats = device["stats"] if device is not None else None
        stamp = event["time"]
        tag = _id_text(device) if device is not None else f"Slave {sid}"
        if device is not None and tcpip.is_device(device):
            tag = f"{tag} \u00b7 {device.get('name') or sid}"     # several devices can share one IP address
        lc.TAG_IDS[tag] = sid               # the Live traffic views find this device's lines by this tag
        if kind == "tx":
            self._count("tx", device_stats)
            if event["kind"] == "retry":
                self._count("retries", device_stats)
            prefix = {"retry": "Retry TX", "recovery": "Recovery TX", "config": "Config TX", "write": "Write TX"}.get(event["kind"], "TX")
            if event["kind"] == "write" and event.get("attempt"):
                prefix = f"Write Retry {event['attempt']} TX"
            self._terminal(f"{prefix} -> [{event['frame']}] ({tag} / FC {event['function']:02d})", stamp)
        elif kind == "rx":
            self._count("rx", device_stats)
            self._count("successful", device_stats)
            self._stats["last_response"] = f"{event['elapsed_ms']} ms"
            try:
                hist = self._devices[sid].setdefault("resp_hist", [])
                hist.append(int(event["elapsed_ms"]))
                del hist[:-40]
                self._resp_all.append(int(event["elapsed_ms"]))
                del self._resp_all[:-300]
            except Exception:
                pass
            if event.get("kind") != "write":
                self.dashboard_tab.on_response(sid, event["elapsed_ms"])
            self._terminal(f"RX <- [{event['frame']}] ({tag} / FC {event['function']:02d})", stamp)
        elif kind == "fail":
            if event.get("kind") not in ("config", "write"):
                self.dashboard_tab.on_failure(sid, event.get("elapsed_ms"))
            if event["reason"] == "timeout":
                self._count("timeouts", device_stats)
                self._last_timeout = (device["name"] if device is not None else f"Slave {sid}", time.monotonic())
                self._terminal(f"RX <- TIMEOUT ({event['elapsed_ms']} ms) ({tag})", stamp)
            else:
                if event["reason"] == "exception":
                    self._count("rx", device_stats)  # a frame was received
                self._count("errors", device_stats)
                self._terminal(f"Communication error ({tag}): {event['detail']}", stamp)
            if device is not None and event.get("kind") not in ("config", "write"):
                device["quality"] = "BAD"
                self._dirty_devices.add(sid)
        elif kind == "write_session":
            if event["state"] == "paused":
                self._writing = True
                self._terminal("---- Polling paused: writing ----", stamp)
                self.status_indicator.setText("●  Writing...")
                _ss(self.status_indicator, "background:#FFF4E0;color:#E08A00;border-radius:5px;"
                                                    "padding:3px 7px;font-size:9px;font-weight:700;")
            else:
                self._writing = False
                result = "all OK" if not event.get("failed") else f"{event['failed']} FAILED"
                self._terminal(f"---- Write done ({event['count']} write(s), {result}, {event['elapsed_ms']} ms). "
                               "Polling resumed ----", stamp)
                if self._connected:
                    self.status_indicator.setText("●  Connected")
                    _ss(self.status_indicator, "background:#E8F8EF;color:#12A45B;border-radius:5px;"
                                                        "padding:3px 7px;font-size:9px;font-weight:700;")
        elif kind == "write_result":
            self._pending_writes.discard((sid, int(event["function"]), int(event["address"])))
            clicked = (sid, int(event["address"])) in self._fc05_clicks
            self._fc05_clicks.discard((sid, int(event["address"])))
            if (clicked and int(event["function"]) == 5 and event.get("reason") == "timeout"
                    and device is not None and int(device.get("do_write", 15)) == 5):
                # Many DO modules ignore FC05 and only accept FC15 (Write Multiple Coils).
                # Switch this device to FC15 one-coil for the next click; nothing is resent now.
                device["do_write"] = 15
                self._rebuild_device_table()
                self._terminal(f"{device['name']}: no answer to FC05 - DO write switched to "
                               "FC15 (Write Multiple Coils). Click the output again.", stamp)
            name = device["name"] if device is not None else f"Slave {sid}"
            if event["ok"] and device is not None and device.get("kind") == "DO" and self._scanner is not None:
                self._scanner.poll_now(sid)     # show the new output state without waiting a full poll
            for card in self._writer_cards.values():
                if int(card._device["slave_id"]) == sid:
                    card.on_write_result(event["function"], event["address"], event["count"], event["ok"])
            if event["ok"]:
                tries = f", after {event['attempts'] - 1} retry" if event.get("attempts", 1) > 1 else ""
                self._terminal(f"Write OK: {name} FC{event['function']:02d} address {event['address']} "
                               f"({event['count']} value(s), {event['elapsed_ms']} ms{tries}).", stamp)
            else:
                why = {"timeout": "no response (timeout)", "exception": "device returned a Modbus exception",
                       "skipped": "not sent, the device did not answer the previous write"}.get(
                    event["reason"], event["detail"])
                self._terminal(f"Write FAILED: {name} FC{event['function']:02d} address {event['address']} - {why}.", stamp)
        elif kind == "config":
            if device is not None:
                device["ip_types"] = event["ip_types"]
                device["latest_units"] = event["units"]
                self._dirty_devices.add(sid)
        elif kind == "state":
            if device is not None:
                for key in ("status", "retry_count", "next_poll", "next_retry", "next_recovery", "last_response"):
                    device[key] = event[key]
                self._alarms.on_status(sid, device["name"], event["status"])
                self._dirty_devices.add(sid)
        elif kind == "reading":
            reading = event["reading"]
            if device is not None:
                self.dashboard_tab.on_reading(sid, device.get("kind"), reading)
                device["latest_data"] = reading.channels
                device["latest_regs"] = getattr(reading, "registers", None) or device.get("latest_regs")
                if reading.units:
                    device["latest_units"] = reading.units
                device["quality"] = reading.quality
                device["timestamp"] = reading.timestamp
                vhist = device.setdefault("vhist", [])
                vhist.append(dict(reading.channels))
                del vhist[:-120]
                if device.get("kind") == "AI":
                    self._alarms.on_reading(sid, device["name"], reading.channels,
                                            reading.units or device.get("latest_units"), reading.timestamp)
                self._dirty_devices.add(sid)
        elif kind == "log":
            self._terminal(event["text"], stamp)
        elif kind == "port_lost":
            self._port_lost = True
            self._terminal(f"COM port lost ({event['detail']}). Scanner stopped; devices kept as NOT POLLED.", stamp)
            self._disconnect()
        if self._csv_file is not None:
            self._csv_event(kind, sid, device, event, stamp)
        self._stats_dirty = True

    def _count(self, key, device_stats):
        self._stats[key] += 1
        if device_stats is not None:
            device_stats[key] += 1

    def _watch_port(self):
        """Disconnect when the COM port disappears (USB-RS485 adapter unplugged)."""
        if not self._connected or list_ports is None or "rtu" not in self._links:
            return
        if not self._port_present:
            self._port_present = True
            self._port_lost = True
            self._terminal(f"COM port {self.com_port.currentText()} is no longer available. Communication stopped.")
            self._disconnect()
            return
        now = time.monotonic()
        if self._port_check_busy or now - self._port_check_at < 2.0:
            return
        self._port_check_busy = True
        self._port_check_at = now
        port = self.com_port.currentText().strip()

        def check():
            try:
                present = port in [p.device for p in list_ports.comports()]
            except Exception:
                present = True
            if present:
                self._port_seen = True
            self._port_present = present or not self._port_seen
            self._port_check_busy = False
        threading.Thread(target=check, daemon=True).start()

    def _refresh_ui(self):
        self._sync_add_panel()
        self._watch_port()
        self._sync_topbar()
        self._flush_terminal()
        self._check_db_status()
        for sid in self._dirty_devices:
            self._refresh_device_row(sid)
            self._refresh_device_card(sid)
        for sid, card in self._card_refs.items():
            device = self._devices.get(sid)
            if device is not None:
                card.refresh_footer(device, self._status_text(device))
        if self._dirty_devices:
            self._live.devices.refresh_filter()
        self._dirty_devices.clear()
        if self._spot_sid in self._devices:
            self._refresh_spotlight(self._devices[self._spot_sid])
        if self._stats_dirty:
            self._stats_dirty = False
            self._update_statistics()
        self._update_next_poll()

    def _update_statistics(self):
        total = len(self._devices)
        running = sum(1 for device in self._devices.values() if device.get("enabled", False))
        online = sum(1 for device in self._devices.values() if device.get("status") == "ONLINE")
        offline = sum(1 for device in self._devices.values() if device.get("status") == "OFFLINE")
        retrying = sum(1 for device in self._devices.values() if device.get("status") == "RETRYING")
        not_polled = max(0, total - online - offline - retrying)

        summary = (
            f"Total Devices   :   {total}\n"
            f"Running Devices :   {running}\n"
            f"Total TX        :   {self._stats['tx']}\n"
            f"Total RX        :   {self._stats['rx']}\n"
            f"Successful      :   {self._stats['successful']}\n"
            f"Timeouts        :   {self._stats['timeouts']}\n"
            f"Retries         :   {self._stats.get('retries', 0)}\n"
            f"Errors          :   {self._stats['errors']}"
        )
        self._update_live_stats(online, total)
        if self.session_summary.text() != summary:
            self.session_summary.setText(summary)

        stats_text = (
            summary + "\n"
            "\n"
            "============================\n"
            "DEVICE STATISTICS\n"
            "============================\n"
        )
        for index, device in enumerate(sorted(self._devices.values(), key=lambda x: x["slave_id"]), 1):
            device_stats = device.get("stats") or _empty_device_stats()
            stats_text += (
                f"\nDevice {index} - {device['name']}\n"
                f"{_id_line(device)}\n"
                f"TX           : {device_stats['tx']}\n"
                f"RX           : {device_stats['rx']}\n"
                f"Successful   : {device_stats['successful']}\n"
                f"Timeouts     : {device_stats['timeouts']}\n"
                f"Retries      : {device_stats['retries']}\n"
                f"Errors       : {device_stats['errors']}\n"
                "----------------------------\n"
            )
        if self.statistics.toPlainText() != stats_text:
            bar = self.statistics.verticalScrollBar()
            position = bar.value()
            self.statistics.setPlainText(stats_text)
            bar.setValue(position)  # keep the user's scroll position

        if hasattr(self, "polling_donut"):
            self.polling_donut.set_counts(online, offline, retrying, not_polled)
            self.poll_online.setText(f"●  Online      {online}")
            self.poll_offline.setText(f"●  Offline      {offline}")
            self.poll_retry.setText(f"●  Retrying      {retrying}")
            self.poll_idle.setText(f"●  Not Polled   {not_polled}")

    def _update_next_poll(self):
        """Next 5 scheduled bus jobs. Reuses a fixed pool of row widgets."""
        if self._next_poll_frame.isHidden():
            return
        now = time.monotonic()
        entries = []
        for device in self._devices.values():
            if not device.get("enabled", False):
                continue
            status = device.get("status")
            if status == "OFFLINE":
                due, suffix, color, bg = device.get("next_recovery"), " (Recovery)", "#E53935", "#FDECEC"
            elif status == "RETRYING":
                due, suffix, color, bg = device.get("next_retry"), " (Retry)", "#D88B00", "#FFF6E5"
            else:
                due, suffix, color, bg = device.get("next_poll"), "", "#07528A", "#F1F7FB"
            remaining = max(0, int((due - now) * 1000)) if due is not None else 0
            entries.append((remaining, device["slave_id"], device["name"], f"{remaining} ms{suffix}", color, bg))
        entries.sort()
        entries = entries[:5]

        while len(self._next_poll_labels) < len(entries):
            row = QFrame()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(6, 4, 8, 4)
            row_layout.setSpacing(8)
            number = QLabel()
            number.setFixedSize(18, 18)
            number.setAlignment(Qt.AlignCenter)
            name = QLabel()
            when = QLabel()
            when.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row_layout.addWidget(number)
            row_layout.addWidget(name, 1)
            row_layout.addWidget(when)
            self.next_poll_list.addWidget(row)
            self._next_poll_labels.append((row, number, name, when, {}))
        for index, (row, number, name, when, cache) in enumerate(self._next_poll_labels):
            if index >= len(entries):
                row.setVisible(False)
                continue
            _, _, text, when_text, color, bg = entries[index]
            if name.text() != text:
                name.setText(text)
            if when.text() != when_text:
                when.setText(when_text)
            if number.text() != str(index + 1):
                number.setText(str(index + 1))
            if cache.get("style") != (color, bg, index == 0):
                cache["style"] = (color, bg, index == 0)
                _ss(row, f"QFrame{{background:{'#E3F0FB' if (index == 0 and bg == '#F1F7FB') else bg};border-radius:6px;}}")
                _ss(number, 
                    f"background:{'#1E88E5' if index == 0 else '#8B9BAA'};color:white;border-radius:9px;"
                    "font-size:9px;font-weight:700;")
                _ss(name, f"color:{color};font-size:10px;font-weight:600;background:transparent;")
                _ss(when, f"color:{color};font-size:10px;font-weight:600;background:transparent;")
            row.setVisible(True)

    def _clear_terminal_and_statistics(self):
        """Clear terminal + session/device statistics only. Devices,
        configuration and the connection are not touched."""
        self._terminal_buffer = []
        self.terminal.clear()
        self._stats = {
            "tx": 0,
            "rx": 0,
            "successful": 0,
            "timeouts": 0,
            "retries": 0,
            "errors": 0,
            "last_response": "--",
        }
        for device in self._devices.values():
            device["stats"] = _empty_device_stats()
        self._update_statistics()

    def _terminal(self, message, stamp=None):
        stamped = f"[{(stamp or datetime.now()).strftime('%H:%M:%S.%f')[:-3]}] {message}"
        if self._log_file is not None:
            self._log_pending.append(stamped)          # file always keeps the time
        self._console_buffer.append(stamped)
        if hasattr(self, "show_timestamps") and self.show_timestamps.isChecked():
            message = stamped
        self._terminal_buffer.append(message)
        self._term_dirty = True
        if not self._ui_timer.isActive():
            self._flush_terminal()

    @staticmethod
    def _terminal_color(line):
        lower = line.lower()
        if "polling paused" in lower or "polling resumed" in lower:
            return "#FFB74D"
        if "write failed" in lower:
            return "#FF7B7B"
        if "alarm cleared" in lower:
            return "#7EE0A0"
        if "timeout" in lower or "!!" in line or "error" in lower or "lost" in lower:
            return "#FF7B7B"
        if "retry" in lower or "recovery" in lower or "config tx" in lower:
            return "#FFC857"
        if "tx ->" in lower:
            return "#8FD3FF"
        if "rx <-" in lower or "recovered" in lower:
            return "#7EE0A0"
        return "#D6E4F0"

    def _flush_terminal(self):
        self._flush_log()
        if self._console_buffer and hasattr(self, "_live"):
            lines, self._console_buffer = self._console_buffer[-1500:], []
            self._live.console.append(lines)
            if self._spot_sid is not None:
                own = [h for kind, slave, h in map(lc.parse_line, lines) if slave == self._spot_sid]
                for h in own:
                    self._live.detail.traffic.appendHtml(f'<div style="white-space:pre">{h}</div>')
        if not self._terminal_buffer:
            return
        lines = self._terminal_buffer[-self.terminal.maximumBlockCount():]
        self._terminal_buffer = []
        self.terminal.setUpdatesEnabled(False)
        for line in lines:
            self.terminal.appendHtml(
                f'<span style="color:{self._terminal_color(line)};white-space:pre">{html.escape(line)}</span>')
        self.terminal.setUpdatesEnabled(True)
        if hasattr(self, "auto_scroll") and self.auto_scroll.isChecked():
            self.terminal.verticalScrollBar().setValue(self.terminal.verticalScrollBar().maximum())

    # ---------------------------------------------------------------- #
    # Record Log: stream the terminal to a text file for later analysis
    # ---------------------------------------------------------------- #
    def _toggle_log(self):
        if self._log_file is not None:
            self._stop_log("stopped by user")
            return
        default_dir = os.path.join(os.path.expanduser("~"), "Documents")
        if not os.path.isdir(default_dir):
            default_dir = os.path.expanduser("~")
        name = f"modbus_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        path, _ = QFileDialog.getSaveFileName(self, "Record TX/RX log", os.path.join(default_dir, name),
                                              "Log files (*.txt);;All files (*)")
        if path:
            self._start_log(path)

    def _start_log(self, path):
        try:
            self._log_file = open(path, "w", encoding="utf-8", newline="\n")
        except OSError as exc:
            self._log_file = None
            self._terminal(f"Unable to create log file: {exc}")
            return
        self._log_path = path
        self._log_started = time.monotonic()
        self._log_lines = 0
        self._log_pending = []
        minutes = self.log_duration.currentData() or 0
        w = self._log_file.write
        w("# Nelumbo Modbus RTU log\n")
        w(f"# started   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        w(f"# duration  {str(minutes) + ' min' if minutes else 'until stopped'}\n")
        if self._connected and len(self._links) > 1:
            for link in LINKS:
                if link in self._links:
                    w(f"# link      {self._link_line(link)}\n")
        elif self._is_tcp():
            w(f"# link      {self.connection_type.currentText()}  {self._link_text()}\n")
        else:
            w(f"# port      {self.com_port.currentText()}  {self.baud_rate.currentText()} baud  "
              f"{self.data_bits.currentText()}{self.parity.currentText()[:1]}{self.stop_bits.currentText()}\n")
        for device in sorted(self._devices.values(), key=lambda d: d["slave_id"]):
            w(f"# DEVICE slave={device['slave_id']} link={link_of(device, self._legacy_link)} name={device.get('name', '')!r} kind={device.get('kind', '')} "
              f"fc={device.get('function')} addr={device.get('address')} count={device.get('count')} "
              f"poll={device.get('polling')} scan={device.get('scan_rate')} timeout={device.get('timeout')} "
              f"retries={device.get('max_retries')} enabled={bool(device.get('enabled', True))}"
              + (f" do_write={device.get('do_write', 15)}" if device.get("kind") == "DO" else "") + "\n")
        for device in self._writers.values():
            w(f"# WRITER slave={device['slave_id']} name={device.get('name', '')!r} fc={device.get('function')} "
              f"addr={device.get('address')} count={device.get('count')}\n")
        w("#\n")
        self._log_file.flush()
        self._update_duration_enabled()
        if not hasattr(self, "_log_timer"):
            self._log_timer = QTimer(self)
            self._log_timer.setInterval(1000)
            self._log_timer.timeout.connect(self._flush_log)
        self._log_timer.start()
        self._terminal(f"Recording log to {path}" + (f" for {minutes} min." if minutes else " (press Stop Log to end)."))
        self._update_log_button()

    def _flush_log(self):
        if self._log_file is None:
            return
        if self._log_pending:
            try:
                self._log_file.write("\n".join(self._log_pending) + "\n")
                self._log_file.flush()
            except OSError as exc:
                self._log_pending = []
                self._stop_log(f"write error: {exc}")
                return
            self._log_lines += len(self._log_pending)
            self._log_pending = []
        minutes = self.log_duration.currentData() or 0
        if minutes and time.monotonic() - self._log_started >= minutes * 60:
            self._stop_log(f"{minutes} min completed")
            return
        self._update_log_button()

    def _stop_log(self, reason=""):
        if self._log_file is None:
            return
        path = self._log_path
        try:
            if self._log_pending:
                self._log_file.write("\n".join(self._log_pending) + "\n")
                self._log_lines += len(self._log_pending)
            st = self._stats
            self._log_file.write(
                f"#\n# stopped   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ({reason})\n"
                f"# session   TX={st.get('tx', 0)} RX={st.get('rx', 0)} successful={st.get('successful', 0)} "
                f"timeouts={st.get('timeouts', 0)} retries={st.get('retries', 0)} errors={st.get('errors', 0)}\n")
            self._log_file.close()
        except OSError:
            pass
        self._log_file = None
        self._log_pending = []
        if hasattr(self, "_log_timer"):
            self._log_timer.stop()
        self._update_duration_enabled()
        self._update_log_button()
        self._terminal(f"Log saved ({self._log_lines} lines, {reason}): {path}")

    def _update_log_button(self):
        if not hasattr(self, "log_button"):
            return
        if self._log_file is None:
            self.log_button.setText("\u25cf  Record Log")
            _ss(self.log_button, "")
            return
        secs = int(time.monotonic() - self._log_started)
        self.log_button.setText(f"\u25a0  Stop Log  {secs // 60:02d}:{secs % 60:02d}")
        _ss(self.log_button, "color:white;background:#E53935;border:1px solid #E53935;"
                                      "border-radius:5px;font-weight:700;")

    # ---------------------------------------------------------------- #
    # Record CSV: readings, timeouts and writes as rows of a .csv file
    # ---------------------------------------------------------------- #
    CSV_CHANNELS = 16

    def _update_duration_enabled(self):
        self.log_duration.setEnabled(self._log_file is None and self._csv_file is None)

    def _toggle_csv(self):
        if self._csv_file is not None:
            self._stop_csv("stopped by user")
            return
        default_dir = os.path.join(os.path.expanduser("~"), "Documents")
        if not os.path.isdir(default_dir):
            default_dir = os.path.expanduser("~")
        name = f"modbus_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Record readings to CSV", os.path.join(default_dir, name),
                                              "CSV files (*.csv);;All files (*)")
        if path:
            self._start_csv(path)

    def _start_csv(self, path):
        try:
            self._csv_file = open(path, "w", encoding="utf-8-sig", newline="")     # BOM: Excel opens it cleanly
        except OSError as exc:
            self._csv_file = None
            self._terminal(f"Unable to create CSV file: {exc}")
            return
        self._csv_writer = csv.writer(self._csv_file)
        self._csv_path = path
        self._csv_started = time.monotonic()
        self._csv_rows = 0
        self._csv_pending = []
        self._csv_resp = {}
        self._csv_writer.writerow(["timestamp", "event", "slave_id", "device", "type", "function", "response_ms",
                                   "quality"] + [f"CH{i + 1}" for i in range(self.CSV_CHANNELS)] + ["units", "note"])
        self._csv_file.flush()
        self._update_duration_enabled()
        if not hasattr(self, "_csv_timer"):
            self._csv_timer = QTimer(self)
            self._csv_timer.setInterval(1000)
            self._csv_timer.timeout.connect(self._flush_csv)
        self._csv_timer.start()
        minutes = self.log_duration.currentData() or 0
        self._terminal(f"Recording CSV to {path}" + (f" for {minutes} min." if minutes else " (press Stop CSV to end)."))
        self._update_csv_button()

    def _csv_event(self, kind, sid, device, event, stamp):
        name = device["name"] if device is not None else f"Slave {sid}"
        dtype = device.get("kind", "") if device is not None else ""
        function = device.get("function", "") if device is not None else ""
        blank = [""] * self.CSV_CHANNELS
        when = stamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        row = None
        if kind == "rx" and event.get("kind") != "write":
            self._csv_resp[sid] = event.get("elapsed_ms", "")
        elif kind == "reading" and device is not None:
            reading = event["reading"]
            values = [value for _name, value in reading.channels][:self.CSV_CHANNELS]
            values += [""] * (self.CSV_CHANNELS - len(values))
            units = reading.units or device.get("latest_units") or []
            unit_text = ";".join(u or "" for u in units) if any(units) else ""
            row = [when, "READ", sid, name, dtype, function, self._csv_resp.get(sid, ""),
                   reading.quality or "", *values, unit_text, ""]
        elif kind == "fail" and event.get("kind") not in ("config", "write"):
            row = [when, str(event.get("reason", "error")).upper(), sid, name, dtype, function,
                   event.get("elapsed_ms", ""), "BAD", *blank, "", event.get("detail", "") or ""]
        elif kind == "write_result":
            ok = bool(event.get("ok"))
            note = f"address {event.get('address')}" + ("" if ok else f" - {event.get('reason', 'failed')}")
            row = [when, "WRITE_OK" if ok else "WRITE_FAIL", sid, name, dtype, event.get("function", ""),
                   "", "", *blank, "", note]
        if row is not None:
            self._csv_pending.append(row)

    def _flush_csv(self):
        if self._csv_file is None:
            return
        if self._csv_pending:
            try:
                self._csv_writer.writerows(self._csv_pending)
                self._csv_file.flush()
            except (OSError, ValueError) as exc:
                self._csv_pending = []
                self._stop_csv(f"write error: {exc}")
                return
            self._csv_rows += len(self._csv_pending)
            self._csv_pending = []
        minutes = self.log_duration.currentData() or 0
        if minutes and time.monotonic() - self._csv_started >= minutes * 60:
            self._stop_csv(f"{minutes} min completed")
            return
        self._update_csv_button()

    def _stop_csv(self, reason=""):
        if self._csv_file is None:
            return
        path = self._csv_path
        try:
            if self._csv_pending:
                self._csv_writer.writerows(self._csv_pending)
                self._csv_rows += len(self._csv_pending)
            self._csv_file.close()
        except (OSError, ValueError):
            pass
        self._csv_file = None
        self._csv_writer = None
        self._csv_pending = []
        if hasattr(self, "_csv_timer"):
            self._csv_timer.stop()
        self._update_duration_enabled()
        self._update_csv_button()
        self._terminal(f"CSV saved ({self._csv_rows} rows, {reason}): {path}")

    def _update_csv_button(self):
        if not hasattr(self, "csv_button"):
            return
        if self._csv_file is None:
            self.csv_button.setText("\u25cf  Record CSV")
            _ss(self.csv_button, "")
            return
        secs = int(time.monotonic() - self._csv_started)
        self.csv_button.setText(f"\u25a0  Stop CSV  {secs // 60:02d}:{secs % 60:02d}  ({self._csv_rows + len(self._csv_pending)})")
        _ss(self.csv_button, "color:white;background:#E53935;border:1px solid #E53935;"
                             "border-radius:5px;font-weight:700;")

    def closeEvent(self, event):
        self._save_project()
        self._stop_log("window closed")
        self._stop_csv("window closed")
        scanner = self._scanner
        self._connected = False
        if scanner is not None:
            scanner.request_stop()
            longest = max([int(d.get("timeout", 2000)) for d in self._devices.values()] or [2000])
            scanner.wait(longest + 1000)
        self._ui_timer.stop()
        self._stop_db_writer()