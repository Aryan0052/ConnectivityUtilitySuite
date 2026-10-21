"""White + teal analytics Dashboard tab (replaces the first light Dashboard).

Modes
  LIVE          rolling window over the readings the scanner is receiving right now
  15 MIN .. 7 D a period ending now, read from MongoDB
  CUSTOM        any From / To, read from MongoDB
  FILE          a CSV imported by the user (the database and the bus are not touched)

In every mode the same analysis (analytics.py) runs over the same kind of documents,
so the numbers mean the same thing whether they come from the bus, the database or a file.
Database reads and CSV parsing run in worker threads; the GUI thread only paints.
"""
import os
import time
from bisect import bisect_left
from collections import deque
from datetime import datetime, timedelta

from PySide6.QtCore import Qt, QTimer, QDateTime, QRectF, QSizeF, QMarginsF
from PySide6.QtGui import QPainter, QColor, QPixmap, QRadialGradient, QPdfWriter, QPageSize, QPageLayout
from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox, QPushButton, QScrollArea,
    QDateTimeEdit, QFileDialog, QTableWidget, QAbstractItemView, QHeaderView, QTableWidgetItem, QStackedWidget,
    QSizePolicy, QButtonGroup,
)

try:
    from . import analytics as A
    from . import neon_widgets as NW
    from .neon_widgets import (NeonCard, Chip, KpiTile, RingScore, ArcGauge, SeriesChart, BrushBar, HistChart,
                               LaneChart, HBars, HeatMap, ChannelTile, DigitalTile, InsightList, rolling_minmax,
                               FreshnessStrip, ValueBoard, StatusTimeline, qc, font, chip_style, FONT, BG, BLUE, TEAL, VIOLET, GREEN, RED, AMBER, WHITE,
                               MUTED, SERIES, TAG_COLORS, SURFACE, SOFT, BORDER, FAINT, GRID, TRACK, INDIGO, ACCENT_SOFT, PINK, TEXT)
    from .history_views import run_async, _error_text, _DeviceCombo
    from .db_history import period_snapshot, list_stored_devices, diagnose
except ImportError:
    import analytics as A
    import neon_widgets as NW
    from neon_widgets import (NeonCard, Chip, KpiTile, RingScore, ArcGauge, SeriesChart, BrushBar, HistChart,
                              LaneChart, HBars, HeatMap, ChannelTile, DigitalTile, InsightList, rolling_minmax,
                              FreshnessStrip, ValueBoard, StatusTimeline, qc, font, chip_style, FONT, BG, BLUE, TEAL, VIOLET, GREEN, RED, AMBER, WHITE,
                              MUTED, SERIES, TAG_COLORS, SURFACE, SOFT, BORDER, FAINT, GRID, TRACK, INDIGO, ACCENT_SOFT, PINK, TEXT)
    from history_views import run_async, _error_text, _DeviceCombo
    from db_history import period_snapshot, list_stored_devices, diagnose

PRESETS = (("LIVE", None), ("15 MIN", 900), ("1 H", 3600), ("24 H", 86400), ("7 D", 604800), ("CUSTOM", -1))
LIVE_WINDOWS = (("5 min", 300), ("15 min", 900), ("1 hour", 3600))
AUTO_REFRESH_S = 30


def make_qss():
    """Style sheet for the Dashboard, built from the current palette (see neon_widgets.PALETTES)."""
    return f"""
#neonRoot {{ background:{BG}; }}
QScrollArea {{ background:transparent; border:none; }}
QScrollArea > QWidget > QWidget {{ background:transparent; }}
QLabel {{ background:transparent; font-family:'{FONT}'; }}
QComboBox, QDateTimeEdit {{ background:{SURFACE}; color:{WHITE}; border:1px solid {BORDER}; border-radius:8px;
    padding:4px 10px; min-height:24px; font-family:'{FONT}'; font-size:12px; font-weight:500; }}
QComboBox:disabled, QDateTimeEdit:disabled {{ color:{FAINT}; background:{SOFT}; }}
QComboBox:hover, QDateTimeEdit:hover {{ border-color:{FAINT}; }}
QComboBox:focus, QDateTimeEdit:focus {{ border-color:{BLUE}; }}
QComboBox::drop-down, QDateTimeEdit::drop-down {{ border:none; width:22px; }}
QComboBox QAbstractItemView {{ background:{SURFACE}; color:{WHITE}; border:1px solid {BORDER};
    selection-background-color:{ACCENT_SOFT}; selection-color:{WHITE}; outline:none; }}
QCalendarWidget QWidget {{ background:{SURFACE}; color:{WHITE}; }}
QCalendarWidget QAbstractItemView {{ selection-background-color:{ACCENT_SOFT}; selection-color:{WHITE}; }}
QPushButton#seg {{ background:transparent; color:{MUTED}; border:none; border-radius:7px; padding:5px 12px;
    font-family:'{FONT}'; font-size:12px; font-weight:600; }}
QPushButton#seg:hover {{ color:{WHITE}; }}
QPushButton#seg:checked {{ color:{WHITE}; background:{SURFACE}; border:1px solid {BORDER}; }}
QPushButton#segV {{ background:transparent; color:{MUTED}; border:none; border-radius:7px; padding:5px 12px;
    font-family:'{FONT}'; font-size:12px; font-weight:600; }}
QPushButton#segV:hover {{ color:{WHITE}; }}
QPushButton#segV:checked {{ color:{WHITE}; background:{SURFACE}; border:1px solid {BORDER}; }}
QPushButton#neonBtn, QPushButton#neonV {{ color:{WHITE}; background:{SURFACE}; border:1px solid {BORDER};
    border-radius:8px; padding:7px 14px; font-family:'{FONT}'; font-size:12px; font-weight:600; }}
QPushButton#neonBtn:hover, QPushButton#neonV:hover {{ background:{SOFT}; border-color:{FAINT}; }}
QPushButton#neonBtn:disabled, QPushButton#neonV:disabled {{ color:{FAINT}; background:transparent; }}
QPushButton#neonP {{ color:#FFFFFF; border:none; border-radius:8px; padding:7px 16px; font-family:'{FONT}';
    font-size:12px; font-weight:600; background:{BLUE}; }}
QPushButton#neonP:hover {{ background:{INDIGO}; }}
QPushButton#neonP:disabled {{ background:{TRACK}; color:{FAINT}; }}
QPushButton#legend {{ color:{TEXT}; background:{SURFACE}; border:1px solid {BORDER}; border-radius:11px; padding:3px 10px;
    font-family:'{FONT}'; font-size:11px; font-weight:600; }}
QTableWidget {{ background:transparent; color:{TEXT}; border:none; gridline-color:transparent; font-size:12px;
    font-family:'{FONT}'; selection-background-color:{ACCENT_SOFT}; selection-color:{WHITE}; }}
QTableWidget::item {{ border-bottom:1px solid {GRID}; padding:2px 6px; }}
QHeaderView {{ background:transparent; }}
QTableCornerButton::section {{ background:transparent; border:none; }}
QHeaderView::section {{ background:transparent; color:{MUTED}; border:none; border-bottom:1px solid {BORDER};
    padding:6px; font-size:11px; font-weight:600; font-family:'{FONT}'; }}
QScrollBar:vertical {{ background:transparent; width:10px; margin:0; }}
QScrollBar::handle:vertical {{ background:{BORDER}; border-radius:4px; min-height:30px; margin:2px; }}
QScrollBar::handle:vertical:hover {{ background:{FAINT}; }}
QScrollBar:horizontal {{ background:transparent; height:10px; }}
QScrollBar::handle:horizontal {{ background:{BORDER}; border-radius:4px; min-width:30px; margin:2px; }}
QScrollBar::handle:horizontal:hover {{ background:{FAINT}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width:0; height:0; }}
QToolTip {{ background:{SURFACE}; color:{WHITE}; border:1px solid {BORDER}; }}
"""


# ------------------------------------------------------------------------------------ pure job
def build_period_result(kind, docs, prev_docs, pair_docs, limit_for, th=None):
    """Runs in a worker thread: all analysis for one period (pure Python, no Qt)."""
    result = A.analyze(kind, docs, limit_for, th)
    prev = A.analyze(kind, prev_docs, limit_for, th) if prev_docs else None
    feedback = []
    if kind == "DO" and pair_docs and result["n"]:
        feedback = A.feedback_check(result, A.analyze_digital(pair_docs, "DI", th), th)
    return {"result": result, "prev": prev, "feedback": feedback,
            "compare": A.compare_results(result, prev) if prev else []}


class _Backdrop(QWidget):
    """Content widget: the plain page background (no grid, no glows)."""

    def __init__(self):
        super().__init__()
        self.setObjectName("neonContent")

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG))
        p.end()


class _Segmented(QWidget):
    """Segmented selector: sunken track, the checked segment is a raised white chip."""

    def __init__(self, items, violet=False, parent=None):
        super().__init__(parent)
        self._buttons = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.retheme()
        for text in items:
            b = QPushButton(text)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self._group.addButton(b)
            lay.addWidget(b)
            self._buttons[text] = b
        first = next(iter(self._buttons.values()))
        first.setChecked(True)

    def retheme(self):
        self.setStyleSheet(f"_Segmented{{background:{SOFT};border:1px solid {BORDER};border-radius:10px;}}")

    def value(self):
        for k, b in self._buttons.items():
            if b.isChecked():
                return k

    def set_value(self, text, emit=False):
        self._group.blockSignals(not emit)
        self._buttons[text].setChecked(True)
        self._group.blockSignals(False)

    def connect(self, slot):
        self._group.buttonClicked.connect(lambda _b: slot(self.value()))


def _field(caption, widget):
    box = QVBoxLayout()
    box.setSpacing(2)
    lab = QLabel(caption)
    lab.setStyleSheet(f"color:{MUTED};font-size:11px;font-weight:600;")
    box.addWidget(lab)
    box.addWidget(widget)
    return box


def _button(text, name, handler):
    b = QPushButton(text)
    b.setObjectName(name)
    b.setCursor(Qt.PointingHandCursor)
    b.clicked.connect(handler)
    return b


def _rich(text="", size=12, color=None):
    lab = QLabel(text)
    lab.setTextFormat(Qt.RichText)
    lab.setWordWrap(True)
    lab.setProperty("rich_size", size)
    lab.setStyleSheet(f"color:{color or TEXT};font-size:{size}px;")
    return lab


# ------------------------------------------------------------------------------------ the tab
class DashboardTab(QWidget):
    def __init__(self, engine, get_devices, get_stats, get_runtime, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._get_devices = get_devices
        self._get_stats = get_stats
        self._get_runtime = get_runtime
        self.session = A.SessionData()
        self.imported = None                  # load_csv() result while in FILE mode
        self._stored = []
        self._db_ok = None
        self._db_error = ""
        self._req = 0
        self._busy = False
        self._view = None                     # {"result","prev","feedback","compare"} currently shown
        self._live = True
        self._docs = []                       # docs behind the current view (for CSV export)
        self._pair_docs = []
        self._events = []
        self._loaded = None                   # {"ts","vals","range"} overview of the loaded period
        self._range_shown = (datetime.now(), datetime.now())
        self._hidden = set()
        self._focus = None
        self._tile_sig = None
        self._legend_sig = None
        self._live_rev = -1
        self._live_key = None
        self._last_live_calc = 0.0
        self._last_auto = time.monotonic()
        self._sig_scores = {}
        self._spark = {k: deque(maxlen=60) for k in ("online", "alarms", "success", "resp", "thr", "saved")}
        self._spark_acc = 0.0
        self._last = time.monotonic()
        self._status_msg = ""
        self._status_hist = {}                # sid -> deque of (t, status), one sample per second
        self._expanded_card = None
        self._card_state = {}
        self.setObjectName("neonRoot")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(make_qss())
        self.setAcceptDrops(True)
        self._build()
        self._wire_cards()
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ================================================================== theme
    def apply_theme(self, name):
        """Light / dark for the Dashboard (same palette family as the Live console)."""
        NW.set_theme(name)
        self.setStyleSheet(make_qss())
        self.title.setStyleSheet(f"font-size:22px;font-weight:700;color:{WHITE};")
        self.strip.setStyleSheet(f"QFrame#dashStrip{{background:{SOFT};border:1px solid {BORDER};border-radius:10px;}}")
        self.source_label.setStyleSheet(f"color:{MUTED};font-size:12px;border:none;background:transparent;")
        for w in self.findChildren(QWidget):
            if hasattr(w, "retheme"):
                w.retheme()
            w.update()
        self._legend_sig = None
        self._tile_sig = None
        self._dist_sig = None
        try:
            self._render_current()
        except Exception:
            pass

    # ================================================================== build
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)      # light margin like the other tabs: the dark page never touches the header/tabs
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.content = _Backdrop()
        self.scroll.setWidget(self.content)
        outer.addWidget(self.scroll)
        root = QVBoxLayout(self.content)
        root.setContentsMargins(22, 18, 22, 28)
        root.setSpacing(16)

        # ---- title row
        title = QHBoxLayout()
        self.title = QLabel("Analysis")
        self.title.setObjectName("dashTitle")
        title.addWidget(self.title)
        self.chip_live = Chip("● LIVE", GREEN)
        title.addWidget(self.chip_live)
        title.addStretch(1)
        self.pill_conn, self.pill_db, self.pill_session, self.pill_clock = Chip(), Chip(), Chip(), Chip()
        for pill in (self.pill_conn, self.pill_db, self.pill_session, self.pill_clock):
            title.addWidget(pill)
        root.addLayout(title)

        # ---- period bar
        bar = NeonCard("", BLUE)
        grid = QHBoxLayout()
        grid.setSpacing(14)
        lab = QLabel("Period")
        lab.setStyleSheet(f"color:{MUTED};font-size:11px;font-weight:600;")
        self.seg_period = _Segmented([p[0] for p in PRESETS], violet=True)
        self.seg_period.connect(self._period_changed)
        self.live_window = QComboBox()
        for text, secs in LIVE_WINDOWS:
            self.live_window.addItem(text, secs)
        self.live_window.setCurrentIndex(1)
        self.live_window.currentIndexChanged.connect(self._live_window_changed)
        self.edit_from, self.edit_to = QDateTimeEdit(), QDateTimeEdit()
        for e in (self.edit_from, self.edit_to):
            e.setDisplayFormat("dd MMM yyyy · HH:mm:ss")
            e.setCalendarPopup(True)
            e.setMinimumWidth(190)
        now = datetime.now()
        self.edit_to.setDateTime(QDateTime(now))
        self.edit_from.setDateTime(QDateTime(now - timedelta(hours=1)))
        self.btn_apply = _button("Analyse", "neonP", self._apply_custom)
        self.seg_kind = _Segmented(["AI", "DI", "DO"])
        self.seg_kind.connect(self._kind_changed)
        self.device_combo = _DeviceCombo(kinds=("AI",))
        self.device_combo.setMinimumWidth(210)
        self.device_combo.currentIndexChanged.connect(self._device_changed)
        grid.addWidget(lab)
        grid.addWidget(self.seg_period)
        self.live_box = QWidget()
        lb = QVBoxLayout(self.live_box)
        lb.setContentsMargins(0, 0, 0, 0)
        lb.addLayout(_field("Live window", self.live_window))
        grid.addWidget(self.live_box)
        self.range_box = QWidget()
        rb = QHBoxLayout(self.range_box)
        rb.setContentsMargins(0, 0, 0, 0)
        rb.setSpacing(10)
        rb.addLayout(_field("From", self.edit_from))
        rb.addLayout(_field("To", self.edit_to))
        rb.addWidget(self.btn_apply, 0, Qt.AlignBottom)
        grid.addWidget(self.range_box)
        grid.addSpacing(6)
        grid.addLayout(_field("Signal", self.seg_kind))
        grid.addLayout(_field("Device", self.device_combo))
        grid.addStretch(1)
        self.btn_import = _button("Import CSV", "neonV", self._import_csv)
        self.btn_export = _button("Export CSV", "neonBtn", self._export_csv)
        self.btn_report = _button("Export report", "neonP", self._export_report)
        for b in (self.btn_import, self.btn_export, self.btn_report):
            grid.addWidget(b, 0, Qt.AlignBottom)
        bar.body.addLayout(grid)
        bar.layout().setContentsMargins(18, 14, 18, 14)
        root.addWidget(bar)

        # ---- source strip
        strip = QFrame()
        strip.setObjectName("dashStrip")
        self.strip = strip
        sl = QHBoxLayout(strip)
        sl.setContentsMargins(14, 6, 10, 6)
        self.source_label = QLabel()
        self.source_label.setTextFormat(Qt.RichText)
        self.source_label.setObjectName("dashSource")
        self.btn_close_file = _button("Close file", "neonBtn", self._close_file)
        self.btn_close_file.hide()
        sl.addWidget(self.source_label, 1)
        sl.addWidget(self.btn_close_file)
        root.addWidget(strip)

        # ---- KPI row
        krow = QHBoxLayout()
        krow.setSpacing(16)
        self.kpis = [KpiTile() for _ in range(6)]
        for k in self.kpis:
            krow.addWidget(k, 1)
        root.addLayout(krow)

        # ---- data freshness strip (live only)
        self.fresh_card = NeonCard("Data Freshness", TEAL)
        self.fresh_card.add_chip("TIME SINCE LAST READING", TEAL)
        self.fresh = FreshnessStrip()
        self.fresh_card.body.addWidget(self.fresh)
        root.addWidget(self.fresh_card)

        # ---- main row: live values | chart/lanes | insights
        main = QHBoxLayout()
        main.setSpacing(16)
        self.health_card = NeonCard("Live Values", GREEN)
        self.health_card.setFixedWidth(330)
        self.chip_values = self.health_card.add_chip("NOW \u00b7 TREND", GREEN)
        self.values = ValueBoard()
        self.values_scroll = QScrollArea()          # many channels: scroll inside the card, never stretch the page
        self.values_scroll.setWidget(self.values)
        self.values_scroll.setWidgetResizable(True)
        self.values_scroll.setFrameShape(QFrame.NoFrame)
        self.values_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.values_scroll.setMinimumHeight(420)
        self.values_scroll.setMaximumHeight(16777215)
        self.values_scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}"
                                         "QScrollArea > QWidget > QWidget{background:transparent;}")
        self.health_card.body.addWidget(self.values_scroll, 1)
        main.addWidget(self.health_card)

        self.chart_card = NeonCard("Live Rolling Analysis", BLUE)
        self.chip_chart_a = self.chart_card.add_chip("STREAMING", GREEN)
        self.chip_chart_b = self.chart_card.add_chip("MOVING AVG", VIOLET)
        self.focus_combo = QComboBox()
        self.focus_combo.setMinimumWidth(90)
        self.focus_combo.currentIndexChanged.connect(self._focus_changed)
        self.chart_card.header.addWidget(self.focus_combo)
        # many channels: the legend scrolls sideways instead of stretching the whole page
        self.legend_holder = QWidget()
        self.legend_holder.setStyleSheet("background:transparent;")
        self.legend_row = QHBoxLayout(self.legend_holder)
        self.legend_row.setContentsMargins(0, 0, 0, 0)
        self.legend_row.setSpacing(6)
        self.legend_row.addStretch(1)
        self.legend_scroll = QScrollArea()
        self.legend_scroll.setWidget(self.legend_holder)
        self.legend_scroll.setWidgetResizable(True)
        self.legend_scroll.setFrameShape(QFrame.NoFrame)
        self.legend_scroll.setFixedHeight(52)
        self.legend_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.legend_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.legend_scroll.setMinimumWidth(0)
        self.legend_scroll.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.legend_scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}"
                                         "QScrollArea > QWidget > QWidget{background:transparent;}")
        self.chart_card.body.addWidget(self.legend_scroll)
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("QStackedWidget{background:transparent;}")
        self.chart = SeriesChart(min_height=300)
        self.lanes = LaneChart()
        self.stack.addWidget(self.chart)
        self.stack.addWidget(self.lanes)
        self.chart_card.body.addWidget(self.stack, 1)
        self.brush = BrushBar()
        self.brush.rangeChanged.connect(self._brush_changed)
        self.chart_card.body.addWidget(self.brush)
        main.addWidget(self.chart_card, 1)

        self.insight_card = NeonCard("Live Insights", VIOLET)
        self.insight_card.setFixedWidth(430)
        self.chip_insight = self.insight_card.add_chip("AUTO-DETECTED", VIOLET)
        self.insights = InsightList(limit=7)
        self.insight_card.body.addWidget(self.insights)
        self.report_label = _rich("", 12)
        self.insight_card.body.addWidget(self.report_label)
        self.compare_label = _rich("", 11)
        self.insight_card.body.addWidget(self.compare_label)
        self.insight_card.body.addStretch(1)
        main.addWidget(self.insight_card)
        root.addLayout(main)

        # ---- device status timeline (live only)
        self.timeline_card = NeonCard("Device Status Timeline", BLUE)
        self.chip_timeline = self.timeline_card.add_chip("THIS SESSION", BLUE)
        self.timeline = StatusTimeline()
        self.timeline_card.body.addWidget(self.timeline)
        root.addWidget(self.timeline_card)

        # ---- AI group
        self.grp_ai = QWidget()
        ai = QVBoxLayout(self.grp_ai)
        ai.setContentsMargins(0, 0, 0, 0)
        ai.setSpacing(16)
        self.chan_card = NeonCard("Channel Health & Anomaly Detection", BLUE)
        self.chan_card.add_chip("SCORE = STABILITY · NOISE · DRIFT · LIMIT RISK", BLUE)
        self.chan_grid = QGridLayout()
        self.chan_grid.setSpacing(14)
        self.chan_card.body.addLayout(self.chan_grid)
        ai.addWidget(self.chan_card)
        self.stats_card = NeonCard("Channel Statistics · selected period only", BLUE)
        self.stats_card.add_chip("CLICK A ROW TO FOCUS THE CHART", BLUE)
        self.stats_table = QTableWidget(0, 10)
        self.stats_table.setHorizontalHeaderLabels(["CHANNEL", "UNIT", "MIN", "MAX", "MEAN", "σ", "TREND", "STATE",
                                                    "BREACHES", "TIME IN ALARM"])
        self._style_table(self.stats_table)
        self.stats_table.cellClicked.connect(self._table_clicked)
        self.stats_card.body.addWidget(self.stats_table)
        ai.addWidget(self.stats_card)
        row = QHBoxLayout()
        row.setSpacing(16)
        self.fc_card = NeonCard("Limit Forecast", VIOLET)
        self.chip_fc = self.fc_card.add_chip("NO LIMIT SET", MUTED)
        self.fc_chart = SeriesChart(min_height=230)
        self.fc_card.body.addWidget(self.fc_chart)
        self.dist_card = NeonCard("Value Distribution", TEAL)
        self.chip_dist = self.dist_card.add_chip("WINDOW", BLUE)
        self.dist_chart = HistChart(min_height=210)
        self.dist_card.body.addWidget(self.dist_chart)
        self.dist_stats = _rich("", 11)
        self.dist_card.body.addWidget(self.dist_stats)
        self.roc_card = NeonCard("Rate of Change · all channels", AMBER)
        self.roc_card.add_chip("PER MINUTE", BLUE)
        self.roc_bars = HBars()
        self.roc_card.body.addWidget(self.roc_bars)
        self.roc_card.body.addStretch(1)
        row.addWidget(self.fc_card, 5)
        row.addWidget(self.dist_card, 4)
        row.addWidget(self.roc_card, 4)
        ai.addLayout(row)
        root.addWidget(self.grp_ai)

        # ---- digital group
        self.grp_dig = QWidget()
        dg = QVBoxLayout(self.grp_dig)
        dg.setContentsMargins(0, 0, 0, 0)
        dg.setSpacing(16)
        drow = QHBoxLayout()
        drow.setSpacing(16)
        self.tog_card = NeonCard("Change Count per Channel", BLUE)
        self.tog_card.add_chip("PERIOD", BLUE)
        self.tog_bars = HBars()
        self.tog_card.body.addWidget(self.tog_bars)
        self.duty_card = NeonCard("ON Time (duty cycle)", TEAL)
        self.duty_card.add_chip("% OF PERIOD", BLUE)
        self.duty_bars = HBars()
        self.duty_card.body.addWidget(self.duty_bars)
        self.third_card = NeonCard("Longest ON", GREEN)
        self.chip_third = self.third_card.add_chip("PER CHANNEL", BLUE)
        self.third_bars = HBars()
        self.third_card.body.addWidget(self.third_bars)
        for c in (self.tog_card, self.duty_card, self.third_card):
            drow.addWidget(c, 1)
        dg.addLayout(drow)
        self.dtile_card = NeonCard("Channel Health", BLUE)
        self.chip_dtile = self.dtile_card.add_chip("", BLUE)
        self.dtile_grid = QGridLayout()
        self.dtile_grid.setSpacing(14)
        self.dtile_card.body.addLayout(self.dtile_grid)
        dg.addWidget(self.dtile_card)
        self.fb_card = NeonCard("DO → DI Feedback Check", AMBER)
        self.chip_fb = self.fb_card.add_chip("", AMBER)
        self.fb_table = QTableWidget(0, 6)
        self.fb_table.setHorizontalHeaderLabels(["COMMAND", "FEEDBACK", "SENT", "CONFIRMED", "AVG DELAY", "RESULT"])
        self._style_table(self.fb_table)
        self.fb_card.body.addWidget(self.fb_table)
        dg.addWidget(self.fb_card)
        root.addWidget(self.grp_dig)

        # ---- communication analytics (live)
        self.grp_comm = QWidget()
        cm = QHBoxLayout(self.grp_comm)
        cm.setContentsMargins(0, 0, 0, 0)
        cm.setSpacing(16)
        self.rt_card = NeonCard("Response Time", VIOLET)
        self.rt_hist = HistChart(min_height=200)
        self.rt_card.body.addWidget(self.rt_hist)
        self.lat_card = NeonCard("Latency per Device", BLUE)
        self.lat_card.add_chip("ms · LAST 15 MIN", BLUE)
        self.lat_chart = SeriesChart(min_height=200)
        self.lat_card.body.addWidget(self.lat_chart)
        self.heat_card = NeonCard("Reliability · success % per 5 min", GREEN)
        self.heat = HeatMap()
        self.heat_card.body.addWidget(self.heat)
        self.heat_card.body.addStretch(1)
        self.bus_card = NeonCard("Bus Load", TEAL)
        self.bus_card.setFixedWidth(220)
        self.bus_gauge = ArcGauge("bus busy")
        self.bus_card.body.addWidget(self.bus_gauge)
        cm.addWidget(self.rt_card, 4)
        cm.addWidget(self.lat_card, 5)
        cm.addWidget(self.heat_card, 5)
        cm.addWidget(self.bus_card)
        root.addWidget(self.grp_comm)
        root.addStretch(1)

        for name in ("grp_ai", "grp_dig", "grp_comm", "live_box", "range_box"):
            box = getattr(self, name)
            box.setObjectName(name)
            box.setStyleSheet(f"#{name}{{background:transparent;}}")
        self.grp_dig.hide()
        self._apply_mode_visibility()
        self._update_source()

    def _style_table(self, table):
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(30)
        table.setShowGrid(False)
        table.setFocusPolicy(Qt.NoFocus)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def _kpi(self, i, title, *args, **kwargs):
        tile = self.kpis[i]
        if tile.title != title:
            tile.title = title
            tile._sig = None
        tile.set(*args, **kwargs)

    # ================================================================== public hooks (used by the view)
    def set_devices(self, devices):
        self.device_combo.set_devices(devices)
        self._device_changed()

    def on_response(self, slave_id, elapsed_ms):
        self.session.add_response(slave_id, elapsed_ms, time.time())

    def on_failure(self, slave_id, elapsed_ms):
        self.session.add_failure(slave_id, elapsed_ms, time.time())

    def on_reading(self, slave_id, kind, reading):
        self.session.add_reading(slave_id, kind, reading.timestamp, reading.channels, reading.units, reading.quality)

    def reset_session(self):
        self.session.clear()
        self._status_hist.clear()
        for series in self._spark.values():
            series.clear()
        self._live_key = None

    def fetch(self):
        self._run_period()

    def showEvent(self, event):
        super().showEvent(event)
        run_async(self, list_stored_devices, self._stored_loaded)
        self._live_key = None
        self._tick()

    def _stored_loaded(self, result, error):
        if error is None:
            self._stored = result
            self.device_combo.set_stored(result)
            self._device_changed()
            self._db_ok, self._db_error = True, ""
        else:
            self._db_ok, self._db_error = False, _error_text(error)

    # ================================================================== selection helpers
    def _mode(self):
        return self.seg_period.value()

    def _is_live(self):
        return self._mode() == "LIVE" and self.imported is None

    def _selected(self):
        data = self.device_combo.currentData()
        return (data[0], data[1], data[2]) if data else None

    def _limit_for(self, sid, snapshot=True):
        limits = dict(self.engine.limits) if snapshot else self.engine.limits
        if sid is None:
            return None
        return lambda ch: limits.get((sid, ch))

    def _range(self):
        mode = self._mode()
        secs = dict(PRESETS).get(mode)
        if self.imported is not None and mode != "CUSTOM":
            end = self.imported["docs"][-1]["timestamp"]
            start = end - timedelta(seconds=secs) if secs and secs > 0 else self.imported["docs"][0]["timestamp"]
            return start, end
        if mode == "CUSTOM":
            return self.edit_from.dateTime().toPython(), self.edit_to.dateTime().toPython()
        end = datetime.now()
        return end - timedelta(seconds=secs or 900), end

    def _apply_mode_visibility(self):
        if self._expanded_card is not None and not getattr(self, "_collapsing", False):
            self._collapse_card()
            return
        live = self._is_live()
        self.live_box.setVisible(live)
        self.range_box.setVisible(self._mode() == "CUSTOM")
        self.health_card.setVisible(live)
        self.fresh_card.setVisible(live)
        self.timeline_card.setVisible(live)
        self.grp_comm.setVisible(live)
        self.brush.setVisible(not live and self.stack.currentIndex() == 0)
        self.chip_live.setVisible(live)
        self.btn_close_file.setVisible(self.imported is not None)
        self.chart_card.title_label.setText("LIVE ROLLING ANALYSIS" if live else "PERIOD ANALYSIS")
        self.insight_card.title_label.setText("LIVE INSIGHTS" if live else "PERIOD REPORT")
        self.chip_chart_a.setText("STREAMING" if live else "PERIOD")
        self.report_label.setVisible(not live)
        self.compare_label.setVisible(not live)
        self.stats_card.setVisible(not live and self._kind() == "AI")
        self.chan_card.setVisible(self._kind() == "AI")
        self.device_combo.setEnabled(self.imported is None)
        self.seg_kind.setEnabled(self.imported is None)

    def _kind(self):
        return self.seg_kind.value()

    # ================================================================== user actions
    def _period_changed(self, _value):
        self._apply_mode_visibility()
        self._req += 1
        self._view = None
        if self._mode() == "LIVE" and self.imported is None:
            self._live_key = None
            self._tick()
        elif self._mode() != "CUSTOM":
            self._run_period()
        else:                              # CUSTOM: start from the last range, run on ANALYSE
            if self.imported is None:
                self._run_period()

    def _live_window_changed(self, _i):
        self._live_key = None
        self._tick()

    def _kind_changed(self, kind):
        self.device_combo._kinds = (kind,)
        self.device_combo._populate()
        self._focus = None
        self._hidden.clear()
        self._apply_mode_visibility()
        self._device_changed()

    def _device_changed(self, *_):
        self._focus = None
        self._hidden.clear()
        self._view = None
        self._live_key = None
        self._req += 1
        if self._is_live():
            self._tick()
        elif self.imported is None and self.isVisible():
            self._run_period()
        else:
            self._render_empty("Choose a device")

    def _focus_changed(self, _i):
        name = self.focus_combo.currentText()
        if name and name != self._focus:
            self._focus = name
            self._render_current()

    def _table_clicked(self, row, _col):
        item = self.stats_table.item(row, 0)
        if item:
            self._set_focus(item.text())

    def _set_focus(self, name):
        self._focus = name
        self.focus_combo.blockSignals(True)
        i = self.focus_combo.findText(name)
        if i >= 0:
            self.focus_combo.setCurrentIndex(i)
        self.focus_combo.blockSignals(False)
        self._render_current()

    def _apply_custom(self):
        start, end = self._range()
        if end <= start:
            self._set_status("To must be later than From.", True)
            return
        self._run_period()

    def _brush_changed(self, t0, t1):
        """Narrow the analysed period using the data already loaded (no database query)."""
        if self._live or not self._docs:
            return
        start, end = datetime.fromtimestamp(t0), datetime.fromtimestamp(t1)
        self.seg_period.set_value("CUSTOM")
        self.edit_from.setDateTime(QDateTime(start))
        self.edit_to.setDateTime(QDateTime(end))
        self._apply_mode_visibility()
        sel = self._selected()
        kind = self.imported["kind"] if self.imported else (sel[1] if sel else self._kind())
        docs = A.slice_docs(self._docs, start, end)
        pair = A.slice_docs(self._pair_docs, start, end) if self._pair_docs else []
        limit_for = self._limit_for(self._sid_for_limits())
        self._req += 1
        token = self._req
        self._busy = True
        self._set_status("Re-analysing the narrowed period…")
        run_async(self, lambda: build_period_result(kind, docs, [], pair, limit_for),
                  lambda res, err: self._period_done(token, res, err, kind, docs, self._pair_docs, self._events,
                                                     (start, end), keep_loaded=True, capped=False))

    def _sid_for_limits(self):
        if self.imported is not None:
            sl = self.imported.get("slaves") or []
            return int(sl[0]) if sl and str(sl[0]).isdigit() else None
        sel = self._selected()
        return sel[0] if sel else None

    # ================================================================== period analysis (DB / file)
    def _run_period(self):
        if self._is_live():
            return
        if self.imported is None and self._selected() is None:
            self._render_empty("No device selected. Add a device on the Live tab, or import a CSV.")
            return
        start, end = self._range()
        if end <= start:
            self._set_status("To must be later than From.", True)
            return
        self._req += 1
        token = self._req
        self._busy = True
        self._last_auto = time.monotonic()
        self._set_status("Loading and analysing…")
        limit_for = self._limit_for(self._sid_for_limits())
        if self.imported is not None:
            imp = self.imported
            span = end - start

            def job():
                docs = A.slice_docs(imp["docs"], start, end)
                prev = A.slice_docs(imp["docs"], start - span, start)
                out = build_period_result(imp["kind"], docs, prev, [], limit_for)
                out.update(docs=docs, pair_docs=[], events=[], capped=False)
                return out
            kind = imp["kind"]
        else:
            sid, kind, _name = self._selected()
            pair = self._pair_device() if kind == "DO" else None

            def job():
                snap = period_snapshot(kind, sid, start, end, pair)
                out = build_period_result(kind, snap["docs"], snap["prev"], snap["pair_docs"], limit_for)
                out.update(docs=snap["docs"], pair_docs=snap["pair_docs"], events=snap["events"],
                           capped=snap["capped"])
                return out
        run_async(self, job, lambda res, err: self._period_done(
            token, res, err, kind, None, None, None, (start, end), keep_loaded=False, capped=None))

    def _pair_device(self):
        cands = [(d["slave_id"], "DI") for d in self._get_devices() if d.get("kind") == "DI"]
        cands += [(s, k) for s, k in self._stored if k == "DI"]
        return min(cands) if cands else None

    def _period_done(self, token, res, err, kind, docs, pair_docs, events, rng, keep_loaded, capped):
        if token != self._req:
            return
        self._busy = False
        if err is not None:
            self._db_ok, self._db_error = False, _error_text(err)
            self._set_status(f"Database error: {self._db_error}", True)
            self._render_empty("Could not read the database. Check the connection, then press ANALYSE.")
            return
        if self.imported is None:
            self._db_ok, self._db_error = True, ""
        if res.get("docs") is not None:
            docs, pair_docs, events, capped = res["docs"], res["pair_docs"], res["events"], res["capped"]
        if not keep_loaded:
            self._docs, self._pair_docs, self._events = docs, pair_docs, events
            result = res["result"]
            series = result["series"] if result["kind"] == "AI" else {}
            first = next(iter(series.values()), None) if series else None
            if first is None and docs:       # digital: overview = number of ON channels
                ts = [A.to_epoch(d["timestamp"]) for d in docs]
                vals = [sum(1 for e in d["channels"].values() if e.get("value")) for d in docs]
            else:
                ts, vals = (first[0], first[1]) if first else ([], [])
            self._loaded = {"ts": ts, "vals": vals, "range": (A.to_epoch(rng[0]), A.to_epoch(rng[1]))}
        self._view = res
        self._live = False
        self._range_shown = rng
        self._status_msg = ""
        if capped:
            self._set_status(f"Only the newest {len(docs):,} readings were analysed. Narrow the period for full detail.")
        else:
            self._set_status("")
        self._render_current()

    # ================================================================== CSV import / export
    def _import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import CSV", "", "CSV files (*.csv *.txt);;All files (*.*)")
        if path:
            self._import_path(path)

    def _import_path(self, path):
        self._set_status(f"Reading {os.path.basename(path)}…")
        self._busy = True
        run_async(self, lambda: A.load_csv(path), self._import_done)

    def _import_done(self, data, err):
        self._busy = False
        if err is not None:
            self._set_status(f"Import failed: {err}", True)
            return
        self.imported = data
        kind = data["kind"] if data["kind"] in ("AI", "DI", "DO") else "AI"
        self.seg_kind.set_value(kind)
        self.device_combo._kinds = (kind,)
        self.device_combo._populate()
        self._focus = None
        self._hidden.clear()
        first, last = data["docs"][0]["timestamp"], data["docs"][-1]["timestamp"]
        self.seg_period.set_value("CUSTOM")
        self.edit_from.setDateTime(QDateTime(first))
        self.edit_to.setDateTime(QDateTime(last))
        self._apply_mode_visibility()
        self._update_source()
        self._run_period()

    def _close_file(self):
        self.imported = None
        self._view = None
        self._docs = []
        self.seg_period.set_value("LIVE")
        self._apply_mode_visibility()
        self._update_source()
        self._period_changed("LIVE")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith((".csv", ".txt"))
                                              for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith((".csv", ".txt")):
                self._import_path(path)
                break

    def _export_docs(self):
        """(docs, kind, name, start, end) of what is on screen."""
        if self._live:
            sel = self._selected()
            if not sel:
                return [], None, "", None, None
            window = self.live_window.currentData()
            docs = self.session.docs(sel[0], window)
            end = datetime.now()
            return docs, sel[1], sel[2], end - timedelta(seconds=window), end
        start, end = self._range_shown
        docs = A.slice_docs(self._docs, start, end)
        name = self.imported["name"].rsplit(".", 1)[0] if self.imported else (self._selected() or (0, 0, "device"))[2]
        kind = self.imported["kind"] if self.imported else self._kind()
        return docs, kind, name, start, end

    def _export_csv(self):
        docs, kind, name, start, end = self._export_docs()
        if not docs:
            self._set_status("Nothing to export in this period.", True)
            return
        default = f"analysis_{str(name).replace(' ', '_')}_{start:%Y%m%d_%H%M}-{end:%H%M}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", default, "CSV files (*.csv)")
        if not path:
            return
        try:
            n = A.write_csv(path, docs, kind)
            self._set_status(f"Exported {n:,} rows ({start:%d %b %H:%M} → {end:%d %b %H:%M}) to {path}")
        except OSError as exc:
            self._set_status(f"Export failed: {exc}", True)

    def _export_report(self):
        default = f"analytics_report_{datetime.now():%Y%m%d_%H%M%S}.png"
        path, chosen = QFileDialog.getSaveFileName(self, "Export report", default,
                                                   "PNG image (*.png);;PDF document (*.pdf)")
        if not path:
            return
        pix = self.content.grab()
        try:
            if path.lower().endswith(".pdf"):
                writer = QPdfWriter(path)
                writer.setResolution(110)
                mm = QSizeF(pix.width() * 25.4 / 110, pix.height() * 25.4 / 110)
                writer.setPageSize(QPageSize(mm, QPageSize.Millimeter))
                writer.setPageMargins(QMarginsF(0, 0, 0, 0))
                painter = QPainter(writer)
                painter.drawPixmap(0, 0, pix)
                painter.end()
                ok = True
            else:
                ok = pix.save(path if path.lower().endswith(".png") else path + ".png")
            self._set_status(f"Report saved to {path}" if ok else "Could not save the report.", not ok)
        except Exception as exc:        # noqa: BLE001 - shown to the user
            self._set_status(f"Report failed: {exc}", True)

    # ================================================================== status / header
    def _set_status(self, text, error=False):
        self._status_msg = ("!" if error else "") + text
        self._update_source()

    def _update_source(self):
        extra = ""
        if self._status_msg:
            err = self._status_msg.startswith("!")
            extra = (f" &nbsp;·&nbsp; <span style='color:{RED if err else AMBER}'><b>{self._status_msg.lstrip('!')}</b></span>")
        if self.imported is not None:
            imp = self.imported
            first, last = imp["docs"][0]["timestamp"], imp["docs"][-1]["timestamp"]
            skip = f", {imp['skipped']} rows skipped" if imp["skipped"] else ""
            text = (f"<b style='color:{WHITE}'>Imported file</b> &nbsp;{imp['name']} &nbsp;·&nbsp; "
                    f"<b style='color:{WHITE}'>{len(imp['docs']):,} records</b>{skip} &nbsp;·&nbsp; "
                    f"{first:%d %b %Y %H:%M} → {last:%d %b %Y %H:%M} &nbsp;·&nbsp; {imp['kind']} channels "
                    f"{imp['channels'][0]}…{imp['channels'][-1]} &nbsp;·&nbsp; the live bus and database are not touched")
        elif self._is_live():
            sel = self._selected()
            text = (f"<b style='color:{WHITE}'>Live bus</b> &nbsp;{sel[2] if sel else 'no device'} "
                    f"&nbsp;·&nbsp; rolling {self.live_window.currentText()} window &nbsp;·&nbsp; every figure is computed "
                    f"from readings received since you pressed Connect")
        else:
            sel = self._selected()
            start, end = self._range_shown if self._view else self._range()
            n = self._view["result"]["n"] if self._view else 0
            text = (f"<b style='color:{WHITE}'>Database</b> &nbsp;nelumbo_utility · "
                    f"{sel[2] if sel else 'no device'} &nbsp;·&nbsp; <b style='color:{WHITE}'>{n:,} records</b> &nbsp;·&nbsp; "
                    f"{start:%d %b %H:%M} → {end:%d %b %H:%M} ({A.fmt_duration((end - start).total_seconds())}) "
                    f"&nbsp;·&nbsp; every figure below is computed from this period only")
        self.source_label.setText(text + extra)

    def _update_header(self, runtime):
        if runtime["connected"]:
            self.pill_conn.setText(f"● {runtime['port']} CONNECTED · {runtime['baud']}")
            self.pill_conn.set_color(GREEN)
        else:
            self.pill_conn.setText("● COM PORT DISCONNECTED")
            self.pill_conn.set_color(MUTED)
        db = runtime.get("db")
        if db is not None and db["connected"]:
            kind, text = GREEN, "ONLINE"
        elif db is not None and db["last_error"]:
            kind, text = RED, "OFFLINE"
        elif self._db_ok is False:
            kind, text = RED, "OFFLINE"
        elif self._db_ok:
            kind, text = GREEN, "ONLINE"
        else:
            kind, text = MUTED, "NOT CONNECTED YET"
        self.pill_db.setText(f"● DATABASE {text}")
        self.pill_db.set_color(kind)
        since = runtime.get("since")
        s = int((datetime.now() - since).total_seconds()) if since else 0
        self.pill_session.setText(f"SESSION {s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}")
        self.pill_session.set_color(MUTED)
        self.pill_clock.setText(datetime.now().strftime("%d %b %Y · %H:%M:%S"))
        self.pill_clock.set_color(MUTED)

    # ================================================================== timer
    def _tick(self):
        now = time.monotonic()
        dt = now - self._last
        self._last = now
        self._spark_acc += dt
        if self._spark_acc >= 1.0:
            self._spark_acc = 0.0
            self._sample_sparks()
        if not self.isVisible():
            return
        runtime = self._get_runtime()
        self._update_header(runtime)
        if self._is_live():
            self._live = True
            self._live_update(runtime)
            self._reapply_expand()
        else:
            if (self._mode() not in ("CUSTOM",) and self.imported is None and not self._busy
                    and now - self._last_auto >= AUTO_REFRESH_S):
                self._run_period()

    def _sample_sparks(self):
        s = self._spark
        stats = self._get_stats()
        devices = self._get_devices()
        now_t = time.time()
        for d in devices:
            self._status_hist.setdefault(d["slave_id"], deque(maxlen=7200)).append((now_t, d.get("status") or ""))
        s["online"].append(sum(1 for d in devices if d.get("status") == "ONLINE"))
        s["alarms"].append(self.engine.counts()[0])
        if stats["tx"]:
            s["success"].append(100.0 * stats["successful"] / stats["tx"])
        resp = self.session.all_response_ms()
        if resp:
            s["resp"].append(sum(resp[-50:]) / len(resp[-50:]))
        s["thr"].append(self.session.throughput(time.time()))
        db = self._get_runtime().get("db")
        if db:
            s["saved"].append(db["saved"])

    # ================================================================== live mode
    def _live_update(self, runtime):
        sel = self._selected()
        window = self.live_window.currentData()
        key = (sel[:2] if sel else None, window, self.session.revision, self._focus,
               tuple(sorted(self._hidden)), self.engine.revision)
        if key != self._live_key or time.monotonic() - self._last_live_calc > 1.0:
            self._live_key = key
            self._last_live_calc = time.monotonic()
            if sel:
                docs = self.session.docs(sel[0], window)
                limit_for = self._limit_for(sel[0], snapshot=False)
                result = A.analyze(sel[1], docs, limit_for, recent_s=min(window, 120))
                feedback = []
                if sel[1] == "DO" and result["n"]:
                    pair = self._pair_device()
                    if pair:
                        pdocs = self.session.docs(pair[0], window)
                        if pdocs:
                            feedback = A.feedback_check(result, A.analyze_digital(pdocs, "DI"))
                self._docs = docs
                self._view = {"result": result, "prev": None, "feedback": feedback, "compare": []}
                if sel[1] == "AI" and result["n"] >= 5:
                    self._sig_scores[sel[0]] = result["signal_score"]
                end = datetime.now()
                self._range_shown = (end - timedelta(seconds=window), end)
                self._render_current()
            else:
                self._view = None
                self._render_empty("No device selected. Add a device on the Live tab, press Connect and Run All.")
        self._update_live_panels(runtime)

    def _update_live_panels(self, runtime):
        devices = self._get_devices()
        stats = self._get_stats()
        total = len(devices)
        online = [d for d in devices if d.get("status") == "ONLINE"]
        offline = [d for d in devices if d.get("status") == "OFFLINE"]
        sp = self._spark
        k = self.kpis
        for t in k:
            t.show()
        self._kpi(0, "Devices online", f"{len(online)}", f"/ {total}", f"{len(offline)} offline" if offline else
                 ("all polled devices healthy" if total else "no devices"),
                 GREEN if online or not total else MUTED, sp["online"])
        active, unacked = self.engine.counts()
        self._kpi(1, "Active alarms", active, "", f"{unacked} unacknowledged" if active else "no active alarms",
                 RED if unacked else (AMBER if active else GREEN), sp["alarms"])
        tx = stats["tx"]
        rate = 100.0 * stats["successful"] / tx if tx else None
        self._kpi(2, "Success rate", "--" if rate is None else f"{rate:.2f}", "" if rate is None else "%", "RX ok / TX", BLUE, sp["success"])
        resp = self.session.all_response_ms()
        if resp:
            p95 = A.percentile(resp, 95)
            self._kpi(3, "Avg response", f"{sum(resp) / len(resp):.0f}", "ms", f"p95 {p95:.0f} ms", VIOLET, sp["resp"])
        else:
            self._kpi(3, "Avg response", "--", "", "no replies yet", VIOLET)
        thr = self.session.throughput(time.time())
        self._kpi(4, "Throughput", f"{thr:.1f}", "req/s", f"timeouts {stats['timeouts']}", TEAL, sp["thr"])
        db = runtime.get("db")
        if db is not None:
            self._kpi(5, "Records saved", f"{db['saved']:,}", "", f"queued {db['queued']} · dropped {db['dropped']}", GREEN, sp["saved"])
        else:
            self._kpi(5, "Records saved", "--", "", "starts when polling begins", GREEN)
        # live values board, freshness strip, status timeline
        self._update_values(devices)
        self._update_freshness(devices)
        self._update_timeline(devices)
        # communication analytics
        ms = self.session.all_response_ms()
        if ms:
            e, c, _m, _s = A.histogram(ms, 13)
            self.rt_hist.set_data(c, e, None, f"{len(ms)} replies", {"p50": A.percentile(ms, 50), "p95": A.percentile(ms, 95)},
                                  VIOLET)
        else:
            self.rt_hist.set_data([], [])
        now = time.time()
        series = []
        names = {d["slave_id"]: d["name"] for d in devices}
        for i, (sid, data) in enumerate(sorted(self.session.resp.items())):
            pts = [(t, v) for t, v in data if now - t <= 900]
            if pts:
                series.append({"name": names.get(sid, f"Slave {sid}"), "color": SERIES[i % len(SERIES)],
                               "ts": [p[0] for p in pts], "vals": [p[1] for p in pts], "unit": "ms"})
        first = min((s_["ts"][0] for s_ in series), default=now - 900)
        self.lat_chart.set_data(series, max(now - 900, first - 1.0), now, ymin=0, unit="ms", message="No replies yet", fill=False)
        sids = sorted(self.session.comm)
        if sids:
            heat = self.session.heatmap(sids, now, 24)
            size = A.THRESHOLDS["comm_bucket_s"]
            labels = [(datetime.fromtimestamp(now - (23 - c) * size).strftime("%H:%M") if c % 6 == 0 else "")
                      for c in range(24)]
            self.heat.set_rows([(names.get(s, f"Slave {s}"), heat[s]) for s in sids], labels)
        else:
            self.heat.set_rows([])
        self.bus_gauge.set_value(self.session.bus_util(now), f"{runtime['baud'].split(' ')[0]} baud · {total} devices"
                                 if runtime["connected"] else "not connected")

    # ---- live values / freshness / timeline
    def _update_values(self, devices):
        sel = self._selected()
        if not sel:
            self.values.set_items([], "No device selected")
            return
        kind = sel[1]
        docs = self._docs or []
        latest = docs[-1] if docs else None
        if latest is None:
            self.values.set_items([], "Waiting for live readings. Press Run All and make sure the device is ONLINE.")
            return
        self.chip_values.setText("NOW \u00b7 TREND" if kind == "AI" else "ON / OFF NOW")
        items = []
        t_ref = latest["timestamp"] - timedelta(seconds=60)
        for i, (name, ch) in enumerate(latest["channels"].items()):
            value = ch["value"]
            if kind == "AI":
                series = [d["channels"][name]["value"] for d in docs[-60:] if name in d["channels"]]
                old = next((d["channels"][name]["value"] for d in docs if d["timestamp"] >= t_ref and name in d["channels"]),
                           series[0] if series else value)
                diff = value - old
                if abs(diff) < max(1e-9, abs(value) * 0.002):
                    delta, dcol = "\u2192 stable", MUTED
                else:
                    delta, dcol = (f"\u2191 +{diff:.3g}" if diff > 0 else f"\u2193 {diff:.3g}"), (BLUE if diff > 0 else AMBER)
                items.append({"name": name, "value": f"{value:.3f}".rstrip("0").rstrip(".") if abs(value) < 1000 else f"{value:,.0f}",
                              "unit": ch.get("unit") or "", "delta": delta + " /min", "delta_color": dcol,
                              "spark": series, "color": SERIES[i % len(SERIES)]})
            else:
                on = bool(value)
                items.append({"name": name, "value": "ON" if on else "OFF", "unit": "", "delta": "", "delta_color": MUTED,
                              "spark": [], "color": GREEN if on else MUTED, "digital": True})
        self.values.set_items(items)

    def _update_freshness(self, devices):
        now = datetime.now()
        items = []
        for d in devices:
            sid = d["slave_id"]
            data = self.session.readings.get(sid)
            age = (now - data[-1]["timestamp"]).total_seconds() if data else None
            poll = max(0.1, int(d.get("polling") or 1000) / 1000.0)
            items.append({"name": d["name"], "age": None if age is None else max(0.0, round(age, 1)),
                          "state": d.get("status") or "", "fresh_s": max(5.0, poll * 3), "stale_s": max(30.0, poll * 10)})
        self.fresh.set_items(items)

    def _update_timeline(self, devices):
        now = time.time()
        window = float(self.live_window.currentData() or 900)
        names = {d["slave_id"]: d["name"] for d in devices}
        rows = []
        for sid in sorted(names):
            hist = self._status_hist.get(sid)
            segs = []
            if hist:
                start_t, cur = hist[0]
                prev_t = start_t
                for t, st in list(hist)[1:]:
                    if st != cur:
                        segs.append((start_t, t, cur))
                        start_t, cur = t, st
                    prev_t = t
                segs.append((start_t, max(now, prev_t), cur))
            rows.append({"name": names[sid], "segments": segs})
        self.timeline.set_rows(rows, now - window, now, "No devices yet. Add a device on the Live tab.")

    def _comm_insights(self):
        """Device-level plain-language findings (live mode)."""
        out = []
        devices = self._get_devices()
        names = {d["slave_id"]: d["name"] for d in devices}
        avg = {sid: sum(v for _, v in data) / len(data) for sid, data in self.session.resp.items() if data}
        if len(avg) >= 2:
            sid = max(avg, key=avg.get)
            out.append({"sev": "SPEED", "color": "blue", "icon": "\u23f1", "ts": None,
                        "text": f"<b>{names.get(sid, sid)}</b> is the slowest device, average reply {avg[sid]:.0f} ms"})
        elif len(avg) == 1:
            sid = next(iter(avg))
            out.append({"sev": "SPEED", "color": "blue", "icon": "\u23f1", "ts": None,
                        "text": f"<b>{names.get(sid, sid)}</b> replies in {avg[sid]:.0f} ms on average"})
        drops = 0
        for sid, hist in self._status_hist.items():
            last = None
            for _, st in hist:
                if st == "OFFLINE" and last not in (None, "OFFLINE"):
                    drops += 1
                last = st
        if drops:
            out.append({"sev": "LINK", "color": "red", "icon": "!", "ts": None,
                        "text": f"A device went OFFLINE <b>{drops} time{'s' if drops != 1 else ''}</b> this session. See the timeline below"})
        elif devices and any(self._status_hist.values()):
            out.append({"sev": "LINK", "color": "green", "icon": "\u2713", "ts": None,
                        "text": "No device has gone offline this session"})
        return out

    # ---- tap a card to enlarge it
    def _wire_cards(self):
        self._cards = [c for c in self.content.findChildren(NeonCard) if c.title_label.text()]
        for card in self._cards:
            card.clicked.connect(self._card_clicked)
            self._card_state[card] = card.maximumWidth()

    def _card_clicked(self, card):
        if self._expanded_card is card:
            self._collapse_card()
        else:
            self._expand_card(card)

    def _expand_card(self, card):
        if self._expanded_card is not None:
            self._collapse_card()
        self._expanded_card = card
        self._hidden_by_expand = [c for c in self._cards if c is not card and c.isVisibleTo(self.content)]
        for c in self._hidden_by_expand:
            c.setVisible(False)
        card.setMaximumWidth(16777215)
        card.setMinimumWidth(0)
        card.setMinimumHeight(max(520, self.scroll.viewport().height() - 20))
        card.set_expanded(True)
        if card is self.health_card:
            self.values_scroll.setMaximumHeight(16777215)
        self.scroll.verticalScrollBar().setValue(0)

    def _collapse_card(self):
        card, self._expanded_card = self._expanded_card, None
        if card is None:
            return
        self._collapsing = True
        for c in getattr(self, "_hidden_by_expand", []):
            c.setVisible(True)
        self._hidden_by_expand = []
        card.setMinimumHeight(0)
        fixed = {self.health_card: 330, self.insight_card: 430}.get(card)
        if fixed:
            card.setFixedWidth(fixed)
        card.set_expanded(False)
        self._apply_mode_visibility()
        self._collapsing = False

    def _reapply_expand(self):
        card = self._expanded_card
        if card is None:
            return
        for c in self._cards:
            if c is not card and c.isVisibleTo(self.content):
                c.setVisible(False)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self._expanded_card is not None:
            self._collapse_card()
            return
        super().keyPressEvent(event)

    # ================================================================== rendering
    def _render_empty(self, message):
        self.chart.set_data([], 0, 1, message=message)
        self.lanes.set_lanes([], 0, 1, message=message)
        self.insights.set_items([{"sev": "INFO", "color": "blue", "icon": "i", "text": message, "ts": None}])
        for t in self.kpis:
            t.set("--", "", "", BLUE)
        if not self._is_live():
            self.kpis[5].hide()
        self.report_label.setText("")
        self.compare_label.setText("")
        self.brush.set_overview([], [], (0, 1), (0, 1))
        self._clear_grid(self.chan_grid)
        self.stats_table.setRowCount(0)
        self.fc_chart.set_data([], 0, 1, message="No data")
        self.dist_chart.set_data([], [])
        self.roc_bars.set_rows([])
        self.dist_stats.setText("")
        self._update_source()

    def _render_current(self):
        self._render_current_inner()
        self._reapply_expand()

    def _render_current_inner(self):
        view = self._view
        if not view:
            return
        result = view["result"]
        kind = result["kind"]
        self.grp_ai.setVisible(kind == "AI")
        self.grp_dig.setVisible(kind in ("DI", "DO"))
        self.stack.setCurrentIndex(0 if kind == "AI" else 1)
        self.brush.setVisible(not self._live and kind == "AI")
        self.focus_combo.setVisible(kind == "AI")
        self.stats_card.setVisible(not self._live and kind == "AI")
        self._update_source()
        if not result["n"]:
            self._render_no_data(kind)
            return
        if kind == "AI":
            self._render_analog(view)
        else:
            self._render_digital(view)

    def _render_no_data(self, kind):
        live = self._live
        msg = ("Waiting for live readings. Connect, press Run All, and make sure the device is ONLINE."
               if live else "No readings in this period. Widen the period or pick another device.")
        self._render_empty(msg)
        if not live and self.imported is None:
            sel = self._selected()
            if sel:
                self._explain_empty(sel)

    def _explain_empty(self, sel):
        def done(info, err):
            if err is not None:
                self._set_status(f"Database error: {_error_text(err)}", True)
            elif info["device"] == 0:
                self._set_status(f"No records saved for Slave {sel[0]} in '{info['collection']}' yet.")
            else:
                self._set_status(f"Slave {sel[0]} has {info['device']:,} saved records; newest: "
                                 f"{info['newest']:%d %b %H:%M:%S}. Widen the period.")
        run_async(self, lambda: diagnose(sel[1], sel[0]), done)

    def _clear_grid(self, grid):
        while grid.count():
            w = grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        self._tile_sig = None

    # ---------------------------------------------------------------- analog
    def _render_analog(self, view):
        result = view["result"]
        chans = {c["name"]: c for c in result["channels"]}
        names = list(result["series"].keys())
        if not names:
            self._render_empty("No analog values in this period.")
            return
        if self._focus not in chans:
            self._focus = names[0]
        # focus combo
        if [self.focus_combo.itemText(i) for i in range(self.focus_combo.count())] != names:
            self.focus_combo.blockSignals(True)
            self.focus_combo.clear()
            self.focus_combo.addItems(names)
            self.focus_combo.blockSignals(False)
        self.focus_combo.blockSignals(True)
        self.focus_combo.setCurrentText(self._focus)
        self.focus_combo.blockSignals(False)
        self._build_legend(names)
        focus = chans[self._focus]
        start, end = self._range_shown
        t0, t1 = A.to_epoch(start), A.to_epoch(end)
        if self._live and result["start"] is not None:      # until the window is full, show only what exists
            t0 = max(t0, A.to_epoch(result["start"]) - 1.0)
        # chart
        series = []
        for i, name in enumerate(names):
            if name in self._hidden:
                continue
            ts, vals, unit = result["series"][name]
            s = {"name": name, "color": SERIES[i % len(SERIES)], "ts": ts, "vals": vals, "unit": unit}
            if name == self._focus and len(vals) > 12:
                k = max(5, min(60, len(vals) // 40))
                s["ma"] = A.moving_average(vals, k)
                s["band"] = rolling_minmax(vals, k)
            series.append(s)
        limits = []
        if focus["limit"]:
            u = " " + focus["unit"] if focus["unit"] else ""
            limits = [(focus["limit"]["high"], f"HIGH LIMIT {focus['limit']['high']:g}{u}"
                       + (f" · {focus['breaches']} breaches" if focus["breaches"] else ""), RED),
                      (focus["limit"]["low"], f"LOW LIMIT {focus['limit']['low']:g}{u}", RED)]
        self.chart.set_data(series, t0, t1, limits=limits, unit=focus["unit"], fill=True)
        self.chip_chart_b.setText(f"{self._focus} · MOVING AVG + MIN/MAX BAND")
        if self._loaded and not self._live:
            self.brush.set_overview(self._loaded["ts"], self._loaded["vals"], self._loaded["range"], (t0, t1))
        # KPIs
        self._kpis_analog(result, view)
        # insights / report
        live = self._live
        items = A.analog_insights(result, live)
        if live:
            items = items[:5] + self._comm_insights()
        for it in items:
            it["ts"] = None
        self.insights.set_items(items)
        self._report(result, view)
        # channel tiles
        self._tiles_analog(result, chans)
        if not live:
            self._fill_stats_table(result)
        self._forecast(result, focus)
        self._distribution(result, focus)
        self._roc(result)

    def _build_legend(self, names):
        sig = (tuple(names), tuple(sorted(self._hidden)))
        if sig == self._legend_sig:
            return
        self._legend_sig = sig
        while self.legend_row.count():
            w = self.legend_row.takeAt(0).widget()
            if w:
                w.deleteLater()
        for i, name in enumerate(names):
            b = QPushButton(f" {name}")
            b.setObjectName("legend")
            b.setCheckable(True)
            b.setChecked(name not in self._hidden)
            color = SERIES[i % len(SERIES)]
            b.setStyleSheet(f"QPushButton{{color:{WHITE};background:{SURFACE};border:1px solid {BORDER};border-radius:11px;"
                            f"padding:3px 10px;font-family:'{FONT}';font-size:11px;font-weight:600;}}"
                            f"QPushButton:!checked{{color:{FAINT};background:{SOFT};}}")
            b.setProperty("series_color", color)
            dot = QPixmap(12, 12)
            dot.fill(Qt.transparent)
            dp = QPainter(dot)
            dp.setRenderHint(QPainter.Antialiasing)
            dp.setPen(Qt.NoPen)
            dp.setBrush(QColor(color))
            dp.drawEllipse(1, 1, 10, 10)
            dp.end()
            b.setIcon(dot)
            b.setCursor(Qt.PointingHandCursor)
            b.toggled.connect(lambda on, n=name: self._legend_toggled(n, on))
            self.legend_row.addWidget(b)
        self.legend_row.addStretch(1)

    def _legend_toggled(self, name, on):
        (self._hidden.discard if on else self._hidden.add)(name)
        self._legend_sig = None
        self._render_current()

    def _kpis_analog(self, result, view):
        k = self.kpis
        if self._live:
            return                         # live KPIs are the system KPIs (set in _update_live_panels)
        k[5].hide()
        for t in k[:5]:
            t.show()
        prev = view.get("prev")
        dcov = f"{result['coverage'] - prev['coverage']:+.1f} pt" if prev and prev["n"] else ""
        self._kpi(0, "Records", f"{result['n']:,}", "", f"{A.fmt_duration(result['duration_s'])} · coverage {result['coverage']:.1f} %",
                 BLUE, None, "")
        ev = sum(1 for e in self._events if e.get("event") == "RAISED")
        self._kpi(1, "Limit breaches", result["breaches"], "", f"{ev} alarm events saved" if self.imported is None else "limit breaches",
                 RED if result["breaches"] else GREEN, None,
                 f"{result['breaches'] - prev['breaches']:+d} vs prev" if prev and prev["n"] else "",
                 RED if prev and result["breaches"] > prev["breaches"] else GREEN)
        tags = sorted({c["tag"] for c in result["channels"] if c["tag"] in ("SPIKE", "NOISY", "DRIFT", "STUCK")})
        self._kpi(2, "Anomalies", result["anomalies"], "", " · ".join(tags) if tags else "none detected", AMBER if tags else GREEN)
        self._kpi(3, "Time in alarm", A.fmt_short_duration(result["alarm_s"]), "", "time outside limits", VIOLET if result["alarm_s"] else GREEN)
        self._kpi(4, "Signal quality", result["signal_score"], "/100", "period signal score",
                 GREEN if result["signal_score"] >= 85 else AMBER if result["signal_score"] >= 60 else RED)

    def _report(self, result, view):
        if self._live:
            return
        name = self.imported["name"] if self.imported else (self._selected() or (0, 0, "device"))[2]
        parts = A.period_report(result, name, "imported file" if self.imported else "database")
        html = ""
        for head, text in parts[:-1]:
            html += (f"<div style='color:{MUTED};font-size:10px;font-weight:600;letter-spacing:1px;margin-top:8px'>"
                     f"{head}</div><div style='color:{TEXT}'>{text}</div>")
        self.report_label.setText(html)
        cmp_rows = view.get("compare") or []
        if cmp_rows:
            cells = "".join(f"<td style='padding:6px 12px;border:1px solid {BORDER};background:{SURFACE}'>"
                            f"<b style='color:{GREEN if good else RED};font-size:14px'>{txt}</b><br>"
                            f"<span style='color:{MUTED};font-size:10px'>{label}</span></td>"
                            for label, txt, good in cmp_rows)
            self.compare_label.setText(f"<div style='color:{MUTED};font-size:10px;font-weight:600;letter-spacing:1px'>"
                                       f"COMPARED WITH THE PREVIOUS PERIOD OF THE SAME LENGTH</div><table>"
                                       f"<tr>{cells}</tr></table>")
        else:
            self.compare_label.setText(f"<span style='color:{MUTED};font-size:10px'>No earlier data to compare with.</span>")

    def _tiles_analog(self, result, chans):
        names = list(chans)
        sig = ("AI", tuple(names))
        if sig != self._tile_sig:
            self._clear_grid(self.chan_grid)
            self._tiles = {}
            for i, n in enumerate(names):
                t = ChannelTile()
                t.clicked = self._set_focus
                self.chan_grid.addWidget(t, i // 4, i % 4)
                self._tiles[n] = t
            self._tile_sig = sig
        for n, c in chans.items():
            u = c["unit"]
            if c["last"] is None:
                continue
            meta1 = f"Δ {A.fmt_rate(c['slope_min'])}"
            meta2 = (f"limit in {A.fmt_duration(c['ttl_s'])}" if c["ttl_s"] is not None else
                     f"σ {c['noise']:.2g}" if c["tag"] == "NOISY" else
                     f"flat {A.fmt_duration(c['span_s'])}" if c["tag"] == "STUCK" else
                     "in alarm" if c["in_alarm"] else "no limit risk")
            self._tiles[n].set(n, c["tag"], f"{c['last']:.2f}", u, c["score"], meta1, meta2, n == self._focus)

    def _fill_stats_table(self, result):
        t = self.stats_table
        t.setRowCount(len(result["channels"]))
        for r, c in enumerate(result["channels"]):
            u = c["unit"]
            vals = ["", u, A.fmt_num(c["min"]), A.fmt_num(c["max"]), A.fmt_num(c["mean"]), A.fmt_num(c["std"]),
                    A.fmt_rate(c["slope_min"]), c["tag"], str(c["breaches"]),
                    A.fmt_short_duration(c["alarm_s"]) if c["alarm_s"] else "—"]
            for col, text in enumerate(vals):
                item = QTableWidgetItem(c["name"] if col == 0 else text)
                item.setTextAlignment((Qt.AlignLeft if col == 0 else Qt.AlignRight) | Qt.AlignVCenter)
                if col == 0:
                    item.setForeground(QColor(WHITE))
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                if col == 7:
                    item.setForeground(QColor(TAG_COLORS.get(c["tag"], MUTED)))
                if col == 8 and c["breaches"]:
                    item.setForeground(QColor(RED))
                t.setItem(r, col, item)
        t.setFixedHeight(len(result["channels"]) * 30 + 34)

    def _forecast(self, result, c):
        ts, vals, unit = result["series"][c["name"]]
        self.fc_card.title_label.setText(f"LIMIT FORECAST · {c['name']}")
        if len(ts) < 8:
            self.fc_chart.set_data([], 0, 1, message="Not enough data for a forecast")
            self.chip_fc.setText("WAITING FOR DATA")
            self.chip_fc.set_color(MUTED)
            return
        ttl = c["ttl_s"]
        span = ts[-1] - ts[0]
        horizon = max(60.0, min(1.5 * ttl, 21600.0)) if ttl else min(max(span * 0.3, 300.0), 3600.0)
        k = bisect_left(ts, ts[-1] - max(horizon * 1.5, 120.0))
        hist = {"name": c["name"], "color": BLUE, "ts": ts[k:], "vals": vals[k:], "unit": unit}
        line = A.forecast_line(ts, vals, A.THRESHOLDS["forecast_tail_s"], horizon)
        tail_k = bisect_left(ts, ts[-1] - A.THRESHOLDS["forecast_tail_s"])
        resid = A.linreg(ts[tail_k:], vals[tail_k:])[2] if len(ts) - tail_k >= 3 else 0.0
        limits, eta = [], None
        if c["limit"]:
            u = " " + unit if unit else ""
            limits = [(c["limit"]["high"], f"HIGH LIMIT {c['limit']['high']:g}{u}", RED),
                      (c["limit"]["low"], f"LOW LIMIT {c['limit']['low']:g}{u}", RED)]
            if ttl is not None:
                edge = c["limit"]["high"] if c["ttl_kind"] == "HIGH" else c["limit"]["low"]
                eta = (ts[-1] + ttl, edge, f"ETA {A.fmt_duration(ttl)}")
        fc = {"pts": line, "color": VIOLET, "eta": eta, "spread": resid * 2.0}
        self.fc_chart.set_data([hist], ts[k], ts[-1] + horizon, limits=limits, forecast=fc, now_t=ts[-1], unit=unit,
                               fill=True)
        if ttl is not None:
            self.chip_fc.setText(f"REACHES {c['ttl_kind']} LIMIT IN {A.fmt_duration(ttl)}")
            self.chip_fc.set_color(RED)
        elif c["limit"]:
            self.chip_fc.setText("NO LIMIT RISK")
            self.chip_fc.set_color(GREEN)
        else:
            self.chip_fc.setText("NO LIMIT SET · SEE ALARMS TAB")
            self.chip_fc.set_color(MUTED)

    def _distribution(self, result, c):
        ts, vals, unit = result["series"][c["name"]]
        edges, counts, mean, std = A.histogram(vals, 15)
        self.dist_card.title_label.setText(f"VALUE DISTRIBUTION · {c['name']}")
        self.chip_dist.setText("LIVE WINDOW" if self._live else "PERIOD")
        self.dist_chart.set_data(counts, edges, mean, unit=unit)
        u = f" {unit}" if unit else ""
        sig = (round(mean, 2), round(std, 2), round(max(vals), 2) if vals else 0, round(min(vals), 2) if vals else 0, u)
        if vals and sig != getattr(self, "_dist_sig", None):
            self._dist_sig = sig
            self.dist_stats.setText(
                "<table width='100%'><tr>" + "".join(
                    f"<td align='center' style='padding:6px;border:1px solid {BORDER};background:{SURFACE}'>"
                    f"<b style='color:{WHITE};font-size:15px'>{v}</b><br><span style='color:{MUTED};font-size:10px'>{l}</span></td>"
                    for v, l in ((f"{mean:.2f}", f"mean{u}"), (f"{std:.2f}", "std dev σ"),
                                 (f"{max(vals):.2f}", "max"), (f"{min(vals):.2f}", "min"))) + "</tr></table>")

    def _roc(self, result):
        rows = []
        mx = max([abs(c["slope_min"]) for c in result["channels"]] + [1e-9])
        for c in result["channels"]:
            if c["last"] is None:
                continue
            s = c["slope_min"]
            arrow = "▲" if s > 1e-6 else "▼" if s < -1e-6 else "·"
            rows.append((c["name"], abs(s), f"{arrow} {A.fmt_rate(s)}" if c["tag"] != "STUCK" else "flat",
                         c["tag"] in ("DRIFT", "SPIKE")))
        self.roc_bars.set_rows(rows, mx)

    # ---------------------------------------------------------------- digital
    def _render_digital(self, view):
        result = view["result"]
        kind = result["kind"]
        start, end = self._range_shown
        t0, t1 = A.to_epoch(start), A.to_epoch(end)
        if self._live and result["start"] is not None:
            t0 = max(t0, A.to_epoch(result["start"]) - 1.0)
        lanes = []
        for i, c in enumerate(result["channels"]):
            color = AMBER if c["tag"] in ("CHATTER", "HUNTING") else RED if c["tag"] == "STUCK" else (TEAL, BLUE, GREEN, VIOLET)[i % 4]
            lanes.append({"name": c["name"], "segments": c["segments"], "color": color})
        self.lanes.set_lanes(lanes, t0, t1)
        self.chart_card.title_label.setText((f"{kind} STATE TIMELINE" + (" · LIVE" if self._live else "")))
        self.chip_chart_b.setText("ON = BRIGHT BAR")
        self.focus_combo.hide()
        while self.legend_row.count():
            w = self.legend_row.takeAt(0).widget()
            if w:
                w.deleteLater()
        self._legend_sig = None
        self.legend_row.addStretch(1)
        # KPIs
        if not self._live:
            for t in self.kpis[:5]:
                t.show()
            self.kpis[5].hide()
            k = self.kpis
            prev = view.get("prev")
            self._kpi(0, "Total changes", f"{result['total_toggles']:,}", "", f"{result['n']:,} readings · {A.fmt_duration(result['duration_s'])}",
                     BLUE, None, f"{result['total_toggles'] - prev['total_toggles']:+d} vs prev" if prev and prev["n"] else "",
                     AMBER)
            b = result["busiest"]
            self._kpi(1, "Most active", b[0] if b else "--", "", f"{b[1]} changes · {b[2]:.0f} % of all" if b else "no changes",
                     AMBER if b else MUTED)
            lo = result["longest_on"]
            self._kpi(2, "Longest ON", A.fmt_short_duration(lo[1]) if lo else "--", "", f"{lo[0]}" if lo else "no ON time", GREEN)
            word = "Hunting" if kind == "DO" else "Chatter"
            self._kpi(3, "Hunting alerts" if kind == "DO" else "Chatter alerts", result["chatter"], "", "relays switching too often" if kind == "DO" else "channels toggling too fast", RED if result["chatter"] else GREEN)
            self._kpi(4, "Idle / stuck", result["idle"], "", "stuck / never changed" if kind == "DI" else "never switched",
                     AMBER if result["idle"] else GREEN)
        # bars
        chans = result["channels"]
        self.tog_card.title_label.setText("CHANGE COUNT PER CHANNEL" if kind == "DI" else "SWITCH COUNT PER RELAY")
        self.tog_bars.set_rows([(c["name"], c["toggles"], f"{c['toggles']}", c["tag"] in ("CHATTER", "HUNTING"))
                                for c in chans])
        self.duty_card.title_label.setText("ON TIME (DUTY CYCLE)" if kind == "DI" else "RUN TIME (DUTY CYCLE)")
        self.duty_bars.set_rows([(c["name"], c["duty"], f"{c['duty']:.0f}%", False) for c in chans], 100)
        if kind == "DI":
            self.third_card.title_label.setText("LONGEST ON")
            self.chip_third.setText("PER CHANNEL")
            top = max([c["longest_on"] for c in chans] + [1])
            self.third_bars.set_rows([(c["name"], c["longest_on"], A.fmt_short_duration(c["longest_on"]), False)
                                      for c in chans], top)
        else:
            self.third_card.title_label.setText("SWITCH CYCLES · CONTACT WEAR")
            self.chip_third.setText("ON→OFF PAIRS")
            self.third_bars.set_rows([(c["name"], c["toggles"] // 2, f"{c['toggles'] // 2}", c["tag"] == "HUNTING")
                                      for c in chans])
        # tiles
        labels = (("Toggles", "Duty cycle", "Longest ON", "Last change") if kind == "DI" else
                  ("Switches", "Run time", "Longest ON", "Last switch"))
        sig = (kind, tuple(c["name"] for c in chans))
        if sig != self._tile_sig:
            self._clear_grid(self.dtile_grid)
            self._dtiles = {}
            for i, c in enumerate(chans):
                t = DigitalTile(labels)
                self.dtile_grid.addWidget(t, i // 4, i % 4)
                self._dtiles[c["name"]] = t
            self._tile_sig = sig
        self.dtile_card.title_label.setText(f"{kind} CHANNEL HEALTH" if kind == "DI" else "DO RELAY HEALTH")
        self.chip_dtile.setText(" · ".join(labels).upper())
        for c in chans:
            lc = c["last_change"].strftime("%H:%M:%S") if c["last_change"] else "never"
            second = f"{c['duty']:.0f} %" if kind == "DI" else A.fmt_short_duration(c["on_time"])
            self._dtiles[c["name"]].set(c["name"], "ON" if c["state"] else "OFF", c["tag"],
                                        (str(c["toggles"]), second, A.fmt_short_duration(c["longest_on"]), lc))
        # feedback
        fb = view.get("feedback") or []
        show_fb = kind == "DO"
        self.fb_card.setVisible(show_fb)
        if show_fb:
            self._fill_feedback(fb)
        items = A.digital_insights(result, fb, self._live)
        if self._live:
            items = items[:5] + self._comm_insights()
        self.insights.set_items(items)
        if not self._live:
            name = self.imported["name"] if self.imported else (self._selected() or (0, 0, "device"))[2]
            parts = A.period_report(result, name, "")
            html = ""
            for head, text in parts[:-1]:
                html += (f"<div style='color:{MUTED};font-size:10px;font-weight:600;letter-spacing:1px;margin-top:8px'>"
                         f"{head}</div><div style='color:{TEXT}'>{text}</div>")
            self.report_label.setText(html)
            cmp_rows = view.get("compare") or []
            self.compare_label.setText(
                "" if not cmp_rows else f"<span style='color:{MUTED};font-size:10px'>vs previous period: " + " · ".join(
                    f"<b style='color:{GREEN if g else RED}'>{t}</b> {l}" for l, t, g in cmp_rows) + "</span>")

    def _fill_feedback(self, rows):
        t = self.fb_table
        pair = self._pair_device()
        self.chip_fb.setText(f"PAIRED WITH DI SLAVE {pair[0]}" if pair else "NO DI DEVICE FOUND")
        t.setRowCount(len(rows))
        problems = 0
        for r, row in enumerate(rows):
            if row["confirmed"] == 0:
                res, col = "NO FEEDBACK", RED
            elif row["confirmed"] < row["sent"]:
                res, col = f"{row['sent'] - row['confirmed']} MISSED", AMBER
            else:
                res, col = "OK", GREEN
            problems += col != GREEN
            vals = (row["do"], row["di"], str(row["sent"]), str(row["confirmed"]),
                    f"{row['delay_ms']:.0f} ms" if row["delay_ms"] is not None else "—", res)
            for c, text in enumerate(vals):
                item = QTableWidgetItem(text)
                item.setTextAlignment((Qt.AlignLeft if c == 0 else Qt.AlignRight) | Qt.AlignVCenter)
                if c == 0:
                    item.setForeground(QColor(WHITE))
                if c == 5:
                    item.setForeground(QColor(col))
                t.setItem(r, c, item)
        t.setFixedHeight(max(1, len(rows)) * 30 + 34)
        self.chip_fb.set_color(RED if problems else (GREEN if rows else MUTED))
        if not rows:
            self.chip_fb.setText("NO RELAY SWITCHED, OR NO DI DEVICE TO CHECK AGAINST")