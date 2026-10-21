"""History, Trends and Alarms tabs for the Multi Device screen (Phase 5).

Database access always runs in a worker thread (``run_async``), so the UI
never waits for MongoDB. Charts are drawn with QPainter (no extra libraries).
"""
import csv
from bisect import bisect_left
from datetime import datetime, timedelta

from PySide6.QtCore import (Qt, Signal, Slot, QObject, QRunnable, QThreadPool, QTimer,
                            QRectF, QPointF, QDateTime)
from PySide6.QtGui import QFontMetrics, QPainter, QPen, QColor, QPainterPath, QFont
from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
    QDateTimeEdit, QDoubleSpinBox, QFileDialog, QSplitter, QAbstractItemView,
)

try:
    from .db_history import (query_readings, query_alarm_events, load_limits, save_limits, diagnose, list_stored_devices)
except ImportError:
    from db_history import (query_readings, query_alarm_events, load_limits, save_limits, diagnose, list_stored_devices)

MAX_FETCH = 20000          # records fetched per query
MAX_TABLE_ROWS = 2000      # rows shown in the history table (newest first)
CHANNELS_BY_KIND = {"AI": 8, "DI": 16, "DO": 16, "AO": 4}
SERIES_COLORS = ["#168CF0", "#E5484D", "#12A45B", "#F5A300", "#7D46C7", "#0CAFC4", "#E05C97", "#6B7C8C"]
TIME_FMT = "%Y-%m-%d %H:%M:%S"

# The chart is painted by hand, so it follows light / dark here (Multi Device calls set_theme()).
_THEME = "light"
_DARK = {"#FFFFFF": "#161B22", "#D6E6F1": "#2C3541", "#E4EEF5": "#242C36", "#7893A8": "#8A9BAD",
         "#5C7A92": "#93A5B8", "#244D70": "#CBD8E6"}


def set_theme(name):
    global _THEME
    _THEME = "dark" if name == "dark" else "light"


def _tone(hex_):
    return QColor(_DARK.get(hex_.upper(), hex_) if _THEME == "dark" else hex_)


# ---------------------------------------------------------------- async helper
class _Bridge(QObject):
    done = Signal(object, object)

    def __init__(self, callback, parent):
        super().__init__(parent)
        self._callback = callback
        self.done.connect(self._on_done)

    @Slot(object, object)
    def _on_done(self, result, error):
        try:
            self._callback(result, error)
        finally:
            self.deleteLater()


class _Task(QRunnable):
    def __init__(self, function, bridge):
        super().__init__()
        self._function = function
        self._bridge = bridge

    def run(self):
        try:
            result, error = self._function(), None
        except Exception as exc:           # reported to the GUI thread
            result, error = None, exc
        self._bridge.done.emit(result, error)


def run_async(owner, function, callback):
    """Run function() in a worker thread; callback(result, error) runs in the GUI thread."""
    bridge = _Bridge(callback, owner)
    QThreadPool.globalInstance().start(_Task(function, bridge))


def _error_text(error):
    text = str(error).strip().splitlines()[0] if str(error).strip() else type(error).__name__
    return text[:140]


def explain_empty(owner, kind, slave_id, label):
    """Fill `label` with the reason a query returned nothing (runs in the background)."""
    def done(info, error):
        if error is not None:
            label.setText(f"Database error: {_error_text(error)}")
        elif info["device"] == 0:
            label.setText(f"No records saved yet for Slave {slave_id} in '{info['collection']}' "
                          f"({info['total']} records from all devices). Connect, press Run All, wait ~10 s "
                          f"and check the terminal for 'Database connected'.")
        else:
            label.setText(f"No records in this time range. Slave {slave_id} has {info['device']} records in "
                          f"'{info['collection']}', newest: {_fmt_time(info['newest'])} "
                          f"(now: {_fmt_time(datetime.now())}). Widen the range.")
    run_async(owner, lambda: diagnose(kind, slave_id), done)


# ---------------------------------------------------------------- small widgets
def _panel(title):
    frame = QFrame()
    frame.setObjectName("panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(8)
    label = QLabel(title)
    label.setObjectName("panelTitle")
    layout.addWidget(label)
    return frame, layout


def _table(headers, widths=None):
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.ExtendedSelection)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(28)
    table.horizontalHeader().setStretchLastSection(True)
    table.setShowGrid(False)
    for index, width in enumerate(widths or []):
        table.setColumnWidth(index, width)
    return table


def _item(text, color=None, align=Qt.AlignCenter, bold=False, background=None):
    item = QTableWidgetItem(str(text))
    item.setTextAlignment(align | Qt.AlignVCenter)
    if color:
        item.setForeground(QColor(color))
    if background:
        item.setBackground(QColor(background))
    if bold:
        font = item.font()
        font.setBold(True)
        item.setFont(font)
    return item


def _fmt_time(value):
    return value.strftime(TIME_FMT) if isinstance(value, datetime) else str(value)


def _fmt_value(value):
    return f"{value:.2f}" if isinstance(value, (int, float)) else "--"


class RangeSelector(QWidget):
    PRESETS = [("Last 5 minutes", 300), ("Last 15 minutes", 900), ("Last hour", 3600),
               ("Last 6 hours", 21600), ("Last 24 hours", 86400), ("Last 7 days", 604800),
               ("Custom", None)]

    def __init__(self, default_index=2, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.combo = QComboBox()
        for label, seconds in self.PRESETS:
            self.combo.addItem(label, seconds)
        self.combo.setCurrentIndex(default_index)
        self.start_edit = QDateTimeEdit()
        self.end_edit = QDateTimeEdit()
        for edit in (self.start_edit, self.end_edit):
            edit.setDisplayFormat("dd-MM-yyyy HH:mm:ss")
            edit.setCalendarPopup(True)
            edit.setMinimumHeight(28)
            edit.setEnabled(False)
        layout.addWidget(self.combo)
        layout.addWidget(self.start_edit)
        layout.addWidget(QLabel("to"))
        layout.addWidget(self.end_edit)
        self._never_set = True
        self.combo.currentIndexChanged.connect(self._preset_changed)
        self._preset_changed()

    def _preset_changed(self):
        seconds = self.combo.currentData()
        custom = seconds is None
        self.start_edit.setEnabled(custom)
        self.end_edit.setEnabled(custom)
        if not custom or not self.start_edit.dateTime().isValid() or self._never_set:
            end = datetime.now()
            self.end_edit.setDateTime(QDateTime(end))
            self.start_edit.setDateTime(QDateTime(end - timedelta(seconds=seconds or 3600)))
            self._never_set = False

    def range(self):
        seconds = self.combo.currentData()
        if seconds is None:
            return self.start_edit.dateTime().toPython(), self.end_edit.dateTime().toPython()
        end = datetime.now()
        return end - timedelta(seconds=seconds), end


class _DeviceCombo(QComboBox):
    """Configured devices plus devices that only exist in the database.
    Item data = (slave_id, kind, name)."""

    def __init__(self, parent=None, kinds=None):
        super().__init__(parent)
        self._devices = []
        self._stored = []
        self._kinds = kinds          # e.g. ("AI",) to list only those device types

    def set_devices(self, devices):
        self._devices = list(devices)
        self._populate()

    def set_stored(self, stored):
        self._stored = list(stored)
        self._populate()

    def _populate(self):
        current = self.currentData()
        self.blockSignals(True)
        self.clear()
        configured = set()
        for device in sorted(self._devices, key=lambda d: d["slave_id"]):
            kind = device.get("kind") or "?"
            if self._kinds and kind not in self._kinds:
                continue
            configured.add((device["slave_id"], device.get("kind")))
            self.addItem(f"{device['name']}  (Slave {device['slave_id']} · {kind})",
                         (device["slave_id"], device.get("kind"), device["name"]))
        for slave_id, kind in self._stored:
            if self._kinds and kind not in self._kinds:
                continue
            if (slave_id, kind) not in configured:
                self.addItem(f"Slave {slave_id} · {kind}  (saved data)",
                             (slave_id, kind, f"Slave{slave_id}_{kind}"))
        if current is not None:
            for index in range(self.count()):
                if self.itemData(index)[:2] == current[:2]:
                    self.setCurrentIndex(index)
                    break
        self.blockSignals(False)


def load_stored_devices(owner, combo, after=None):
    """Background query: add devices found in the database to `combo`."""
    def done(result, error):
        if error is None:
            combo.set_stored(result)
            if after:
                after()
    run_async(owner, list_stored_devices, done)


# ---------------------------------------------------------------- trend chart
class TrendChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(300)
        self.setMouseTracking(True)
        self._series = []
        self._digital = False
        self._t0 = 0.0
        self._t1 = 1.0
        self._message = "Press Refresh to load data"
        self._hover_x = None

    def set_data(self, series, digital, t0, t1, message=""):
        self._series = series
        self._digital = digital
        self._t0, self._t1 = float(t0), float(max(t1, t0 + 1))
        self._message = message
        self.update()

    # ---- geometry
    @staticmethod
    def _label(value):
        return f"{value:,.0f}" if abs(value) >= 1000 else f"{value:.2f}"

    def _left(self):
        """Left margin that always fits the widest Y-axis label (big raw values used to be cut off)."""
        shown = [s for s in self._series if s["times"]]
        if not shown:
            return 62
        if self._digital:
            names = [s["name"] for s in self._series]
            width = max(QFontMetrics(QFont("Segoe UI", 8)).horizontalAdvance(n) for n in names)
        else:
            low = min(min(s["values"]) for s in shown)
            high = max(max(s["values"]) for s in shown)
            fm = QFontMetrics(QFont("Segoe UI", 8))
            width = max(fm.horizontalAdvance(self._label(v)) for v in (low, high, low - abs(high - low) * 0.08,
                                                                       high + abs(high - low) * 0.08))
        return int(max(62, width + 18))

    def _plot(self):
        left = self._left()
        return QRectF(left, 12, max(10, self.width() - left - 16), max(10, self.height() - 12 - 34))

    def _x(self, t, rect):
        return rect.left() + (t - self._t0) / (self._t1 - self._t0) * rect.width()

    # ---- painting
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), _tone("#FFFFFF"))
        rect = self._plot()
        painter.setPen(QPen(_tone("#D6E6F1"), 1))
        painter.drawRect(rect)

        shown = [s for s in self._series if s["times"]]
        if not shown:
            painter.setPen(_tone("#7893A8"))
            painter.setFont(QFont("Segoe UI", 10))
            painter.drawText(rect, Qt.AlignCenter, self._message or "No data in the selected range")
            return

        if self._digital:
            lanes = len(self._series)
            ymin, ymax = 0.0, float(lanes)
        else:
            low = min(min(s["values"]) for s in shown)
            high = max(max(s["values"]) for s in shown)
            if high - low < 1e-9:
                low, high = low - 1.0, high + 1.0
            pad = (high - low) * 0.08
            ymin, ymax = low - pad, high + pad

        def y_of(value):
            return rect.bottom() - (value - ymin) / (ymax - ymin) * rect.height()

        small = QFont("Segoe UI", 8)
        painter.setFont(small)
        # horizontal grid + labels
        if self._digital:
            for lane, series in enumerate(self._series):
                painter.setPen(QPen(_tone("#E4EEF5"), 1))
                painter.drawLine(QPointF(rect.left(), y_of(lane)), QPointF(rect.right(), y_of(lane)))
                painter.setPen(QColor(series["color"]))
                painter.drawText(QRectF(2, y_of(lane + 0.9), rect.left() - 8, y_of(lane + 0.1) - y_of(lane + 0.9)),
                                 Qt.AlignRight | Qt.AlignVCenter, series["name"])
        else:
            for step in range(6):
                value = ymin + (ymax - ymin) * step / 5
                y = y_of(value)
                painter.setPen(QPen(_tone("#E4EEF5"), 1))
                painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
                painter.setPen(_tone("#5C7A92"))
                painter.drawText(QRectF(2, y - 8, rect.left() - 8, 16), Qt.AlignRight | Qt.AlignVCenter, self._label(value))
        # time grid + labels
        span = self._t1 - self._t0
        fmt = "%d %b %H:%M" if span > 86400 else ("%H:%M" if span > 21600 else "%H:%M:%S")
        for step in range(7):
            t = self._t0 + span * step / 6
            x = self._x(t, rect)
            painter.setPen(QPen(_tone("#E4EEF5"), 1))
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            painter.setPen(_tone("#5C7A92"))
            left = min(max(x - 50, 0), self.width() - 100)
            painter.drawText(QRectF(left, rect.bottom() + 4, 100, 16), Qt.AlignCenter,
                             datetime.fromtimestamp(t).strftime(fmt))

        # series
        painter.save()
        painter.setClipRect(rect.adjusted(-1, -1, 1, 1))
        for lane, series in enumerate(self._series):
            if not series["times"]:
                continue
            painter.setPen(QPen(QColor(series["color"]), 1.6))
            painter.setBrush(Qt.NoBrush)
            if self._digital:
                painter.drawPath(self._digital_path(series, lane, rect, y_of))
            else:
                painter.drawPath(self._analog_path(series, rect, y_of))
        painter.restore()

        # legend
        x = rect.left() + 8
        painter.setFont(small)
        for series in self._series:
            label = series["name"] + (f" ({series['unit']})" if series["unit"] else "")
            width = painter.fontMetrics().horizontalAdvance(label) + 24
            painter.fillRect(QRectF(x, rect.top() + 8, 10, 10), QColor(series["color"]))
            painter.setPen(_tone("#244D70"))
            painter.drawText(QRectF(x + 14, rect.top() + 4, width, 18), Qt.AlignLeft | Qt.AlignVCenter, label)
            x += width + 6
        self._paint_hover(painter, rect, shown)

    def _gap(self, times):
        if len(times) < 3:
            return float("inf")
        diffs = sorted(times[i + 1] - times[i] for i in range(min(len(times) - 1, 200)))
        return max(diffs[len(diffs) // 2] * 5, 10.0)

    def _analog_path(self, series, rect, y_of):
        times, values = series["times"], series["values"]
        gap = self._gap(times)
        path = QPainterPath()
        segment_start = 0
        width = max(1, int(rect.width()))
        for i in range(1, len(times) + 1):
            if i == len(times) or times[i] - times[i - 1] > gap:
                seg_t, seg_v = times[segment_start:i], values[segment_start:i]
                first = True
                for index in self._decimate(seg_v, width):
                    point = QPointF(self._x(seg_t[index], rect), y_of(seg_v[index]))
                    if first:
                        path.moveTo(point)
                        first = False
                    else:
                        path.lineTo(point)
                if len(seg_t) == 1:
                    path.lineTo(QPointF(self._x(seg_t[0], rect) + 0.5, y_of(seg_v[0])))
                segment_start = i
        return path

    @staticmethod
    def _decimate(values, width):
        """Indices to draw: everything for small series, min/max per pixel column otherwise."""
        count = len(values)
        if count <= width * 3:
            return range(count)
        keep = []
        size = count / width
        for column in range(width):
            lo, hi = int(column * size), max(int((column + 1) * size), int(column * size) + 1)
            chunk = values[lo:hi]
            low_i = lo + chunk.index(min(chunk))
            high_i = lo + chunk.index(max(chunk))
            keep.extend(sorted({lo, low_i, high_i, hi - 1}))
        return keep

    def _digital_path(self, series, lane, rect, y_of):
        times, values = series["times"], series["values"]
        gap = self._gap(times)
        path = QPainterPath()
        previous_level = None
        previous_t = None
        for index, (t, value) in enumerate(zip(times, values)):
            level = y_of(lane + (0.85 if value else 0.15))
            x = self._x(t, rect)
            if previous_level is None or t - previous_t > gap:
                path.moveTo(x, level)
            else:
                if level != previous_level:
                    path.lineTo(x, previous_level)
                    path.lineTo(x, level)
                elif index == len(times) - 1:
                    path.lineTo(x, level)
            previous_level, previous_t = level, t
        return path

    def _paint_hover(self, painter, rect, shown):
        if self._hover_x is None or not rect.contains(self._hover_x, rect.center().y()):
            return
        t = self._t0 + (self._hover_x - rect.left()) / rect.width() * (self._t1 - self._t0)
        painter.setPen(QPen(QColor("#8FC6EA"), 1, Qt.DashLine))
        painter.drawLine(QPointF(self._hover_x, rect.top()), QPointF(self._hover_x, rect.bottom()))
        lines = [datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")]
        for series in shown:
            times = series["times"]
            i = bisect_left(times, t)
            candidates = [j for j in (i - 1, i) if 0 <= j < len(times)]
            if not candidates:
                continue
            j = min(candidates, key=lambda k: abs(times[k] - t))
            if abs(times[j] - t) > self._gap(times):
                continue          # no data near the cursor (gap / outside the recorded span)
            value = series["values"][j]
            text = ("ON" if value else "OFF") if self._digital else f"{value:.2f} {series['unit']}".strip()
            lines.append(f"{series['name']}: {text}")
        metrics = painter.fontMetrics()
        box_w = max(metrics.horizontalAdvance(line) for line in lines) + 16
        box_h = len(lines) * 16 + 8
        bx = self._hover_x + 12
        if bx + box_w > rect.right():
            bx = self._hover_x - 12 - box_w
        box = QRectF(bx, rect.top() + 28, box_w, box_h)
        painter.setBrush(QColor(11, 34, 57, 230))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(box, 5, 5)
        painter.setPen(_tone("#FFFFFF"))
        for index, line in enumerate(lines):
            painter.drawText(QRectF(box.left() + 8, box.top() + 4 + index * 16, box_w, 16),
                             Qt.AlignLeft | Qt.AlignVCenter, line)

    def mouseMoveEvent(self, event):
        self._hover_x = event.position().x()
        self.update()

    def leaveEvent(self, event):
        self._hover_x = None
        self.update()


# ---------------------------------------------------------------- history tab
class HistoryTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._request = 0
        self._docs = []
        self._units = {}
        self._channels = []
        self._kind = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        panel, body = _panel("Reading History")
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.device_combo = _DeviceCombo()
        self.device_combo.setMinimumWidth(240)
        self.range = RangeSelector()
        self.load_button = QPushButton("LOAD")
        self.load_button.setObjectName("primaryButton")
        self.export_button = QPushButton("EXPORT CSV")
        self.export_button.setObjectName("outlineButton")
        self.export_button.setEnabled(False)
        bar.addWidget(self.device_combo)
        bar.addWidget(self.range)
        bar.addWidget(self.load_button)
        bar.addWidget(self.export_button)
        bar.addStretch()
        body.addLayout(bar)
        self.status = QLabel("Choose a device and time range, then press LOAD.")
        self.status.setObjectName("muted")
        body.addWidget(self.status)
        self.table = _table(["Time"], [160])
        body.addWidget(self.table, 1)
        layout.addWidget(panel)
        self.load_button.clicked.connect(self.load)
        self.export_button.clicked.connect(self.export_csv)

    def set_devices(self, devices):
        self.device_combo.set_devices(devices)

    def showEvent(self, event):
        super().showEvent(event)
        load_stored_devices(self, self.device_combo)

    def load(self):
        data = self.device_combo.currentData()
        if data is None:
            self.status.setText("No device in the list. Add the device on the Live tab first "
                                "(same Slave ID and type as when the data was saved).")
            return
        slave_id, kind, _name = data
        start, end = self.range.range()
        self._request += 1
        token = self._request
        self.load_button.setEnabled(False)
        self.status.setText("Loading from database...")
        run_async(self, lambda: query_readings(kind, slave_id, start, end, MAX_FETCH),
                  lambda result, error: self._loaded(token, kind, result, error))

    def _loaded(self, token, kind, docs, error):
        if token != self._request:
            return
        self.load_button.setEnabled(True)
        if error is not None:
            self.status.setText(f"Database error: {_error_text(error)}")
            return
        self._docs, self._kind = docs, kind
        self.export_button.setEnabled(bool(docs))
        self._fill(docs, kind)

    def _fill(self, docs, kind):
        table = self.table
        table.setUpdatesEnabled(False)
        table.setRowCount(0)
        if not docs:
            table.setColumnCount(1)
            table.setHorizontalHeaderLabels(["Time"])
            table.setUpdatesEnabled(True)
            self.status.setText("No records in this time range. Checking database...")
            data = self.device_combo.currentData()
            if data:
                explain_empty(self, kind, data[0], self.status)
            return
        channels = list(docs[-1].get("channels", {}).keys())
        units = {}
        for doc in reversed(docs):
            for name, entry in doc.get("channels", {}).items():
                if entry.get("unit") and name not in units:
                    units[name] = entry["unit"]
        self._channels, self._units = channels, units
        digital = kind in ("DI", "DO")
        headers = ["Time"] + [f"{c} ({units[c]})" if c in units else c for c in channels] + ["Quality"]
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setColumnWidth(0, 160)
        shown = docs[::-1][:MAX_TABLE_ROWS]
        table.setRowCount(len(shown))
        for row, doc in enumerate(shown):
            table.setItem(row, 0, _item(_fmt_time(doc["timestamp"]), align=Qt.AlignLeft))
            for column, name in enumerate(channels, start=1):
                value = doc.get("channels", {}).get(name, {}).get("value")
                if digital and value is not None:
                    table.setItem(row, column, _item("ON" if value else "OFF",
                                                     "#12A45B" if value else "#7893A8", bold=bool(value)))
                else:
                    table.setItem(row, column, _item("--" if value is None else f"{value:.3f}"))
            table.setItem(row, len(headers) - 1, _item(doc.get("quality", "")))
        table.setUpdatesEnabled(True)
        extra = f" (showing newest {len(shown)})" if len(docs) > len(shown) else ""
        capped = f" - only the newest {MAX_FETCH} were fetched, narrow the range" if len(docs) >= MAX_FETCH else ""
        self.status.setText(f"{len(docs)} records{extra}{capped}.")

    def export_csv(self):
        if not self._docs:
            return
        name = self.device_combo.currentData()[2].replace(" ", "_")
        default = f"history_{name}_{datetime.now():%Y%m%d_%H%M%S}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", default, "CSV files (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Time"] + [f"{c} ({self._units[c]})" if c in self._units else c
                                            for c in self._channels] + ["Quality"])
                for doc in self._docs:
                    channels = doc.get("channels", {})
                    writer.writerow([doc["timestamp"].strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                                     if isinstance(doc["timestamp"], datetime) else doc["timestamp"]]
                                    + [channels.get(c, {}).get("value", "") for c in self._channels]
                                    + [doc.get("quality", "")])
            self.status.setText(f"Exported {len(self._docs)} records to {path}")
        except OSError as exc:
            self.status.setText(f"Export failed: {exc}")


# ---------------------------------------------------------------- trends tab
class TrendsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._request = 0
        self._boxes = []
        self._box_kind = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        panel, body = _panel("Trend Chart")
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.device_combo = _DeviceCombo()
        self.device_combo.setMinimumWidth(240)
        self.range = RangeSelector()
        self.refresh_button = QPushButton("REFRESH")
        self.refresh_button.setObjectName("primaryButton")
        self.auto_box = QCheckBox("Auto refresh (5 s)")
        bar.addWidget(self.device_combo)
        bar.addWidget(self.range)
        bar.addWidget(self.refresh_button)
        bar.addWidget(self.auto_box)
        bar.addStretch()
        body.addLayout(bar)
        self.channel_row = QHBoxLayout()
        self.channel_row.setSpacing(10)
        _channels_label = QLabel("Channels:")
        _channels_label.setObjectName("fieldLabel")
        self.channel_row.addWidget(_channels_label)
        self._channel_holder = QHBoxLayout()
        self._channel_holder.setSpacing(10)
        self.channel_row.addLayout(self._channel_holder)
        self.channel_row.addStretch()
        body.addLayout(self.channel_row)
        self.status = QLabel("Choose a device, channels and time range, then press REFRESH.")
        self.status.setObjectName("muted")
        body.addWidget(self.status)
        self.chart = TrendChart()
        body.addWidget(self.chart, 1)
        layout.addWidget(panel)
        self._timer = QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self._auto_tick)
        self.auto_box.toggled.connect(lambda on: self._timer.start() if on else self._timer.stop())
        self.refresh_button.clicked.connect(self.refresh)
        self.device_combo.currentIndexChanged.connect(self._device_changed)

    def set_devices(self, devices):
        self.device_combo.set_devices(devices)
        self._device_changed()

    def showEvent(self, event):
        super().showEvent(event)
        load_stored_devices(self, self.device_combo, self._device_changed)

    def _device_changed(self):
        data = self.device_combo.currentData()
        kind = data[1] if data else None
        if kind == self._box_kind and self._boxes:
            return
        self._box_kind = kind
        for box in self._boxes:
            self._channel_holder.removeWidget(box)
            box.deleteLater()
        self._boxes = []
        count = CHANNELS_BY_KIND.get(kind, 0)
        for index in range(count):
            box = QCheckBox(f"{kind}{index + 1}")
            box.setChecked(index < (8 if kind == "AI" else 4))
            self._boxes.append(box)
            self._channel_holder.addWidget(box)

    def _auto_tick(self):
        if self.isVisible() and self.refresh_button.isEnabled():
            self.refresh()

    def refresh(self):
        data = self.device_combo.currentData()
        if data is None:
            self.status.setText("No device in the list. Add the device on the Live tab first "
                                "(same Slave ID and type as when the data was saved).")
            return
        slave_id, kind, _name = data
        selected = [b.text() for b in self._boxes if b.isChecked()]
        if not selected:
            self.status.setText("Select at least one channel.")
            return
        start, end = self.range.range()
        self._request += 1
        token = self._request
        self.refresh_button.setEnabled(False)
        self.status.setText("Loading from database...")
        run_async(self, lambda: query_readings(kind, slave_id, start, end, MAX_FETCH),
                  lambda result, error: self._loaded(token, kind, selected, start, end, result, error))

    def _loaded(self, token, kind, selected, start, end, docs, error):
        if token != self._request:
            return
        self.refresh_button.setEnabled(True)
        if error is not None:
            self.status.setText(f"Database error: {_error_text(error)}")
            self.chart.set_data([], False, start.timestamp(), end.timestamp(), "Database not reachable")
            return
        series = []
        for index, name in enumerate(selected):
            times, values, unit = [], [], ""
            for doc in docs:
                entry = doc.get("channels", {}).get(name)
                if entry is None or entry.get("value") is None:
                    continue
                times.append(doc["timestamp"].timestamp())
                values.append(entry["value"])
                unit = entry.get("unit", unit)
            series.append({"name": name, "color": SERIES_COLORS[index % len(SERIES_COLORS)],
                           "times": times, "values": values, "unit": unit})
        digital = kind in ("DI", "DO")
        self.chart.set_data(series, digital, start.timestamp(), end.timestamp(),
                            "No data in the selected range")
        mixed = len({s["unit"] for s in series if s["unit"]}) > 1
        note = " - channels use different units, one scale is shared" if mixed and not digital else ""
        if docs:
            self.status.setText(f"{len(docs)} records.{note}")
        else:
            self.status.setText("No records in this time range. Checking database...")
            data = self.device_combo.currentData()
            if data:
                explain_empty(self, kind, data[0], self.status)