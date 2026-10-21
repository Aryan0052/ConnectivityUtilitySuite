"""Modern Live console for the Multi Device page.

Layout (see the approved mock-up): slim icon navigation, a top bar with the connection
pill and the bus actions, one stats card, a device list next to a device detail panel,
and a traffic console at the bottom.  Every colour comes from a small token table, so
light and dark are the same widgets with a different palette.
"""
import re
import time
from datetime import datetime

from PySide6.QtCore import Qt, Signal, QPointF, QRectF, QSize
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QLinearGradient, QFont
from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QGridLayout, QLineEdit,
    QScrollArea, QStackedWidget, QPlainTextEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox, QListView, QSizePolicy, QAbstractItemView,
)

try:
    from .device_data import (DATA_FORMATS, WORD_ORDERS, WIDE_FORMATS, ENABLE_FORMATS,
                              effective_format, format_value, MFT_PARAMS)
except ImportError:
    from device_data import (DATA_FORMATS, WORD_ORDERS, WIDE_FORMATS, ENABLE_FORMATS,
                             effective_format, format_value, MFT_PARAMS)

# --------------------------------------------------------------------------- tokens
LIGHT = {
    "bg": "#F6F7F9", "surface": "#FFFFFF", "sunken": "#F1F3F6", "hover": "#F4F6F9",
    "border": "#E4E7EC", "border2": "#D5DAE1",
    "text": "#0F1720", "text2": "#3A4452", "muted": "#6B7480", "faint": "#9AA3AE",
    "accent": "#0B6FD6", "accent_soft": "#E8F1FD", "accent_text": "#0A5FB8", "on_accent": "#FFFFFF",
    "ok": "#15803D", "ok_soft": "#E7F6EC", "warn": "#B45309", "warn_soft": "#FDF3E3",
    "bad": "#C2312F", "bad_soft": "#FCEBEA", "idle": "#9AA3AE",
    "r": "#D9363E", "y": "#C98A00", "b": "#2E5BD8", "violet": "#7C4DDB", "teal": "#0E9384", "pink": "#C4327A",
    "console": "#0E1116", "console_bar": "#FFFFFF",
}
DARK = {
    "bg": "#0C0E12", "surface": "#13161B", "sunken": "#0F1216", "hover": "#181C22",
    "border": "#22272F", "border2": "#2C323B",
    "text": "#ECEFF3", "text2": "#C4CAD2", "muted": "#8B939E", "faint": "#5F6772",
    "accent": "#4C9AFF", "accent_soft": "#16253A", "accent_text": "#7FB6FF", "on_accent": "#FFFFFF",
    "ok": "#3FB76A", "ok_soft": "#12261A", "warn": "#E3A33B", "warn_soft": "#2A2113",
    "bad": "#F06A64", "bad_soft": "#2C1615", "idle": "#5F6772",
    "r": "#F0625F", "y": "#E8B03A", "b": "#5B8DEF", "violet": "#9F7AEA", "teal": "#2DB3A3", "pink": "#E2629F",
    "console": "#090B0E", "console_bar": "#13161B",
}
THEME = "light"
SCALE = 1.0
SERIES = ("accent", "r", "y", "ok", "violet", "teal", "pink", "b")
STATUS_TONE = {"ONLINE": "ok", "RETRYING": "warn", "OFFLINE": "bad"}
_TOKEN = re.compile(r"@([a-z0-9_]+)")
_PX = re.compile(r"(\d+(?:\.\d+)?)px")


def tok(name):
    return (DARK if THEME == "dark" else LIGHT).get(name, name)


def qc(name, alpha=None):
    color = QColor(tok(name))
    if alpha is not None:
        color.setAlpha(alpha)
    return color


def px(value):
    return max(1, int(round(value * SCALE)))


def _render(text, k=1.0):
    text = _TOKEN.sub(lambda m: tok(m.group(1)), text)
    factor = SCALE * k

    def one(m):
        v = float(m.group(1))
        return m.group(0) if v <= 1 else f"{max(1, int(round(v * factor)))}px"
    return _PX.sub(one, text)


def tss(widget, template, k=1.0):
    """Style sheet written with @tokens: re-rendered on every theme / scale change."""
    widget.setProperty("_lc_qss", template)
    widget.setProperty("_lc_k", k)
    widget.setStyleSheet(_render(template, k))


def restyle(root, theme, scale):
    """Apply a theme / UI scale to every console widget below root."""
    global THEME, SCALE
    THEME, SCALE = ("dark" if theme == "dark" else "light"), scale
    for widget in [root] + root.findChildren(QWidget):
        template = widget.property("_lc_qss")
        if template:
            widget.setStyleSheet(_render(template, widget.property("_lc_k") or 1.0))
        if hasattr(widget, "retheme"):
            widget.retheme()
        widget.update()


def unit_html(value, unit, size=13):
    if not unit:
        return value
    return (f'{value}<span style="font-size:{px(size)}px;color:{tok("muted")};font-weight:500">'
            f'&nbsp;{unit}</span>')


def finite(v):
    return isinstance(v, (int, float)) and v == v and abs(v) != float("inf")


def num(v, dec=2):
    if not finite(v):
        return "--"
    if abs(v) >= 10000:
        return f"{v:,.0f}"
    return f"{v:.{dec}f}"


BASE_QSS = """
QLabel { background:transparent; color:@text; font-family:"Segoe UI"; }
QLabel#muted { color:@muted; font-size:12px; }
QLabel#faint { color:@faint; font-size:11px; }
QPushButton { font-family:"Segoe UI"; }
QPushButton#lcBtn { background:@surface; color:@text; border:1px solid @border2; border-radius:8px;
    padding:0 14px; min-height:32px; font-size:12px; font-weight:600; }
QPushButton#lcBtn:hover { background:@hover; }
QPushButton#lcBtn:disabled { color:@faint; }
QPushButton#lcPrimary { background:@accent; color:@on_accent; border:1px solid @accent; border-radius:8px;
    padding:0 16px; min-height:32px; font-size:12px; font-weight:600; }
QPushButton#lcPrimary:disabled { background:@border2; border-color:@border2; }
QPushButton#lcGhost { background:transparent; color:@muted; border:0; border-radius:7px;
    padding:0 10px; min-height:28px; font-size:12px; font-weight:600; }
QPushButton#lcGhost:hover { background:@hover; color:@text; }
QPushButton#lcIcon { background:@surface; color:@muted; border:1px solid @border; border-radius:8px;
    min-width:32px; max-width:32px; min-height:32px; max-height:32px; font-size:14px; padding:0; }
QPushButton#lcIcon:hover { color:@text; background:@hover; }
QFrame#lcCard { background:@surface; border:1px solid @border; border-radius:12px; }
QFrame#lcBox { background:transparent; border:1px solid @border; border-radius:10px; }
QFrame#lcKpi { background:@sunken; border:1px solid @border; border-radius:10px; }
QLineEdit#lcSearch { background:@sunken; border:1px solid @border; border-radius:8px; color:@text;
    padding:0 10px; min-height:32px; font-size:12px; }
QLineEdit#lcSearch:focus { border-color:@accent; }
QScrollArea { background:transparent; border:0; }
QScrollArea > QWidget > QWidget { background:transparent; }
QScrollBar:vertical { width:8px; background:transparent; margin:2px; }
QScrollBar::handle:vertical { background:@border2; border-radius:4px; min-height:30px; }
QScrollBar::add-line, QScrollBar::sub-line { height:0; width:0; }
QScrollBar:horizontal { height:8px; background:transparent; margin:2px; }
QScrollBar::handle:horizontal { background:@border2; border-radius:4px; min-width:30px; }
QComboBox#lcCombo { background:@surface; border:1px solid @border2; border-radius:7px; color:@text;
    padding:0 8px; min-height:26px; font-size:11px; font-weight:600; }
QComboBox#lcCombo::drop-down { border:0; width:16px; }
QComboBox#lcCombo QAbstractItemView { background:@surface; color:@text; border:1px solid @border;
    selection-background-color:@accent_soft; selection-color:@text; }
"""


# --------------------------------------------------------------------------- small painted widgets
class Dot(QWidget):
    """Status dot with a soft ring."""
    def __init__(self, size=8):
        super().__init__()
        self._tone = "idle"
        self._d = size
        self.setFixedSize(size + 8, size + 8)

    def set_tone(self, tone):
        if tone != self._tone:
            self._tone = tone
            self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        c = QPointF(self.width() / 2, self.height() / 2)
        p.setPen(Qt.NoPen)
        if self._tone != "idle":
            p.setBrush(qc(self._tone + "_soft"))
            p.drawEllipse(c, self._d / 2 + 3, self._d / 2 + 3)
        p.setBrush(qc(self._tone))
        p.drawEllipse(c, self._d / 2, self._d / 2)
        p.end()


class Spark(QWidget):
    """Tiny trend line."""
    def __init__(self, w=90, h=28, fill=False):
        super().__init__()
        self._data, self._tone, self._fill, self._wh = [], "accent", fill, (w, h)
        self.setFixedSize(px(w), px(h))
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def retheme(self):
        self.setFixedSize(px(self._wh[0]), px(self._wh[1]))

    def set_data(self, data, tone="accent"):
        data = [v for v in data if finite(v)][-40:]
        if data != self._data or tone != self._tone:
            self._data, self._tone = data, tone
            self.update()

    def paintEvent(self, _event):
        d = self._data
        if len(d) < 2:
            return
        w, h = self.width(), self.height()
        lo, hi = min(d), max(d)
        span = (hi - lo) or 1.0
        step = (w - 2) / (len(d) - 1)
        pts = [QPointF(1 + i * step, h - 3 - (v - lo) / span * (h - 6)) for i, v in enumerate(d)]
        path = QPainterPath(pts[0])
        for pt in pts[1:]:
            path.lineTo(pt)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        if self._fill:
            area = QPainterPath(path)
            area.lineTo(pts[-1].x(), h)
            area.lineTo(pts[0].x(), h)
            area.closeSubpath()
            grad = QLinearGradient(0, 0, 0, h)
            grad.setColorAt(0, qc(self._tone, 60))
            grad.setColorAt(1, qc(self._tone, 0))
            p.fillPath(area, grad)
        p.setPen(QPen(qc(self._tone), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path)
        p.end()


class Meter(QWidget):
    """Row of small bars, one per device, coloured by status."""
    def __init__(self):
        super().__init__()
        self._tones = []
        self.setFixedHeight(px(6))

    def retheme(self):
        self.setFixedHeight(px(6))

    def set_tones(self, tones):
        if tones != self._tones:
            self._tones = list(tones)
            self.update()

    def paintEvent(self, _event):
        if not self._tones:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        n = len(self._tones)
        gap = 3.0
        w = (self.width() - gap * (n - 1)) / n
        for i, tone in enumerate(self._tones):
            p.setBrush(qc(tone))
            p.drawRoundedRect(QRectF(i * (w + gap), 0, w, self.height()), 2.5, 2.5)
        p.end()


class Bar(QWidget):
    """Thin progress bar (phase voltage balance)."""
    def __init__(self, tone):
        super().__init__()
        self._tone, self._f = tone, 0.0
        self.setFixedHeight(px(4))

    def retheme(self):
        self.setFixedHeight(px(4))

    def set_fraction(self, f):
        f = max(0.0, min(1.0, f)) if finite(f) else 0.0
        if abs(f - self._f) > 0.002:
            self._f = f
            self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        r = self.height() / 2
        p.setBrush(qc("border"))
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), r, r)
        p.setBrush(qc(self._tone))
        p.drawRoundedRect(QRectF(0, 0, self.width() * self._f, self.height()), r, r)
        p.end()


class LineChart(QWidget):
    """Multi-series line chart with three grid lines and a value axis."""
    def __init__(self, unit=""):
        super().__init__()
        self._series, self._unit = [], unit
        self.setMinimumHeight(px(120))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_series(self, series, unit=None):
        """series: [(tone, [values])]"""
        self._series = [(tone, [v for v in values if finite(v)]) for tone, values in series]
        if unit is not None:
            self._unit = unit
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        font = QFont("Segoe UI")
        font.setPixelSize(px(10))
        p.setFont(font)
        values = [v for _t, s in self._series for v in s]
        w, h = self.width(), self.height()
        if len(values) < 2:
            p.setPen(qc("faint"))
            p.drawText(self.rect(), Qt.AlignCenter, "Waiting for data")
            p.end()
            return
        lo, hi = min(values), max(values)
        if hi - lo < 1e-9:
            lo, hi = lo - 1, hi + 1
        pad = (hi - lo) * 0.15
        lo, hi = lo - pad, hi + pad
        left, top, bottom = px(54), px(8), px(6)
        plot_h = h - top - bottom
        for i in range(3):
            y = top + plot_h * i / 2
            v = hi - (hi - lo) * i / 2
            p.setPen(QPen(qc("border"), 1))
            p.drawLine(QPointF(left, y), QPointF(w, y))
            p.setPen(qc("faint"))
            label = f"{v:,.0f}" if abs(v) >= 100 else f"{v:.2f}"
            p.drawText(QRectF(0, y - px(8), left - px(8), px(16)), Qt.AlignRight | Qt.AlignVCenter,
                       f"{label} {self._unit}".strip())
        for tone, data in self._series:
            if len(data) < 2:
                continue
            step = (w - left - 4) / (len(data) - 1)
            path = QPainterPath(QPointF(left + 2, top + (hi - data[0]) / (hi - lo) * plot_h))
            for i, v in enumerate(data[1:], 1):
                path.lineTo(QPointF(left + 2 + i * step, top + (hi - v) / (hi - lo) * plot_h))
            p.setPen(QPen(qc(tone), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        p.end()


# --------------------------------------------------------------------------- navigation
class NavButton(QPushButton):
    def __init__(self, key, tip):
        super().__init__()
        self.key = key
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setToolTip(tip)
        self.setFixedSize(px(40), px(40))
        self._hover = False

    def retheme(self):
        self.setFixedSize(px(40), px(40))

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(0, 0, self.width(), self.height())
        if self.isChecked():
            p.setPen(Qt.NoPen)
            p.setBrush(qc("accent_soft"))
            p.drawRoundedRect(r, px(10), px(10))
        elif self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(qc("hover"))
            p.drawRoundedRect(r, px(10), px(10))
        s = self.width() / 40.0 * 0.8
        p.translate(self.width() / 2 - 12 * s, self.height() / 2 - 12 * s)
        p.scale(s, s)
        p.setPen(QPen(qc("accent" if self.isChecked() else "muted"), 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        k = self.key
        if k == "dashboard":
            for x, y, w, h in ((3, 3, 7, 9), (14, 3, 7, 5), (14, 12, 7, 9), (3, 16, 7, 5)):
                p.drawRoundedRect(QRectF(x, y, w, h), 1.5, 1.5)
        elif k == "live":
            path = QPainterPath(QPointF(3, 12))
            for x, y in ((7, 12), (10, 4), (14, 20), (17, 12), (21, 12)):
                path.lineTo(QPointF(x, y))
            p.drawPath(path)
        elif k == "history":
            p.drawEllipse(QPointF(12, 12), 9, 9)
            p.drawPolyline([QPointF(12, 7), QPointF(12, 12), QPointF(15, 14)])
        elif k == "trends":
            p.drawPolyline([QPointF(4, 5), QPointF(4, 19), QPointF(20, 19)])
            p.drawPolyline([QPointF(8, 15), QPointF(12, 10), QPointF(15, 13), QPointF(20, 7)])
        elif k == "setup":
            p.drawEllipse(QPointF(12, 12), 3, 3)
            p.drawEllipse(QPointF(12, 12), 7.5, 7.5)
            import math
            for i in range(8):
                a = i * math.pi / 4
                p.drawLine(QPointF(12 + 7.5 * math.cos(a), 12 + 7.5 * math.sin(a)),
                           QPointF(12 + 10 * math.cos(a), 12 + 10 * math.sin(a)))
        p.end()


def _logo_path():
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    for base in (os.path.dirname(here), here):
        for name in ("13.ico", "NelumboLogo.png", "logo.png"):
            path = os.path.join(base, "assets", name)
            if os.path.exists(path):
                return path
    return None


_LOGO = []


def _logo_image():
    """assets/13.ico (Nelumbo tile). The file may really be a JPEG/PNG with an .ico name,
    so the format is detected from the content."""
    from PySide6.QtGui import QImageReader, QPixmap
    if not _LOGO:
        path = _logo_path()
        pixmap = None
        if path:
            reader = QImageReader(path)
            reader.setDecideFormatFromContent(True)
            image = reader.read()
            if not image.isNull():
                pixmap = QPixmap.fromImage(image)
        _LOGO.append(pixmap)
    return _LOGO[0]


class LogoTile(QWidget):
    """Nelumbo logo tile in the navigation rail."""
    def __init__(self):
        super().__init__()
        self.setToolTip("Nelumbo Automation Pvt Ltd")
        self.retheme()

    def retheme(self):
        self.setFixedSize(px(48), px(36))
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        rect = QRectF(0, 0, self.width(), self.height())
        clip = QPainterPath()
        clip.addRoundedRect(rect, px(8), px(8))
        p.setClipPath(clip)
        grad = QLinearGradient(0, 0, self.width(), self.height())
        grad.setColorAt(0, QColor("#23AEC1"))
        grad.setColorAt(1, QColor("#2D5A93"))
        p.fillRect(rect, grad)
        logo = _logo_image()
        if logo is not None:
            ratio = self.devicePixelRatioF()
            scaled = logo.scaled(int(self.width() * ratio), int(self.height() * ratio),
                                 Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            scaled.setDevicePixelRatio(ratio)
            w, h = scaled.width() / ratio, scaled.height() / ratio
            p.drawPixmap(QPointF((self.width() - w) / 2, (self.height() - h) / 2), scaled)
        else:
            font = QFont("Segoe UI")
            font.setPixelSize(px(16))
            font.setBold(True)
            p.setFont(font)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(self.rect(), Qt.AlignCenter, "N")
        p.end()


class NavRail(QFrame):
    picked = Signal(str)
    ITEMS = (("dashboard", "Dashboard"), ("live", "Live"))

    def __init__(self):
        super().__init__()
        self.setObjectName("lcNav")
        tss(self, "QFrame#lcNav { background:@surface; border:0; border-right:1px solid @border; }")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 14, 0, 14)
        self._lay.setSpacing(6)
        self._lay.addWidget(LogoTile(), 0, Qt.AlignHCenter)
        self._lay.addSpacing(14)
        self.buttons = {}
        for key, tip in self.ITEMS:
            self._add(key, tip)
        self._lay.addStretch(1)
        self._add("setup", "Setup: devices, connection, full terminal")
        self.retheme()

    def _add(self, key, tip):
        b = NavButton(key, tip)
        b.clicked.connect(lambda _c=False, k=key: self.picked.emit(k))
        self._lay.addWidget(b, 0, Qt.AlignHCenter)
        self.buttons[key] = b

    def retheme(self):
        self.setFixedWidth(px(64))

    def set_current(self, key):
        for k, b in self.buttons.items():
            b.setChecked(k == key)


# --------------------------------------------------------------------------- top bar
class TopBar(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("lcTop")
        tss(self, BASE_QSS + """
            QFrame#lcTop { background:@surface; border:0; border-bottom:1px solid @border; }
            QFrame#lcConn { background:@surface; border:1px solid @border; border-radius:8px; }
            QLabel#crumb { color:@muted; font-size:13px; }
            QLabel#crumbB { color:@text; font-size:15px; font-weight:600; }
            QLabel#connText { color:@text2; font-size:12px; }
            QFrame#vsep { background:@border; border:0; }
            QPushButton#connLink { background:transparent; border:0; color:@accent_text; font-size:12px;
                font-weight:600; padding:0 4px; }
            QPushButton#connLink:hover { text-decoration:underline; }
        """)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 24, 0)
        lay.setSpacing(12)
        self.back_btn = QPushButton("\u2190")
        self.back_btn.setObjectName("lcIcon")
        self.back_btn.setToolTip("Back")
        self.back_btn.setCursor(Qt.PointingHandCursor)
        lay.addWidget(self.back_btn)
        self.crumb = QLabel("Multi Device  /")
        self.crumb.setObjectName("crumb")
        self.page = QLabel("Live")
        self.page.setObjectName("crumbB")
        lay.addWidget(self.crumb)
        lay.addWidget(self.page)
        lay.addSpacing(6)

        conn = QFrame()
        conn.setObjectName("lcConn")
        cl = QHBoxLayout(conn)
        cl.setContentsMargins(8, 0, 6, 0)
        cl.setSpacing(8)
        self.dot = Dot()
        cl.addWidget(self.dot)
        self._parts = []
        for _ in range(4):
            label = QLabel("")
            label.setObjectName("connText")
            sep = QFrame()
            sep.setObjectName("vsep")
            sep.setFixedSize(1, 14)
            cl.addWidget(label)
            cl.addWidget(sep)
            self._parts.append((label, sep))
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("connLink")
        self.connect_btn.setCursor(Qt.PointingHandCursor)
        cl.addWidget(self.connect_btn)
        self._conn = conn
        lay.addWidget(conn)
        lay.addStretch(1)

        self.rescan_btn = self._button("\u27f3  Rescan", "lcGhost")
        self.add_btn = self._button("\uff0b  Add device", "lcBtn")
        self.stop_btn = self._button("\u25a0  Stop", "lcBtn")
        self.start_btn = self._button("\u25b6  Start polling", "lcPrimary")
        for b in (self.rescan_btn, self.add_btn, self.stop_btn, self.start_btn):
            lay.addWidget(b)
        self.theme_btn = QPushButton("\u263e")
        self.theme_btn.setObjectName("lcIcon")
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.setToolTip("Light / dark theme")
        lay.addWidget(self.theme_btn)
        self.retheme()

    @staticmethod
    def _button(text, name):
        b = QPushButton(text)
        b.setObjectName(name)
        b.setCursor(Qt.PointingHandCursor)
        b.setFocusPolicy(Qt.NoFocus)
        return b

    def retheme(self):
        self.setFixedHeight(px(60))
        self._conn.setFixedHeight(px(32))
        self.theme_btn.setText("\u2600" if THEME == "dark" else "\u263e")

    def set_page(self, text):
        self.page.setText(text)

    def set_connection(self, tone, parts, link_text, link_enabled=True):
        self.dot.set_tone(tone)
        for i, (label, sep) in enumerate(self._parts):
            text = parts[i] if i < len(parts) else ""
            if label.text() != text:
                label.setText(text)
            label.setVisible(bool(text))
            sep.setVisible(bool(text))
        if self.connect_btn.text() != link_text:
            self.connect_btn.setText(link_text)
        self.connect_btn.setEnabled(link_enabled)


# --------------------------------------------------------------------------- stats card
class StatCell(QWidget):
    def __init__(self, title):
        super().__init__()
        lay = QGridLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setVerticalSpacing(4)
        self.title = QLabel(title)
        tss(self.title, "color:@muted; font-size:12px; font-weight:500;")
        self.value = QLabel("--")
        self.value.setTextFormat(Qt.RichText)
        tss(self.value, "color:@text; font-size:24px; font-weight:600;")
        self.sub = QLabel("")
        tss(self.sub, "color:@muted; font-size:11px;")
        self.extra = None
        lay.addWidget(self.title, 0, 0)
        lay.addWidget(self.value, 1, 0)
        lay.addWidget(self.sub, 2, 0)
        self._lay = lay
        self._cache = None
        self._sub_tone = None

    def add_extra(self, widget, beside=True):
        self.extra = widget
        if beside:
            self._lay.addWidget(widget, 1, 1, 2, 1, Qt.AlignRight | Qt.AlignBottom)
        else:
            self._lay.addWidget(widget, 2, 0, 1, 2)
            self.sub.hide()

    def set(self, value, unit="", sub="", sub_tone=None):
        self._cache = (value, unit, sub, sub_tone)
        html = unit_html(value, unit)
        if self.value.text() != html:
            self.value.setText(html)
        if self.sub.text() != sub:
            self.sub.setText(sub)
        if sub_tone != self._sub_tone:
            self._sub_tone = sub_tone
            tss(self.sub, f"color:@{sub_tone or 'muted'}; font-size:11px;")

    def retheme(self):
        if self._cache:
            self.value.setText("")
            self.set(*self._cache)


class StatsCard(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("lcCard")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.cells = {}
        for i, (key, title) in enumerate((("online", "Devices online"), ("req", "Requests"),
                                          ("rate", "Success rate"), ("resp", "Avg response"),
                                          ("to", "Timeouts"))):
            if i:
                sep = QFrame()
                sep.setFixedWidth(1)
                tss(sep, "background:@border; border:0;")
                lay.addWidget(sep)
            cell = StatCell(title)
            self.cells[key] = cell
            lay.addWidget(cell, 1)
        self.meter = Meter()
        self.cells["online"].add_extra(self.meter, beside=False)
        self.req_spark = Spark(90, 28)
        self.cells["req"].add_extra(self.req_spark)
        self.resp_spark = Spark(90, 28)
        self.cells["resp"].add_extra(self.resp_spark)


# --------------------------------------------------------------------------- segmented / tabs
class Segmented(QFrame):
    changed = Signal(str)

    def __init__(self, items, current):
        super().__init__()
        self.setObjectName("lcSeg")
        tss(self, """
            QFrame#lcSeg { background:@sunken; border:1px solid @border; border-radius:7px; }
            QPushButton { background:transparent; border:0; border-radius:5px; color:@muted;
                font-size:11px; font-weight:600; padding:0 9px; min-height:22px; max-height:22px; }
            QPushButton:checked { background:@surface; color:@text; border:1px solid @border; }
        """)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        self.buttons = {}
        for key, text in items:
            b = QPushButton(text)
            b.setCheckable(True)
            b.setChecked(key == current)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _c=False, k=key: self.select(k, emit=True))
            lay.addWidget(b)
            self.buttons[key] = b
        self.current = current

    def select(self, key, emit=False):
        self.current = key
        for k, b in self.buttons.items():
            b.setChecked(k == key)
        if emit:
            self.changed.emit(key)


class UnderlineTabs(QFrame):
    changed = Signal(str)

    def __init__(self, items):
        super().__init__()
        self.setObjectName("lcTabs")
        tss(self, """
            QFrame#lcTabs { background:transparent; border:0; border-bottom:1px solid @border; }
            QPushButton { background:transparent; border:0; color:@muted; font-size:13px; font-weight:500;
                padding:10px 0; margin-right:20px; border-bottom:2px solid transparent; }
            QPushButton:hover { color:@text; }
            QPushButton:checked { color:@text; font-weight:600; border-bottom:2px solid @accent; }
        """)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(0)
        self.buttons = {}
        for key, text in items:
            b = QPushButton(text)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _c=False, k=key: self.select(k, emit=True))
            lay.addWidget(b)
            self.buttons[key] = b
        lay.addStretch(1)
        self.current = items[0][0]
        self.select(self.current)

    def select(self, key, emit=False):
        self.current = key
        for k, b in self.buttons.items():
            b.setChecked(k == key)
        if emit:
            self.changed.emit(key)


# --------------------------------------------------------------------------- device list
class DeviceRow(QWidget):
    picked = Signal(int)

    def __init__(self, device):
        super().__init__()
        self.sid = device["slave_id"]
        self.kind = device.get("kind") or ""
        self.search_text = ""
        self.status = "NOT POLLED"
        self._sel = self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        g = QGridLayout(self)
        g.setContentsMargins(30, 9, 10, 9)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(3)
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        self.name = QLabel(device["name"])
        tss(self.name, "color:@text; font-size:13px; font-weight:600;")
        self.tag = QLabel(self.kind or device.get("type", ""))
        tss(self.tag, "color:@text2; background:@sunken; border:1px solid @border; border-radius:5px;"
                      "font-size:10px; font-weight:600; padding:0 6px;")
        name_row.addWidget(self.name)
        name_row.addWidget(self.tag)
        name_row.addStretch(1)
        self.value = QLabel("--")
        self.value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.meta = QLabel("")
        tss(self.meta, "color:@muted; font-size:11px;")
        right = QHBoxLayout()
        right.setSpacing(6)
        right.addStretch(1)
        self.spark = Spark(54, 14)
        self.ms = QLabel("")
        tss(self.ms, "color:@muted; font-size:11px;")
        right.addWidget(self.spark)
        right.addWidget(self.ms)
        g.addLayout(name_row, 0, 0)
        g.addWidget(self.value, 0, 1)
        g.addWidget(self.meta, 1, 0)
        g.addLayout(right, 1, 1)
        g.setColumnStretch(0, 1)
        self._value_tone = None
        self._set_value_tone("text")

    def _set_value_tone(self, tone):
        if tone != self._value_tone:
            self._value_tone = tone
            tss(self.value, f"color:@{tone}; font-size:13px; font-weight:600;")

    def set_selected(self, on):
        if on != self._sel:
            self._sel = on
            self.update()

    def refresh(self, device, status, value_text, meta_text, resp):
        self.status = status
        if self.name.text() != device["name"]:
            self.name.setText(device["name"])
        if self.value.text() != value_text:
            self.value.setText(value_text)
        self._set_value_tone("bad" if status == "OFFLINE" else ("muted" if status not in ("ONLINE", "RETRYING") else "text"))
        if self.meta.text() != meta_text:
            self.meta.setText(meta_text)
        tone = STATUS_TONE.get(status, "idle")
        self.spark.set_data(resp if status in ("ONLINE", "RETRYING") else [], tone if tone != "idle" else "muted")
        ms = f"{resp[-1]} ms" if resp and status in ("ONLINE", "RETRYING") else ""
        if self.ms.text() != ms:
            self.ms.setText(ms)
        self.search_text = f"{device['name']} {self.sid} {self.kind}".lower()
        self.update()

    def event(self, e):
        if e.type() in (e.Type.HoverEnter, e.Type.HoverLeave):
            self._hover = e.type() == e.Type.HoverEnter
            self.update()
        return super().event(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.picked.emit(self.sid)
        super().mousePressEvent(e)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        if self._sel:
            p.setBrush(qc("accent_soft"))
            p.setPen(QPen(qc("accent", 90), 1))
            p.drawRoundedRect(r, px(9), px(9))
        elif self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(qc("hover"))
            p.drawRoundedRect(r, px(9), px(9))
        tone = STATUS_TONE.get(self.status, "idle")
        c = QPointF(px(15), px(9) + px(9))
        p.setPen(Qt.NoPen)
        if tone != "idle":
            p.setBrush(qc(tone + "_soft"))
            p.drawEllipse(c, px(7), px(7))
        p.setBrush(qc(tone))
        p.drawEllipse(c, px(4), px(4))
        p.end()


class DeviceList(QFrame):
    picked = Signal(int)

    def __init__(self):
        super().__init__()
        self.setObjectName("lcCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 14, 0, 8)
        lay.setSpacing(10)
        head = QHBoxLayout()
        head.setContentsMargins(16, 0, 16, 0)
        head.setSpacing(10)
        title = QLabel("Devices")
        tss(title, "color:@text; font-size:14px; font-weight:600;")
        self.count = QLabel("0")
        tss(self.count, "color:@muted; background:@sunken; border:1px solid @border; border-radius:6px;"
                        "font-size:11px; padding:1px 7px;")
        self.count.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        head.addWidget(title)
        head.addWidget(self.count, 0, Qt.AlignVCenter)
        head.addStretch(1)
        self.seg = Segmented((("all", "All"), ("online", "Online"), ("faults", "Faults")), "all")
        self.seg.changed.connect(lambda _k: self._apply_filter())
        head.addWidget(self.seg)
        lay.addLayout(head)
        self.search = QLineEdit()
        self.search.setObjectName("lcSearch")
        self.search.setPlaceholderText("\u2315  Search devices or slave ID")
        self.search.textChanged.connect(lambda _t: self._apply_filter())
        sw = QHBoxLayout()
        sw.setContentsMargins(16, 0, 16, 0)
        sw.addWidget(self.search)
        lay.addLayout(sw)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        self._list = QVBoxLayout(host)
        self._list.setContentsMargins(8, 0, 8, 0)
        self._list.setSpacing(2)
        self._empty = QLabel("No devices")
        self._empty.setAlignment(Qt.AlignCenter)
        tss(self._empty, "color:@faint; font-size:12px; padding:20px;")
        self._list.addWidget(self._empty)
        self._list.addStretch(1)
        self.scroll.setWidget(host)
        lay.addWidget(self.scroll, 1)
        self.rows = {}
        self.selected = None

    def set_devices(self, devices):
        for row in self.rows.values():
            row.setParent(None)
            row.deleteLater()
        self.rows = {}
        for device in devices:
            row = DeviceRow(device)
            row.picked.connect(self.picked.emit)
            self._list.insertWidget(self._list.count() - 1, row)
            self.rows[device["slave_id"]] = row
        self.count.setText(str(len(devices)))
        self.select(self.selected)
        self._apply_filter()

    def select(self, sid):
        self.selected = sid
        for key, row in self.rows.items():
            row.set_selected(key == sid)

    def _apply_filter(self):
        mode = self.seg.current
        text = self.search.text().strip().lower()
        shown = 0
        for row in self.rows.values():
            ok = (mode == "all" or (mode == "online" and row.status == "ONLINE")
                  or (mode == "faults" and row.status in ("OFFLINE", "RETRYING")))
            if text and text not in row.search_text:
                ok = False
            row.setVisible(ok)
            shown += ok
        self._empty.setVisible(shown == 0)
        self._empty.setText("No devices yet \u2014 use Add device" if not self.rows else "No matching devices")

    def refresh_filter(self):
        if self.seg.current != "all":
            self._apply_filter()


# --------------------------------------------------------------------------- detail panel
class Kpi(QFrame):
    def __init__(self, title):
        super().__init__()
        self.setObjectName("lcKpi")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 11, 14, 11)
        lay.setSpacing(2)
        self.title = QLabel(title)
        tss(self.title, "color:@muted; font-size:12px;")
        self.value = QLabel("--")
        self.value.setTextFormat(Qt.RichText)
        tss(self.value, "color:@text; font-size:22px; font-weight:600;")
        lay.addWidget(self.title)
        lay.addWidget(self.value)
        self._cache = None

    def set(self, value, unit=""):
        self._cache = (value, unit)
        html = unit_html(value, unit)
        if self.value.text() != html:
            self.value.setText(html)

    def retheme(self):
        if self._cache:
            self.value.setText("")
            self.set(*self._cache)


class ChannelChip(QWidget):
    clicked = Signal(int)

    def __init__(self, index, name, clickable):
        super().__init__()
        self.index, self.name, self.on = index, name, None
        self.clickable = clickable
        if clickable:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip(f"Click to switch {name}")
        self.setMinimumHeight(px(54))

    def retheme(self):
        self.setMinimumHeight(px(54))

    def set_state(self, on):
        if on != self.on:
            self.on = on
            self.update()

    def mousePressEvent(self, e):
        if self.clickable and e.button() == Qt.LeftButton:
            self.clicked.emit(self.index)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        on = bool(self.on)
        p.setBrush(qc("ok_soft" if on else "sunken"))
        p.setPen(QPen(qc("ok", 110) if on else qc("border"), 1))
        p.drawRoundedRect(r, px(9), px(9))
        font = QFont("Segoe UI")
        font.setPixelSize(px(11))
        font.setWeight(QFont.DemiBold)
        p.setFont(font)
        p.setPen(qc("text2"))
        p.drawText(QRectF(px(10), px(8), self.width(), px(16)), Qt.AlignLeft | Qt.AlignVCenter, self.name)
        p.setPen(qc("ok" if on else ("muted" if self.on is not None else "faint")))
        state = "--" if self.on is None else ("ON" if on else "OFF")
        p.drawText(QRectF(px(10), self.height() - px(24), self.width(), px(16)), Qt.AlignLeft | Qt.AlignVCenter, state)
        p.setPen(Qt.NoPen)
        p.setBrush(qc("ok") if on else qc("border2"))
        p.drawEllipse(QPointF(self.width() - px(14), px(16)), px(4), px(4))
        p.end()


def _legend(items):
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)
    for tone, text in items:
        label = QLabel(f'<span style="color:{tok(tone)}">\u2014</span> {text}')
        label.setProperty("_legend", (tone, text))
        tss(label, "color:@muted; font-size:11px; font-weight:500;")
        lay.addWidget(label)
    return w


class DetailPanel(QFrame):
    pause_clicked = Signal(int)
    edit_clicked = Signal(int)
    do_toggle = Signal(int, int)
    format_changed = Signal(int, str, str)

    def __init__(self):
        super().__init__()
        self.setObjectName("lcCard")
        self.sid = None
        self._built_for = None
        self._device = None
        self._status = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(20, 16, 20, 0)
        head.setSpacing(14)
        self.avatar = QLabel("")
        self.avatar.setAlignment(Qt.AlignCenter)
        tss(self.avatar, "background:@accent_soft; color:@accent; border-radius:10px; font-size:12px; font-weight:700;"
                         "min-width:42px; max-width:42px; min-height:42px; max-height:42px;")
        head.addWidget(self.avatar, 0, Qt.AlignTop)
        titles = QVBoxLayout()
        titles.setSpacing(3)
        self.name = QLabel("")
        tss(self.name, "color:@text; font-size:18px; font-weight:600;")
        self.sub = QLabel("")
        tss(self.sub, "color:@muted; font-size:12px;")
        titles.addWidget(self.name)
        titles.addWidget(self.sub)
        head.addLayout(titles, 1)
        self.pill = QLabel("")
        head.addWidget(self.pill, 0, Qt.AlignTop)
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setObjectName("lcBtn")
        self.edit_btn = QPushButton("Edit")
        self.edit_btn.setObjectName("lcBtn")
        for b in (self.pause_btn, self.edit_btn):
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            head.addWidget(b, 0, Qt.AlignTop)
        self.pause_btn.clicked.connect(lambda: self.sid is not None and self.pause_clicked.emit(self.sid))
        self.edit_btn.clicked.connect(lambda: self.sid is not None and self.edit_clicked.emit(self.sid))
        self._head = QWidget()
        self._head.setLayout(head)
        root.addWidget(self._head)
        root.addSpacing(14)
        self.tabs = UnderlineTabs((("overview", "Overview"), ("registers", "Registers"), ("traffic", "Traffic")))
        self.tabs.changed.connect(self._on_tab)
        root.addWidget(self.tabs)
        self.pages = QStackedWidget()
        root.addWidget(self.pages, 1)
        self.overview = QWidget()
        self._ov = QVBoxLayout(self.overview)
        self._ov.setContentsMargins(20, 16, 20, 16)
        self._ov.setSpacing(14)
        ov_scroll = QScrollArea()
        ov_scroll.setWidgetResizable(True)
        ov_scroll.setFrameShape(QFrame.NoFrame)
        self.overview.setObjectName("lcOverview")
        tss(self.overview, "QWidget#lcOverview { background:@surface; }")
        self.overview.setAttribute(Qt.WA_StyledBackground, True)
        ov_scroll.setWidget(self.overview)
        tss(ov_scroll, "QScrollArea { background:@surface; border:0; }")
        ov_scroll.viewport().setAutoFillBackground(False)
        self.pages.addWidget(ov_scroll)
        # registers
        reg = QWidget()
        rl = QVBoxLayout(reg)
        rl.setContentsMargins(20, 12, 20, 16)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Parameter", "Value", "Unit"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        tss(self.table, """
            QTableWidget { background:transparent; border:1px solid @border; border-radius:10px; color:@text;
                font-size:12px; }
            QTableWidget::item { padding:6px 10px; border-bottom:1px solid @border; }
            QHeaderView::section { background:@sunken; color:@muted; border:0; border-bottom:1px solid @border;
                padding:7px 10px; font-size:11px; font-weight:600; }
        """)
        rl.addWidget(self.table)
        self.pages.addWidget(reg)
        # traffic
        tr = QWidget()
        tl = QVBoxLayout(tr)
        tl.setContentsMargins(20, 12, 20, 16)
        self.traffic = QPlainTextEdit()
        self.traffic.setReadOnly(True)
        self.traffic.setMaximumBlockCount(800)
        tss(self.traffic, "QPlainTextEdit { background:@console; color:#C9D1DA; border:1px solid @border;"
                          " border-radius:10px; font-family:Consolas,'Cascadia Mono',monospace; font-size:12px; padding:8px; }")
        tl.addWidget(self.traffic)
        self.pages.addWidget(tr)
        self.empty = QLabel("Select a device on the left")
        self.empty.setAlignment(Qt.AlignCenter)
        tss(self.empty, "color:@faint; font-size:14px;")
        root.addWidget(self.empty, 1)
        self._parts = {}
        self.set_empty(True)

    # -- state -------------------------------------------------------------
    def set_empty(self, empty, text="Select a device on the left"):
        self.empty.setText(text)
        self.empty.setVisible(empty)
        for w in (self._head, self.tabs, self.pages):
            w.setVisible(not empty)
        if empty:
            self.sid = None
            self._built_for = None

    def _on_tab(self, key):
        self.pages.setCurrentIndex({"overview": 0, "registers": 1, "traffic": 2}[key])

    def _clear_overview(self):
        while self._ov.count():
            item = self._ov.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            elif item.layout() is not None:
                _drop_layout(item.layout())
        self._parts = {}

    def show_device(self, device):
        self.set_empty(False)
        kind = device.get("kind") or ""
        key = (device["slave_id"], kind, int(device.get("function", 0) or 0), int(device.get("count", 0) or 0),
               device.get("data_format"), device.get("word_order"))
        self.sid = device["slave_id"]
        if key == self._built_for:
            return
        self._built_for = key
        self._clear_overview()
        self.table.setRowCount(0)
        if kind == "MFT":
            self._build_mft()
        elif kind in ("DI", "DO"):
            self._build_digital(device)
        else:
            self._build_analog(device)
        self._ov.addStretch(1)

    def _box(self, title, right=None):
        box = QFrame()
        box.setObjectName("lcBox")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        if title:
            h = QHBoxLayout()
            h.setSpacing(10)
            t = QLabel(title)
            tss(t, "color:@text; font-size:12px; font-weight:600;")
            h.addWidget(t)
            h.addStretch(1)
            if right is not None:
                h.addWidget(right)
            lay.addLayout(h)
        return box, lay

    def _kpi_row(self, titles):
        row = QHBoxLayout()
        row.setSpacing(12)
        kpis = []
        for t in titles:
            k = Kpi(t)
            row.addWidget(k, 1)
            kpis.append(k)
        self._ov.addLayout(row)
        return kpis

    # -- MFT ---------------------------------------------------------------
    PHASE_ROWS = (("Voltage", ("AVrms", "BVrms", "CVrms"), "V", 1),
                  ("Current", ("IA", "IB", "IC"), "A", 2),
                  ("Active power", ("P_A", "P_B", "P_C"), "W", 1),
                  ("Reactive power", ("Q_A", "Q_B", "Q_C"), "var", 1),
                  ("Apparent power", ("S_A", "S_B", "S_C"), "VA", 1),
                  ("Power factor", ("PF_A", "PF_B", "PF_C"), "", 2),
                  ("Frequency", ("FreqA", "FreqB", "FreqC"), "Hz", 2),
                  ("Voltage THD", ("VTHD_A", "VTHD_B", "VTHD_C"), "%", 2),
                  ("Current THD", ("ITHD_A", "ITHD_B", "ITHD_C"), "%", 2))

    def _build_mft(self):
        self._parts["kpis"] = self._kpi_row(("Active power", "Apparent power", "Power factor", "Frequency"))
        grid = QHBoxLayout()
        grid.setSpacing(14)
        box, lay = self._box(None)
        lay.setContentsMargins(4, 4, 4, 4)
        table = QGridLayout()
        table.setHorizontalSpacing(0)
        table.setVerticalSpacing(0)
        header_tones = (("Parameter", None), ("R", "r"), ("Y", "y"), ("B", "b"))
        for col, (text, tone) in enumerate(header_tones):
            label = QLabel(text if tone is None else f'<span style="color:{tok(tone)}">\u25a0</span>&nbsp;{text}')
            label.setAlignment((Qt.AlignLeft if col == 0 else Qt.AlignRight) | Qt.AlignVCenter)
            tss(label, "color:@muted; font-size:11px; font-weight:500; padding:8px 10px; border-bottom:1px solid @border;")
            if tone:
                label.setProperty("_hdr", (tone, text))
            table.addWidget(label, 0, col)
        self._parts["hdr"] = [table.itemAtPosition(0, c).widget() for c in range(1, 4)]
        cells = {}
        bars = []
        last = len(self.PHASE_ROWS)
        for r, (title, names, unit, dec) in enumerate(self.PHASE_ROWS, 1):
            border = "" if r == last else "border-bottom:1px solid @border;"
            name = QLabel(title)
            tss(name, f"color:@text2; font-size:12px; padding:6px 10px; {border}")
            table.addWidget(name, r, 0)
            for c, key in enumerate(names, 1):
                holder = QWidget()
                tss(holder, f"QWidget {{ background:transparent; {border} }}")
                hl = QVBoxLayout(holder)
                hl.setContentsMargins(10, 5, 10, 5)
                hl.setSpacing(4)
                v = QLabel("--")
                v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                tss(v, "color:@text; font-size:13px; font-weight:600; border:0;")
                hl.addWidget(v)
                if title == "Voltage":
                    bar = Bar(("r", "y", "b")[c - 1])
                    hl.addWidget(bar)
                    bars.append(bar)
                table.addWidget(holder, r, c)
                cells[key] = (v, unit, dec)
        table.setColumnStretch(0, 3)
        for c in (1, 2, 3):
            table.setColumnStretch(c, 2)
        lay.addLayout(table)
        lay.addStretch(1)
        self._parts["cells"] = cells
        self._parts["bars"] = bars
        grid.addWidget(box, 5)
        right = QVBoxLayout()
        right.setSpacing(14)
        cbox, cl = self._box("Active power", _legend((("r", "R"), ("y", "Y"), ("b", "B"))))
        chart = LineChart("W")
        cl.addWidget(chart, 1)
        self._parts["chart"] = chart
        right.addWidget(cbox, 1)
        lbox, ll = self._box("Line voltages")
        lrow = QHBoxLayout()
        lrow.setSpacing(18)
        lines = {}
        for key, title, unit in (("VAB", "R\u2013Y", "V"), ("VBC", "Y\u2013B", "V"), ("VCA", "B\u2013R", "V"),
                                 ("IN", "Neutral", "A")):
            col = QVBoxLayout()
            col.setSpacing(2)
            t = QLabel(title)
            tss(t, "color:@muted; font-size:11px;")
            v = QLabel("--")
            v.setTextFormat(Qt.RichText)
            tss(v, "color:@text; font-size:17px; font-weight:600;")
            col.addWidget(t)
            col.addWidget(v)
            lrow.addLayout(col)
            lines[key] = (v, unit)
        lrow.addStretch(1)
        ll.addLayout(lrow)
        self._parts["lines"] = lines
        right.addWidget(lbox)
        grid.addLayout(right, 4)
        self._ov.addLayout(grid, 1)

    def _refresh_mft(self, device, values):
        P = [values.get(k) for k in ("P_A", "P_B", "P_C")]
        S = [values.get(k) for k in ("S_A", "S_B", "S_C")]
        Q = [values.get(k) for k in ("Q_A", "Q_B", "Q_C")]
        F = [values.get(k) for k in ("FreqA", "FreqB", "FreqC")]

        def total(vals):
            vals = [v for v in vals if finite(v)]
            return sum(vals) if vals else None

        def mean(vals):
            vals = [v for v in vals if finite(v)]
            return sum(vals) / len(vals) if vals else None

        p, s, q = total(P), total(S), total(Q)
        k = self._parts["kpis"]

        def power(v, base):
            if not finite(v):
                return "--", base
            return (num(v / 1000.0, 2), "k" + base) if abs(v) >= 1000 else (num(v, 1), base)
        k[0].set(*power(p, "W"))
        k[1].set(*power(s, "VA"))
        pf = (p / s) if finite(p) and finite(s) and s else mean([values.get(x) for x in ("PF_A", "PF_B", "PF_C")])
        k[2].set(num(pf, 2), ("lag" if not finite(q) or q >= 0 else "lead") if finite(pf) else "")
        k[3].set(num(mean(F), 2), "Hz")
        volts = [values.get(x) for x in ("AVrms", "BVrms", "CVrms")]
        vmax = max([v for v in volts if finite(v)] or [0]) * 1.08 or 1
        for key, (label, unit, dec) in self._parts["cells"].items():
            v = values.get(key)
            text = "--" if not finite(v) else (f"{num(v, dec)} {unit}".strip())
            if label.text() != text:
                label.setText(text)
        for bar, v in zip(self._parts["bars"], volts):
            bar.set_fraction(v / vmax if finite(v) else 0)
        for key, (label, unit) in self._parts["lines"].items():
            label.setText(unit_html(num(values.get(key), 2 if unit == "A" else 1), unit, 12))
        hist = device.get("vhist") or []
        self._parts["chart"].set_series([(tone, [h.get(key) for h in hist])
                                         for tone, key in (("r", "P_A"), ("y", "P_B"), ("b", "P_C"))], "W")

    # -- digital -----------------------------------------------------------
    def _build_digital(self, device):
        kind = device.get("kind")
        self._parts["kpis"] = self._kpi_row(("Active channels", "Response", "Last update", "Function"))
        word = "Inputs" if kind == "DI" else "Outputs"
        clickable = kind == "DO" and int(device.get("function", 0)) == 1
        hint = QLabel("Click an output to switch it" if clickable else "")
        tss(hint, "color:@muted; font-size:11px;")
        box, lay = self._box(word, hint)
        grid = QGridLayout()
        grid.setSpacing(10)
        chips = []
        count = int(device.get("count", 16) or 16)
        cols = 8 if count > 8 else count
        for i in range(count):
            chip = ChannelChip(i, f"{kind}{i + 1}", clickable)
            chip.clicked.connect(lambda idx, s=device["slave_id"]: self.do_toggle.emit(s, idx))
            grid.addWidget(chip, i // cols, i % cols)
            chips.append(chip)
        lay.addLayout(grid)
        self._parts["chips"] = chips
        self._ov.addWidget(box)
        cbox, cl = self._box("Response time", None)
        chart = LineChart("ms")
        chart.setMinimumHeight(px(140))
        cl.addWidget(chart, 1)
        self._parts["chart"] = chart
        self._ov.addWidget(cbox, 1)

    def _refresh_digital(self, device, values, live):
        kind = device.get("kind")
        chips = self._parts["chips"]
        on = 0
        for chip in chips:
            v = values.get(f"{kind}{chip.index + 1}")
            chip.set_state(None if v is None else bool(int(v)))
            on += bool(v)
        k = self._parts["kpis"]
        k[0].set(f"{on}" if values else "--", f"/ {len(chips)}")
        resp = device.get("resp_hist") or []
        k[1].set(str(resp[-1]) if resp and live else "--", "ms")
        k[2].set(*_age(device.get("timestamp")))
        k[3].set(f"FC{int(device.get('function', 0)):02d}", f"@{device.get('address', 0)}")
        self._parts["chart"].set_series([("accent", resp)], "ms")

    # -- analog ------------------------------------------------------------
    def _build_analog(self, device):
        self._parts["kpis"] = self._kpi_row(("Channels", "Minimum", "Maximum", "Response"))
        fmt_row = None
        if ENABLE_FORMATS and int(device.get("function", 0)) in (3, 4) and device.get("kind") in ("AI", "AO"):
            fmt_row = QWidget()
            fl = QHBoxLayout(fmt_row)
            fl.setContentsMargins(0, 0, 0, 0)
            fl.setSpacing(6)
            fmt_box, order_box = QComboBox(), QComboBox()
            for code, text in DATA_FORMATS.items():
                fmt_box.addItem(text.split(" (")[0].split(" - ")[0], code)
            for code in WORD_ORDERS:
                order_box.addItem(code, code)
            for box in (fmt_box, order_box):
                box.setObjectName("lcCombo")
                box.setView(QListView())
                box.setCursor(Qt.PointingHandCursor)
                fl.addWidget(box)
            fmt_box.setCurrentIndex(max(0, fmt_box.findData(effective_format(device))))
            order_box.setCurrentIndex(max(0, order_box.findData(device.get("word_order") or "MSRF")))
            order_box.setVisible(fmt_box.currentData() in WIDE_FORMATS)
            sid = device["slave_id"]

            def changed(_i=None):
                order_box.setVisible(fmt_box.currentData() in WIDE_FORMATS)
                self.format_changed.emit(sid, fmt_box.currentData(), order_box.currentData())
            fmt_box.currentIndexChanged.connect(changed)
            order_box.currentIndexChanged.connect(changed)
        box, lay = self._box("Channels", fmt_row)
        grid = QGridLayout()
        grid.setSpacing(10)
        self._parts["grid"] = grid
        self._parts["tiles"] = {}
        lay.addLayout(grid)
        self._ov.addWidget(box)
        cbox, cl = self._box("Trend", None)
        chart = LineChart("")
        chart.setMinimumHeight(px(160))
        cl.addWidget(chart, 1)
        self._parts["chart"] = chart
        self._ov.addWidget(cbox, 1)

    def _analog_tile(self, name, index):
        tile = QFrame()
        tile.setObjectName("lcKpi")
        tl = QGridLayout(tile)
        tl.setContentsMargins(12, 10, 12, 10)
        tl.setVerticalSpacing(2)
        t = QLabel(name)
        tss(t, "color:@muted; font-size:11px; font-weight:600;")
        v = QLabel("--")
        v.setTextFormat(Qt.RichText)
        tss(v, "color:@text; font-size:18px; font-weight:600;")
        spark = Spark(60, 22)
        tl.addWidget(t, 0, 0)
        tl.addWidget(v, 1, 0)
        tl.addWidget(spark, 0, 1, 2, 1, Qt.AlignRight | Qt.AlignBottom)
        grid = self._parts["grid"]
        grid.addWidget(tile, index // 4, index % 4)
        self._parts["tiles"][name] = (v, spark, SERIES[index % len(SERIES)])
        return self._parts["tiles"][name]

    def _refresh_analog(self, device, pairs, live):
        units = device.get("latest_units") or []
        kind = device.get("kind")
        fmt = effective_format(device) if kind in ("AI", "AO") else "raw16"
        numbers = []
        hist = device.get("vhist") or []
        for index, (name, value) in enumerate(pairs):
            tile = self._parts["tiles"].get(name) or self._analog_tile(name, index)
            unit = units[index] if index < len(units) and units[index] else ""
            if value is None:
                text = "--"
            elif fmt in ("hex16", "hex32"):
                text = format_value(value, fmt)
                unit = ""
            else:
                text = f"{value:.2f}" if isinstance(value, float) else str(value)
                if finite(value):
                    numbers.append(value)
            tile[0].setText(unit_html(text, unit, 11))
            tile[1].set_data([h.get(name) for h in hist], tile[2])
        k = self._parts["kpis"]
        k[0].set(str(len(pairs)) if pairs else "--")
        k[1].set(num(min(numbers), 2) if numbers else "--")
        k[2].set(num(max(numbers), 2) if numbers else "--")
        resp = device.get("resp_hist") or []
        k[3].set(str(resp[-1]) if resp and live else "--", "ms")
        series = [(self._parts["tiles"][name][2], [h.get(name) for h in hist])
                  for name, _v in pairs[:8] if name in self._parts["tiles"]]
        self._parts["chart"].set_series(series, units[0] if units and len(set(u for u in units if u)) == 1 else "")

    # -- refresh -----------------------------------------------------------
    def refresh(self, device, status):
        if self.sid != device["slave_id"]:
            return
        self._device, self._status = device, status
        self.show_device(device)
        kind = device.get("kind") or ""
        self.avatar.setText(kind or "DEV")
        self.name.setText(device["name"])
        function = int(device.get("function", 0) or 0)
        bits = [{"DI": "Digital input", "DO": "Digital output", "AI": "Analog input", "AO": "Analog output",
                 "MFT": "Multi-function transducer"}.get(kind, device.get("type", "")),
                f"Slave {device['slave_id']}", f"FC{function:02d} @{device.get('address', 0)} \u00d7 {device.get('count', 0)}"]
        if function in (3, 4) and kind in ("AI", "AO", "MFT"):
            fmt = effective_format(device)
            bits.append(fmt.capitalize() + (f" {device.get('word_order') or 'MSRF'}" if fmt in WIDE_FORMATS else ""))
        self.sub.setText("  \u00b7  ".join(bits))
        live = status in ("ONLINE", "RETRYING")
        tone = STATUS_TONE.get(status, "idle")
        resp = device.get("resp_hist") or []
        text = {"ONLINE": f"Online \u00b7 {resp[-1]} ms" if resp else "Online",
                "RETRYING": f"Retrying {device.get('retry_count', 0)}/{device.get('max_retries', 3)}",
                "OFFLINE": "Offline", "DISABLED": "Paused"}.get(status, status.title())
        soft = tone + "_soft" if tone != "idle" else "sunken"
        fg = tone if tone != "idle" else "muted"
        pill = f"\u25cf  {text}"
        if self.pill.text() != pill or self.pill.property("_tone") != tone + THEME:
            self.pill.setText(pill)
            self.pill.setProperty("_tone", tone + THEME)
            tss(self.pill, f"background:@{soft}; color:@{fg}; border-radius:12px; padding:4px 11px;"
                           "font-size:11px; font-weight:600;")
        self.pause_btn.setText("Pause" if device.get("enabled") else "Resume")
        values = dict(device.get("latest_data") or []) if live else {}
        if kind == "MFT":
            self._refresh_mft(device, values)
        elif kind in ("DI", "DO"):
            self._refresh_digital(device, values, live)
        else:
            self._refresh_analog(device, list(device.get("latest_data") or []) if live else
                                 [(n, None) for n in self._parts.get("tiles", {})], live)
        if self.tabs.current == "registers":
            self._refresh_registers(device, live)

    def _refresh_registers(self, device, live):
        rows = list(device.get("latest_data") or []) if live else []
        units = device.get("latest_units") or []
        if device.get("kind") == "MFT":
            units = [u for _n, u in MFT_PARAMS]
        if self.table.rowCount() != len(rows):
            self.table.setRowCount(len(rows))
        for r, (name, value) in enumerate(rows):
            for c, text in enumerate((str(name), (f"{value:.3f}" if isinstance(value, float) else str(value)),
                                      units[r] if r < len(units) and units[r] else "")):
                item = self.table.item(r, c)
                if item is None:
                    item = QTableWidgetItem()
                    item.setTextAlignment((Qt.AlignLeft if c != 1 else Qt.AlignRight) | Qt.AlignVCenter)
                    self.table.setItem(r, c, item)
                if item.text() != text:
                    item.setText(text)

    def retheme(self):
        hdr = self._parts.get("hdr")
        if hdr:
            for label in hdr:
                tone, text = label.property("_hdr")
                label.setText(f'<span style="color:{tok(tone)}">\u25a0</span>&nbsp;{text}')
        for label in self.findChildren(QLabel):
            leg = label.property("_legend")
            if leg:
                label.setText(f'<span style="color:{tok(leg[0])}">\u2014</span> {leg[1]}')
        if self._device is not None and self.sid == self._device["slave_id"]:
            self.pill.setProperty("_tone", None)
            self.refresh(self._device, self._status)


def _drop_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        elif item.layout() is not None:
            _drop_layout(item.layout())


def _age(stamp):
    if stamp is None:
        return "--", ""
    ms = max(0, int((datetime.now() - stamp).total_seconds() * 1000))
    if ms < 1000:
        return str(ms), "ms ago"
    if ms < 60000:
        return f"{ms / 1000:.1f}", "s ago"
    return str(ms // 60000), "min ago"


# --------------------------------------------------------------------------- traffic console
_LINE = re.compile(r"^\[(\d\d:\d\d:\d\d\.\d{3})\] (.*)$")
# The device tag in a TX / RX line is "Slave 3" (RTU), "TCP \u00b7 ID 3" (gateway) or "192.168.0.181" (own IP).
_TXL = re.compile(r"^(.*?TX) -> \[(.*?)\] \((.+?) / FC (\d+)\)$")
_RXL = re.compile(r"^RX <- \[(.*?)\] \((.+?) / FC (\d+)\)$")
_TOL = re.compile(r"^RX <- TIMEOUT \((\d+) ms\) \((.+?)\)$")
_SLV = re.compile(r"Slave (\d+)")
_TAG_NUM = re.compile(r"(?:Slave|ID) (\d+)$")
TAG_IDS = {}          # device tag -> device key; filled by the page that writes the lines (Multi Device)


def tag_id(tag):
    """Device key of a line's device tag, or None."""
    if tag in TAG_IDS:
        return TAG_IDS[tag]
    m = _TAG_NUM.search(tag)
    return int(m.group(1)) if m else None


def parse_line(line):
    """-> (kind, slave, html).  kind: tx / rx / err / info."""
    from html import escape
    m = _LINE.match(line)
    stamp, body = (m.group(1), m.group(2)) if m else ("", line)
    t = f'<span style="color:#6B7684">{stamp}</span>&nbsp;&nbsp;' if stamp else ""
    m = _TXL.match(body)
    if m:
        tag = m.group(1)
        color = "#5AA9FF" if tag == "TX" else "#E3A33B"
        label = "TX" if tag == "TX" else escape(tag.replace(" TX", "").upper()[:5]) + " TX"
        return "tx", tag_id(m.group(3)), (f'{t}<b style="color:{color}">{label}</b>&nbsp;&nbsp;'
                                          f'<span style="color:#7B8794">{escape(m.group(3))} \u00b7 FC{int(m.group(4)):02d}</span>'
                                          f'&nbsp;&nbsp;{escape(m.group(2))}')
    m = _RXL.match(body)
    if m:
        return "rx", tag_id(m.group(2)), (f'{t}<b style="color:#4CC38A">RX</b>&nbsp;&nbsp;'
                                          f'<span style="color:#7B8794">{escape(m.group(2))} \u00b7 FC{int(m.group(3)):02d}</span>'
                                          f'&nbsp;&nbsp;{escape(m.group(1))}')
    m = _TOL.match(body)
    if m:
        return "err", tag_id(m.group(2)), (f'{t}<b style="color:#F07167">TO</b>&nbsp;&nbsp;'
                                           f'<span style="color:#7B8794">{escape(m.group(2))}</span>'
                                           f'&nbsp;&nbsp;no reply after {m.group(1)} ms')
    lower = body.lower()
    bad = bool(re.search(r"communication error|failed|port lost|no longer available|exception|timeout \(", lower))
    s = _SLV.search(body)
    color = "#F07167" if bad else "#9AA4B1"
    return ("err" if bad else "info"), (int(s.group(1)) if s else None), \
        f'{t}<span style="color:{color}">{escape(body)}</span>'


class TrafficConsole(QFrame):
    record_clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("lcConsole")
        tss(self, BASE_QSS + """
            QFrame#lcConsole { background:@console_bar; border:0; border-top:1px solid @border; }
            QPlainTextEdit { background:@console; color:#C9D1DA; border:0;
                font-family:Consolas,'Cascadia Mono',monospace; font-size:12px; padding:6px 18px; }
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        bar = QHBoxLayout()
        bar.setContentsMargins(24, 6, 24, 6)
        bar.setSpacing(10)
        title = QLabel("Traffic")
        tss(title, "color:@text; font-size:12px; font-weight:600;")
        bar.addWidget(title)
        self.filter = Segmented((("all", "All"), ("tx", "TX"), ("rx", "RX"), ("err", "Errors"), ("dev", "This device")), "all")
        self.filter.changed.connect(lambda _k: self._rebuild())
        bar.addWidget(self.filter)
        bar.addStretch(1)
        self.record_btn = QPushButton("\u25cf  Record log")
        self.clear_btn = QPushButton("Clear")
        self.expand_btn = QPushButton("\u2303  Expand")
        for b in (self.record_btn, self.clear_btn, self.expand_btn):
            b.setObjectName("lcGhost")
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            bar.addWidget(b)
        self.record_btn.clicked.connect(self.record_clicked.emit)
        self.clear_btn.clicked.connect(self.clear)
        self.expand_btn.clicked.connect(self.toggle_expand)
        lay.addLayout(bar)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(1500)
        self.view.setLineWrapMode(QPlainTextEdit.NoWrap)
        lay.addWidget(self.view, 1)
        self._entries = []
        self._errors = 0
        self.device = None
        self.expanded = False
        self.retheme()

    def retheme(self):
        self.setFixedHeight(px(420 if self.expanded else 176))

    def toggle_expand(self):
        self.expanded = not self.expanded
        self.expand_btn.setText("\u2304  Collapse" if self.expanded else "\u2303  Expand")
        self.retheme()

    def set_recording(self, on):
        text = "\u25a0  Stop log" if on else "\u25cf  Record log"
        if self.record_btn.text() != text:
            self.record_btn.setText(text)

    def set_device(self, sid):
        self.device = sid
        if self.filter.current == "dev":
            self._rebuild()

    def _keep(self, kind, slave):
        f = self.filter.current
        return (f == "all" or (f == "tx" and kind == "tx") or (f == "rx" and kind == "rx")
                or (f == "err" and kind == "err") or (f == "dev" and slave is not None and slave == self.device))

    def append(self, lines):
        if not lines:
            return
        out = []
        for line in lines:
            entry = parse_line(line)
            self._entries.append(entry)
            if entry[0] == "err":
                self._errors += 1
            if self._keep(entry[0], entry[1]):
                out.append(entry[2])
        del self._entries[:-3000]
        self.filter.buttons["err"].setText(f"Errors \u00b7 {self._errors}" if self._errors else "Errors")
        if out:
            bar = self.view.verticalScrollBar()
            at_end = bar.value() >= bar.maximum() - 4
            self.view.setUpdatesEnabled(False)
            for h in out:
                self.view.appendHtml(f'<div style="white-space:pre">{h}</div>')
            self.view.setUpdatesEnabled(True)
            if at_end:
                bar.setValue(bar.maximum())

    def _rebuild(self):
        self.view.clear()
        shown = [h for kind, slave, h in self._entries if self._keep(kind, slave)][-1500:]
        self.view.setUpdatesEnabled(False)
        for h in shown:
            self.view.appendHtml(f'<div style="white-space:pre">{h}</div>')
        self.view.setUpdatesEnabled(True)
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())

    def clear(self):
        self._entries = []
        self._errors = 0
        self.filter.buttons["err"].setText("Errors")
        self.view.clear()

    def lines_for(self, sid, limit=300):
        return [h for kind, slave, h in self._entries if slave == sid][-limit:]


# --------------------------------------------------------------------------- page
class LivePage(QWidget):
    """Stats card + device list + detail panel + traffic console."""
    def __init__(self):
        super().__init__()
        self.setObjectName("lcPage")
        tss(self, BASE_QSS + "QWidget#lcPage { background:@bg; }")
        self.setAttribute(Qt.WA_StyledBackground, True)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(24, 20, 24, 16)
        il.setSpacing(16)
        self.stats = StatsCard()
        il.addWidget(self.stats)
        work = QHBoxLayout()
        work.setSpacing(16)
        self.devices = DeviceList()
        self.detail = DetailPanel()
        work.addWidget(self.devices)
        work.addWidget(self.detail, 1)
        il.addLayout(work, 1)
        root.addWidget(inner, 1)
        self.console = TrafficConsole()
        root.addWidget(self.console)
        self.retheme()

    def retheme(self):
        self.devices.setFixedWidth(px(400))