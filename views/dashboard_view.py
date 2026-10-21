"""Dashboard tab for the Multi Device screen (Phase 5b).

Live values come from the scanner (device dicts owned by the view); history,
statistics, alarm-per-hour and "last saved" values come from MongoDB through
one background job every 10 s. Nothing here blocks the GUI thread.
Everything is painted with QPainter, in the Utility Suite's light theme.
"""
import math
import time
from collections import deque
from datetime import datetime, timedelta

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import QPainter, QPen, QColor, QFont, QLinearGradient, QBrush
from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox,
    QCheckBox, QScrollArea, QProgressBar, QSizePolicy, QAbstractItemView,
)

try:
    from .history_views import (_panel, _table, _item, _DeviceCombo, TrendChart, run_async,
                                _error_text, SERIES_COLORS, CHANNELS_BY_KIND)
    from .db_history import dashboard_snapshot
    from .alarm_engine import HIGH, LOW, OFFLINE, RAISED, CLEARED, ACKNOWLEDGED
except ImportError:
    from history_views import (_panel, _table, _item, _DeviceCombo, TrendChart, run_async,
                               _error_text, SERIES_COLORS, CHANNELS_BY_KIND)
    from db_history import dashboard_snapshot
    from alarm_engine import HIGH, LOW, OFFLINE, RAISED, CLEARED, ACKNOWLEDGED

BLUE, TEAL, GREEN, RED = "#168CF0", "#12B8C5", "#12A45B", "#E53935"
AMBER, VIOLET, NAVY, MUTED, TRACK = "#E39A00", "#7D46C7", "#07528A", "#7893A8", "#E6EFF7"
DB_REFRESH_MS = 10000
FONT = "Segoe UI"

# input-type name (from the module's I/P-type register) -> gauge scale
AI_RANGES = {
    "0-50mV": (0, 50), "0-100mV": (0, 100), "0-250mV": (0, 250), "0-5V": (0, 5), "0-10V": (0, 10),
    "4-20mA": (4, 20), "0-20mA": (0, 20), "-250mV to +250mV": (-250, 250), "-10V to +10V": (-10, 10),
}
UNIT_RANGES = {"mA": (0, 20), "V": (0, 10), "mV": (0, 250)}
STATUS_STYLE = {   # status -> (background, text)
    "ONLINE": ("#E8F8EF", GREEN), "RETRYING": ("#FFF7E7", "#D88B00"), "OFFLINE": ("#FFF0F0", RED),
    "NOT POLLED": ("#EEF2F5", "#5C7A92"), "SAVED DATA": ("#EAF3FC", BLUE),
}


def _font(size, bold=False):
    font = QFont(FONT)
    font.setPixelSize(int(size))
    font.setBold(bold)
    return font


def _label(text="", style="", wrap=False):
    label = QLabel(text)
    label.setStyleSheet(style + "background:transparent;")
    label.setWordWrap(wrap)
    return label


def _pill_style(kind):
    background, color = {"green": ("#E8F8EF", GREEN), "red": ("#FFF0F0", RED), "amber": ("#FFF7E7", "#D88B00"),
                         "blue": ("#EAF3FC", BLUE), "grey": ("#EEF2F5", "#5C7A92")}[kind]
    return f"background:{background};color:{color};border-radius:5px;padding:4px 10px;font-size:10px;font-weight:700;"


# ---------------------------------------------------------------- small painted widgets
class Spark(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(100, 32)
        self._values = []
        self._color = QColor(BLUE)

    def set_values(self, values, color):
        values = list(values)
        if values != self._values or QColor(color) != self._color:
            self._values, self._color = values, QColor(color)
            self.update()

    def paintEvent(self, event):
        if len(self._values) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        lo, hi = min(self._values), max(self._values)
        span = (hi - lo) or 1.0
        step = (self.width() - 2) / (len(self._values) - 1)
        points = [QPointF(1 + i * step, self.height() - 3 - (v - lo) / span * (self.height() - 7))
                  for i, v in enumerate(self._values)]
        fill = QColor(self._color)
        fill.setAlpha(40)
        polygon = [QPointF(1, self.height())] + points + [QPointF(self.width() - 1, self.height())]
        from PySide6.QtGui import QPolygonF
        painter.setPen(Qt.NoPen)
        painter.setBrush(fill)
        painter.drawPolygon(QPolygonF(polygon))
        painter.setPen(QPen(self._color, 1.7))
        painter.setBrush(Qt.NoBrush)
        for a, b in zip(points, points[1:]):
            painter.drawLine(a, b)


class KpiCard(QFrame):
    def __init__(self, title, spark=False, parent=None):
        super().__init__(parent)
        self.setObjectName("kpi")
        self.setMinimumHeight(92)
        self._accent = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 9, 12, 9)
        layout.setSpacing(0)
        layout.addWidget(_label(title.upper(), f"color:{MUTED};font-size:9px;font-weight:700;letter-spacing:1px;"))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.value = QLabel("--")
        row.addWidget(self.value)
        row.addStretch()
        self.spark = Spark() if spark else None
        if self.spark:
            row.addWidget(self.spark, 0, Qt.AlignBottom)
        layout.addLayout(row)
        self.sub = _label("", f"color:{MUTED};font-size:10px;")
        layout.addWidget(self.sub)

    def set(self, value, sub="", accent=BLUE, spark=None, unit=""):
        if accent != self._accent:
            self._accent = accent
            self.setStyleSheet(f"QFrame#kpi{{background:#FFFFFF;border:1px solid #CFE2F0;"
                               f"border-left:4px solid {accent};border-radius:9px;}}")
            self.value.setStyleSheet(f"color:{accent};font-size:28px;font-weight:700;background:transparent;")
        text = f"{value}<span style='font-size:13px;color:{MUTED}'> {unit}</span>" if unit else str(value)
        if self.value.text() != text:
            self.value.setText(text)
        if self.sub.text() != sub:
            self.sub.setText(sub)
        if self.spark is not None and spark is not None:
            self.spark.set_values(spark, accent)


class GaugeWidget(QWidget):
    """270 degree ring gauge: value arc, tick marks, limit ring and a knob."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(118, 132)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._state = None

    def set_state(self, name, value, unit, vmin, vmax, lo, hi, mode):
        state = (name, None if value is None else round(value, 3), unit, vmin, vmax, lo, hi, mode)
        if state != self._state:
            self._state = state
            self.update()

    @staticmethod
    def _xy(cx, cy, radius, deg):
        rad = math.radians(deg)
        return cx + radius * math.cos(rad), cy - radius * math.sin(rad)

    def paintEvent(self, event):
        if self._state is None:
            return
        name, value, unit, vmin, vmax, lo, hi, mode = self._state
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width, height = self.width(), self.height()
        pen_w = max(6.0, min(width, height) * 0.085)
        radius = min(width / 2, height / 2) - pen_w / 2 - 11
        cx, cy = width / 2, height / 2 - 2
        rect = QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius)
        span = (vmax - vmin) or 1.0

        def fraction(v):
            return max(0.0, min(1.0, (v - vmin) / span))

        def arc(pen, f0, f1, ring=0.0):
            r = QRectF(rect.adjusted(-ring, -ring, ring, ring))
            painter.setPen(pen)
            painter.drawArc(r, int((225 - 270 * f0) * 16), int(-270 * (f1 - f0) * 16))

        # limit ring (outside)
        if lo is not None and hi is not None:
            ring = pen_w / 2 + 5
            fl, fh = fraction(lo), fraction(hi)
            bad = QPen(QColor("#F4A7A5"), 2.6)
            ok = QPen(QColor("#8FDDB4"), 2.6)
            if fl > 0:
                arc(bad, 0, fl, ring)
            arc(ok, fl, fh, ring)
            if fh < 1:
                arc(bad, fh, 1, ring)
        # track
        track = QPen(QColor(TRACK), pen_w)
        track.setCapStyle(Qt.RoundCap)
        arc(track, 0, 1)
        # ticks
        painter.setPen(QPen(QColor("#C4D6E6"), 1.1))
        for i in range(11):
            deg = 225 - 270 * i / 10
            x0, y0 = self._xy(cx, cy, radius - pen_w / 2 - 3, deg)
            x1, y1 = self._xy(cx, cy, radius - pen_w / 2 - 7, deg)
            painter.drawLine(QPointF(x0, y0), QPointF(x1, y1))
        # value arc + knob
        if value is not None and mode != "none":
            f = max(0.004, fraction(value))
            if mode == "alarm":
                colors = (AMBER, RED)
            elif mode == "stale":
                colors = ("#B7CCE0", "#8FA9C4")
            else:
                colors = (TEAL, BLUE)
            gradient = QLinearGradient(cx - radius, cy + radius, cx + radius, cy - radius)
            gradient.setColorAt(0, QColor(colors[0]))
            gradient.setColorAt(1, QColor(colors[1]))
            pen = QPen(QBrush(gradient), pen_w)
            pen.setCapStyle(Qt.RoundCap)
            arc(pen, 0, f)
            kx, ky = self._xy(cx, cy, radius, 225 - 270 * f)
            painter.setBrush(QColor("#FFFFFF"))
            painter.setPen(QPen(QColor(colors[1]), 2.2))
            painter.drawEllipse(QPointF(kx, ky), pen_w * 0.36, pen_w * 0.36)
        # texts
        shown = "--" if value is None or mode == "none" else f"{value:.2f}"
        color = {"alarm": RED, "stale": "#6F8AA6", "none": "#B5C6D6"}.get(mode, NAVY)
        painter.setPen(QColor(color))
        painter.setFont(_font(max(12, radius * 0.40), True))
        painter.drawText(QRectF(cx - radius, cy - radius * 0.38, 2 * radius, radius * 0.5), Qt.AlignCenter, shown)
        painter.setPen(QColor(MUTED))
        painter.setFont(_font(max(8, radius * 0.17), True))
        painter.drawText(QRectF(cx - radius, cy + radius * 0.08, 2 * radius, radius * 0.3), Qt.AlignCenter, unit)
        painter.setPen(QColor("#5C7A92"))
        painter.setFont(_font(max(9, radius * 0.19), True))
        painter.drawText(QRectF(cx - radius, cy + radius * 0.62, 2 * radius, radius * 0.36), Qt.AlignCenter, name)


class DonutWidget(QWidget):
    COLORS = ((HIGH, RED), (LOW, AMBER), (OFFLINE, VIOLET))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(132, 132)
        self._counts = None

    def set_counts(self, counts):
        if counts != self._counts:
            self._counts = dict(counts)
            self.update()

    def paintEvent(self, event):
        if self._counts is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(14, 14, self.width() - 28, self.height() - 28)
        total = sum(self._counts.values())
        track = QPen(QColor(GREEN if total == 0 else TRACK), 12)
        painter.setPen(track)
        painter.drawArc(rect, 0, 360 * 16)
        start = 90.0
        if total:
            for key, color in self.COLORS:
                count = self._counts.get(key, 0)
                if not count:
                    continue
                sweep = 360.0 * count / total
                pen = QPen(QColor(color), 12)
                pen.setCapStyle(Qt.FlatCap)
                painter.setPen(pen)
                painter.drawArc(rect, int(start * 16), int(-(sweep - (3 if len(self._counts) > 1 else 0)) * 16))
                start -= sweep
        painter.setPen(QColor(NAVY if total == 0 else RED))
        painter.setFont(_font(30, True))
        painter.drawText(QRectF(0, 36, self.width(), 40), Qt.AlignCenter, str(total))
        painter.setPen(QColor(GREEN if total == 0 else MUTED))
        painter.setFont(_font(9, True))
        painter.drawText(QRectF(0, 76, self.width(), 16), Qt.AlignCenter, "ALL CLEAR" if total == 0 else "ACTIVE")


class BarChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(170)
        self._values = []
        self._labels = []
        self._message = "Loading..."

    def set_data(self, values, labels, message=""):
        self._values, self._labels, self._message = list(values), list(labels), message
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width, height = self.width(), self.height()
        if not self._values or sum(self._values) == 0:
            painter.setPen(QColor(GREEN if self._values else MUTED))
            painter.setFont(_font(12, True))
            painter.drawText(QRectF(0, 0, width, height), Qt.AlignCenter,
                             self._message or "No alarms in the last 24 hours")
            return
        left, bottom, top = 30, 24, 10
        plot_h = height - bottom - top
        top_value = max(3, math.ceil(max(self._values) / 3) * 3)   # whole-number gridlines
        painter.setFont(_font(9))
        for step in range(4):
            y = top + plot_h * step / 3
            painter.setPen(QPen(QColor("#E4EEF5"), 1))
            painter.drawLine(QPointF(left, y), QPointF(width - 6, y))
            painter.setPen(QColor(MUTED))
            painter.drawText(QRectF(0, y - 8, left - 6, 16), Qt.AlignRight | Qt.AlignVCenter,
                             f"{top_value * (3 - step) / 3:.0f}")
        count = len(self._values)
        slot = (width - left - 6) / count
        bar_w = max(4.0, slot * 0.62)
        for i, value in enumerate(self._values):
            x = left + i * slot + (slot - bar_w) / 2
            h = max(3.0, value / top_value * plot_h) if value else 3.0
            rect = QRectF(x, top + plot_h - h, bar_w, h)
            if value:
                gradient = QLinearGradient(0, rect.top(), 0, rect.bottom())
                gradient.setColorAt(0, QColor(RED))
                gradient.setColorAt(1, QColor("#F4A7A5"))
                painter.setBrush(QBrush(gradient))
            else:
                painter.setBrush(QColor(TRACK))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 3, 3)
            if i % 4 == 0 and i < len(self._labels):
                painter.setPen(QColor(MUTED))
                painter.drawText(QRectF(x - 14, height - bottom + 5, bar_w + 28, 14), Qt.AlignCenter, self._labels[i])


class Led(QWidget):
    def __init__(self, number, parent=None):
        super().__init__(parent)
        self.setMinimumSize(26, 40)
        self._number = number
        self._state = None

    def set_state(self, state):
        if state != self._state:
            self._state = state
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        cx, cy, r = self.width() / 2, 13, 9
        if self._state == 1:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#DDF5E8"))
            painter.drawEllipse(QPointF(cx, cy), r + 3.5, r + 3.5)
            gradient = QLinearGradient(cx - r, cy - r, cx + r, cy + r)
            gradient.setColorAt(0, QColor("#7FE3AE"))
            gradient.setColorAt(1, QColor(GREEN))
            painter.setBrush(QBrush(gradient))
            painter.setPen(QPen(QColor("#0E8A4C"), 1))
        else:
            painter.setBrush(QColor("#E3ECF3" if self._state == 0 else "#F1F5F9"))
            painter.setPen(QPen(QColor("#CFDDE9"), 1))
        painter.drawEllipse(QPointF(cx, cy), r, r)
        painter.setPen(QColor(MUTED))
        painter.setFont(_font(9, True))
        painter.drawText(QRectF(0, 26, self.width(), 14), Qt.AlignCenter, str(self._number))


class _SectionHeader(QWidget):
    """Device name, slave info, status pill and a right-aligned footer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 4, 0, 2)
        row.setSpacing(8)
        self.name = _label("", f"color:{NAVY};font-size:12px;font-weight:700;")
        self.info = _label("", f"color:{MUTED};font-size:10px;font-weight:600;")
        self.pill = QLabel()
        self.footer = QLabel()
        row.addWidget(self.name)
        row.addWidget(self.info)
        row.addWidget(self.pill)
        row.addStretch()
        row.addWidget(self.footer)
        self._pill_text = None

    def update_info(self, name, info, status, footer):
        self.name.setText(name)
        self.info.setText(info)
        if status != self._pill_text:
            self._pill_text = status
            background, color = STATUS_STYLE.get(status, STATUS_STYLE["NOT POLLED"])
            self.pill.setText(status)
            self.pill.setStyleSheet(f"background:{background};color:{color};border-radius:5px;"
                                    f"padding:2px 8px;font-size:9px;font-weight:700;")
        self.footer.setText(footer)
        self.footer.setStyleSheet("background:#EEF2F5;color:#5C7A92;border-radius:5px;padding:2px 8px;"
                                  "font-size:9px;font-weight:700;")


class GaugeSection(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.header = _SectionHeader()
        layout.addWidget(self.header)
        grid = QGridLayout()
        grid.setSpacing(2)
        self.gauges = []
        for index in range(8):
            gauge = GaugeWidget()
            self.gauges.append(gauge)
            grid.addWidget(gauge, 0, index)
        layout.addLayout(grid)


class LedSection(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.header = _SectionHeader()
        layout.addWidget(self.header)
        grid = QGridLayout()
        grid.setHorizontalSpacing(4)
        self.leds = []
        for index in range(16):
            led = Led(index + 1)
            self.leds.append(led)
            grid.addWidget(led, 0, index)
        layout.addLayout(grid)


# ---------------------------------------------------------------- dashboard tab
class DashboardTab(QWidget):
    WINDOWS = (("Last 5 minutes", 300), ("Last 15 minutes", 900), ("Last hour", 3600),
               ("Last 6 hours", 21600), ("Last 24 hours", 86400))

    def __init__(self, engine, get_devices, get_stats, get_runtime, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._get_devices = get_devices
        self._get_stats = get_stats
        self._get_runtime = get_runtime
        self._latest = {}
        self._stored = []
        self._events = []
        self._trend_docs = []
        self._trend_range = (datetime.now() - timedelta(hours=1), datetime.now())
        self._db_error = ""
        self._db_ok = None
        self._busy = False
        self._again = False
        self._fetch_target = None
        self._resp_all = deque(maxlen=200)
        self._resp = {}
        self._uptime = {}
        self._spark = {key: deque(maxlen=60) for key in ("online", "alarms", "success", "resp", "timeouts", "saved")}
        self._spark_acc = 0.0
        self._last = time.monotonic()
        self._ai_sig = self._io_sig = None
        self._ai_sections = []
        self._io_sections = []
        self._health_rows = -1
        self._events_sig = None
        self._build()
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._db_timer = QTimer(self)
        self._db_timer.setInterval(DB_REFRESH_MS)
        self._db_timer.timeout.connect(self.fetch)

    # ------------------------------------------------------------ build
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(8, 6, 8, 12)
        root.setSpacing(8)

        # title bar
        bar = QHBoxLayout()
        bar.addWidget(_label("Plant Overview", f"color:{NAVY};font-size:15px;font-weight:700;"))
        bar.addStretch()
        self.pill_conn, self.pill_db, self.pill_session, self.pill_clock = QLabel(), QLabel(), QLabel(), QLabel()
        for pill in (self.pill_conn, self.pill_db, self.pill_session, self.pill_clock):
            bar.addWidget(pill)
        root.addLayout(bar)

        # KPI cards
        grid = QGridLayout()
        grid.setSpacing(8)
        self.k_online = KpiCard("Devices Online", spark=True)
        self.k_offline = KpiCard("Devices Offline")
        self.k_alarms = KpiCard("Active Alarms", spark=True)
        self.k_success = KpiCard("Success Rate", spark=True)
        self.k_resp = KpiCard("Avg Response", spark=True)
        self.k_tx = KpiCard("Total Requests")
        self.k_timeouts = KpiCard("Timeouts", spark=True)
        self.k_retries = KpiCard("Retries")
        self.k_saved = KpiCard("Records Saved", spark=True)
        self.k_db = KpiCard("Database")
        cards = (self.k_online, self.k_offline, self.k_alarms, self.k_success, self.k_resp,
                 self.k_tx, self.k_timeouts, self.k_retries, self.k_saved, self.k_db)
        for index, card in enumerate(cards):
            grid.addWidget(card, index // 5, index % 5)
        for column in range(5):
            grid.setColumnStretch(column, 1)
        root.addLayout(grid)

        # row 1: gauges | alarms + health
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        ai_panel, ai_body = _panel("Analog Inputs")
        self.ai_layout = QVBoxLayout()
        self.ai_layout.setSpacing(4)
        ai_body.addLayout(self.ai_layout)
        ai_body.addStretch()
        row1.addWidget(ai_panel, 155)
        right = QVBoxLayout()
        right.setSpacing(8)
        alarm_panel, alarm_body = _panel("Alarm Summary")
        top = QHBoxLayout()
        self.donut = DonutWidget()
        top.addWidget(self.donut)
        legend = QVBoxLayout()
        self.legend = {}
        for key, color in DonutWidget.COLORS:
            line = QHBoxLayout()
            dot = QLabel()
            dot.setFixedSize(10, 10)
            dot.setStyleSheet(f"background:{color};border-radius:3px;")
            count = _label("0", f"color:{NAVY};font-size:15px;font-weight:700;")
            line.addWidget(dot)
            line.addWidget(_label(key, f"color:{'#123B61'};font-size:12px;font-weight:600;"))
            line.addStretch()
            line.addWidget(count)
            self.legend[key] = count
            legend.addLayout(line)
        self.unacked_label = _label("", f"color:{RED};font-size:10px;font-weight:700;")
        legend.addWidget(self.unacked_label)
        top.addLayout(legend, 1)
        alarm_body.addLayout(top)
        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet("color:#E8F0F5;")
        alarm_body.addWidget(divider)
        self.event_rows = [QLabel() for _ in range(5)]
        for row in self.event_rows:
            row.setTextFormat(Qt.RichText)
            row.setStyleSheet("background:transparent;")
            alarm_body.addWidget(row)
        right.addWidget(alarm_panel)
        health_panel, health_body = _panel("Device Health")
        self.health = _table(["Device", "Status", "Uptime", "Resp"], [130, 90, 170, 70])
        self.health.setSelectionMode(QAbstractItemView.NoSelection)
        health_body.addWidget(self.health)
        right.addWidget(health_panel)
        row1.addLayout(right, 100)
        root.addLayout(row1)

        # row 2: trend | statistics
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        trend_panel, trend_body = _panel("Trend")
        controls = QHBoxLayout()
        self.trend_device = _DeviceCombo(kinds=("AI",))
        self.trend_device.setMinimumWidth(230)
        self.window = QComboBox()
        for text, seconds in self.WINDOWS:
            self.window.addItem(text, seconds)
        self.window.setCurrentIndex(2)
        controls.addWidget(self.trend_device)
        controls.addWidget(self.window)
        controls.addSpacing(8)
        self.channel_boxes = []
        for index in range(8):
            box = QCheckBox(f"AI{index + 1}")
            box.setChecked(index < 4)
            box.setStyleSheet(f"QCheckBox{{color:#123B61;font-size:10px;font-weight:600;}}")
            box.toggled.connect(self._render_trend)
            self.channel_boxes.append(box)
            controls.addWidget(box)
        controls.addStretch()
        trend_body.addLayout(controls)
        self.trend_status = _label("", f"color:{MUTED};font-size:10px;")
        trend_body.addWidget(self.trend_status)
        self.chart = TrendChart()
        self.chart.setMinimumHeight(250)
        trend_body.addWidget(self.chart, 1)
        row2.addWidget(trend_panel, 155)
        stats_panel, stats_body = _panel("Channel Statistics")
        self.stats_title = _label("", f"color:{MUTED};font-size:10px;")
        stats_body.addWidget(self.stats_title)
        self.stats = _table(["Channel", "Min", "Max", "Avg", "Last"], [80, 70, 70, 70])
        self.stats.setSelectionMode(QAbstractItemView.NoSelection)
        stats_body.addWidget(self.stats, 1)
        row2.addWidget(stats_panel, 100)
        root.addLayout(row2)

        # row 3: digital IO | alarms per hour
        row3 = QHBoxLayout()
        row3.setSpacing(8)
        io_panel, io_body = _panel("Digital I/O")
        self.io_layout = QVBoxLayout()
        self.io_layout.setSpacing(6)
        io_body.addLayout(self.io_layout)
        io_body.addStretch()
        row3.addWidget(io_panel, 155)
        bars_panel, bars_body = _panel("Alarms per Hour (last 24 h)")
        self.bars = BarChart()
        bars_body.addWidget(self.bars, 1)
        row3.addWidget(bars_panel, 100)
        root.addLayout(row3)
        root.addStretch()

        self.window.currentIndexChanged.connect(lambda _i: self.fetch())
        self.trend_device.currentIndexChanged.connect(lambda _i: self.fetch())

    # ------------------------------------------------------------ public hooks
    def set_devices(self, devices):
        self.trend_device.set_devices(devices)

    def on_response(self, slave_id, elapsed_ms):
        self._resp_all.append(float(elapsed_ms))
        self._resp.setdefault(slave_id, deque(maxlen=50)).append(float(elapsed_ms))

    def reset_session(self):
        self._uptime.clear()
        self._resp.clear()
        self._resp_all.clear()
        for series in self._spark.values():
            series.clear()

    def showEvent(self, event):
        super().showEvent(event)
        self.fetch()
        self._db_timer.start()
        self._refresh_live()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._db_timer.stop()

    # ------------------------------------------------------------ database job
    def _trend_target(self):
        data = self.trend_device.currentData()
        return (data[0], data[1]) if data else None

    def fetch(self):
        if self._busy:
            self._again = True
            return
        self._busy = True
        target = self._trend_target()
        self._fetch_target = target
        now = datetime.now()
        start = now - timedelta(seconds=self.window.currentData())
        self._trend_range = (start, now)
        run_async(self, lambda: dashboard_snapshot(target, start, now, now), self._fetched)

    def _fetched(self, result, error):
        self._busy = False
        if error is not None:
            self._db_error = _error_text(error)
            self._db_ok = False
        else:
            self._db_error, self._db_ok = "", True
            self._stored = result["stored"]
            self._latest = result["latest"]
            self._events = result["events"]
            self._trend_docs = result["trend"]
            self.trend_device.set_stored(self._stored)
            if self._trend_target() != self._fetch_target:
                self._again = True
        self._render_trend()
        self._render_stats()
        self._render_bars()
        self._events_sig = None
        self._refresh_live()
        if self._again:
            self._again = False
            self.fetch()

    # ------------------------------------------------------------ DB-backed renderers
    def _render_trend(self, *_):
        start, end = self._trend_range
        selected = [box.text() for box in self.channel_boxes if box.isChecked()]
        series = []
        for index, box in enumerate(self.channel_boxes):
            if not box.isChecked():
                continue
            times, values, unit = [], [], ""
            for doc in self._trend_docs:
                entry = doc.get("channels", {}).get(box.text())
                if entry is None or entry.get("value") is None:
                    continue
                times.append(doc["timestamp"].timestamp())
                values.append(entry["value"])
                unit = entry.get("unit", unit)
            series.append({"name": box.text(), "color": SERIES_COLORS[index % len(SERIES_COLORS)],
                           "times": times, "values": values, "unit": unit})
        message = f"Database error: {self._db_error}" if self._db_error else (
            "No device selected" if self._trend_target() is None else "No saved data in this window")
        self.chart.set_data(series, False, start.timestamp(), end.timestamp(), message)
        if self._db_error:
            self.trend_status.setText(f"Database error: {self._db_error}")
        elif self._trend_target() is None:
            self.trend_status.setText("Add or select an analog input device.")
        else:
            self.trend_status.setText(f"{len(self._trend_docs)} records from the database"
                                      f" · auto refresh {DB_REFRESH_MS // 1000} s")

    def _render_stats(self):
        table = self.stats
        docs = self._trend_docs
        channels = [f"AI{i + 1}" for i in range(CHANNELS_BY_KIND["AI"])]
        table.setRowCount(len(channels))
        self.stats_title.setText(f"{self.window.currentText()} · {len(docs)} records" if docs else "No data")
        for row, name in enumerate(channels):
            values, unit = [], ""
            for doc in docs:
                entry = doc.get("channels", {}).get(name)
                if entry and entry.get("value") is not None:
                    values.append(entry["value"])
                    unit = entry.get("unit", unit)
            cells = [f"{name} {unit}".strip()]
            if values:
                cells += [f"{min(values):.2f}", f"{max(values):.2f}", f"{sum(values) / len(values):.2f}", f"{values[-1]:.2f}"]
            else:
                cells += ["--"] * 4
            for column, text in enumerate(cells):
                table.setItem(row, column, _item(text, NAVY if column in (0, 4) else None,
                                                 Qt.AlignLeft if column == 0 else Qt.AlignCenter, bold=column in (0, 4)))

    def _render_bars(self):
        now = datetime.now()
        source = self._events if self._db_ok else [e for e in self.engine.history]
        counts = [0] * 24
        for event in source:
            if event.get("event") != RAISED:
                continue
            hours_ago = int((now - event["timestamp"]).total_seconds() // 3600)
            if 0 <= hours_ago < 24:
                counts[23 - hours_ago] += 1
        labels = [(now - timedelta(hours=23 - i)).strftime("%H:00") for i in range(24)]
        self.bars.set_data(counts, labels, "No alarms in the last 24 hours" if self._db_ok or not self._db_error else "Database not reachable")

    # ------------------------------------------------------------ live refresh
    def _tick(self):
        now = time.monotonic()
        dt = now - self._last
        self._last = now
        runtime = self._get_runtime()
        devices = self._get_devices()
        if runtime["connected"]:
            for device in devices:
                if device.get("enabled"):
                    entry = self._uptime.setdefault(device["slave_id"], [0.0, 0.0])
                    entry[1] += dt
                    if device.get("status") == "ONLINE":
                        entry[0] += dt
        self._spark_acc += dt
        if self._spark_acc >= 1.0:
            self._spark_acc = 0.0
            self._sample_sparks(devices)
        if self.isVisible():
            self._refresh_live()

    def _sample_sparks(self, devices):
        stats = self._get_stats()
        runtime = self._get_runtime()
        s = self._spark
        s["online"].append(sum(1 for d in devices if d.get("status") == "ONLINE"))
        s["alarms"].append(self.engine.counts()[0])
        if stats["tx"]:
            s["success"].append(100.0 * stats["successful"] / stats["tx"])
        if self._resp_all:
            s["resp"].append(sum(self._resp_all) / len(self._resp_all))
        s["timeouts"].append(stats["timeouts"])
        if runtime["db"]:
            s["saved"].append(runtime["db"]["saved"])

    def _refresh_live(self):
        devices = self._get_devices()
        runtime = self._get_runtime()
        stats = self._get_stats()
        self._update_header(runtime)
        self._update_kpis(devices, stats, runtime)
        self._update_ai(devices)
        self._update_io(devices)
        self._update_alarm_summary()
        self._update_health(devices)

    def _update_header(self, runtime):
        if runtime["connected"]:
            self.pill_conn.setText(f"●  {runtime['port']} CONNECTED · {runtime['baud']}")
            self.pill_conn.setStyleSheet(_pill_style("green"))
        else:
            self.pill_conn.setText("●  COM PORT DISCONNECTED")
            self.pill_conn.setStyleSheet(_pill_style("grey"))
        db_kind, db_text = self._db_state(runtime)
        self.pill_db.setText(f"●  DATABASE {db_text}")
        self.pill_db.setStyleSheet(_pill_style(db_kind))
        since = runtime.get("since")
        seconds = int((datetime.now() - since).total_seconds()) if since else 0
        self.pill_session.setText(f"SESSION {seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}")
        self.pill_session.setStyleSheet(_pill_style("grey"))
        self.pill_clock.setText(datetime.now().strftime("%d %b %Y · %H:%M:%S").upper())
        self.pill_clock.setStyleSheet(_pill_style("grey"))

    def _db_state(self, runtime):
        db = runtime.get("db")
        if db is not None:
            if db["connected"]:
                return "green", "ONLINE"
            if db["last_error"]:
                return "red", "OFFLINE"
        if self._db_ok is False:
            return "red", "ERROR"
        if self._db_ok:
            return "green", "ONLINE"
        return "grey", "CONNECTING"

    def _update_kpis(self, devices, stats, runtime):
        total = len(devices)
        online = [d for d in devices if d.get("status") == "ONLINE"]
        offline = [d for d in devices if d.get("status") == "OFFLINE"]
        spark = self._spark
        self.k_online.set(f"{len(online)}<span style='font-size:15px;color:{MUTED}'> / {total}</span>",
                          f"{len(offline)} offline" if offline else ("all polled devices healthy" if total else "no devices"),
                          GREEN if online or not total else MUTED, spark["online"])
        self.k_offline.set(len(offline), ", ".join(d["name"] for d in offline[:2]) if offline else "none",
                           RED if offline else "#9FB3C8")
        active, unacked = self.engine.counts()
        self.k_alarms.set(active, f"{unacked} unacknowledged" if active else "no active alarms",
                          RED if unacked else (AMBER if active else GREEN), spark["alarms"])
        tx = stats["tx"]
        rate = 100.0 * stats["successful"] / tx if tx else None
        self.k_success.set("--" if rate is None else f"{rate:.2f}", "RX ok / TX", BLUE, spark["success"],
                           unit="" if rate is None else "%")
        average = sum(self._resp_all) / len(self._resp_all) if self._resp_all else None
        self.k_resp.set("--" if average is None else f"{average:.0f}",
                        f"last {self._resp_all[-1]:.0f} ms" if self._resp_all else "no replies yet", VIOLET,
                        spark["resp"], unit="" if average is None else "ms")
        self.k_tx.set(f"{tx:,}", f"RX {stats['rx']:,} · ok {stats['successful']:,}", BLUE)
        pct = 100.0 * stats["timeouts"] / tx if tx else 0.0
        self.k_timeouts.set(stats["timeouts"], f"{pct:.2f} % of requests", AMBER, spark["timeouts"])
        self.k_retries.set(stats["retries"], f"errors {stats['errors']}", AMBER)
        db = runtime.get("db")
        if db is not None:
            self.k_saved.set(f"{db['saved']:,}", f"queued {db['queued']} · dropped {db['dropped']}", GREEN, spark["saved"])
        else:
            self.k_saved.set("--", "starts when polling begins", GREEN)
        kind, text = self._db_state(runtime)
        accent = {"green": GREEN, "red": RED, "grey": "#9FB3C8"}.get(kind, GREEN)
        sub = (self._db_error or (db or {}).get("last_error") or "")[:46] or "MongoDB Atlas · nelumbo_utility"
        self.k_db.set(text, sub, accent)

    # ---- sources / values
    def _sources(self, kinds):
        devices = [d for d in sorted(self._get_devices(), key=lambda d: d["slave_id"]) if d.get("kind") in kinds]
        sources = [{"sid": d["slave_id"], "kind": d["kind"], "name": d["name"], "device": d} for d in devices]
        if not self._get_devices():       # nothing configured (fresh start): show what the database has
            sources = [{"sid": sid, "kind": kind, "name": f"Slave {sid}", "device": None}
                       for sid, kind in self._stored if kind in kinds]
        return sources

    def _resolve(self, src):
        device = src["device"]
        if device is not None and device.get("status") in ("ONLINE", "RETRYING") and device.get("latest_data"):
            return {"mode": "live", "channels": list(device["latest_data"]),
                    "units": list(device.get("latest_units") or []), "ts": device.get("timestamp")}
        doc = self._latest.get((src["sid"], src["kind"]))
        if doc:
            entries = doc.get("channels", {})
            return {"mode": "stale", "channels": [(k, v.get("value")) for k, v in entries.items()],
                    "units": [v.get("unit", "") for v in entries.values()], "ts": doc.get("timestamp")}
        return {"mode": "none", "channels": [], "units": [], "ts": None}

    @staticmethod
    def _status_text(src, data):
        device = src["device"]
        status = device.get("status") if device else None
        if status in ("ONLINE", "RETRYING", "OFFLINE"):
            return status
        return "SAVED DATA" if data["mode"] == "stale" else "NOT POLLED"

    @staticmethod
    def _footer(data):
        ts = data["ts"]
        if data["mode"] == "none" or ts is None:
            return "NO DATA YET"
        if data["mode"] == "live":
            age = max(0.0, (datetime.now() - ts).total_seconds())
            return f"UPDATED {age:.1f} s AGO" if age < 60 else f"UPDATED {age / 60:.0f} min AGO"
        return "LAST SAVED " + ts.strftime("%d %b %H:%M:%S").upper()

    def _clear(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _update_ai(self, _devices):
        sources = self._sources(("AI",))
        signature = tuple((s["sid"], s["name"]) for s in sources)
        if signature != self._ai_sig:
            self._ai_sig = signature
            self._clear(self.ai_layout)
            self._ai_sections = []
            if not sources:
                self.ai_layout.addWidget(_label("No analog input devices. Add one on the Live tab, "
                                                "or connect to see saved data.", f"color:{MUTED};font-size:11px;padding:16px;"))
            for _src in sources:
                section = GaugeSection()
                self._ai_sections.append(section)
                self.ai_layout.addWidget(section)
        for src, section in zip(sources, self._ai_sections):
            data = self._resolve(src)
            device = src["device"] or {}
            types = device.get("ip_types") or []
            values = dict(data["channels"])
            for index in range(8):
                name = f"AI{index + 1}"
                value = values.get(name)
                unit = data["units"][index] if index < len(data["units"]) else ""
                vmin, vmax = AI_RANGES.get(types[index] if index < len(types) else "", UNIT_RANGES.get(unit, (0, 100)))
                limit = self.engine.limits.get((src["sid"], name))
                lo = hi = None
                if limit and limit.get("enabled"):
                    lo, hi = limit["low"], limit["high"]
                mode = data["mode"]
                if value is None:
                    mode = "none"
                elif mode == "live" and ((src["sid"], name, HIGH) in self.engine.active
                                         or (src["sid"], name, LOW) in self.engine.active):
                    mode = "alarm"
                section.gauges[index].set_state(name, value, unit, vmin, vmax, lo, hi, mode)
            kind_text = " · ".join(sorted({u for u in data["units"] if u})) or "AI"
            section.header.update_info(src["name"], f"Slave {src['sid']} · {kind_text}",
                                       self._status_text(src, data), self._footer(data))

    def _update_io(self, _devices):
        sources = self._sources(("DI", "DO"))
        signature = tuple((s["sid"], s["kind"], s["name"]) for s in sources)
        if signature != self._io_sig:
            self._io_sig = signature
            self._clear(self.io_layout)
            self._io_sections = []
            if not sources:
                self.io_layout.addWidget(_label("No digital input / output devices.", f"color:{MUTED};font-size:11px;padding:16px;"))
            for _src in sources:
                section = LedSection()
                self._io_sections.append(section)
                self.io_layout.addWidget(section)
        for src, section in zip(sources, self._io_sections):
            data = self._resolve(src)
            values = [v for _n, v in data["channels"]]
            for index, led in enumerate(section.leds):
                value = values[index] if index < len(values) and data["mode"] != "none" else None
                led.set_state(None if value is None else (1 if value else 0))
            section.header.update_info(src["name"], f"Slave {src['sid']} · {'INPUTS' if src['kind'] == 'DI' else 'OUTPUTS'}",
                                       self._status_text(src, data), self._footer(data))

    def _update_alarm_summary(self):
        counts = {HIGH: 0, LOW: 0, OFFLINE: 0}
        for alarm in self.engine.active.values():
            counts[alarm["type"]] += 1
        self.donut.set_counts(counts)
        for key, label in self.legend.items():
            label.setText(str(counts[key]))
        total, unacked = self.engine.counts()
        self.unacked_label.setText(f"{unacked} UNACKNOWLEDGED" if unacked else "")
        events = list(reversed(self.engine.history))[:5] or self._events[:5]
        signature = (self.engine.revision, len(self._events), id(self._events))
        if signature == self._events_sig:
            return
        self._events_sig = signature
        colors = {RAISED: RED, CLEARED: GREEN, ACKNOWLEDGED: AMBER}
        for index, row in enumerate(self.event_rows):
            if index >= len(events):
                row.setText(f"<span style='color:{MUTED};font-size:11px'>{'No alarm events yet' if index == 0 else ''}</span>")
                continue
            e = events[index]
            where = e["device"] + (f" {e['channel']}" if e.get("channel") else "")
            value = ""
            if e["type"] != OFFLINE and isinstance(e.get("value"), (int, float)):
                value = f" · {e['value']:.2f} {e.get('unit', '')}".rstrip()
            when = e["timestamp"].strftime("%H:%M:%S") if isinstance(e["timestamp"], datetime) else ""
            row.setText(
                f"<table width='100%'><tr><td width='14'><span style='color:{colors.get(e['event'], MUTED)}'>●</span></td>"
                f"<td style='color:#123B61;font-size:11px'>{e['event']} · {e['type']} · {where}{value}</td>"
                f"<td align='right' style='color:{MUTED};font-size:10px'>{when}</td></tr></table>")

    def _update_health(self, devices):
        devices = sorted(devices, key=lambda d: d["slave_id"])
        table = self.health
        if len(devices) != self._health_rows:
            self._health_rows = len(devices)
            table.setRowCount(len(devices))
            table.setFixedHeight(40 + 28 * max(1, len(devices)))
            for row in range(len(devices)):
                bar = QProgressBar()
                bar.setRange(0, 100)
                bar.setFixedHeight(14)
                bar.setStyleSheet("QProgressBar{border:0;border-radius:5px;background:#E6EFF7;color:#123B61;font-size:9px;"
                                  "font-weight:700;text-align:center;}QProgressBar::chunk{border-radius:5px;background:#168CF0;}")
                table.setCellWidget(row, 2, bar)
        for row, device in enumerate(devices):
            status = device.get("status", "NOT_POLLED").replace("_", " ")
            background, color = STATUS_STYLE.get(status, STATUS_STYLE["NOT POLLED"])
            table.setItem(row, 0, _item(device["name"], NAVY, Qt.AlignLeft, bold=True))
            table.setItem(row, 1, _item(status, color, bold=True))
            online, seen = self._uptime.get(device["slave_id"], (0.0, 0.0))
            bar = table.cellWidget(row, 2)
            percent = 100.0 * online / seen if seen > 0 else 0.0
            bar.setValue(int(percent))
            bar.setFormat(f"{percent:.1f}%" if seen > 0 else "--")
            resp = self._resp.get(device["slave_id"])
            table.setItem(row, 3, _item(f"{sum(resp) / len(resp):.0f} ms" if resp else "--"))
