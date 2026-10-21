"""Light (white + teal) painted widgets for the analytics Dashboard.

Everything is drawn with QPainter (gradients and layered strokes for the glow),
because Qt style sheets cannot do glow or blur. The widgets hold no data logic;
analytics.py computes, these only paint.
"""
import math
from bisect import bisect_left
from datetime import datetime

from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import (QPainter, QPen, QColor, QFont, QLinearGradient, QRadialGradient, QPainterPath,
                           QBrush)
from PySide6.QtWidgets import QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy

FONT = "Segoe UI"

# Palette follows the Live console (live_console.LIGHT / DARK). set_theme() rewrites these module globals in place
# and in every module that imported them, so painted widgets always read the current colours at paint time.
PALETTES = {
    "light": dict(BG="#F6F7F9", SURFACE="#FFFFFF", SOFT="#F1F3F6", BORDER="#E4E7EC",
                  BLUE="#0B6FD6", TEAL="#0E9384", VIOLET="#7C4DDB", GREEN="#15803D", RED="#C2312F", AMBER="#B45309",
                  PINK="#C4327A", INDIGO="#2E5BD8",
                  WHITE="#0F1720", TEXT="#3A4452", MUTED="#6B7480", FAINT="#9AA3AE", GRID="#EEF0F3", TRACK="#E9ECF0",
                  ACCENT_SOFT="#E8F1FD"),
    "dark": dict(BG="#0C0E12", SURFACE="#13161B", SOFT="#0F1216", BORDER="#22272F",
                 BLUE="#4C9AFF", TEAL="#2DB3A3", VIOLET="#9F7AEA", GREEN="#3FB76A", RED="#F06A64", AMBER="#E3A33B",
                 PINK="#E2629F", INDIGO="#5B8DEF",
                 WHITE="#ECEFF3", TEXT="#C4CAD2", MUTED="#8B939E", FAINT="#5F6772", GRID="#1D2128", TRACK="#222730",
                 ACCENT_SOFT="#16253A"),
}
THEME = "light"
globals().update(PALETTES["light"])
SERIES = [TEAL, BLUE, VIOLET, AMBER, GREEN, RED, PINK, INDIGO]
TAG_COLORS = {"STABLE": GREEN, "NOISY": AMBER, "DRIFT": VIOLET, "STUCK": RED, "SPIKE": RED, "CHATTER": AMBER,
              "HUNTING": AMBER, "IDLE": MUTED, "WAIT": MUTED, "NO DATA": MUTED}


def set_theme(name="light"):
    """Switch the palette of every painted widget (call update() / re-render on the tabs afterwards)."""
    import sys
    global THEME
    THEME = "dark" if name == "dark" else "light"
    pal = PALETTES[THEME]
    g = globals()
    g.update(pal)
    SERIES[:] = [g["TEAL"], g["BLUE"], g["VIOLET"], g["AMBER"], g["GREEN"], g["RED"], g["PINK"], g["INDIGO"]]
    TAG_COLORS.clear()
    TAG_COLORS.update({"STABLE": g["GREEN"], "NOISY": g["AMBER"], "DRIFT": g["VIOLET"], "STUCK": g["RED"],
                       "SPIKE": g["RED"], "CHATTER": g["AMBER"], "HUNTING": g["AMBER"], "IDLE": g["MUTED"],
                       "WAIT": g["MUTED"], "NO DATA": g["MUTED"]})
    mine = sys.modules[__name__]
    for mod in list(sys.modules.values()):                 # modules that did `from neon_widgets import BLUE, ...`
        if mod is None or mod is mine or getattr(mod, "NeonCard", None) is not NeonCard:
            continue
        for key, val in pal.items():
            if key in mod.__dict__:
                mod.__dict__[key] = val
        hook = mod.__dict__.get("_palette_changed")
        if callable(hook):
            hook()


_KEEP = {"AI", "DI", "DO", "CSV", "COM", "DB", "TX", "RX", "RTU", "MFT", "UI", "OK", "ID", "AI/DI/DO", "PDF", "RS-485", "µA"}


def soften(text):
    """SHOUTING CAPS -> sentence case (codes like AI1, DI, CSV stay as they are)."""
    if not text or any(ch.islower() for ch in text):
        return text
    out, first = [], True
    for tok in text.split(" "):
        letters = [c for c in tok if c.isalpha()]
        if not letters or any(c.isdigit() for c in tok) or tok.strip("()·,:") in _KEEP:
            out.append(tok)
        elif first:
            out.append(tok[:1] + tok[1:].lower())
        else:
            out.append(tok.lower())
        if letters:
            first = False
    return " ".join(out)


class _SoftLabel(QLabel):
    def setText(self, text):
        super().setText(soften(text))


def remap(color):
    """A colour from the other palette -> the same role in the current one."""
    for other in PALETTES.values():
        for key, val in other.items():
            if val == color and key in PALETTES[THEME]:
                return PALETTES[THEME][key]
    return color


def qc(color, alpha=255):
    c = QColor(color)
    c.setAlpha(alpha)
    return c


def font(size, bold=False, spacing=0.0):
    f = QFont(FONT)
    f.setPixelSize(int(size))
    f.setBold(bold)
    if spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return f


def nice_ticks(lo, hi, count=5):
    if hi - lo < 1e-12:
        hi = lo + 1.0
    raw = (hi - lo) / max(1, count)
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        step = m * mag
        if step >= raw:
            break
    start = math.ceil(lo / step) * step
    ticks = []
    v = start
    while v <= hi + step * 1e-6:
        ticks.append(round(v, 10))
        v += step
    return ticks


def fmt_tick(v):
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    if abs(v) >= 100 or v == int(v):
        return f"{v:.0f}"
    return f"{v:.2f}".rstrip("0").rstrip(".") if abs(v) < 10 else f"{v:.1f}"


def time_label(t, span):
    dt = datetime.fromtimestamp(t)
    if span <= 2 * 3600:
        return dt.strftime("%H:%M:%S")
    if span <= 2 * 86400:
        return dt.strftime("%H:%M")
    return dt.strftime("%d %b %H:%M")


def glow_path(p, path, color, width=2.0):
    """A crisp rounded line (the old neon glow strokes are gone)."""
    pen = QPen(qc(color), width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.drawPath(path)


def chip_style(color=None):
    color = color or BLUE
    return (f"QLabel{{color:{color};background:{qc(color, 20).name(QColor.HexArgb)};"
            f"border:none;border-radius:9px;"
            f"padding:2px 9px;font-family:'{FONT}';font-size:10px;font-weight:600;}}")


def draw_tag(p, x, y, text, color, h=15):
    """Small rounded tag; returns its width."""
    p.setFont(font(9, True, 0.4))
    w = p.fontMetrics().horizontalAdvance(text) + 14
    rect = QRectF(x, y, w, h)
    p.setPen(Qt.NoPen)
    p.setBrush(qc(color, 30))
    p.drawRoundedRect(rect, h / 2, h / 2)
    p.setPen(qc(color))
    p.drawText(rect, Qt.AlignCenter, text)
    return w


def _transparent(widget):
    """Painted widgets must not pick up the suite's global light QWidget background."""
    widget.setAutoFillBackground(False)
    widget.setStyleSheet(f"{type(widget).__name__}{{background:transparent;}}")


# ------------------------------------------------------------------------------------ containers
class Chip(_SoftLabel):
    def __init__(self, text="", color=None, parent=None):
        super().__init__(soften(text), parent)
        self._color = None
        self.set_color(color or BLUE)

    def set_color(self, color):
        if color != getattr(self, "_color", None):
            self._color = color
            self.setStyleSheet(chip_style(color))

    def retheme(self):
        color = remap(self._color)
        self._color = None
        self.set_color(color)


class NeonCard(QFrame):
    """Flat surface card with a hairline border. `header` holds the title and chips, `body` the content."""

    clicked = Signal(object)

    def __init__(self, title="", accent=None, parent=None):
        super().__init__(parent)
        _transparent(self)
        self._accent = accent or BLUE
        self._expanded = False
        self._press = None
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_StyledBackground, False)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 16)
        outer.setSpacing(10)
        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        self.title_label = _SoftLabel(soften(title))
        self.header.addWidget(self.title_label)
        self.header.addStretch(1)
        self.expand_label = QLabel("Expand")
        self.expand_label.setToolTip("Tap the card to enlarge it, tap again to go back")
        self.header.addWidget(self.expand_label)
        outer.addLayout(self.header)
        self.body = QVBoxLayout()
        self.body.setSpacing(6)
        outer.addLayout(self.body, 1)
        self.retheme()
        if not title:
            self.title_label.hide()
            self.expand_label.hide()
            self.setCursor(Qt.ArrowCursor)

    def retheme(self):
        self.title_label.setStyleSheet(
            f"color:{WHITE};font-family:'{FONT}';font-size:13px;font-weight:600;background:transparent;")
        self.expand_label.setStyleSheet(
            f"color:{MUTED};background:transparent;font-family:'{FONT}';font-size:11px;font-weight:500;")

    def add_chip(self, text, color=None):
        chip = Chip(text, color or BLUE)
        self.header.insertWidget(self.header.count() - 1, chip)     # before the EXPAND label
        return chip

    def set_expanded(self, on):
        self._expanded = bool(on)
        self.expand_label.setText("Back" if on else "Expand")
        self.update()

    def mousePressEvent(self, event):
        self._press = event.position() if event.button() == Qt.LeftButton else None
        event.accept()

    def mouseReleaseEvent(self, event):
        press, self._press = self._press, None
        if press is not None and event.button() == Qt.LeftButton and \
                (event.position() - press).manhattanLength() < 6 and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self)
        event.accept()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(qc(SURFACE))
        p.setPen(QPen(qc(BLUE if self._expanded else BORDER), 1.4 if self._expanded else 1.0))
        p.drawRoundedRect(r, 12, 12)
        p.end()


# ------------------------------------------------------------------------------------ KPI tile
class KpiTile(QWidget):
    def __init__(self, title="", parent=None):
        super().__init__(parent)
        _transparent(self)
        self.setMinimumHeight(116)
        self.setMinimumWidth(150)
        self.title = title
        self.value, self.unit, self.sub, self.delta = "--", "", "", ""
        self.color = BLUE
        self.delta_color = GREEN
        self.spark = []
        self.delta_up = True

    def set(self, value, unit="", sub="", color=None, spark=None, delta="", delta_color=None):
        color = color or BLUE
        new = (value, unit, sub, color, tuple(spark or ()), delta, delta_color)
        if new == getattr(self, "_sig", None):
            return
        self._sig = new
        self.value, self.unit, self.sub, self.color = str(value), unit, sub, color
        self.spark = list(spark or [])
        self.delta = delta
        self.delta_color = delta_color or GREEN
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(qc(SURFACE))
        p.setPen(QPen(qc(BORDER), 1))
        p.drawRoundedRect(r, 12, 12)
        x = r.left() + 18
        p.setPen(Qt.NoPen)                                   # status dot in the accent colour
        p.setBrush(qc(self.color))
        p.drawEllipse(QPointF(x + 3.5, r.top() + 22), 3.5, 3.5)
        p.setPen(qc(MUTED))
        p.setFont(font(12, True))
        p.drawText(QPointF(x + 14, r.top() + 27), self.title)
        p.setFont(font(32, True))
        vw = p.fontMetrics().horizontalAdvance(self.value)
        p.setPen(qc(WHITE))
        p.drawText(QPointF(x, r.top() + 66), self.value)
        if self.unit:
            p.setFont(font(13, True))
            p.setPen(qc(MUTED))
            p.drawText(QPointF(x + vw + 5, r.top() + 66), self.unit)
        y = r.bottom() - 14
        dx = x
        if self.delta:
            p.setFont(font(11, True))
            p.setPen(qc(self.delta_color))
            p.drawText(QPointF(dx, y), self.delta)
            dx += p.fontMetrics().horizontalAdvance(self.delta) + 8
        p.setFont(font(11))
        p.setPen(qc(MUTED))
        avail = int(r.right() - 120 - dx) if len(self.spark) > 1 else int(r.right() - 12 - dx)
        p.drawText(QPointF(dx, y), p.fontMetrics().elidedText(self.sub, Qt.ElideRight, max(20, avail)))
        if len(self.spark) > 1:
            self._draw_spark(p, QRectF(r.right() - 112, r.bottom() - 52, 98, 32))
        p.end()

    def _draw_spark(self, p, box):
        v = self.spark[-60:]
        lo, hi = min(v), max(v)
        rng = (hi - lo) or 1.0
        pts = [QPointF(box.left() + box.width() * i / (len(v) - 1), box.bottom() - 3 - (x - lo) / rng * (box.height() - 6))
               for i, x in enumerate(v)]
        path = QPainterPath(pts[0])
        for pt in pts[1:]:
            path.lineTo(pt)
        fill = QPainterPath(path)
        fill.lineTo(box.right(), box.bottom())
        fill.lineTo(box.left(), box.bottom())
        fill.closeSubpath()
        g = QLinearGradient(box.topLeft(), box.bottomLeft())
        g.setColorAt(0, qc(self.color, 46))
        g.setColorAt(1, qc(self.color, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawPath(fill)
        p.setBrush(Qt.NoBrush)
        glow_path(p, path, self.color, 1.6)


# ------------------------------------------------------------------------------------ rings / gauges
class RingScore(QWidget):
    def __init__(self, size=84, parent=None):
        super().__init__(parent)
        _transparent(self)
        self.score = None
        self.caption = ""
        self.setMinimumSize(size, size)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

    def set_score(self, score, caption=""):
        if (score, caption) != (self.score, self.caption):
            self.score, self.caption = score, caption
            self.update()

    @staticmethod
    def color_for(score):
        return GREEN if score >= 85 else AMBER if score >= 60 else RED

    def paintEvent(self, event):
        p = QPainter(self)
        draw_ring(p, QRectF(self.rect()), self.score, self.caption)
        p.end()


def draw_ring(p, rect, score, caption="", number_size=None):
    p.setRenderHint(QPainter.Antialiasing)
    side = min(rect.width(), rect.height())
    w = max(4.0, side * 0.085)
    box = QRectF(rect.center().x() - side / 2 + w, rect.center().y() - side / 2 + w, side - 2 * w, side - 2 * w)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(qc(TRACK), w, Qt.SolidLine, Qt.RoundCap))
    p.drawEllipse(box)
    if score is None:
        p.setPen(qc(MUTED))
        p.setFont(font(side * 0.3, True))
        p.drawText(rect, Qt.AlignCenter, "--")
        return
    color = RingScore.color_for(score)
    span = int(-360 * 16 * max(0, min(100, score)) / 100.0)
    p.setPen(QPen(qc(color), w, Qt.SolidLine, Qt.RoundCap))
    p.drawArc(box, 90 * 16, span)
    p.setPen(qc(WHITE))
    p.setFont(font(number_size or side * 0.34, True))
    if caption:
        p.drawText(QRectF(rect.left(), rect.center().y() - side * 0.28, rect.width(), side * 0.42), Qt.AlignCenter, str(score))
        p.setPen(qc(MUTED))
        p.setFont(font(max(8, side * 0.075), True, 2.0))
        p.drawText(QRectF(rect.left(), rect.center().y() + side * 0.08, rect.width(), side * 0.2), Qt.AlignCenter, caption)
    else:
        p.drawText(rect, Qt.AlignCenter, str(score))


class ArcGauge(QWidget):
    def __init__(self, caption="", parent=None):
        super().__init__(parent)
        _transparent(self)
        self.setMinimumSize(170, 150)
        self.value = 0.0
        self.caption = caption
        self.foot = ""

    def set_value(self, value, foot=""):
        if (round(value, 1), foot) != (round(self.value, 1), self.foot):
            self.value, self.foot = value, foot
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height() - 24)
        cx, cy = self.width() / 2, side / 2 + 6
        w = 11
        box = QRectF(cx - side / 2 + w, cy - side / 2 + w, side - 2 * w, side - 2 * w)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(qc(TRACK), w, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(box, 225 * 16, -270 * 16)
        frac = max(0.0, min(1.0, self.value / 100.0))
        color = TEAL if frac < 0.6 else AMBER if frac < 0.85 else RED
        if frac > 0:
            for ww, a in ((w * 1.9, 26), (w * 1.35, 60)):
                p.setPen(QPen(qc(color, a), ww, Qt.SolidLine, Qt.RoundCap))
                p.drawArc(box, 225 * 16, int(-270 * 16 * frac))
            g = QLinearGradient(box.topLeft(), box.bottomRight())
            g.setColorAt(0, qc(TEAL))
            g.setColorAt(1, qc(VIOLET if color == TEAL else color))
            p.setPen(QPen(QBrush(g), w, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(box, 225 * 16, int(-270 * 16 * frac))
        p.setPen(qc(WHITE))
        p.setFont(font(side * 0.27, True))
        p.drawText(QRectF(0, cy - side * 0.2, self.width(), side * 0.3), Qt.AlignCenter, f"{self.value:.0f}%")
        p.setPen(qc(MUTED))
        p.setFont(font(9, True, 1.6))
        p.drawText(QRectF(0, cy + side * 0.12, self.width(), 16), Qt.AlignCenter, self.caption.upper())
        if self.foot:
            p.setFont(font(10))
            p.drawText(QRectF(0, self.height() - 18, self.width(), 16), Qt.AlignCenter, self.foot)
        p.end()


# ------------------------------------------------------------------------------------ series chart
class SeriesChart(QWidget):
    """Multi-series time chart: glow lines, min/max band, moving average, limit lines,
    forecast cone with ETA marker, hover tooltip. Decimated to the pixel width."""
    L, R, T, B = 54, 16, 12, 28

    def __init__(self, parent=None, min_height=260):
        super().__init__(parent)
        _transparent(self)
        self.setMinimumHeight(min_height)
        self.setMouseTracking(True)
        self.series = []
        self.limits = []            # [(value, label, color)]
        self.forecast = None        # {"pts": [(t, v)], "color", "eta": (t, v, text), "cone": 0.0}
        self.t0, self.t1 = 0.0, 1.0
        self.now_t = None
        self.ymin = self.ymax = None
        self.unit = ""
        self.message = "No data"
        self.fill = True
        self._hover = None

    def set_data(self, series, t0, t1, limits=None, forecast=None, now_t=None, ymin=None, ymax=None,
                 unit="", message="No data", fill=True):
        self.series, self.t0, self.t1 = series, float(t0), float(max(t1, t0 + 1e-3))
        self.limits, self.forecast, self.now_t = limits or [], forecast, now_t
        self.ymin, self.ymax, self.unit, self.message, self.fill = ymin, ymax, unit, message, fill
        self.update()

    # ---- geometry
    def _plot(self):
        return QRectF(self.L, self.T, max(10, self.width() - self.L - self.R), max(10, self.height() - self.T - self.B))

    def _yrange(self):
        if self.ymin is not None and self.ymax is not None:
            return self.ymin, self.ymax
        lo, hi = math.inf, -math.inf
        for s in self.series:
            vals = s["vals"]
            if vals:
                lo, hi = min(lo, min(vals)), max(hi, max(vals))
        for v, _l, _c in self.limits:
            lo, hi = min(lo, v), max(hi, v)
        if self.forecast:
            for _t, v in self.forecast["pts"]:
                lo, hi = min(lo, v), max(hi, v)
        if lo == math.inf:
            return 0.0, 1.0
        if hi - lo < 1e-9:
            lo, hi = lo - 0.5, hi + 0.5
        pad = (hi - lo) * 0.08
        lo = lo - pad if self.ymin is None else self.ymin
        hi = hi + pad if self.ymax is None else self.ymax
        return lo, hi

    def _decimate(self, ts, vals, width):
        """Indices to draw: every point if few, else the min and max of each pixel column."""
        i0 = bisect_left(ts, self.t0)
        i1 = min(len(ts), bisect_left(ts, self.t1) + 1)
        n = i1 - i0
        if n <= 2 * width:
            return range(max(0, i0 - 1), i1)
        out = []
        per = n / float(width)
        for c in range(int(width)):
            a, b = i0 + int(c * per), min(i1, i0 + int((c + 1) * per) + 1)
            seg = vals[a:b]
            if not seg:
                continue
            lo_i = a + seg.index(min(seg))
            hi_i = a + seg.index(max(seg))
            out.extend(sorted({lo_i, hi_i}))
        return out

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        plot = self._plot()
        ylo, yhi = self._yrange()
        span = self.t1 - self.t0

        def X(t):
            return plot.left() + (t - self.t0) / span * plot.width()

        def Y(v):
            return plot.bottom() - (v - ylo) / (yhi - ylo) * plot.height()

        p.setFont(font(10))
        for v in nice_ticks(ylo, yhi, 5):
            y = Y(v)
            p.setPen(QPen(qc(GRID), 1))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(qc(MUTED))
            p.drawText(QRectF(0, y - 8, self.L - 8, 16), Qt.AlignRight | Qt.AlignVCenter, fmt_tick(v))
        if self.unit:
            p.setPen(qc(MUTED, 160))
            p.setFont(font(9, True, 1.0))
            p.drawText(QPointF(self.L + 6, self.T + 11), self.unit)
            p.setFont(font(10))
        ticks = 6
        for i in range(ticks + 1):
            t = self.t0 + span * i / ticks
            x = X(t)
            p.setPen(QPen(qc(GRID), 1, Qt.DotLine))
            p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            p.setPen(qc(MUTED))
            label = time_label(t, span)
            align = Qt.AlignHCenter
            rect = QRectF(x - 40, plot.bottom() + 6, 80, 16)
            if i == 0:
                rect, align = QRectF(x - 4, plot.bottom() + 6, 80, 16), Qt.AlignLeft
            elif i == ticks:
                rect, align = QRectF(x - 76, plot.bottom() + 6, 80, 16), Qt.AlignRight
            p.drawText(rect, align | Qt.AlignVCenter, label)
        if not any(s["ts"] for s in self.series):
            p.setPen(qc(MUTED))
            p.setFont(font(13))
            p.drawText(plot, Qt.AlignCenter, self.message)
            p.end()
            return
        p.save()
        p.setClipRect(plot.adjusted(-2, -4, 2, 4))
        w = plot.width()
        # forecast cone first (under the lines)
        fc = self.forecast
        if fc and len(fc["pts"]) > 1:
            pts = fc["pts"]
            cone = QPainterPath()
            spread = fc.get("spread", 0.0)
            n = len(pts)
            cone.moveTo(X(pts[0][0]), Y(pts[0][1]))
            for i, (t, v) in enumerate(pts):
                cone.lineTo(X(t), Y(v + spread * i / (n - 1)))
            for i in range(n - 1, -1, -1):
                t, v = pts[i]
                cone.lineTo(X(t), Y(v - spread * i / (n - 1)))
            cone.closeSubpath()
            p.setPen(Qt.NoPen)
            p.setBrush(qc(fc["color"], 34))
            p.drawPath(cone)
        for idx, s in enumerate(self.series):
            ts, vals = s["ts"], s["vals"]
            if not ts:
                continue
            color = s["color"]
            if s.get("band"):                      # min/max band
                lo_b, hi_b = s["band"]
                ix = list(self._decimate(ts, vals, w / 2))
                band = QPainterPath()
                band.moveTo(X(ts[ix[0]]), Y(hi_b[ix[0]]))
                for i in ix:
                    band.lineTo(X(ts[i]), Y(hi_b[i]))
                for i in reversed(ix):
                    band.lineTo(X(ts[i]), Y(lo_b[i]))
                band.closeSubpath()
                p.setPen(Qt.NoPen)
                p.setBrush(qc(color, 30))
                p.drawPath(band)
            ix = list(self._decimate(ts, vals, w))
            if not ix:
                continue
            path = QPainterPath()
            started = False
            gap = s.get("gap")
            prev = None
            for i in ix:
                pt = QPointF(X(ts[i]), Y(vals[i]))
                if not started or (gap and prev is not None and ts[i] - ts[prev] > gap):
                    path.moveTo(pt)
                    started = True
                else:
                    path.lineTo(pt)
                prev = i
            if self.fill and len(self.series) <= 4 and not gap:
                area = QPainterPath(path)
                area.lineTo(X(ts[ix[-1]]), plot.bottom())
                area.lineTo(X(ts[ix[0]]), plot.bottom())
                area.closeSubpath()
                g = QLinearGradient(0, plot.top(), 0, plot.bottom())
                g.setColorAt(0, qc(color, 62))
                g.setColorAt(1, qc(color, 0))
                p.setPen(Qt.NoPen)
                p.setBrush(g)
                p.drawPath(area)
            p.setBrush(Qt.NoBrush)
            glow_path(p, path, color, 1.9 if len(ix) < 4 * w else 1.4)
            if s.get("ma"):
                ma = s["ma"]
                mpath = QPainterPath()
                for n_, i in enumerate(ix):
                    pt = QPointF(X(ts[i]), Y(ma[i]))
                    mpath.moveTo(pt) if n_ == 0 else mpath.lineTo(pt)
                pen = QPen(qc(WHITE, 230), 1.5, Qt.DashLine)
                p.setPen(pen)
                p.drawPath(mpath)
        for v, label, color in self.limits:
            y = Y(v)
            p.setPen(QPen(qc(color, 230), 1.4, Qt.DashLine))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setFont(font(9, True))
            p.setPen(qc(color))
            p.drawText(QPointF(plot.left() + 6, y - 5), label)
        if fc and len(fc["pts"]) > 1:
            path = QPainterPath()
            for i, (t, v) in enumerate(fc["pts"]):
                pt = QPointF(X(t), Y(v))
                path.moveTo(pt) if i == 0 else path.lineTo(pt)
            p.setPen(QPen(qc(fc["color"]), 2, Qt.DashLine))
            p.drawPath(path)
            if fc.get("eta"):
                et, ev, text = fc["eta"]
                pt = QPointF(X(et), Y(ev))
                p.setPen(Qt.NoPen)
                p.setBrush(qc(RED, 45))
                p.drawEllipse(pt, 11, 11)
                p.setBrush(qc(SURFACE))
                p.setPen(QPen(qc(RED), 2.4))
                p.drawEllipse(pt, 5, 5)
                p.setFont(font(11, True))
                p.setPen(qc(RED))
                tw = p.fontMetrics().horizontalAdvance(text)
                tx = min(max(pt.x() - tw / 2, plot.left() + 4), plot.right() - tw - 4)
                p.drawText(QPointF(tx, min(pt.y() + 24, plot.bottom() - 4)), text)
        if self.now_t is not None and self.t0 < self.now_t < self.t1:
            x = X(self.now_t)
            p.setPen(QPen(qc(FAINT), 1, Qt.DashLine))
            p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            p.setPen(qc(MUTED))
            p.setFont(font(9, True, 1.0))
            p.drawText(QPointF(x - 30, plot.top() + 11), "NOW")
        p.restore()
        # live head dot
        if self.now_t is None and self.series:
            for s in self.series[:4]:
                if s["ts"] and s["ts"][-1] >= self.t1 - span * 0.02:
                    pt = QPointF(X(s["ts"][-1]), Y(s["vals"][-1]))
                    p.setPen(Qt.NoPen)
                    p.setBrush(qc(s["color"], 50))
                    p.drawEllipse(pt, 8, 8)
                    p.setBrush(qc(SURFACE))
                    p.setPen(QPen(qc(s["color"]), 2))
                    p.drawEllipse(pt, 3.8, 3.8)
        if self._hover is not None and plot.left() <= self._hover <= plot.right():
            self._paint_tooltip(p, plot, X, span)
        p.end()

    def _paint_tooltip(self, p, plot, X, span):
        t = self.t0 + (self._hover - plot.left()) / plot.width() * span
        lines = [(datetime.fromtimestamp(t).strftime("%d %b %H:%M:%S"), MUTED)]
        for s in self.series[:8]:
            ts = s["ts"]
            if not ts:
                continue
            i = bisect_left(ts, t)
            if i >= len(ts) or (i > 0 and t - ts[i - 1] < ts[i] - t):
                i = max(0, i - 1)
            if abs(ts[i] - t) > max(span * 0.05, 5):
                continue
            lines.append((f"{s['name']}  {s['vals'][i]:.2f}{(' ' + s['unit']) if s.get('unit') else ''}", s["color"]))
        if len(lines) < 2:
            return
        p.setPen(QPen(qc(FAINT), 1, Qt.DashLine))
        p.drawLine(QPointF(self._hover, plot.top()), QPointF(self._hover, plot.bottom()))
        p.setFont(font(11, True))
        bw = max(p.fontMetrics().horizontalAdvance(txt) for txt, _ in lines) + 20
        bh = len(lines) * 17 + 10
        bx = self._hover + 14
        if bx + bw > plot.right():
            bx = self._hover - 14 - bw
        box = QRectF(bx, plot.top() + 8, bw, bh)
        p.setBrush(qc(SURFACE, 248))
        p.setPen(QPen(qc(BLUE, 130), 1))
        p.drawRoundedRect(box, 9, 9)
        for i, (txt, col) in enumerate(lines):
            p.setPen(qc(col))
            p.drawText(QRectF(box.left() + 10, box.top() + 5 + i * 17, bw, 17), Qt.AlignLeft | Qt.AlignVCenter, txt)

    def mouseMoveEvent(self, event):
        self._hover = event.position().x()
        self.update()

    def leaveEvent(self, event):
        self._hover = None
        self.update()


# ------------------------------------------------------------------------------------ brush
class BrushBar(QWidget):
    """Overview strip with two draggable handles; narrows the analysed period without a new query."""
    rangeChanged = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        _transparent(self)
        self.setMinimumHeight(58)
        self.setMouseTracking(True)
        self.ts, self.vals = [], []
        self.full = (0.0, 1.0)
        self.sel = (0.0, 1.0)
        self._drag = None

    def set_overview(self, ts, vals, full, sel):
        step = max(1, len(ts) // 400)
        self.ts, self.vals = ts[::step], vals[::step]
        self.full, self.sel = (float(full[0]), float(max(full[1], full[0] + 1e-3))), (float(sel[0]), float(sel[1]))
        self.update()

    def _x(self, t):
        w = self.width() - 28
        return 14 + (t - self.full[0]) / (self.full[1] - self.full[0]) * w

    def _t(self, x):
        w = self.width() - 28
        return self.full[0] + (x - 14) / w * (self.full[1] - self.full[0])

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        box = QRectF(14, 6, self.width() - 28, 30)
        p.setBrush(qc(SURFACE))
        p.setPen(QPen(qc(BORDER), 1))
        p.drawRoundedRect(box, 8, 8)
        if len(self.vals) > 1:
            lo, hi = min(self.vals), max(self.vals)
            rng = (hi - lo) or 1.0
            path = QPainterPath()
            for i, (t, v) in enumerate(zip(self.ts, self.vals)):
                pt = QPointF(self._x(t), box.bottom() - 4 - (v - lo) / rng * (box.height() - 8))
                path.moveTo(pt) if i == 0 else path.lineTo(pt)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(qc(BLUE, 150), 1.2))
            p.drawPath(path)
        x0, x1 = self._x(self.sel[0]), self._x(self.sel[1])
        sel = QRectF(x0, box.top(), max(2.0, x1 - x0), box.height())
        p.setBrush(qc(VIOLET, 28))
        p.setPen(QPen(qc(VIOLET), 1.4))
        p.drawRoundedRect(sel, 8, 8)
        p.setPen(Qt.NoPen)
        p.setBrush(qc(VIOLET))
        for x in (x0, x1):
            p.drawRoundedRect(QRectF(x - 4.5, box.top() + 3, 9, box.height() - 6), 4, 4)
        p.setPen(qc(MUTED))
        p.setFont(font(9))
        p.drawText(QRectF(14, 38, self.width() - 28, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   "drag the handles to narrow the analysed period · drag inside to move it")
        label = f"{time_label(self.full[0], self.full[1] - self.full[0])}  ·····  loaded range  ·····  " \
                f"{time_label(self.full[1], self.full[1] - self.full[0])}"
        p.drawText(QRectF(14, 38, self.width() - 28, 16), Qt.AlignRight | Qt.AlignVCenter, label)
        p.end()

    def mousePressEvent(self, event):
        x = event.position().x()
        x0, x1 = self._x(self.sel[0]), self._x(self.sel[1])
        if abs(x - x0) <= 9:
            self._drag = ("l", x)
        elif abs(x - x1) <= 9:
            self._drag = ("r", x)
        elif x0 < x < x1:
            self._drag = ("m", x)

    def mouseMoveEvent(self, event):
        x = event.position().x()
        x0, x1 = self._x(self.sel[0]), self._x(self.sel[1])
        if self._drag is None:
            self.setCursor(Qt.SizeHorCursor if min(abs(x - x0), abs(x - x1)) <= 9 else
                           Qt.OpenHandCursor if x0 < x < x1 else Qt.ArrowCursor)
            return
        mode, last = self._drag
        t = self._t(x)
        lo, hi = self.sel
        minw = (self.full[1] - self.full[0]) * 0.01
        if mode == "l":
            lo = max(self.full[0], min(t, hi - minw))
        elif mode == "r":
            hi = min(self.full[1], max(t, lo + minw))
        else:
            dt = self._t(x) - self._t(last)
            dt = max(self.full[0] - lo, min(self.full[1] - hi, dt))
            lo, hi = lo + dt, hi + dt
            self._drag = ("m", x)
        self.sel = (lo, hi)
        self.update()

    def mouseReleaseEvent(self, event):
        if self._drag is not None:
            self._drag = None
            self.rangeChanged.emit(self.sel[0], self.sel[1])


# ------------------------------------------------------------------------------------ histogram
class HistChart(QWidget):
    def __init__(self, parent=None, min_height=200):
        super().__init__(parent)
        _transparent(self)
        self.setMinimumHeight(min_height)
        self.counts, self.edges = [], []
        self.mean = None
        self.note = ""
        self.mark = {}            # {"p50": value, "p95": value} drawn as vertical markers
        self.unit = ""
        self.color = TEAL

    def set_data(self, counts, edges, mean=None, note="", marks=None, color=None, unit=""):
        color = color or TEAL
        self.counts, self.edges, self.mean, self.note, self.mark, self.color, self.unit = \
            list(counts), list(edges), mean, note, marks or {}, color, unit
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        L, R, T, B = 34, 10, 22, 28
        plot = QRectF(L, T, self.width() - L - R, self.height() - T - B)
        p.setFont(font(10))
        if not self.counts or sum(self.counts) == 0:
            p.setPen(qc(MUTED))
            p.setFont(font(13))
            p.drawText(QRectF(self.rect()), Qt.AlignCenter, "No data")
            p.end()
            return
        peak = max(self.counts)
        for i in range(4):
            y = plot.bottom() - plot.height() * i / 3
            p.setPen(QPen(qc(GRID), 1))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(qc(MUTED))
            p.drawText(QRectF(0, y - 8, L - 6, 16), Qt.AlignRight | Qt.AlignVCenter, str(int(round(peak * i / 3))))
        n = len(self.counts)
        bw = plot.width() / n
        g = QLinearGradient(0, plot.top(), 0, plot.bottom())
        g.setColorAt(0, qc(self.color))
        g.setColorAt(1, qc(BLUE, 120))
        tops = []
        for i, c in enumerate(self.counts):
            h = c / peak * (plot.height() - 4)
            rect = QRectF(plot.left() + i * bw + 2, plot.bottom() - h, bw - 4, max(h, 2))
            p.setPen(Qt.NoPen)
            p.setBrush(qc(self.color, 40))
            p.drawRoundedRect(rect.adjusted(-2, -2, 2, 0), 4, 4)
            p.setBrush(g)
            p.drawRoundedRect(rect, 4, 4)
            tops.append(QPointF(rect.center().x(), rect.top() - 1))
        if len(tops) > 2:
            path = QPainterPath(tops[0])
            for a, b in zip(tops, tops[1:]):
                mid = (a.x() + b.x()) / 2
                path.cubicTo(QPointF(mid, a.y()), QPointF(mid, b.y()), b)
            p.setBrush(Qt.NoBrush)
            glow_path(p, path, VIOLET, 1.8)
        lo, hi = self.edges[0], self.edges[-1]
        step = max(1, n // 7)
        p.setPen(qc(MUTED))
        p.setFont(font(10))
        for i in range(0, n, step):
            cx = plot.left() + (i + 0.5) * bw
            p.drawText(QRectF(cx - 30, plot.bottom() + 6, 60, 16), Qt.AlignCenter, fmt_tick((self.edges[i] + self.edges[i + 1]) / 2))

        def mark(value, label, color):
            if value is None or hi <= lo:
                return
            x = plot.left() + (value - lo) / (hi - lo) * plot.width()
            x = min(max(x, plot.left()), plot.right())
            p.setPen(QPen(qc(color, 230), 1.4, Qt.DashLine))
            p.drawLine(QPointF(x, plot.top() - 4), QPointF(x, plot.bottom()))
            p.setFont(font(10, True))
            p.setPen(qc(color))
            tw = p.fontMetrics().horizontalAdvance(label)
            p.drawText(QPointF(min(x + 5, plot.right() - tw), plot.top() + 6), label)
        if self.mean is not None:
            mark(self.mean, f"μ {self.mean:.2f}", WHITE)
        for key, color in (("p50", AMBER), ("p95", RED)):
            if key in self.mark:
                mark(self.mark[key], f"{key} {self.mark[key]:.0f} ms", color)
        if self.note:
            p.setFont(font(10))
            p.setPen(qc(MUTED))
            p.drawText(QRectF(plot.left(), 0, plot.width(), 16), Qt.AlignRight | Qt.AlignVCenter, self.note)
        p.end()


# ------------------------------------------------------------------------------------ lanes (DI/DO)
class LaneChart(QWidget):
    ROW = 28
    L, R, B = 58, 12, 26

    def __init__(self, parent=None):
        super().__init__(parent)
        _transparent(self)
        self.lanes = []
        self.t0, self.t1 = 0.0, 1.0
        self.setMouseTracking(True)
        self._hover = None
        self.message = "No data"

    def set_lanes(self, lanes, t0, t1, message="No data"):
        """lanes: [{"name", "segments": [(t0, t1, state)], "tag", "color"}]"""
        self.lanes, self.t0, self.t1, self.message = lanes, float(t0), float(max(t1, t0 + 1e-3)), message
        self.setMinimumHeight(max(60, len(lanes) * self.ROW + self.B + 8))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width() - self.L - self.R
        span = self.t1 - self.t0
        if not self.lanes:
            p.setPen(qc(MUTED))
            p.setFont(font(13))
            p.drawText(QRectF(self.rect()), Qt.AlignCenter, self.message)
            p.end()
            return

        def X(t):
            return self.L + (t - self.t0) / span * w
        plot_bottom = len(self.lanes) * self.ROW
        p.setFont(font(10))
        for i in range(7):
            x = self.L + w * i / 6
            p.setPen(QPen(qc(GRID), 1, Qt.DotLine))
            p.drawLine(QPointF(x, 0), QPointF(x, plot_bottom))
            p.setPen(qc(MUTED))
            label = time_label(self.t0 + span * i / 6, span)
            if i == 0:
                p.drawText(QRectF(x - 4, plot_bottom + 4, 80, 16), Qt.AlignLeft, label)
            elif i == 6:
                p.drawText(QRectF(x - 76, plot_bottom + 4, 80, 16), Qt.AlignRight, label)
            else:
                p.drawText(QRectF(x - 40, plot_bottom + 4, 80, 16), Qt.AlignHCenter, label)
        for r, lane in enumerate(self.lanes):
            y = r * self.ROW + 3
            color = lane.get("color", BLUE)
            p.setPen(qc(WHITE))
            p.setFont(font(11, True))
            p.drawText(QRectF(0, y, self.L - 8, 22), Qt.AlignRight | Qt.AlignVCenter, lane["name"])
            p.setBrush(qc(SURFACE))
            p.setPen(QPen(qc(BORDER), 1))
            p.drawRoundedRect(QRectF(self.L, y, w, 22), 6, 6)
            p.setPen(Qt.NoPen)
            for a, b, state in lane["segments"]:
                if not state or b < self.t0 or a > self.t1:
                    continue
                x0, x1 = max(X(a), self.L), min(X(b), self.L + w)
                width = max(x1 - x0, 1.4)
                p.setBrush(qc(color, 50))
                p.drawRoundedRect(QRectF(x0 - 1, y + 1, width + 2, 20), 4, 4)
                p.setBrush(qc(color, 225))
                p.drawRoundedRect(QRectF(x0, y + 3, width, 16), 3, 3)
        if self._hover is not None and self.L <= self._hover <= self.L + w:
            t = self.t0 + (self._hover - self.L) / w * span
            p.setPen(QPen(qc(FAINT), 1, Qt.DashLine))
            p.drawLine(QPointF(self._hover, 0), QPointF(self._hover, plot_bottom))
            p.setPen(qc(WHITE))
            p.setFont(font(10, True))
            p.drawText(QPointF(min(self._hover + 6, self.width() - 110), 12),
                       datetime.fromtimestamp(t).strftime("%d %b %H:%M:%S"))
        p.end()

    def mouseMoveEvent(self, event):
        self._hover = event.position().x()
        self.update()

    def leaveEvent(self, event):
        self._hover = None
        self.update()


# ------------------------------------------------------------------------------------ bars
class HBars(QWidget):
    ROW = 26

    def __init__(self, parent=None):
        super().__init__(parent)
        _transparent(self)
        self.rows = []
        self.max_value = None
        self.color = BLUE

    def set_rows(self, rows, max_value=None, color=None):
        """rows: [(label, value, text, flagged)]"""
        color = color or BLUE
        self.rows, self.max_value, self.color = rows, max_value, color
        self.setMinimumHeight(max(30, len(rows) * self.ROW + 6))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.rows:
            p.setPen(qc(MUTED))
            p.setFont(font(13))
            p.drawText(QRectF(self.rect()), Qt.AlignCenter, "No data")
            p.end()
            return
        top = self.max_value or max((r[1] for r in self.rows), default=1) or 1
        lw, vw = 44, 78
        bar_w = self.width() - lw - vw
        for i, (label, value, text, flagged) in enumerate(self.rows):
            y = 4 + i * self.ROW
            p.setPen(qc(WHITE))
            p.setFont(font(11, True))
            p.drawText(QRectF(0, y, lw - 6, 20), Qt.AlignLeft | Qt.AlignVCenter, label)
            track = QRectF(lw, y + 4, bar_w, 12)
            p.setPen(Qt.NoPen)
            p.setBrush(qc(BORDER))
            p.drawRoundedRect(track, 6, 6)
            fw = max(4.0, bar_w * min(1.0, value / top)) if value > 0 else 3.0
            bar = QRectF(lw, y + 4, fw, 12)
            g = QLinearGradient(bar.topLeft(), bar.topRight())
            c0, c1 = (AMBER, RED) if flagged else (TEAL, BLUE)
            g.setColorAt(0, qc(c0))
            g.setColorAt(1, qc(c1))
            p.setBrush(qc(c1, 50))
            p.drawRoundedRect(bar.adjusted(-1, -2, 1, 2), 7, 7)
            p.setBrush(g)
            p.drawRoundedRect(bar, 6, 6)
            p.setPen(qc(WHITE))
            p.setFont(font(11, True))
            p.drawText(QRectF(lw + bar_w + 6, y, vw - 6, 20), Qt.AlignRight | Qt.AlignVCenter, text)
        p.end()


# ------------------------------------------------------------------------------------ heat-map
class HeatMap(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        _transparent(self)
        self.rows = []         # [(label, [pct or None])]
        self.col_labels = []
        self.setMinimumHeight(90)

    def set_rows(self, rows, col_labels=None):
        self.rows, self.col_labels = rows, col_labels or []
        self.setMinimumHeight(max(70, len(rows) * 26 + 28))
        self.update()

    @staticmethod
    def color_for(pct):
        if pct is None:
            return TRACK
        return GREEN if pct >= 97 else AMBER if pct >= 90 else RED

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.rows:
            p.setPen(qc(MUTED))
            p.setFont(font(13))
            p.drawText(QRectF(self.rect()), Qt.AlignCenter, "Waiting for communication data")
            p.end()
            return
        lw = 96
        cols = max(len(r[1]) for r in self.rows)
        cw = (self.width() - lw - 4) / cols
        for r, (label, cells) in enumerate(self.rows):
            y = r * 26
            p.setPen(qc(MUTED))
            p.setFont(font(10, True))
            p.drawText(QRectF(0, y, lw - 8, 22), Qt.AlignRight | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(label, Qt.ElideRight, lw - 10))
            for c, pct in enumerate(cells):
                p.setPen(Qt.NoPen)
                p.setBrush(qc(self.color_for(pct)))
                p.drawRoundedRect(QRectF(lw + c * cw, y, max(2, cw - 3), 22), 4, 4)
        p.setPen(qc(MUTED))
        p.setFont(font(9))
        for c, text in enumerate(self.col_labels):
            if text:
                p.drawText(QRectF(lw + c * cw - 20, len(self.rows) * 26 + 2, cw + 40, 16), Qt.AlignHCenter, text)
        p.end()


# ------------------------------------------------------------------------------------ tiles
class ChannelTile(QWidget):
    """AI channel health: score ring, name, tag, value and metrics."""

    def __init__(self, parent=None):
        super().__init__(parent)
        _transparent(self)
        self.setMinimumHeight(84)
        self.d = None
        self.selected = False
        self.clicked = None
        self.setCursor(Qt.PointingHandCursor)

    def set(self, name, tag, value, unit, score, meta1, meta2, selected=False):
        new = (name, tag, value, unit, score, meta1, meta2, selected)
        if new == self.d:
            return
        self.d = new
        self.selected = selected
        self.update()

    def mousePressEvent(self, event):
        if self.clicked and self.d:
            self.clicked(self.d[0])

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        p.setBrush(qc(SURFACE))
        p.setPen(QPen(qc(BLUE if self.selected else BORDER), 1.4 if self.selected else 1))
        p.drawRoundedRect(r, 12, 12)
        if not self.d:
            p.end()
            return
        name, tag, value, unit, score, meta1, meta2, _sel = self.d
        draw_ring(p, QRectF(r.left() + 8, r.top() + 10, 62, 62), score if tag not in ("NO DATA", "WAIT") else None)
        x = r.left() + 80
        p.setPen(qc(WHITE))
        p.setFont(font(12, True))
        p.drawText(QPointF(x, r.top() + 22), name)
        tw = p.fontMetrics().horizontalAdvance(name)
        draw_tag(p, x + tw + 8, r.top() + 10, tag, TAG_COLORS.get(tag, MUTED), 15)
        p.setFont(font(22, True))
        p.setPen(qc(WHITE))
        p.drawText(QPointF(x, r.top() + 46), value)
        vw = p.fontMetrics().horizontalAdvance(value)
        p.setFont(font(11))
        p.setPen(qc(MUTED))
        p.drawText(QPointF(x + vw + 4, r.top() + 46), unit)
        p.setFont(font(10))
        p.drawText(QPointF(x, r.top() + 61), meta1)
        p.drawText(QPointF(x, r.top() + 74), meta2)
        p.end()


class DigitalTile(QWidget):
    """DI/DO channel card: LED, state, tag and four metrics."""

    def __init__(self, labels, parent=None):
        super().__init__(parent)
        _transparent(self)
        self.labels = labels
        self.setMinimumHeight(108)
        self.d = None

    def set(self, name, state, tag, metrics):
        new = (name, state, tag, tuple(metrics))
        if new == self.d:
            return
        self.d = new
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        p.setBrush(qc(SURFACE))
        p.setPen(QPen(qc(BORDER), 1))
        p.drawRoundedRect(r, 12, 12)
        if not self.d:
            p.end()
            return
        name, state, tag, metrics = self.d
        tag_color = TAG_COLORS.get(tag, MUTED)
        led = {"ON": GREEN, "OFF": MUTED}.get(state, MUTED)
        if tag in ("STUCK",):
            led = RED
        if tag in ("CHATTER", "HUNTING"):
            led = AMBER
        c = QPointF(r.left() + 18, r.top() + 20)
        p.setPen(Qt.NoPen)
        p.setBrush(qc(led, 50))
        p.drawEllipse(c, 8, 8)
        p.setBrush(qc(led))
        p.drawEllipse(c, 4.5, 4.5)
        p.setPen(qc(WHITE))
        p.setFont(font(12, True))
        p.drawText(QPointF(r.left() + 32, r.top() + 25), name)
        nw = p.fontMetrics().horizontalAdvance(name)
        p.setPen(qc(MUTED))
        p.setFont(font(11))
        p.drawText(QPointF(r.left() + 40 + nw, r.top() + 25), state)
        if tag and tag != "STABLE":
            p.setFont(font(8, True, 1.0))
            tw = p.fontMetrics().horizontalAdvance(tag) + 14
            draw_tag(p, r.right() - tw - 10, r.top() + 12, tag, tag_color)
        for i, (label, value) in enumerate(zip(self.labels, metrics)):
            col, row = i % 2, i // 2
            x = r.left() + 14 + col * (r.width() / 2 - 4)
            y = r.top() + 54 + row * 34
            p.setPen(qc(WHITE))
            p.setFont(font(14, True))
            p.drawText(QPointF(x, y - 2), value)
            p.setPen(qc(MUTED))
            p.setFont(font(9))
            p.drawText(QPointF(x, y + 10), label)
        p.end()


# ------------------------------------------------------------------------------------ insights
class InsightList(QWidget):
    """Auto-generated insight rows: coloured badge, text, time. Rows are updated in place so a
    once-per-second refresh does not rebuild widgets."""
    @staticmethod
    def _colors():
        return {"red": RED, "amber": AMBER, "violet": VIOLET, "blue": BLUE, "green": GREEN}

    def retheme(self):
        for row, badge, text, tm, state in self._rows:
            row.setStyleSheet(f"QFrame{{background:{SOFT};border:none;border-radius:10px;}}")
            text.setStyleSheet(f"QLabel{{color:{TEXT};font-family:'{FONT}';font-size:12px;border:none;background:transparent;}}")
            tm.setStyleSheet(f"QLabel{{color:{MUTED};font-family:'{FONT}';font-size:10px;border:none;background:transparent;}}")
            state.clear()

    def __init__(self, parent=None, limit=7):
        super().__init__(parent)
        _transparent(self)
        self.limit = limit
        self._rows = []            # [(frame, badge, text_label, time_label, state)]
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._stretch = False

    def _make_row(self):
        row = QFrame()
        row.setStyleSheet(f"QFrame{{background:{SOFT};border:none;border-radius:10px;}}")
        h = QHBoxLayout(row)
        h.setContentsMargins(9, 7, 9, 7)
        h.setSpacing(10)
        badge = QLabel()
        badge.setFixedSize(26, 26)
        badge.setAlignment(Qt.AlignCenter)
        text = QLabel()
        text.setTextFormat(Qt.RichText)
        text.setWordWrap(True)
        text.setStyleSheet(f"QLabel{{color:{TEXT};font-family:'{FONT}';font-size:12px;border:none;background:transparent;}}")
        tm = QLabel()
        tm.setStyleSheet(f"QLabel{{color:{MUTED};font-family:'{FONT}';font-size:10px;border:none;background:transparent;}}")
        h.addWidget(badge, 0, Qt.AlignTop)
        h.addWidget(text, 1)
        h.addWidget(tm, 0, Qt.AlignTop)
        return [row, badge, text, tm, {}]

    def set_items(self, items):
        items = items[:self.limit]
        while len(self._rows) < len(items):
            r = self._make_row()
            self._rows.append(r)
            self._layout.insertWidget(self._layout.count() - (1 if self._stretch else 0), r[0])
        if not self._stretch:
            self._layout.addStretch(1)
            self._stretch = True
        while len(self._rows) > len(items):
            r = self._rows.pop()
            self._layout.removeWidget(r[0])
            r[0].deleteLater()
        for r, item in zip(self._rows, items):
            row, badge, text, tm, state = r
            color = self._colors().get(item["color"], BLUE)
            if state.get("color") != color or state.get("icon") != item["icon"]:
                badge.setText(item["icon"])
                badge.setStyleSheet(f"QLabel{{background:{qc(color, 28).name(QColor.HexArgb)};color:{color};border-radius:8px;border:none;"
                                    f"font-family:'{FONT}';font-size:13px;font-weight:700;}}")
                state["color"], state["icon"] = color, item["icon"]
            html = (f"<span style='color:{color};font-size:10px;'><b>{item['sev'].title()}</b></span>"
                    f"&nbsp; {item['text']}")
            if state.get("html") != html:
                text.setText(html)
                state["html"] = html
            stamp = item["ts"].strftime("%H:%M") if item.get("ts") else ""
            if state.get("stamp") != stamp:
                tm.setText(stamp)
                tm.setVisible(bool(stamp))
                state["stamp"] = stamp
            row.setVisible(True)


def rolling_minmax(vals, k):
    """(lows, highs) rolling over the last k samples, O(n)."""
    from collections import deque
    lo_q, hi_q = deque(), deque()
    lows, highs = [], []
    for i, v in enumerate(vals):
        while lo_q and vals[lo_q[-1]] >= v:
            lo_q.pop()
        lo_q.append(i)
        while hi_q and vals[hi_q[-1]] <= v:
            hi_q.pop()
        hi_q.append(i)
        while lo_q[0] <= i - k:
            lo_q.popleft()
        while hi_q[0] <= i - k:
            hi_q.popleft()
        lows.append(vals[lo_q[0]])
        highs.append(vals[hi_q[0]])
    return lows, highs


# ------------------------------------------------------------------------------------ freshness strip
class FreshnessStrip(QWidget):
    """One chip per device: how long ago its last reading arrived (green / amber / red)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        _transparent(self)
        self.items = []
        self.setMinimumHeight(40)

    def set_items(self, items):
        """items: [{"name", "age" (seconds or None), "state" (ONLINE/OFFLINE/...), "fresh_s", "stale_s"}]"""
        if items != self.items:
            self.items = items
            self.update()

    @staticmethod
    def level(item):
        age = item.get("age")
        if age is None or item.get("state") == "OFFLINE":
            return RED if item.get("state") == "OFFLINE" else MUTED
        return GREEN if age <= item["fresh_s"] else AMBER if age <= item["stale_s"] else RED

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.items:
            p.setPen(qc(MUTED))
            p.setFont(font(12))
            p.drawText(QRectF(self.rect()), Qt.AlignVCenter | Qt.AlignLeft, "No devices yet")
            p.end()
            return
        x, y, h, gap = 0.0, 0.0, 30.0, 10.0
        for it in self.items:
            color = self.level(it)
            age = it.get("age")
            if age is None:
                text2 = "no data yet" if it.get("state") != "OFFLINE" else "offline"
            elif it.get("state") == "OFFLINE":
                text2 = f"offline \u00b7 last {age:.0f} s ago" if age < 100 else "offline"
            else:
                text2 = f"{age:.1f} s ago" if age < 10 else f"{age:.0f} s ago" if age < 120 else f"{age / 60:.0f} min ago"
            p.setFont(font(11, True))
            w1 = p.fontMetrics().horizontalAdvance(it["name"])
            p.setFont(font(11))
            w2 = p.fontMetrics().horizontalAdvance(text2)
            w = 34 + w1 + 10 + w2
            if x + w > self.width() and x > 0:
                x, y = 0.0, y + h + 8
            r = QRectF(x, y, w, h)
            p.setBrush(qc(color, 18))
            p.setPen(QPen(qc(color, 120), 1))
            p.drawRoundedRect(r, h / 2, h / 2)
            p.setPen(Qt.NoPen)
            p.setBrush(qc(color, 60))
            p.drawEllipse(QPointF(x + 16, y + h / 2), 7, 7)
            p.setBrush(qc(color))
            p.drawEllipse(QPointF(x + 16, y + h / 2), 4, 4)
            p.setFont(font(11, True))
            p.setPen(qc(WHITE))
            p.drawText(QPointF(x + 30, y + h / 2 + 4), it["name"])
            p.setFont(font(11))
            p.setPen(qc(color if color != MUTED else MUTED))
            p.drawText(QPointF(x + 30 + w1 + 10, y + h / 2 + 4), text2)
            x += w + gap
        need = int(y + h + 4)
        if need != self.minimumHeight():
            self.setMinimumHeight(need)
        p.end()


# ------------------------------------------------------------------------------------ live value board
class ValueBoard(QWidget):
    """Big current value per channel with a sparkline and an up / down arrow. Digital channels show ON / OFF."""
    TILE_H = 92

    def __init__(self, parent=None):
        super().__init__(parent)
        _transparent(self)
        self.items = []
        self.message = "Waiting for live readings"
        self.setMinimumHeight(self.TILE_H)

    def set_items(self, items, message="Waiting for live readings"):
        """items: [{"name","value","unit","delta","delta_color","spark","color","digital"(bool)}]"""
        sig = (tuple((i["name"], i["value"], i["unit"], i["delta"], len(i["spark"]), i["spark"][-1:] and i["spark"][-1])
                     for i in items), message)
        if sig == getattr(self, "_sig", None):
            return
        self._sig = sig
        self.items, self.message = items, message
        self._relayout()
        self.update()

    def _columns(self):
        return max(1, min(4, int(self.width() // 190)))

    def _relayout(self):
        cols = self._columns()
        rows = max(1, -(-len(self.items) // cols))
        need = rows * (self.TILE_H + 10)
        if need != self.minimumHeight():
            self.setMinimumHeight(need)

    def resizeEvent(self, event):
        self._relayout()
        super().resizeEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.items:
            p.setPen(qc(MUTED))
            p.setFont(font(12))
            p.drawText(QRectF(self.rect()), Qt.AlignCenter | Qt.TextWordWrap, self.message)
            p.end()
            return
        cols = self._columns()
        gap = 10
        tw = (self.width() - gap * (cols - 1)) / cols
        for i, it in enumerate(self.items):
            r = QRectF((i % cols) * (tw + gap), (i // cols) * (self.TILE_H + gap), tw, self.TILE_H)
            color = it["color"]
            p.setBrush(qc(SURFACE))
            p.setPen(QPen(qc(color, 90), 1))
            p.drawRoundedRect(r, 11, 11)
            p.setPen(Qt.NoPen)
            p.setBrush(qc(color))
            p.drawRoundedRect(QRectF(r.left() + 1, r.top() + 12, 3, r.height() - 24), 1.5, 1.5)
            x = r.left() + 14
            p.setFont(font(10, True, 1.2))
            p.setPen(qc(MUTED))
            p.drawText(QPointF(x, r.top() + 20), it["name"])
            p.setFont(font(26 if not it.get("digital") else 22, True))
            p.setPen(qc(color if it.get("digital") else WHITE))
            p.drawText(QPointF(x, r.top() + 54), it["value"])
            vw = p.fontMetrics().horizontalAdvance(it["value"])
            if it["unit"]:
                p.setFont(font(12, True))
                p.setPen(qc(MUTED))
                p.drawText(QPointF(x + vw + 4, r.top() + 54), it["unit"])
            if it["delta"]:
                p.setFont(font(11, True))
                p.setPen(qc(it["delta_color"]))
                p.drawText(QPointF(x, r.bottom() - 11), it["delta"])
            spark = it["spark"]
            if len(spark) > 1:
                box = QRectF(r.right() - min(110, tw * 0.42) - 10, r.top() + 14, min(110, tw * 0.42), r.height() - 28)
                lo, hi = min(spark), max(spark)
                rng = (hi - lo) or 1.0
                pts = [QPointF(box.left() + box.width() * k / (len(spark) - 1),
                               box.bottom() - 2 - (v - lo) / rng * (box.height() - 4)) for k, v in enumerate(spark)]
                path = QPainterPath(pts[0])
                for pt in pts[1:]:
                    path.lineTo(pt)
                fill = QPainterPath(path)
                fill.lineTo(box.right(), box.bottom())
                fill.lineTo(box.left(), box.bottom())
                fill.closeSubpath()
                g = QLinearGradient(box.topLeft(), box.bottomLeft())
                g.setColorAt(0, qc(color, 60))
                g.setColorAt(1, qc(color, 0))
                p.setPen(Qt.NoPen)
                p.setBrush(g)
                p.drawPath(fill)
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(qc(color), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.drawPath(path)
        p.end()


# ------------------------------------------------------------------------------------ device status timeline


class StatusTimeline(QWidget):
    """One strip per device over time: green ONLINE, red OFFLINE, amber RETRYING."""
    ROW = 30
    L, R = 92, 12

    def __init__(self, parent=None):
        super().__init__(parent)
        _transparent(self)
        self.rows, self.t0, self.t1 = [], 0.0, 1.0
        self.message = "No devices yet"
        self.setMouseTracking(True)
        self._hover = None
        self.setMinimumHeight(70)

    def set_rows(self, rows, t0, t1, message="No devices yet"):
        """rows: [{"name", "segments": [(a, b, status)]}]"""
        self.rows, self.t0, self.t1, self.message = rows, float(t0), float(max(t1, t0 + 1.0)), message
        self.setMinimumHeight(max(70, len(rows) * self.ROW + 52))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.rows:
            p.setPen(qc(MUTED))
            p.setFont(font(12))
            p.drawText(QRectF(self.rect()), Qt.AlignCenter, self.message)
            p.end()
            return
        w = self.width() - self.L - self.R
        span = self.t1 - self.t0

        def X(t):
            return self.L + (t - self.t0) / span * w
        bottom = len(self.rows) * self.ROW
        p.setFont(font(10))
        for i in range(7):
            x = self.L + w * i / 6
            p.setPen(QPen(qc(GRID), 1, Qt.DotLine))
            p.drawLine(QPointF(x, 0), QPointF(x, bottom))
            p.setPen(qc(MUTED))
            label = time_label(self.t0 + span * i / 6, span)
            if i == 0:
                p.drawText(QRectF(x - 4, bottom + 4, 80, 16), Qt.AlignLeft, label)
            elif i == 6:
                p.drawText(QRectF(x - 76, bottom + 4, 80, 16), Qt.AlignRight, label)
            else:
                p.drawText(QRectF(x - 40, bottom + 4, 80, 16), Qt.AlignHCenter, label)
        for r, row in enumerate(self.rows):
            y = r * self.ROW + 4
            p.setPen(qc(WHITE))
            p.setFont(font(11, True))
            p.drawText(QRectF(0, y, self.L - 10, 22), Qt.AlignRight | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(row["name"], Qt.ElideRight, self.L - 12))
            p.setBrush(qc(TRACK))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(self.L, y, w, 22), 6, 6)
            for a, b, status in row["segments"]:
                if b < self.t0 or a > self.t1:
                    continue
                color = {"ONLINE": GREEN, "OFFLINE": RED, "RETRYING": AMBER}.get(status)
                if color is None:
                    continue
                x0, x1 = max(X(a), self.L), min(X(b), self.L + w)
                p.setBrush(qc(color, 215))
                p.drawRoundedRect(QRectF(x0, y, max(x1 - x0, 1.5), 22), 4, 4)
        lx = self.L
        ly = bottom + 26
        p.setFont(font(10))
        for text, color in (("ONLINE", GREEN), ("RETRYING", AMBER), ("OFFLINE", RED)):
            p.setBrush(qc(color))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(lx, ly + 2, 10, 10), 3, 3)
            p.setPen(qc(MUTED))
            p.drawText(QPointF(lx + 15, ly + 11), text)
            lx += 20 + p.fontMetrics().horizontalAdvance(text) + 14
        if self._hover is not None and self.L <= self._hover <= self.L + w:
            t = self.t0 + (self._hover - self.L) / w * span
            p.setPen(QPen(qc(FAINT), 1, Qt.DashLine))
            p.drawLine(QPointF(self._hover, 0), QPointF(self._hover, bottom))
            p.setPen(qc(WHITE))
            p.setFont(font(10, True))
            p.drawText(QPointF(min(self._hover + 6, self.width() - 80), 11), datetime.fromtimestamp(t).strftime("%H:%M:%S"))
        p.end()

    def mouseMoveEvent(self, event):
        self._hover = event.position().x()
        self.update()

    def leaveEvent(self, event):
        self._hover = None
        self.update()