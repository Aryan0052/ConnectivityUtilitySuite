"""Shared look of the single-device pages (Digital Input / Output, Analog Input / Output, Communication).

Same design language as the Multi Device page (live_console.py): the same colour tokens, the same
light / dark palette, the same fonts, cards, buttons and status dots.  Nothing here talks to a
device - a page only builds its widgets with these helpers and styles them with the tokens, so the
page logic (serial / TCP code, timers, parsers) stays exactly as it was.

Typical use inside a page:

    from . import ui_theme as ui                      (or: import ui_theme as ui)

    ui.install(self, "pgRoot")                        # page style sheet + theme sync (once, in build_ui)
    header = ui.Header("Digital Input")               # top bar: logo, back, title, status chip, theme toggle
    card = ui.card()                                  # white rounded panel
    ui.button("CONNECT", "primary")                   # primary | secondary | danger | success | ghost
    ui.field("Slave ID (1-63)", line_edit)            # label above an input
    ui.set_status(label, dot, "#D00000")              # keeps the old "colour" calls working (maps to a tone)

Every colour is written as an @token (see live_console.LIGHT / DARK); the page is re-rendered when the
theme is switched.  The theme choice is stored under the same key as Multi Device, so one switch
changes the whole application.
"""
import ast
import re
from types import SimpleNamespace

from PySide6.QtCore import Qt, QObject, QEvent, QSettings, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QPlainTextEdit, QSizePolicy,
    QComboBox, QLineEdit, QLayout,
)

try:
    from . import live_console as lc
except ImportError:
    import live_console as lc

tss = lc.tss
tok = lc.tok


def _make_arrows():
    """Small chevron images for combo boxes / spin boxes (a style sheet cannot draw them). They are drawn once
    into the temp folder and referenced from the style sheet through the @arrow_* tokens."""
    import os
    import tempfile
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QImage, QPainter, QPen
    folder = os.path.join(tempfile.gettempdir(), "nelumbo_ui")
    try:
        os.makedirs(folder, exist_ok=True)
        for theme, palette in (("light", lc.LIGHT), ("dark", lc.DARK)):
            for name, up in (("down", False), ("up", True)):
                path = os.path.join(folder, f"arrow_{name}_{theme}.png")
                if not os.path.exists(path):
                    image = QImage(24, 24, QImage.Format_ARGB32)
                    image.fill(0)
                    p = QPainter(image)
                    p.setRenderHint(QPainter.Antialiasing, True)
                    pen = QPen(QColor(palette["muted"]), 2.6)
                    pen.setCapStyle(Qt.RoundCap)
                    pen.setJoinStyle(Qt.RoundJoin)
                    p.setPen(pen)
                    y1, y2 = (15, 8) if up else (9, 16)
                    p.drawLine(QPointF(6, y1), QPointF(12, y2))
                    p.drawLine(QPointF(12, y2), QPointF(18, y1))
                    p.end()
                    image.save(path)
                palette["arrow_" + name] = path.replace("\\", "/")
    except Exception:
        for palette in (lc.LIGHT, lc.DARK):
            palette.setdefault("arrow_down", "none")
            palette.setdefault("arrow_up", "none")


_make_arrows()

_SETTINGS_KEY = "multi_device/theme"        # same key as the Multi Device page: one switch for the whole app

# --------------------------------------------------------------------------- style sheet
PAGE_QSS = """
QWidget#pgRoot { background:@bg; }
QDialog { background:@surface; }
QLabel { background:transparent; color:@text; font-family:"Segoe UI"; font-size:13px; }
QLabel#pgTitle { font-size:20px; font-weight:700; }
QLabel#pgSub { color:@muted; font-size:12px; }
QLabel#pgSection { color:@muted; font-size:11px; font-weight:700; letter-spacing:1px; }
QLabel#pgField { color:@text2; font-size:12px; font-weight:600; }
QLabel#pgHint { color:@faint; font-size:11px; }
QLabel#pgCrumb { color:@muted; font-size:13px; }
QLabel#pgCrumbB { color:@text; font-size:15px; font-weight:600; }
QLabel#pgValue { color:@text; font-size:13px; font-weight:600; }
QLabel#pgBad { color:@bad; font-size:12px; font-weight:600; }
QLabel#pgChipText { color:@text2; font-size:12px; font-weight:600; }

QFrame#pgTop { background:@surface; border:0; border-bottom:1px solid @border; }
QFrame#pgCard { background:@surface; border:1px solid @border; border-radius:12px; }
QFrame#pgBox { background:@sunken; border:1px solid @border; border-radius:10px; }
QFrame#pgChip { background:@sunken; border:1px solid @border; border-radius:8px; }
QFrame#pgRule { background:@border; border:0; min-height:1px; max-height:1px; }
QFrame#pgTile { background:@sunken; border:1px solid @border; border-radius:10px; }
QFrame#pgTile[state="on"] { background:@ok_soft; border:1px solid @ok; }
QFrame#pgTile[state="bad"] { background:@bad_soft; border:1px solid @bad; }
QFrame#pgTile[state="warn"] { background:@warn_soft; border:1px solid @warn; }
QLabel#pgLed { background:@idle; border:0; border-radius:9px; min-width:18px; max-width:18px;
    min-height:18px; max-height:18px; }
QLabel#pgLed[state="on"] { background:@ok; }
QLabel#pgLed[state="bad"] { background:@bad; }
QLabel#pgLed[state="warn"] { background:@warn; }

QLineEdit, QSpinBox, QDoubleSpinBox { background:@surface; border:1px solid @border2; border-radius:8px;
    color:@text; padding:0 10px; min-height:34px; font-family:"Segoe UI"; font-size:13px;
    selection-background-color:@accent_soft; selection-color:@text; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border:1px solid @accent; }
QLineEdit:read-only { background:@sunken; color:@text2; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled { background:@sunken; color:@faint; }
QSpinBox::up-button, QDoubleSpinBox::up-button { width:20px; border:0; background:transparent; }
QSpinBox::down-button, QDoubleSpinBox::down-button { width:20px; border:0; background:transparent; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image:url(@arrow_up); width:10px; height:10px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image:url(@arrow_down); width:10px; height:10px; }
QComboBox { background:@surface; border:1px solid @border2; border-radius:8px; color:@text; padding:0 10px;
    min-height:34px; font-family:"Segoe UI"; font-size:13px; }
QComboBox::drop-down { border:0; width:28px; }
QComboBox::down-arrow { image:url(@arrow_down); width:12px; height:12px; }
QComboBox QAbstractItemView { background:@surface; color:@text; border:1px solid @border2; outline:0;
    selection-background-color:@accent_soft; selection-color:@text; font-family:"Segoe UI"; font-size:13px; }
QComboBox QAbstractItemView::item { min-height:26px; padding:2px 8px; }

QPlainTextEdit#pgTerminal, QTextEdit#pgTerminal { background:@console; color:#C9D1DA; border:1px solid @border; border-radius:10px;
    font-family:Consolas,'Cascadia Mono',monospace; font-size:12px; padding:8px 10px; }

QPushButton { font-family:"Segoe UI"; font-size:13px; font-weight:600; }
QPushButton#pgPrimary { background:@accent; color:@on_accent; border:1px solid @accent; border-radius:8px;
    padding:0 18px; min-height:34px; }
QPushButton#pgPrimary:hover { background:@accent_text; border-color:@accent_text; }
QPushButton#pgPrimary:disabled { background:@border2; border-color:@border2; color:@surface; }
QPushButton#pgSecondary { background:@surface; color:@text; border:1px solid @border2; border-radius:8px;
    padding:0 18px; min-height:34px; }
QPushButton#pgSecondary:hover { background:@hover; }
QPushButton#pgSecondary:disabled { color:@faint; background:@sunken; }
QPushButton#pgDanger { background:@bad; color:#FFFFFF; border:1px solid @bad; border-radius:8px;
    padding:0 18px; min-height:34px; }
QPushButton#pgDanger:disabled { background:@border2; border-color:@border2; }
QPushButton#pgSuccess { background:@ok; color:#FFFFFF; border:1px solid @ok; border-radius:8px;
    padding:0 18px; min-height:34px; }
QPushButton#pgSuccess:disabled { background:@border2; border-color:@border2; }
QPushButton#pgDangerSoft { background:@bad_soft; color:@bad; border:1px solid @bad; border-radius:8px;
    padding:0 18px; min-height:34px; }
QPushButton#pgDangerSoft:hover { background:@surface; }
QPushButton#pgGhost { background:transparent; color:@accent_text; border:0; border-radius:7px;
    padding:0 10px; min-height:28px; }
QPushButton#pgGhost:hover { background:@hover; }
QPushButton#pgIcon { background:@surface; color:@text2; border:1px solid @border; border-radius:8px;
    min-width:34px; max-width:34px; min-height:34px; max-height:34px; font-size:15px; padding:0; }
QPushButton#pgIcon:hover { background:@hover; color:@text; }

QPushButton#pgChannel { background:@surface; color:@text; border:1px solid @border2; border-radius:10px;
    text-align:left; padding:0 16px; min-height:40px; font-size:13px; font-weight:600; }
QPushButton#pgChannel:hover { background:@hover; border-color:@accent; }
QPushButton#pgChannel[selected="true"] { background:@accent_soft; border:1px solid @accent; color:@accent_text; }
QPushButton#pgMini { background:@accent; color:@on_accent; border:1px solid @accent; border-radius:7px;
    padding:0 12px; min-height:26px; font-size:12px; font-weight:700; }
QPushButton#pgMini:hover { background:@accent_text; border-color:@accent_text; }

QPushButton#pgToggle { background:@sunken; color:@muted; border:1px solid @border2; border-radius:6px;
    padding:0 8px; min-height:22px; font-size:11px; font-weight:700; }
QPushButton#pgToggle:hover { background:@hover; }
QPushButton#pgToggle[state="on"] { background:@ok; color:#FFFFFF; border:1px solid @ok; }
QCheckBox { color:@accent_text; font-family:"Segoe UI"; font-size:11px; font-weight:700; background:transparent; spacing:6px; }
QTableWidget { background:@surface; color:@text; border:1px solid @border; border-radius:8px;
    gridline-color:@border; font-family:"Segoe UI"; font-size:12px; selection-background-color:@accent_soft; }
QTableWidget::item { padding:2px 8px; }
QHeaderView::section { background:@sunken; color:@muted; border:0; border-bottom:1px solid @border;
    border-right:1px solid @border; padding:6px 8px; font-family:"Segoe UI"; font-size:11px; font-weight:700; }
QTableCornerButton::section { background:@sunken; border:0; }

QScrollArea { background:transparent; border:0; }
QScrollArea > QWidget > QWidget { background:transparent; }
QScrollBar:vertical { width:8px; background:transparent; margin:2px; }
QScrollBar::handle:vertical { background:@border2; border-radius:4px; min-height:30px; }
QScrollBar::add-line, QScrollBar::sub-line { height:0; width:0; }
QScrollBar:horizontal { height:8px; background:transparent; margin:2px; }
QScrollBar::handle:horizontal { background:@border2; border-radius:4px; min-width:30px; }
QToolTip { background:@surface; color:@text; border:1px solid @border2; padding:4px 6px; }
"""


# --------------------------------------------------------------------------- theme state
def saved_theme():
    try:
        value = QSettings("Nelumbo", "ConnectivityUtility").value(_SETTINGS_KEY, "light")
        return "dark" if value == "dark" else "light"
    except Exception:
        return "light"


def _save_theme(name):
    try:
        QSettings("Nelumbo", "ConnectivityUtility").setValue(_SETTINGS_KEY, name)
    except Exception:
        pass


def scale_for(root):
    """UI size factor for the window size - the same rule as the Multi Device page (1.0 at the design size
    1250 x 800, up to 1.8 on big windows). At 100 % / 125 % Windows scaling the window is big in pixels, so
    text, inputs and buttons grow with it instead of looking tiny."""
    window = root.window()
    width = window.width() if window is not None else root.width()
    height = window.height() if window is not None else root.height()
    if width <= 0 or height <= 0:
        return lc.SCALE
    return max(1.0, min(1.8, round(min(width / 1250.0, height / 800.0) * 10) / 10.0))


def apply_theme(root, name=None, save=False, scale=None):
    """Render every @token style sheet below root for the theme (light / dark) and UI size."""
    name = name or saved_theme()
    scale = scale_for(root) if scale is None else scale
    lc.restyle(root, name, scale)
    for obj in root.findChildren(QWidget) + root.findChildren(QLayout):
        if obj.property("_pg_sz"):
            _apply_sizes(obj)
    root.setProperty("_pg_applied", f"{name}/{scale}")
    for button in root.findChildren(QPushButton, "pgThemeBtn"):
        button.setText("☀" if name == "dark" else "☾")
    if save:
        _save_theme(name)
    hook = getattr(root, "retheme_page", None)       # optional: page repaints its own painted widgets
    if callable(hook):
        hook()


def toggle_theme(root):
    apply_theme(root, "light" if lc.THEME == "dark" else "dark", save=True)


class _ThemeSync(QObject):
    """When the page is shown, follow the theme saved by the last switch (Multi Device or any page), and
    follow the window size (scale_for) when the page is shown or the window is resized."""

    def __init__(self, root):
        super().__init__(root)
        self._root = root
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)                 # resize: restyle once the window has settled
        self._timer.timeout.connect(self._sync)

    def _sync(self, force=False):
        root = self._root
        if not (root.isVisible() or force):
            return
        theme, scale = saved_theme(), scale_for(root)
        if root.property("_pg_applied") != f"{theme}/{scale}" or theme != lc.THEME:
            apply_theme(root, theme, scale=scale)

    def eventFilter(self, obj, event):
        if obj is self._root:
            kind = event.type()
            if kind == QEvent.Show:
                self._sync()
            elif kind == QEvent.Resize and self._root.isVisible():
                self._timer.start()
        return False


def install(root, root_name="pgRoot"):
    """Call once at the start of build_ui: page style sheet, root object name, theme follow."""
    root.setObjectName(root_name)
    root.setAttribute(Qt.WA_StyledBackground, True)
    if saved_theme() != lc.THEME:
        lc.THEME = saved_theme()
    tss(root, PAGE_QSS)
    root.setProperty("_pg_applied", f"{lc.THEME}/{lc.SCALE}")
    root._pg_sync = _ThemeSync(root)
    root.installEventFilter(root._pg_sync)


def prepare(root):
    """Bring a hidden page to the window's theme / size now (the application calls this while building
    pages in the background, so the first opening of the page does not have to do it)."""
    sync = getattr(root, "_pg_sync", None)
    if sync is not None:
        sync._sync(force=True)


# --------------------------------------------------------------------------- small helpers
def px(value):
    """A design size (px at UI size 1.0) at the current UI size."""
    return lc.px(value)


def sized(obj, method, *args):
    """obj.method(*args) with design sizes (px at UI size 1.0): applied now at the current UI size and again
    whenever the page follows a new window size, e.g. sized(button, "setFixedHeight", 36)."""
    calls = ast.literal_eval(obj.property("_pg_sz") or "{}")
    calls[method] = args
    obj.setProperty("_pg_sz", repr(calls))
    getattr(obj, method)(*[lc.px(a) if a else 0 for a in args])
    return obj


def _apply_sizes(obj):
    for method, args in ast.literal_eval(obj.property("_pg_sz")).items():
        getattr(obj, method)(*[lc.px(a) if a else 0 for a in args])


def repolish(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def set_state(widget, state):
    """state: "" (idle) | "on" | "bad" | "warn" - styled by the [state="..."] rules of PAGE_QSS."""
    if widget.property("state") != state:
        widget.setProperty("state", state)
        repolish(widget)


def label(text="", name=None, wrap=False):
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    if wrap:
        w.setWordWrap(True)
    return w


_KIND = {"primary": "pgPrimary", "secondary": "pgSecondary", "danger": "pgDanger", "softdanger": "pgDangerSoft",
         "success": "pgSuccess", "ghost": "pgGhost", "icon": "pgIcon"}


class ActionButton(QPushButton):
    """Button whose look follows its text: the page code only calls setText("STOP") / setText("DISCONNECT"),
    this class switches the colour (alt = {"STOP": "danger", ...}, texts compared upper-case)."""

    def __init__(self, text, kind, alt):
        super().__init__()
        self._kind, self._alt = kind, {k.upper(): v for k, v in alt.items()}
        self.setText(text)

    def setStyleSheet(self, text):
        pass                                        # old code that paints this button by hand is ignored: the text decides

    def setText(self, text):
        super().setText(text)
        name = _KIND[self._alt.get(str(text).strip().upper(), self._kind)]
        if self.objectName() != name:
            self.setObjectName(name)
            repolish(self)


def button(text, kind="secondary", height=None, alt=None):
    """kind: primary | secondary | danger | softdanger | success | ghost | icon.
    alt={"STOP": "danger"}: the colour changes when the code sets that text."""
    if alt:
        b = ActionButton(text, kind, alt)
    else:
        b = QPushButton(text)
        b.setObjectName(_KIND[kind])
    b.setCursor(Qt.PointingHandCursor)
    b.setFocusPolicy(Qt.NoFocus)
    if height:
        sized(b, "setFixedHeight", height)
    return b


def card(name="pgCard"):
    f = QFrame()
    f.setObjectName(name)
    return f


def rule():
    f = QFrame()
    f.setObjectName("pgRule")
    f.setFixedHeight(1)
    return f


def section(text):
    """Small upper-case section heading with a hairline under it."""
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    sized(lay, "setSpacing", 6)
    lay.addWidget(label(text.upper(), "pgSection"))
    lay.addWidget(rule())
    return box


def field(text, widget, hint=None):
    """Label above an input (and an optional hint under it)."""
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    sized(lay, "setSpacing", 5)
    lay.addWidget(label(text, "pgField"))
    lay.addWidget(widget)
    if hint:
        lay.addWidget(label(hint, "pgHint"))
    return box


def terminal(text=""):
    """Dark read-only console (same look as the Multi Device traffic console)."""
    t = QPlainTextEdit()
    t.setObjectName("pgTerminal")
    t.setReadOnly(True)
    t.setFocusPolicy(Qt.NoFocus)
    t.setLineWrapMode(QPlainTextEdit.WidgetWidth)
    t.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    t.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    if text:
        t.setPlainText(text)
    return t


def led():
    """Round channel indicator; set_state(led, "on") turns it green."""
    w = QLabel()
    w.setObjectName("pgLed")
    sized(w, "setFixedSize", 18, 18)
    return w


def tile():
    """Channel tile frame: set_state(tile, "on" | "bad" | "warn" | "")."""
    f = QFrame()
    f.setObjectName("pgTile")
    return f


# --------------------------------------------------------------------------- status colour -> tone
def tone_of(color, text=""):
    """Old code paints its status text with a hex colour (green = fine, red = problem).  This maps such a
    colour to a theme tone so the text is readable in both themes."""
    if text.strip().lower().startswith(("not connected", "disconnected", "com port not", "not polled")):
        return "idle"
    c = QColor(color)
    if not c.isValid():
        return "text2"
    h, s, v, _a = c.getHsv()
    if s < 40:
        return "muted"
    if 70 <= h <= 175:
        return "ok"
    if h < 22 or h >= 330:
        return "bad"
    if 22 <= h < 70:
        return "warn"
    return "accent_text"


_TONE_COLOR = {"idle": "muted"}


def set_status(label_widget, dot_widget, color):
    """Drop-in for the old _set_status_color(): colour the status text (and dot) by tone."""
    tone = tone_of(color, label_widget.text() if label_widget is not None else "")
    name = _TONE_COLOR.get(tone, tone)
    if label_widget is not None:
        tss(label_widget, f"/*pg*/QLabel {{ color:@{name}; background:transparent; font-family:'Segoe UI'; "
                          f"font-size:12px; font-weight:600; }}")
    if dot_widget is not None:
        dot_name = "idle" if tone == "idle" else name
        tss(dot_widget, f"/*pg*/QLabel {{ color:@{dot_name}; background:transparent; font-size:14px; }}")


_COLOR_IN_QSS = re.compile(r"(?<![-\w])color\s*:\s*(#[0-9A-Fa-f]{6}|[A-Za-z]+)")


class ToneLabel(QLabel):
    """Status text / dot of a page.  The page code still colours it the old way - setStyleSheet("color: #D00000; ...")
    - this label turns that colour into a theme tone (green = ok, red = bad, grey = idle), so the page logic does
    not change and the text stays readable in the light and the dark theme."""

    def __init__(self, text="", dot=False):
        super().__init__(text)
        self._dot = dot

    def setStyleSheet(self, text):
        if "/*pg*/" in text or not text:
            super().setStyleSheet(text)
            return
        found = _COLOR_IN_QSS.search(text)
        if found:
            set_status(None if self._dot else self, self if self._dot else None, found.group(1))


# --------------------------------------------------------------------------- header
class Header(QFrame):
    """Top bar like the Multi Device page: logo, back, 'Suite / Title', status chip, theme switch.

    Attributes the page logic needs:
        back_button   QPushButton   - connect to the page's back handler
        status        QLabel        - the page's status text (setText as before)
        status_dot    QLabel        - dot in front of it (set_status colours both)
        theme_button  QPushButton   - already wired
    Extra widgets can be added to the right with add_right().
    """

    def __init__(self, title, crumb="Connectivity Utility Suite", root=None):
        super().__init__()
        self.setObjectName("pgTop")
        self.setFixedHeight(lc.px(60))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 20, 0)
        lay.setSpacing(12)
        self.back_button = button("←", "icon")
        self.back_button.setToolTip("Back")
        lay.addWidget(self.back_button)
        lay.addWidget(lc.LogoTile())
        lay.addWidget(label(crumb + "  /", "pgCrumb"))
        lay.addWidget(label(title, "pgCrumbB"))
        lay.addSpacing(8)

        chip = QFrame()
        chip.setObjectName("pgChip")
        chip.setFixedHeight(lc.px(32))
        cl = QHBoxLayout(chip)
        cl.setContentsMargins(10, 0, 12, 0)
        cl.setSpacing(6)
        self.status_dot = ToneLabel("\u25cf", dot=True)
        self.status = ToneLabel("Not Connected")
        self.status.setMinimumWidth(lc.px(150))          # status text changes all the time: keep the chip steady,
        self.status.setMaximumWidth(lc.px(380))          # and long device messages are cut instead of pushing
        cl.addWidget(self.status_dot)
        cl.addWidget(self.status)
        lay.addWidget(chip)
        lay.addStretch(1)
        self._right = QHBoxLayout()
        self._right.setSpacing(8)
        lay.addLayout(self._right)

        self.theme_button = button("☾", "icon")
        self.theme_button.setObjectName("pgIcon")
        self.theme_button.setToolTip("Light / dark theme")
        self.theme_button.clicked.connect(lambda _c=False: toggle_theme(root or self.window()))
        self._theme_root = root
        lay.addWidget(self.theme_button)
        set_status(self.status, self.status_dot, "#888888")
        self.retheme()

    def add_right(self, widget):
        self._right.addWidget(widget)

    def retheme(self):
        self.setFixedHeight(lc.px(60))
        self.theme_button.setText("☀" if lc.THEME == "dark" else "☾")


# --------------------------------------------------------------------------- COM-port popup
def skin_dialog(dialog, title_label, port_box, connect_btn, cancel_btn):
    """Style the small 'Select COM Port' popup the pages open (same widgets, new look)."""
    dialog.setFixedSize(380, 200)
    title_label.setObjectName("pgCrumbB")
    port_box.setMinimumHeight(38)
    connect_btn.setObjectName("pgPrimary")
    cancel_btn.setObjectName("pgSecondary")
    for b in (connect_btn, cancel_btn):
        b.setCursor(Qt.PointingHandCursor)
        b.setMinimumHeight(36)
        b.setFixedHeight(36)


# --------------------------------------------------------------------------- left panel shared by the RTU pages
BAUD_RATES = ("9600", "19200", "38400", "57600", "115200")


def rtu_panel(protocol_text, id_label="Slave ID (1-63)", id_hint="Valid Slave IDs: 1 to 63",
              section_title="RTU Slave Settings"):
    """The left card every serial page has: CONNECT, protocol, Slave/Device ID, baud rate, APPLY and the
    Device Terminal.  Returns the card and its widgets - the page stores them under the names its code uses.

        p = ui.rtu_panel("Digital Input")
        self.connect_button, self.protocol, self.slave_id = p.connect, p.protocol, p.id_edit
        self.baud_rate, self.apply_button, self.refresh_button = p.baud, p.apply, p.refresh
        self.terminal_message = p.terminal
    """
    card_ = card()
    sized(card_, "setMinimumWidth", 330)
    sized(card_, "setMaximumWidth", 380)
    lay = QVBoxLayout(card_)
    sized(lay, "setContentsMargins", 18, 18, 18, 18)
    sized(lay, "setSpacing", 12)

    lay.addWidget(section("Connection"))
    connect = button("CONNECT", "primary", 38, alt={"DISCONNECT": "softdanger"})
    lay.addWidget(connect)

    protocol = QComboBox()
    protocol.addItem(protocol_text)
    protocol.setFocusPolicy(Qt.NoFocus)
    lay.addWidget(field("Protocol", protocol))

    lay.addSpacing(4)
    lay.addWidget(section(section_title))
    id_edit = QLineEdit()
    id_edit.setText("1")
    lay.addWidget(field(id_label, id_edit, id_hint))
    baud = QComboBox()
    baud.addItems(list(BAUD_RATES))
    baud.setCurrentText("9600")
    lay.addWidget(field("RTU Baud Rate", baud))
    apply_ = button("APPLY", "secondary", 36)
    lay.addWidget(apply_)

    lay.addSpacing(4)
    heading = QHBoxLayout()
    heading.setContentsMargins(0, 0, 0, 0)
    heading.addWidget(label("DEVICE TERMINAL", "pgSection"))
    heading.addStretch()
    refresh = button("\u27f3  Refresh", "ghost")
    heading.addWidget(refresh)
    lay.addLayout(heading)
    terminal_ = terminal("Device Terminal Ready")
    sized(terminal_, "setMinimumHeight", 110)
    lay.addWidget(terminal_, 1)
    return SimpleNamespace(card=card_, layout=lay, connect=connect, protocol=protocol, id_edit=id_edit,
                           baud=baud, apply=apply_, refresh=refresh, terminal=terminal_)