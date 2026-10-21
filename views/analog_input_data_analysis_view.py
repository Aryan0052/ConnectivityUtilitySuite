import os
from datetime import date, datetime, timedelta
import statistics
from PySide6.QtCore import Qt, Signal, QPoint, QRectF, QDate, QTimer
from PySide6.QtGui import QPixmap, QPainter, QPen, QBrush, QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFrame,
    QHeaderView,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)
try:
    from database.mongodb import MongoDB
except Exception:
    MongoDB = None

try:
    from . import ui_theme as ui
except ImportError:
    import ui_theme as ui

lc = ui.lc


def _tc(name):
    """Colour of the current light / dark theme (painted charts follow the theme switch)."""
    return lc.qc(name)


_FONT = "Segoe UI"

# Data-analysis widgets. Colours are @tokens of the shared light / dark palette (live_console.LIGHT / DARK).
ANALYSIS_QSS = """
QFrame#controlCard, QFrame#kpiCard, QFrame#chartCard { background:@surface; border:1px solid @border;
    border-radius:12px; }
QLabel#pageTitle { color:@text; font-size:20px; font-weight:700; }
QLabel#pageSubtitle { color:@muted; font-size:12px; }
QLabel#pageIcon { background:@accent_soft; color:@accent_text; border:1px solid @accent; border-radius:10px;
    font-size:22px; font-weight:700; }
QLabel#sectionTitle { color:@text2; font-size:12px; font-weight:600; }
QLabel#chartTitle { color:@text; font-size:14px; font-weight:700; }
QLabel#chartSubtitle { color:@muted; font-size:11px; }
QFrame#chartArea { background:@sunken; border:1px solid @border; border-radius:8px; }
QLabel#kpiTitle { color:@muted; font-size:11px; font-weight:600; }
QLabel#kpiValue { color:@text; font-size:22px; font-weight:700; }
QLabel#kpiChange { color:@ok; font-size:11px; font-weight:600; }
QLabel#expandTitle { color:@text; font-size:18px; font-weight:700; }
QLabel#pointLabel { color:@text2; font-size:12px; font-weight:600; }
QFrame#expandContent { background:@surface; border:0; }
QFrame#pgVRule { background:@border; border:0; min-width:1px; max-width:1px; }
QPushButton#rangeButton { background:@surface; color:@text; border:1px solid @border2; border-radius:8px;
    padding:0 14px; min-height:32px; font-size:12px; font-weight:600; }
QPushButton#rangeButton:hover { background:@hover; }
QPushButton#rangeButton:checked { background:@accent; color:@on_accent; border:1px solid @accent; }
QPushButton#refreshButton { background:@accent; color:@on_accent; border:1px solid @accent; border-radius:8px;
    padding:0 16px; min-height:34px; font-size:13px; font-weight:600; }
QPushButton#refreshButton:hover { background:@accent_text; border-color:@accent_text; }
QPushButton#viewAllButton { background:transparent; color:@accent_text; border:0; border-radius:6px;
    padding:0 8px; font-size:12px; font-weight:600; }
QPushButton#viewAllButton:hover { background:@hover; }
QDateEdit { background:@surface; border:1px solid @border2; border-radius:8px; color:@text; padding:0 10px;
    min-height:34px; font-family:"Segoe UI"; font-size:13px; }
QDateEdit:focus { border:1px solid @accent; }
QDateEdit::drop-down { border:0; width:26px; }
QDateEdit::down-arrow { image:url(@arrow_down); width:12px; height:12px; }
QCalendarWidget QWidget { background:@surface; color:@text; alternate-background-color:@sunken; }
QCalendarWidget QToolButton { background:transparent; color:@text; border:0; padding:4px 8px; font-weight:600; }
QCalendarWidget QToolButton:hover { background:@hover; border-radius:6px; }
QCalendarWidget QAbstractItemView { background:@surface; color:@text; selection-background-color:@accent;
    selection-color:@on_accent; outline:0; }
QCalendarWidget QAbstractItemView:disabled { color:@faint; }
QTableWidget { font-size:12px; }
QHeaderView::section { padding:6px 4px; font-size:10px; }
"""

LEGEND_QSS = """
QCheckBox { color:@text2; font-family:"Segoe UI"; font-size:11px; font-weight:700; spacing:4px; background:transparent; }
QCheckBox::indicator { width:12px; height:12px; border:1px solid @border2; border-radius:3px; background:@surface; }
QCheckBox::indicator:checked { background-color:%(c)s; border:1px solid %(c)s; border-radius:3px; }
"""

DIALOG_QSS = """
QDialog { background:@bg; }
QLabel { color:@text; font-family:"Segoe UI"; font-size:20px; font-weight:700; padding:4px; background:transparent; }
QTableWidget { background:@surface; color:@text; border:1px solid @border; border-radius:8px; gridline-color:@border;
    font-family:"Segoe UI"; font-size:13px; selection-background-color:@accent_soft; selection-color:@text; }
QHeaderView::section { background:@sunken; color:@muted; border:0; border-bottom:1px solid @border;
    border-right:1px solid @border; padding:8px; font-family:"Segoe UI"; font-size:12px; font-weight:700; }
QTableCornerButton::section { background:@sunken; border:0; }
QScrollBar:vertical { width:8px; background:transparent; margin:2px; }
QScrollBar::handle:vertical { background:@border2; border-radius:4px; min-height:30px; }
QScrollBar:horizontal { height:8px; background:transparent; margin:2px; }
QScrollBar::handle:horizontal { background:@border2; border-radius:4px; min-width:30px; }
QScrollBar::add-line, QScrollBar::sub-line { height:0; width:0; }
"""

class BackButton(QPushButton):
    """White circular back button matching the main application header."""

    def __init__(self, parent=None):
        super().__init__(parent)
        ui.sized(self, "setFixedSize", 58, 58)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setText("")
        self.setStyleSheet("""
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
        painter.setPen(Qt.NoPen)
        painter.setBrush(Qt.white)
        painter.drawEllipse(0, 0, 58, 58)
        pen = QPen("#155B91")
        pen.setWidth(6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(QPoint(19, 29), QPoint(43, 29))
        painter.drawLine(QPoint(19, 29), QPoint(31, 17))
        painter.drawLine(QPoint(19, 29), QPoint(31, 41))
        painter.end()

class ChartCard(QFrame):
    """Clean chart card; real values can be supplied through set_series()."""

    def __init__(self, title, subtitle="", parent=None):
        super().__init__(parent)
        self.setObjectName("chartCard")
        self.series = {}
        self.x_labels = []
        self.point_times = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 10)
        layout.setSpacing(5)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_label = QLabel(title)
        title_label.setObjectName("chartTitle")
        title_row.addWidget(title_label)
        title_row.addStretch()
        if title == "Channel Values Over Time":
            self.legend = QHBoxLayout()
            self.legend.setSpacing(8)
            title_row.addLayout(self.legend)
        layout.addLayout(title_row)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("chartSubtitle")
            layout.addWidget(subtitle_label)
        self.chart_area = QFrame()
        self.chart_area.setObjectName("chartArea")
        self.chart_area.setMinimumHeight(250)
        self.chart_area.paintEvent = self._paint_chart
        layout.addWidget(self.chart_area, 1)

    def set_series(self, series, x_labels=None, point_times=None):
        self.series = series or {}
        self.x_labels = x_labels or []
        self.point_times = point_times or {}
        self.chart_area.update()

    def point_at(self, position):
        if not self.series:
            return None
        rect = self.chart_area.rect().adjusted(48, 16, -18, -34)
        if not rect.contains(position):
            return None
        max_value = max(
            (max(values) for values in self.series.values() if values),
            default=1.0
        )
        if max_value <= 0:
            max_value = 1.0
        nearest = None
        nearest_distance = None
        for channel, values in self.series.items():
            if not values:
                continue
            denominator = max(len(values) - 1, 1)
            for i, value in enumerate(values):
                x = rect.left() + rect.width() * i / denominator
                y = rect.bottom() - rect.height() * (float(value) / max_value)
                distance = ((position.x() - x) ** 2 + (position.y() - y) ** 2) ** 0.5
                if nearest_distance is None or distance < nearest_distance:
                    times = self.point_times.get(channel, [])
                    timestamp = times[i] if i < len(times) else None
                    nearest = (channel, float(value), timestamp)
                    nearest_distance = distance
        if nearest is None or nearest_distance > 18:
            return None
        return nearest

    def _paint_chart(self, event):
        painter = QPainter(self.chart_area)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.chart_area.rect().adjusted(48, 16, -18, -34)
        grid_pen = QPen(_tc("border"))
        grid_pen.setWidth(1)
        painter.setPen(grid_pen)
        for i in range(6):
            y = rect.top() + rect.height() * i / 5
            painter.drawLine(rect.left(), int(y), rect.right(), int(y))
        for i in range(6):
            x = rect.left() + rect.width() * i / 5
            painter.drawLine(int(x), rect.top(), int(x), rect.bottom())
        if not self.series:
            painter.setPen(QPen(_tc("muted")))
            painter.setFont(QFont(_FONT, 11))
            painter.drawText(
                rect,
                Qt.AlignCenter,
                "No data available for the selected period"
            )
            painter.end()
            return
        palette = [
            "#168BE0", "#26A86B", "#F4A300", "#E94B4B",
            "#7450D9", "#16A6A6", "#E73E9B", "#778899"
        ]
        max_value = max(
            (max(values) for values in self.series.values() if values),
            default=1.0
        )
        if max_value <= 0:
            max_value = 1.0
        for idx, (channel, values) in enumerate(self.series.items()):
            if not values:
                continue
            pen = QPen(palette[idx % len(palette)])
            pen.setWidth(2)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            points = []
            denominator = max(len(values) - 1, 1)
            for i, value in enumerate(values):
                x = rect.left() + rect.width() * i / denominator
                y = rect.bottom() - rect.height() * (float(value) / max_value)
                points.append((int(x), int(y)))
            for i in range(len(points) - 1):
                painter.drawLine(
                    points[i][0], points[i][1],
                    points[i + 1][0], points[i + 1][1]
                )
        painter.setPen(QPen(_tc("muted")))
        painter.setFont(QFont(_FONT, 9))
        painter.drawText(
            rect.left() - 40, rect.top() - 2, 34, 16,
            Qt.AlignRight, f"{max_value:g}"
        )
        painter.drawText(
            rect.left() - 40, rect.bottom() - 8, 34, 16,
            Qt.AlignRight, "0"
        )
        if self.x_labels:
            for i, label in enumerate(self.x_labels[:6]):
                denominator = max(len(self.x_labels) - 1, 1)
                x = rect.left() + rect.width() * i / denominator
                painter.drawText(
                    int(x) - 30, rect.bottom() + 8, 60, 16,
                    Qt.AlignCenter, str(label)
                )
        painter.end()

class BarChartCard(QFrame):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("chartCard")
        self.values = {}
        self.metric_values = {
            "Average Value": {},
            "Maximum Value": {},
            "Minimum Value": {},
        }
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 10)
        layout.setSpacing(5)
        title_row = QHBoxLayout()
        title = QLabel("Channel Comparison (Average Value)")
        title.setObjectName("chartTitle")
        title_row.addWidget(title)
        title_row.addStretch()
        self.metric_combo = QComboBox()
        self.metric_combo.addItems(["Average Value", "Maximum Value", "Minimum Value"])
        ui.sized(self.metric_combo, "setFixedWidth", 145)
        self.metric_combo.currentTextChanged.connect(self._metric_changed)
        title_row.addWidget(self.metric_combo)
        layout.addLayout(title_row)
        self.chart_title = title
        self.chart_subtitle = QLabel(
            "Average voltage of each channel in selected period"
        )
        self.chart_subtitle.setObjectName("chartSubtitle")
        layout.addWidget(self.chart_subtitle)
        self.chart_area = QFrame()
        self.chart_area.setObjectName("chartArea")
        self.chart_area.setMinimumHeight(250)
        self.chart_area.paintEvent = self._paint_chart
        layout.addWidget(self.chart_area, 1)

    def set_values(self, values):
        # Backward-compatible setter for Average Value.
        self.set_metric_values(
            average_values=values or {},
            maximum_values=self.metric_values.get("Maximum Value", {}),
            minimum_values=self.metric_values.get("Minimum Value", {}),
        )

    def set_metric_values(
        self,
        average_values=None,
        maximum_values=None,
        minimum_values=None,
    ):
        self.metric_values = {
            "Average Value": average_values or {},
            "Maximum Value": maximum_values or {},
            "Minimum Value": minimum_values or {},
        }
        self._metric_changed(self.metric_combo.currentText())

    def _metric_changed(self, metric):
        self.values = self.metric_values.get(metric, {})
        self.chart_title.setText(f"Channel Comparison ({metric})")
        subtitle_text = {
            "Average Value": "Average voltage of each channel in selected period",
            "Maximum Value": "Maximum recorded value of each channel in selected period",
            "Minimum Value": "Minimum recorded value of each channel in selected period",
        }.get(metric, "Channel values in selected period")
        self.chart_subtitle.setText(subtitle_text)
        self.chart_area.update()

    def _paint_chart(self, event):
        painter = QPainter(self.chart_area)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.chart_area.rect().adjusted(42, 16, -12, -34)
        grid_pen = QPen(_tc("border"))
        painter.setPen(grid_pen)
        for i in range(6):
            y = rect.top() + rect.height() * i / 5
            painter.drawLine(rect.left(), int(y), rect.right(), int(y))
        if not self.values:
            painter.setPen(QPen(_tc("muted")))
            painter.setFont(QFont(_FONT, 11))
            painter.drawText(rect, Qt.AlignCenter, "No data available")
            painter.end()
            return
        colors = [
            "#168BE0", "#26A86B", "#F4A300", "#E94B4B",
            "#7450D9", "#16A6A6", "#E73E9B", "#778899"
        ]
        items = list(self.values.items())[:8]
        maximum = max((float(v) for _, v in items), default=1.0)
        maximum = maximum if maximum > 0 else 1.0
        bar_width = max(20, int(rect.width() / max(len(items) * 1.65, 1)))
        gap = rect.width() / max(len(items), 1)
        painter.setFont(QFont(_FONT, 8))
        for i, (channel, value) in enumerate(items):
            value = float(value)
            x = rect.left() + gap * i + (gap - bar_width) / 2
            height = rect.height() * value / maximum
            y = rect.bottom() - height
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(colors[i % len(colors)]))
            painter.drawRoundedRect(
                QRectF(x, y, bar_width, height),
                4, 4
            )
            painter.setPen(QPen(_tc("text")))
            painter.drawText(
                int(x) - 10, int(y) - 18, bar_width + 20, 16,
                Qt.AlignCenter, f"{value:.2f}"
            )
            painter.drawText(
                int(x) - 10, rect.bottom() + 8, bar_width + 20, 16,
                Qt.AlignCenter, channel.upper()
            )
        painter.end()

class DonutChartCard(QFrame):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("chartCard")
        self.values = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 10)
        layout.setSpacing(5)
        title = QLabel("Value Distribution (All Channels)")
        title.setObjectName("chartTitle")
        layout.addWidget(title)
        self.chart_area = QFrame()
        self.chart_area.setObjectName("chartArea")
        self.chart_area.setMinimumHeight(210)
        self.chart_area.paintEvent = self._paint_chart
        layout.addWidget(self.chart_area, 1)

    def set_values(self, values):
        self.values = values or {}
        self.chart_area.update()

    def _paint_chart(self, event):
        painter = QPainter(self.chart_area)
        painter.setRenderHint(QPainter.Antialiasing, True)
        if not self.values:
            painter.setPen(QPen(_tc("muted")))
            painter.setFont(QFont(_FONT, 11))
            painter.drawText(
                self.chart_area.rect(),
                Qt.AlignCenter,
                "No data available"
            )
            painter.end()
            return
        colors = [
            "#168BE0", "#26A86B", "#F4A300", "#E94B4B",
            "#7450D9", "#16A6A6", "#E73E9B", "#778899"
        ]
        items = list(self.values.items())[:8]
        total = sum(max(float(v), 0) for _, v in items)
        if total <= 0:
            painter.setPen(QPen(_tc("muted")))
            painter.drawText(self.chart_area.rect(), Qt.AlignCenter, "No data available")
            painter.end()
            return
        size = min(self.chart_area.height() - 28, 165)
        rect = QRectF(18, 20, size, size)
        start_angle = 0
        for i, (_, value) in enumerate(items):
            span = 5760 * max(float(value), 0) / total
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(colors[i % len(colors)]))
            painter.drawPie(rect, int(start_angle), int(span))
            start_angle += span
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(_tc("sunken")))
        inner = rect.adjusted(45, 45, -45, -45)
        painter.drawEllipse(inner)
        painter.setPen(QPen(_tc("text")))
        painter.setFont(QFont(_FONT, 10, QFont.Bold))
        painter.drawText(inner, Qt.AlignCenter, "100%\nReadings")
        legend_x = int(rect.right() + 18)
        legend_y = 26
        painter.setFont(QFont(_FONT, 9))
        for i, (channel, value) in enumerate(items):
            y = legend_y + i * 22
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(colors[i % len(colors)]))
            painter.drawEllipse(QRectF(legend_x, y, 10, 10))
            painter.setPen(QPen(_tc("text")))
            percentage = float(value) / total * 100
            painter.drawText(
                legend_x + 18, y - 2, 55, 16,
                Qt.AlignLeft, channel.upper()
            )
            painter.drawText(
                legend_x + 62, y - 2, 45, 16,
                Qt.AlignRight, f"{percentage:.0f}%"
            )
        painter.end()

class KpiCard(QFrame):

    def __init__(self, icon_text, title, value, change_text, accent, parent=None):
        super().__init__(parent)
        self.setObjectName("kpiCard")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 11, 12, 11)
        layout.setSpacing(11)
        icon = QLabel(icon_text)
        icon.setAlignment(Qt.AlignCenter)
        ui.sized(icon, "setFixedSize", 58, 58)
        icon.setStyleSheet(
            f"background: {accent}; color: white; border-radius: 12px; "
            "font-family: 'Segoe UI'; font-size: 22px; font-weight: bold;"
        )
        layout.addWidget(icon)
        text_layout = QVBoxLayout()
        text_layout.setSpacing(1)
        title_label = QLabel(title)
        title_label.setObjectName("kpiTitle")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("kpiValue")
        self.change_label = QLabel(change_text)
        self.change_label.setObjectName("kpiChange")
        text_layout.addWidget(title_label)
        text_layout.addWidget(self.value_label)
        text_layout.addWidget(self.change_label)
        text_layout.addStretch()
        layout.addLayout(text_layout, 1)
        self.sparkline = QFrame()
        ui.sized(self.sparkline, "setFixedWidth", 72)
        self.sparkline.setStyleSheet("background: transparent;")
        self.sparkline.paintEvent = self._paint_sparkline
        layout.addWidget(self.sparkline)

    def _paint_sparkline(self, event):
        painter = QPainter(self.sparkline)
        painter.setRenderHint(QPainter.Antialiasing, True)
        points = [
            (4, 44), (15, 35), (26, 39),
            (38, 24), (49, 30), (61, 13), (69, 18)
        ]
        pen = QPen(_tc("accent"))
        pen.setWidth(2)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        for i in range(len(points) - 1):
            painter.drawLine(
                points[i][0], points[i][1],
                points[i + 1][0], points[i + 1][1]
            )
        painter.end()

class ExpandedViewDialog(QDialog):
    """Large viewer for an expanded chart."""

    def __init__(self, title, content_widget, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(False)
        self.setWindowFlags(
            Qt.Window | Qt.WindowTitleHint |
            Qt.WindowCloseButtonHint | Qt.WindowMaximizeButtonHint
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 18)
        layout.setSpacing(10)
        lc.tss(self, DIALOG_QSS)
        heading = QLabel(title)
        layout.addWidget(heading)
        content_widget.setParent(self)
        layout.addWidget(content_widget, 1)
        self.resize(1250, 780)

    def showEvent(self, event):
        super().showEvent(event)
        self.showMaximized()

class ExpandedTableDialog(QDialog):
    """Large viewer for a dashboard table."""

    def __init__(self, title, source_table, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(False)
        self.setWindowFlags(
            Qt.Window | Qt.WindowTitleHint |
            Qt.WindowCloseButtonHint | Qt.WindowMaximizeButtonHint
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 18)
        layout.setSpacing(10)
        lc.tss(self, DIALOG_QSS)
        heading = QLabel(title)
        layout.addWidget(heading)
        table = QTableWidget(source_table.rowCount(), source_table.columnCount())
        table.setHorizontalHeaderLabels([
            source_table.horizontalHeaderItem(i).text()
            if source_table.horizontalHeaderItem(i) else ""
            for i in range(source_table.columnCount())
        ])
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.verticalHeader().setVisible(False)
        for row in range(source_table.rowCount()):
            table.setRowHeight(row, max(34, source_table.rowHeight(row)))
            for col in range(source_table.columnCount()):
                item = source_table.item(row, col)
                if item is not None:
                    copied = QTableWidgetItem(item.text())
                    copied.setTextAlignment(item.textAlignment())
                    table.setItem(row, col, copied)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        table.horizontalHeader().setStretchLastSection(True)
        table.resizeColumnsToContents()
        layout.addWidget(table, 1)
        self.resize(1250, 780)

    def showEvent(self, event):
        super().showEvent(event)
        self.showMaximized()

class AnalogInputDataAnalysisView(QWidget):
    """Analog Input Data Analysis dashboard backed by MongoDB.
    Data is loaded from the existing Nelumbo MongoDB collection
    ``analog_input_test_data`` using the central ``database.mongodb.MongoDB``
    connection.
    """
    back_clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Connectivity Utility Suite - Data Analysis")
        self.setMinimumSize(1100, 700)
        self._selected_range = "1 Month"
        self._mongo = None
        self._mongo_collection = None
        self._filtered_records = []
        self._showing_all_readings = False
        self._build_ui()
        # Build the dashboard first; load MongoDB data after it is visible.
        QTimer.singleShot(100, self._connect_mongodb)

    def _build_ui(self):
        # Look: shared with the other pages and the Multi Device page (ui_theme.py). Only widgets and
        # styles change here - every attribute the MongoDB / chart code uses keeps its name.
        ui.install(self)
        ui.tss(self, ui.PAGE_QSS + ANALYSIS_QSS)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        content = QWidget()
        main = QVBoxLayout(content)
        main.setContentsMargins(20, 18, 20, 20)
        main.setSpacing(12)
        # Page header.
        page_header = QHBoxLayout()
        page_header.setSpacing(12)
        page_icon = QLabel("▥")
        page_icon.setObjectName("pageIcon")
        page_icon.setAlignment(Qt.AlignCenter)
        ui.sized(page_icon, "setFixedSize", 46, 46)
        page_header.addWidget(page_icon)
        title_layout = QVBoxLayout()
        title_layout.setSpacing(1)
        title = QLabel("Analog Input Data Analysis")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Analyze historical data of 8 analog input channels with interactive visualizations and insights"
        )
        subtitle.setObjectName("pageSubtitle")
        title_layout.addWidget(title)
        title_layout.addWidget(subtitle)
        page_header.addLayout(title_layout)
        page_header.addStretch()
        main.addLayout(page_header)
        # Filter card.
        self._filter_card = self._build_filter_card()
        main.addWidget(self._filter_card)
        # KPI row.
        kpi_grid = QGridLayout()
        kpi_grid.setHorizontalSpacing(12)
        kpi_grid.setVerticalSpacing(12)
        self.total_kpi = KpiCard("▤", "Total Readings", "—", "Selected period", "#3B82D0")
        self.average_kpi = KpiCard("▥", "Average Value (All Channels)", "—", "Selected period", "#4BC58A")
        self.maximum_kpi = KpiCard("↑", "Maximum Value (All Channels)", "—", "Selected period", "#F06A6A")
        self.minimum_kpi = KpiCard("↓", "Minimum Value (All Channels)", "—", "Selected period", "#7B65D8")
        kpi_grid.addWidget(self.total_kpi, 0, 0)
        kpi_grid.addWidget(self.average_kpi, 0, 1)
        kpi_grid.addWidget(self.maximum_kpi, 0, 2)
        kpi_grid.addWidget(self.minimum_kpi, 0, 3)
        main.addLayout(kpi_grid)
        # Main charts.
        charts_grid = QGridLayout()
        charts_grid.setHorizontalSpacing(12)
        charts_grid.setVerticalSpacing(12)
        self.line_chart = ChartCard(
            "Channel Values Over Time",
            "Analog input values for all 8 channels"
        )
        self._build_channel_legend(self.line_chart)
        self.bar_chart = BarChartCard()
        charts_grid.addWidget(self.line_chart, 0, 0, 1, 2)
        charts_grid.addWidget(self.bar_chart, 0, 2, 1, 1)
        self._enable_chart_expand(
            self.line_chart, "Channel Values Over Time"
        )
        charts_grid.setColumnStretch(0, 3)
        charts_grid.setColumnStretch(1, 1)
        charts_grid.setColumnStretch(2, 2)
        main.addLayout(charts_grid)
        # Bottom section.
        bottom_grid = QGridLayout()
        bottom_grid.setHorizontalSpacing(12)
        bottom_grid.setVerticalSpacing(12)
        self.donut_chart = DonutChartCard()
        statistics = self._build_statistics_table()
        recent = self._build_recent_readings_table()
        bottom_grid.addWidget(self.donut_chart, 0, 0)
        bottom_grid.addWidget(statistics, 0, 1)
        bottom_grid.addWidget(recent, 0, 2)
        bottom_grid.setColumnStretch(0, 1)
        bottom_grid.setColumnStretch(1, 2)
        bottom_grid.setColumnStretch(2, 2)
        main.addLayout(bottom_grid)
        # In-place expansion area. It stays in the same dashboard window.
        self._expanded_host = QFrame()
        self._expanded_host.setObjectName("chartCard")
        self._expanded_host.setMinimumHeight(620)
        self._expanded_host.setVisible(False)
        expanded_layout = QVBoxLayout(self._expanded_host)
        expanded_layout.setContentsMargins(8, 8, 8, 8)
        expanded_layout.setSpacing(8)
        expanded_toolbar = QHBoxLayout()
        self._expanded_title = QLabel("")
        self._expanded_title.setObjectName("expandTitle")
        expanded_toolbar.addWidget(self._expanded_title)
        expanded_toolbar.addStretch()
        self._selected_point_label = QLabel("")
        self._selected_point_label.setObjectName("pointLabel")
        expanded_toolbar.addWidget(self._selected_point_label)
        self._selected_point_label.setVisible(False)
        self._expanded_back = QPushButton("← Back to Dashboard")
        self._expanded_back.setObjectName("refreshButton")
        self._expanded_back.setCursor(Qt.PointingHandCursor)
        self._expanded_back.clicked.connect(self._restore_dashboard)
        expanded_toolbar.addWidget(self._expanded_back)
        expanded_layout.addLayout(expanded_toolbar)
        self._expanded_content = QFrame()
        self._expanded_content.setObjectName("expandContent")
        self._expanded_content_layout = QVBoxLayout(self._expanded_content)
        self._expanded_content_layout.setContentsMargins(0, 0, 0, 0)
        self._expanded_content_layout.setSpacing(0)
        expanded_layout.addWidget(self._expanded_content, 1)
        main.addWidget(self._expanded_host)
        self._expanded_widget = None
        self._expanded_grid = None
        self._expanded_position = None
        self._expanded_sections_hidden = False
        self._charts_grid = charts_grid
        self._bottom_grid = bottom_grid
        self._kpi_grid = kpi_grid
        scroll.setWidget(content)
        root.addWidget(scroll, 1)
        self._refresh_dashboard_state()

    def _build_header(self):
        header = ui.Header("Analog Input  \u00b7  Data Analysis", root=self)
        header.status.setText("Data Analysis")
        ui.set_status(header.status, header.status_dot, "#1684BE")
        back = header.back_button
        back.clicked.connect(self.back_clicked.emit)
        self.back_button = back
        return header

    def _build_filter_card(self):
        card = QFrame()
        card.setObjectName("controlCard")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(14, 9, 14, 9)
        layout.setSpacing(8)
        range_label = QLabel("▣  Time Range")
        range_label.setObjectName("sectionTitle")
        ui.sized(range_label, "setFixedWidth", 105)
        layout.addWidget(range_label)
        self.range_group = QButtonGroup(self)
        self.range_group.setExclusive(True)
        for text in ["1 Week", "1 Month", "2 Months", "6 Months", "1 Year", "Custom Range"]:
            button = QPushButton(text)
            button.setObjectName("rangeButton")
            button.setCheckable(True)
            ui.sized(button, "setMinimumHeight", 34)
            button.setCursor(Qt.PointingHandCursor)
            self.range_group.addButton(button)
            layout.addWidget(button)
            if text == "1 Month":
                button.setChecked(True)
            button.clicked.connect(
                lambda checked, value=text: self._select_range(value)
            )
        separator = QFrame()
        separator.setObjectName("pgVRule")
        separator.setFixedWidth(1)
        layout.addWidget(separator)
        from_label = QLabel("From Date")
        from_label.setObjectName("sectionTitle")
        layout.addWidget(from_label)
        self.from_date = QDateEdit()
        self.from_date.setCalendarPopup(True)
        self.from_date.setDisplayFormat("dd-MM-yyyy")
        self.from_date.setDate(QDate.currentDate().addMonths(-1))
        ui.sized(self.from_date, "setFixedWidth", 145)
        layout.addWidget(self.from_date)
        to_label = QLabel("To Date")
        to_label.setObjectName("sectionTitle")
        layout.addWidget(to_label)
        self.to_date = QDateEdit()
        self.to_date.setCalendarPopup(True)
        self.to_date.setDisplayFormat("dd-MM-yyyy")
        self.to_date.setDate(QDate.currentDate())
        ui.sized(self.to_date, "setFixedWidth", 145)
        layout.addWidget(self.to_date)
        refresh = QPushButton("⟳  Refresh Data")
        refresh.setObjectName("refreshButton")
        ui.sized(refresh, "setFixedHeight", 36)
        ui.sized(refresh, "setMinimumWidth", 150)
        refresh.clicked.connect(self._refresh_dashboard_state)
        self.refresh_button = refresh
        layout.addWidget(refresh)
        self.from_date.dateChanged.connect(self._refresh_dashboard_state)
        self.to_date.dateChanged.connect(self._refresh_dashboard_state)
        return card

    def _build_channel_legend(self, chart_card):
        colors = [
            "#168BE0", "#26A86B", "#F4A300", "#E94B4B",
            "#7450D9", "#16A6A6", "#E73E9B", "#778899"
        ]
        self.channel_checkboxes = {}
        for i in range(8):
            channel_name = f"CH{i + 1}"
            checkbox = QCheckBox(channel_name)
            checkbox.setChecked(True)
            lc.tss(checkbox, LEGEND_QSS % {"c": colors[i]})
            checkbox.toggled.connect(
                lambda checked, channel=channel_name:
                self._toggle_line_channel(channel, checked)
            )
            chart_card.legend.addWidget(checkbox)
            self.channel_checkboxes[channel_name] = checkbox

    def _toggle_line_channel(self, channel, checked):
        """Show/hide one channel without changing MongoDB data."""
        full_series = getattr(self, "_line_series_all", {})
        if not full_series:
            return
        visible = {
            name: values
            for name, values in full_series.items()
            if self.channel_checkboxes.get(name) is not None
            and self.channel_checkboxes[name].isChecked()
        }
        visible_point_times = {
            name: getattr(self, "_line_point_times", {}).get(name, [])
            for name in visible
        }
        self.line_chart.set_series(
            visible, getattr(self, "_line_x_labels", []), visible_point_times
        )

    def _build_statistics_table(self):
        card = QFrame()
        card.setObjectName("chartCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 11, 14, 10)
        layout.setSpacing(6)
        title = QLabel("▣  Channel Statistics")
        title.setObjectName("chartTitle")
        layout.addWidget(title)
        table = QTableWidget(8, 6)
        table.setHorizontalHeaderLabels([
            "Channel", "Total Readings", "Average (V)",
            "Maximum (V)", "Minimum (V)", "Std Dev (V)"
        ])
        table.setMinimumHeight(245)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        ui.sized(table.horizontalHeader(), "setDefaultSectionSize", 85)
        for row in range(8):
            table.setItem(row, 0, QTableWidgetItem(f"CH{row + 1}"))
            for col in range(1, 6):
                table.setItem(row, col, QTableWidgetItem("—"))
        layout.addWidget(table, 1)
        self.statistics_table = table
        self.statistics_card = card
        table.cellClicked.connect(
            lambda row, col: self._expand_table(
                "Channel Statistics", self.statistics_table
            )
        )
        card.mousePressEvent = lambda event: self._expand_table(
            "Channel Statistics", self.statistics_table
        )
        return card

    def _build_recent_readings_table(self):
        card = QFrame()
        card.setObjectName("chartCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 11, 14, 10)
        layout.setSpacing(6)
        title_row = QHBoxLayout()
        title = QLabel("◷  Recent Readings")
        title.setObjectName("chartTitle")
        title_row.addWidget(title)
        title_row.addStretch()
        view_all = QPushButton("View All")
        view_all.setObjectName("viewAllButton")
        view_all.setCursor(Qt.PointingHandCursor)
        ui.sized(view_all, "setFixedHeight", 24)
        view_all.clicked.connect(self._toggle_all_readings)
        title_row.addWidget(view_all)
        self.view_all_button = view_all
        layout.addLayout(title_row)
        headers = ["Timestamp"] + [f"CH{i}" for i in range(1, 9)]
        table = QTableWidget(7, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setMinimumHeight(245)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.verticalHeader().setVisible(False)
        ui.sized(table.horizontalHeader(), "setDefaultSectionSize", 68)
        table.horizontalHeader().setStretchLastSection(True)
        for row in range(7):
            for col in range(len(headers)):
                table.setItem(row, col, QTableWidgetItem("—"))
        layout.addWidget(table, 1)
        self.recent_table = table
        self.recent_card = card
        table.cellClicked.connect(
            lambda row, col: self._expand_table(
                "Recent Readings", self.recent_table
            )
        )
        card.mousePressEvent = lambda event: self._expand_table(
            "Recent Readings", self.recent_table
        )
        return card

    def _enable_chart_expand(self, chart_widget, title):
        """Expand the selected chart inside this same dashboard window."""

        def open_chart(event=None):
            if self._expanded_widget is chart_widget and event is not None and hasattr(chart_widget, "point_at"):
                selected = chart_widget.point_at(event.position().toPoint())
                if selected is not None:
                    channel, value, timestamp = selected
                    time_text = timestamp.strftime("%d-%m-%Y %H:%M:%S") if timestamp else "Time unavailable"
                    self._selected_point_label.setText(
                        f"{channel}  |  Time: {time_text}  |  Value: {value:.3f} V"
                    )
                    self._selected_point_label.setVisible(True)
                return
            self._expand_in_place(chart_widget, title)
            if self._selected_point_label is not None:
                self._selected_point_label.setText("")
                self._selected_point_label.setVisible(False)
        chart_widget.mousePressEvent = open_chart
        if hasattr(chart_widget, "chart_area"):
            chart_widget.chart_area.mousePressEvent = open_chart

    def _widget_grid_info(self, widget):
        """Return the grid and original position for a dashboard widget."""
        if widget is self.line_chart:
            return self._charts_grid, (0, 0, 1, 2)
        if widget is self.bar_chart:
            return self._charts_grid, (0, 2, 1, 1)
        if widget is self.donut_chart:
            return self._bottom_grid, (0, 0, 1, 1)
        if widget is getattr(self, "statistics_card", None):
            return self._bottom_grid, (0, 1, 1, 1)
        if widget is getattr(self, "recent_card", None):
            return self._bottom_grid, (0, 2, 1, 1)
        return None, None

    def _expand_in_place(self, widget, title):
        """Move one dashboard card into the large area in the same window."""
        if self._expanded_widget is widget:
            self._restore_dashboard()
            return
        grid, position = self._widget_grid_info(widget)
        if grid is None:
            return
        # Restore any previous expansion first.
        if self._expanded_widget is not None:
            self._restore_dashboard()
        self._expanded_widget = widget
        self._expanded_grid = grid
        self._expanded_position = position
        # Remove the selected card from its normal grid and move it to the
        # expansion area. No copy and no separate window are created.
        grid.removeWidget(widget)
        widget.setParent(self._expanded_content)
        self._expanded_content_layout.addWidget(widget, 1)
        self._expanded_title.setText(title)
        self._expanded_host.setVisible(True)
        # Keep the same window/header, but give the selected visualization
        # essentially the whole dashboard workspace.
        self._filter_card.setVisible(False)
        self._kpi_grid.setEnabled(False)
        self._kpi_grid_widget = getattr(self, "_kpi_grid_widget", None)
        # Hide the normal chart/table grids. The selected widget is already
        # re-parented, so hiding its old grid does not hide the expanded view.
        self._hide_dashboard_widgets_for_expand(widget)
        self._expanded_widget.setMinimumHeight(560)
        self._expanded_widget.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        # Give the expanded area enough room in the scrollable dashboard.
        self._expanded_host.setMinimumHeight(650)

    def _hide_dashboard_widgets_for_expand(self, selected):
        """Hide normal dashboard cards while one card is expanded."""
        dashboard_widgets = [
            self.total_kpi,
            self.average_kpi,
            self.maximum_kpi,
            self.minimum_kpi,
            self.line_chart,
            self.bar_chart,
            self.donut_chart,
            self.statistics_card,
            self.recent_card,
        ]
        for widget in dashboard_widgets:
            if widget is not selected:
                widget.setVisible(False)

    def _show_dashboard_widgets_after_restore(self):
        """Restore all normal dashboard cards."""
        for widget in [
            self.total_kpi,
            self.average_kpi,
            self.maximum_kpi,
            self.minimum_kpi,
            self.line_chart,
            self.bar_chart,
            self.donut_chart,
            self.statistics_card,
            self.recent_card,
        ]:
            widget.setVisible(True)

    def _restore_dashboard(self):
        """Return the selected card to its original dashboard position."""
        widget = self._expanded_widget
        grid = self._expanded_grid
        position = self._expanded_position
        if widget is None or grid is None or position is None:
            return
        self._expanded_content_layout.removeWidget(widget)
        widget.setParent(None)
        row, col, row_span, col_span = position
        grid.addWidget(widget, row, col, row_span, col_span)
        self._expanded_widget = None
        self._expanded_grid = None
        self._expanded_position = None
        self._expanded_host.setVisible(False)
        self._filter_card.setVisible(True)
        if self._selected_point_label is not None:
            self._selected_point_label.setText("")
            self._selected_point_label.setVisible(False)
        self._show_dashboard_widgets_after_restore()

    def _expand_table(self, title, table):
        """Expand the table's existing card in the same dashboard window."""
        if table is self.statistics_table:
            self._expand_in_place(
                self.statistics_card, "Channel Statistics"
            )
        elif table is self.recent_table:
            self._expand_in_place(
                self.recent_card, "Recent Readings"
            )

    def _populate_recent_readings(self, records):
        """Populate the Recent Readings table with the supplied records."""
        self.recent_table.setRowCount(max(len(records), 1))
        if not records:
            for col in range(9):
                self.recent_table.setItem(
                    0, col, QTableWidgetItem("—")
                )
            return
        for row, record in enumerate(records):
            timestamp = self._normalise_timestamp(record.get("timestamp"))
            timestamp_text = (
                timestamp.strftime("%d-%m-%Y %H:%M:%S")
                if timestamp else str(record.get("timestamp", "—"))
            )
            self.recent_table.setItem(
                row, 0, QTableWidgetItem(timestamp_text)
            )
            record_channels = record.get("channels", {}) or {}
            for index in range(1, 9):
                channel_data = record_channels.get(f"ch{index}", {})
                value = self._channel_value(channel_data)
                value_text = f"{value:.3f}" if value is not None else "—"
                self.recent_table.setItem(
                    row,
                    index,
                    QTableWidgetItem(value_text)
                )
        self.recent_table.resizeRowsToContents()

    def _toggle_all_readings(self):
        """Toggle between the latest 7 readings and all filtered MongoDB readings."""
        if not self._filtered_records:
            self._populate_recent_readings([])
            return
        self._showing_all_readings = not self._showing_all_readings
        if self._showing_all_readings:
            self._populate_recent_readings(self._filtered_records)
            self.view_all_button.setText("Show Recent")
        else:
            self._populate_recent_readings(self._filtered_records[:7])
            self.view_all_button.setText("View All")

    def _select_range(self, value):
        self._selected_range = value
        today = QDate.currentDate()
        if value == "1 Week":
            start = today.addDays(-7)
        elif value == "1 Month":
            start = today.addMonths(-1)
        elif value == "2 Months":
            start = today.addMonths(-2)
        elif value == "6 Months":
            start = today.addMonths(-6)
        elif value == "1 Year":
            start = today.addYears(-1)
        else:
            return
        self.from_date.setDate(start)
        self.to_date.setDate(today)
        self._refresh_dashboard_state()

    def _connect_mongodb(self):
        """Connect to the existing central Nelumbo MongoDB database."""
        if MongoDB is None:
            return
        try:
            self._mongo = MongoDB()
            self._mongo_collection = self._mongo.get_collection(
                "analog_input_test_data"
            )
            self._refresh_dashboard_state()
        except Exception:
            self._mongo = None
            self._mongo_collection = None
            self._clear_dashboard()

    def _clear_dashboard(self):
        self._filtered_records = []
        self._showing_all_readings = False
        if hasattr(self, "view_all_button"):
            self.view_all_button.setText("View All")
        self.total_kpi.value_label.setText("—")
        self.average_kpi.value_label.setText("—")
        self.maximum_kpi.value_label.setText("—")
        self.minimum_kpi.value_label.setText("—")
        self._line_point_times = {}
        self.line_chart.set_series({})
        self.bar_chart.set_values({})
        self.donut_chart.set_values({})
        for row in range(8):
            for col in range(1, 6):
                self.statistics_table.setItem(
                    row, col, QTableWidgetItem("—")
                )
        self.recent_table.setRowCount(7)
        for row in range(7):
            for col in range(9):
                self.recent_table.setItem(
                    row, col, QTableWidgetItem("—")
                )

    @staticmethod
    def _normalise_timestamp(value):
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            value = value.strip()
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%f",
            ):
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    pass
        return None

    @staticmethod
    def _channel_value(channel_data):
        if isinstance(channel_data, dict):
            value = channel_data.get("value")
        else:
            value = channel_data
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _refresh_dashboard_state(self):
        """Load the selected date range from MongoDB and update the dashboard."""
        if self._mongo_collection is None:
            self._connect_mongodb()
            if self._mongo_collection is None:
                return
        start_date = self.from_date.date().toPython()
        end_date = self.to_date.date().toPython()
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(
            end_date + timedelta(days=1),
            datetime.min.time()
        )
        try:
            cursor = self._mongo_collection.find(
                {
                    "device": "Analog Input",
                    "mode": "Test Mode",
                    "timestamp": {
                        "$gte": start_dt,
                        "$lt": end_dt,
                    },
                },
                {
                    "_id": 0,
                    "timestamp": 1,
                    "channels": 1,
                }
            ).sort("timestamp", 1)
            records = list(cursor)
            # Some existing records may contain timestamps as strings.
            # If the typed MongoDB date query returns nothing, read the
            # relevant collection records and filter parsed timestamps.
            if not records:
                fallback_cursor = self._mongo_collection.find(
                    {
                        "device": "Analog Input",
                        "mode": "Test Mode",
                    },
                    {
                        "_id": 0,
                        "timestamp": 1,
                        "channels": 1,
                    }
                ).sort("timestamp", 1)
                records = []
                for record in fallback_cursor:
                    timestamp = self._normalise_timestamp(
                        record.get("timestamp")
                    )
                    if timestamp and start_dt <= timestamp < end_dt:
                        records.append(record)
            self._populate_from_mongodb(records)
        except Exception:
            self._clear_dashboard()

    def _populate_from_mongodb(self, records):
        channels = {f"ch{i}": [] for i in range(1, 9)}
        channel_point_times = {f"CH{i}": [] for i in range(1, 9)}
        channel_timestamps = []
        for record in records:
            timestamp = self._normalise_timestamp(record.get("timestamp"))
            if timestamp:
                channel_timestamps.append(timestamp)
            record_channels = record.get("channels", {}) or {}
            for channel in channels:
                value = self._channel_value(
                    record_channels.get(channel)
                )
                if value is not None:
                    channels[channel].append(value)
                    if timestamp:
                        channel_point_times[channel.upper()].append(timestamp)
        all_values = [
            value
            for values in channels.values()
            for value in values
        ]
        if not all_values:
            self._clear_dashboard()
            return
        total_readings = len(records)
        average_value = statistics.mean(all_values)
        maximum_value = max(all_values)
        minimum_value = min(all_values)
        self.total_kpi.value_label.setText(f"{total_readings:,}")
        self.average_kpi.value_label.setText(f"{average_value:.2f} V")
        self.maximum_kpi.value_label.setText(f"{maximum_value:.2f} V")
        self.minimum_kpi.value_label.setText(f"{minimum_value:.2f} V")
        # Line chart.
        line_series = {}
        for index in range(1, 9):
            values = channels[f"ch{index}"]
            if values:
                line_series[f"CH{index}"] = values
        x_labels = []
        if channel_timestamps:
            count = len(channel_timestamps)
            sample_indexes = [
                round(i * (count - 1) / 5)
                for i in range(min(6, count))
            ]
            for idx in sample_indexes:
                x_labels.append(
                    channel_timestamps[idx].strftime("%d %b")
                )
        self._line_series_all = dict(line_series)
        self._line_x_labels = list(x_labels)
        self._line_point_times = dict(channel_point_times)
        visible_line_series = {
            name: values
            for name, values in line_series.items()
            if self.channel_checkboxes.get(name) is not None
            and self.channel_checkboxes[name].isChecked()
        }
        visible_point_times = {
            name: channel_point_times.get(name, [])
            for name in visible_line_series
        }
        self.line_chart.set_series(
            visible_line_series, x_labels, visible_point_times
        )
        # Per-channel comparison metrics and distribution.
        channel_averages = {}
        channel_maximums = {}
        channel_minimums = {}
        channel_distribution = {}
        for index in range(1, 9):
            key = f"ch{index}"
            values = channels[key]
            if values:
                channel_name = f"CH{index}"
                channel_averages[channel_name] = statistics.mean(values)
                channel_maximums[channel_name] = max(values)
                channel_minimums[channel_name] = min(values)
                channel_distribution[channel_name] = sum(values)
        self.bar_chart.set_metric_values(
            average_values=channel_averages,
            maximum_values=channel_maximums,
            minimum_values=channel_minimums,
        )
        self.donut_chart.set_values(channel_distribution)
        # Statistics table.
        for row in range(8):
            key = f"ch{row + 1}"
            values = channels[key]
            if values:
                average = statistics.mean(values)
                maximum = max(values)
                minimum = min(values)
                std_dev = (
                    statistics.stdev(values)
                    if len(values) > 1
                    else 0.0
                )
                row_values = [
                    f"CH{row + 1}",
                    f"{len(values):,}",
                    f"{average:.2f}",
                    f"{maximum:.2f}",
                    f"{minimum:.2f}",
                    f"{std_dev:.2f}",
                ]
            else:
                row_values = [f"CH{row + 1}", "0", "—", "—", "—", "—"]
            for col, value in enumerate(row_values):
                self.statistics_table.setItem(
                    row, col, QTableWidgetItem(value)
                )
        # Cache all filtered records so View All can display them.
        self._filtered_records = sorted(
            records,
            key=lambda record: (
                self._normalise_timestamp(record.get("timestamp"))
                or datetime.min
            ),
            reverse=True,
        )
        self._showing_all_readings = False
        self.view_all_button.setText("View All")
        self._populate_recent_readings(self._filtered_records[:7])
    # Public hooks for the existing project's real data layer.

    def set_dashboard_data(
        self,
        total_readings=None,
        average_value=None,
        maximum_value=None,
        minimum_value=None,
        channel_series=None,
        channel_averages=None,
        channel_distribution=None,
        channel_statistics=None,
        recent_readings=None,
        x_labels=None,
    ):
        """Populate the dashboard with real application data.
        This method does not generate or replace backend data. It accepts
        already-processed values from the project's existing data layer.
        """
        self.total_kpi.value_label.setText(
            "—" if total_readings is None else f"{total_readings:,}"
        )
        self.average_kpi.value_label.setText(
            "—" if average_value is None else f"{float(average_value):.2f} V"
        )
        self.maximum_kpi.value_label.setText(
            "—" if maximum_value is None else f"{float(maximum_value):.2f} V"
        )
        self.minimum_kpi.value_label.setText(
            "—" if minimum_value is None else f"{float(minimum_value):.2f} V"
        )
        self.line_chart.set_series(channel_series or {}, x_labels)
        self.bar_chart.set_values(channel_averages or {})
        self.donut_chart.set_values(channel_distribution or {})
        if channel_statistics:
            for row, channel in enumerate([f"CH{i}" for i in range(1, 9)]):
                data = channel_statistics.get(channel, {})
                values = [
                    channel,
                    data.get("total", "—"),
                    data.get("average", "—"),
                    data.get("maximum", "—"),
                    data.get("minimum", "—"),
                    data.get("std_dev", "—"),
                ]
                for col, value in enumerate(values):
                    self.statistics_table.setItem(
                        row, col, QTableWidgetItem(str(value))
                    )
        if recent_readings:
            self.recent_table.setRowCount(len(recent_readings))
            for row, record in enumerate(recent_readings):
                timestamp = record.get("timestamp", "—")
                self.recent_table.setItem(
                    row, 0, QTableWidgetItem(str(timestamp))
                )
                channels = record.get("channels", {})
                for channel_index in range(1, 9):
                    channel_key = f"ch{channel_index}"
                    channel_data = channels.get(channel_key, {})
                    value = channel_data.get("value", "—")
                    self.recent_table.setItem(
                        row,
                        channel_index,
                        QTableWidgetItem(str(value))
                    )

if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    window = AnalogInputDataAnalysisView()
    window.showMaximized()
    sys.exit(app.exec())