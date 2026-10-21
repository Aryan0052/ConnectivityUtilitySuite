from __future__ import annotations
import re
import time
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtGui import QPainter, QPen, QPixmap, QColor, QImage
from PySide6.QtWidgets import (
    QSizePolicy,
    QSpacerItem,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QToolButton,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QGraphicsBlurEffect,
)

try:
    from . import image_cache
except ImportError:          # started as a plain script
    import image_cache

# The 4K background is decoded in a background thread (image_cache) while the window is being created:
# a 1920 x 1080 version for normal windows, the full picture only for very large windows.
BACKGROUND_MEDIUM = (1920, 1080)
_PX = re.compile(r"(\d+(?:\.\d+)?)px")


def background_path():
    root = Path(__file__).resolve().parents[1]
    candidates = [root / "assets" / "background" / "login_background.png", root / "assets" / "login_background.png"]
    return next((path for path in candidates if path.exists()), candidates[0])


def preload_assets():
    """Start decoding the login artwork now (call before the window exists)."""
    path = background_path()
    if path.exists():
        image_cache.preload(path, *BACKGROUND_MEDIUM, extra=((0, 0),))


def make_shadow_pixmap(width, height, radius, blur, colour, pad):
    """The card shadow, drawn ONCE. (A QGraphicsDropShadowEffect on the card re-blurs the whole card
    every time anything inside it repaints - every typed character and every cursor blink.)"""
    source = QPixmap(width, height)
    source.fill(Qt.transparent)
    painter = QPainter(source)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(colour)
    painter.drawRoundedRect(0, 0, width, height, radius, radius)
    painter.end()
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(source)
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(blur)
    effect.setBlurHints(QGraphicsBlurEffect.QualityHint)
    item.setGraphicsEffect(effect)
    scene.addItem(item)
    image = QImage(width + 2 * pad, height + 2 * pad, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    scene.setSceneRect(-pad, -pad, width + 2 * pad, height + 2 * pad)
    scene.render(painter)
    painter.end()
    return QPixmap.fromImage(image)
# ================================================================
# FIXED LOGIN CREDENTIALS
# ================================================================
# Change ONLY these two values when the real credentials are decided.
FIXED_USERNAME = "nelumbo"
FIXED_PASSWORD = "1234"

class UserIcon(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(38, 38)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.scale(self.width() / 38.0, self.height() / 38.0)     # drawn at the design size 38 x 38
        pen = QPen(QColor("#DDF8FF"))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawEllipse(13, 3, 12, 12)
        painter.drawArc(6, 17, 27, 23, 0, 180 * 16)
        painter.end()

class LockIcon(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(38, 38)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.scale(self.width() / 38.0, self.height() / 38.0)     # drawn at the design size 38 x 38
        pen = QPen(QColor("#DDF8FF"))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawArc(11, 4, 17, 18, 0, 180 * 16)
        painter.drawRect(8, 16, 23, 20)
        painter.end()

class EyeButton(QToolButton):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(34, 34)
        self.setCursor(Qt.PointingHandCursor)
        self._password_visible = False
        self.setStyleSheet("QToolButton { background: transparent; border: none; }")

    def set_password_visible(self, visible):
        self._password_visible = bool(visible)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.scale(self.width() / 34.0, self.height() / 34.0)     # drawn at the design size 34 x 34
        pen = QPen(QColor("#DDF8FF"))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        # Eye outline + pupil is always visible.
        painter.drawArc(7, 13, 28, 16, 20 * 16, 140 * 16)
        painter.drawArc(7, 13, 28, 16, 200 * 16, 140 * 16)
        painter.drawEllipse(17, 17, 8, 8)
        # IMPORTANT:
        # Hidden password  -> eye-slash is shown.
        # Visible password -> slash disappears.
        if not self._password_visible:
            painter.drawLine(9, 29, 34, 9)
        painter.end()

class LoginView(QWidget):
    """Nelumbo login screen.
    The supplied background is the complete visual composition. The login card
    is an overlay only; the background devices are never moved or redrawn.
    Authentication uses two fixed credentials and does not use SQLite.
    """
    login_successful = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project_root = Path(__file__).resolve().parents[1]
        # Use the supplied full composition. Support both possible asset paths.
        background_candidates = [
            self.project_root / "assets" / "background" / "login_background.png",
            self.project_root / "assets" / "login_background.png",
        ]
        self.background_path = next(
            (path for path in background_candidates if path.exists()),
            background_candidates[0],
        )
        # Stable design canvas matching the supplied 1669x942 background.
        self.reference_width = 1669
        self.reference_height = 942
        self.setMinimumSize(640, 420)
        self._scale = 1.0
        self._sized = []          # (object, method, design-size args): re-applied with the UI size factor

        self._bg_size = None
        self._bg_smooth = True
        self._background_timer = QTimer(self)
        self._background_timer.setSingleShot(True)
        self._background_timer.setInterval(120)
        self._background_timer.timeout.connect(lambda: self._apply_background(smooth=True))
        self.build_ui()

    def build_ui(self):
        self.setObjectName("loginView")
        self._qss = (
            """
            QWidget#loginView {
                background: transparent;
            }
            QWidget#loginPanel {
                background: rgba(5, 48, 42, 235);
                border: 2px solid rgba(203, 176, 58, 235);
                border-radius: 20px;
            }
            QLabel#loginTitle {
                color: #F7F7F0;
                background: transparent;
                border: none;
                font-family: Segoe UI;
                font-size: 25px;
                font-weight: 700;
            }
            QLabel#loginSubtitle {
                color: rgba(235, 244, 240, 215);
                background: transparent;
                border: none;
                font-family: Segoe UI;
                font-size: 12px;
                font-weight: 500;
            }
            QLineEdit#authInput {
                background: rgba(3, 36, 32, 185);
                color: #F4F8F5;
                border: 1px solid rgba(206, 231, 224, 175);
                border-radius: 10px;
                padding-left: 14px;
                padding-right: 12px;
                font-family: Segoe UI;
                font-size: 14px;
            }
            QLineEdit#authInput:focus {
                border: 1px solid #32D7D0;
                background: rgba(5, 48, 43, 175);
            }
            QLineEdit#authInput::placeholder {
                color: rgba(231, 241, 238, 185);
            }
            QPushButton#primaryButton {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #13D7C7,
                    stop: 1 #0879E8
                );
                color: #FFFFFF;
                border: none;
                border-radius: 10px;
                font-family: Segoe UI;
                font-size: 15px;
                font-weight: 700;
            }
            QPushButton#primaryButton:hover {
                background: #16BFE0;
            }
            QPushButton#primaryButton:pressed {
                background: #0870C2;
            }
            QLabel#messageLabel {
                color: #FF6B73;
                background: transparent;
                border: none;
                font-family: Segoe UI;
                font-size: 11px;
                font-weight: 600;
            }
            """
        )
        self.setStyleSheet(self._qss)
        size = self._size
        # ------------------------------------------------------------
        # Full-screen background. This image already contains the logo,
        # devices, landscape, footer and all decorative artwork.
        # ------------------------------------------------------------
        self.background = QLabel(self)
        self.background.setAlignment(Qt.AlignCenter)
        self.background.setStyleSheet("QLabel { background: transparent; border: none; }")
        # Transparent z-order layer retained for predictable stacking.
        self.overlay = QWidget(self)
        self.overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.overlay.setStyleSheet("QWidget { background: transparent; border: none; }")
        # ------------------------------------------------------------
        # Smaller right-side login card.
        # ------------------------------------------------------------
        self.panel = QWidget(self)
        self.panel.setObjectName("loginPanel")
        size(self.panel, "setFixedSize", 370, 360)
        # Static shadow behind the card (same blur / offset / colour as the former drop-shadow effect).
        self.SHADOW_PAD = 60
        self.panel_shadow = QLabel(self)
        self.panel_shadow.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.panel_shadow.setPixmap(make_shadow_pixmap(370, 360, 20, 30, QColor(0, 0, 0, 110), self.SHADOW_PAD))
        self.panel_shadow.resize(370 + 2 * self.SHADOW_PAD, 360 + 2 * self.SHADOW_PAD)
        panel_layout = QVBoxLayout(self.panel)
        size(panel_layout, "setContentsMargins", 28, 24, 28, 24)
        panel_layout.setSpacing(0)
        space = self._spacing
        # Bigger centered Nelumbo logo.
        self.logo = self.create_logo(self.panel)
        size(self.logo, "setFixedHeight", 82)
        panel_layout.addWidget(self.logo, alignment=Qt.AlignCenter)
        space(panel_layout, 8)
        # Only username, password and login remain on the card.
        self.username_input = self.make_input("Username")
        self.add_icon_input(panel_layout, self.username_input, "user")
        space(panel_layout, 13)
        self.password_input = self.make_input("Password", password=True)
        self.add_icon_input(panel_layout, self.password_input, "lock")
        space(panel_layout, 12)
        self.login_error_label = QLabel("")
        self.login_error_label.setObjectName("messageLabel")
        self.login_error_label.setAlignment(Qt.AlignCenter)
        size(self.login_error_label, "setFixedHeight", 18)
        panel_layout.addWidget(self.login_error_label)
        space(panel_layout, 6)
        self.login_button = QPushButton("LOGIN   →")
        self.login_button.setObjectName("primaryButton")
        size(self.login_button, "setFixedHeight", 50)
        self.login_button.setCursor(Qt.PointingHandCursor)
        self.login_button.clicked.connect(self.login)
        panel_layout.addWidget(self.login_button)
        space(panel_layout, 2)
        self.username_input.returnPressed.connect(self.login)
        self.password_input.returnPressed.connect(self.login)

    def create_logo(self, parent):
        logo = QLabel(parent)
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet("background: transparent; border: none;")
        logo_path = self.project_root / "assets" / "NelumboLogo.png"
        if logo_path.exists():
            pixmap = QPixmap(str(logo_path))
            if not pixmap.isNull():
                self._logo_pixmap = pixmap
                # Larger than the previous version, but still contained inside
                # the smaller card.
                logo.setPixmap(
                    pixmap.scaled(
                        112,
                        78,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                )
                return logo
        logo.setText("Nelumbo")
        logo.setStyleSheet(
            "color: #FFFFFF; background: transparent; border: none; "
            "font-family: Segoe UI; font-size: 25px; font-weight: 700;"
        )
        return logo

    def make_input(self, placeholder, password=False):
        field = QLineEdit()
        field.setObjectName("authInput")
        field.setPlaceholderText(placeholder)
        self._size(field, "setFixedHeight", 52)
        if password:
            field.setEchoMode(QLineEdit.Password)
        return field

    def add_icon_input(self, layout, field, icon_type="user"):
        container = QWidget(self.panel)
        self._size(container, "setFixedHeight", 52)
        container.setStyleSheet("background: transparent; border: none;")
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        # Keep the icon inside the input without absolute coordinates.
        icon = UserIcon(container) if icon_type == "user" else LockIcon(container)
        self._size(icon, "setFixedSize", 38, 38)
        icon_holder = QWidget(container)
        self._size(icon_holder, "setFixedWidth", 48)
        icon_holder.setStyleSheet("background: transparent; border: none;")
        self._size(icon, "move", 5, 0)
        row.addWidget(icon_holder)
        # The line edit fills the remaining width.
        field.setContentsMargins(0, 0, 0, 0)
        row.addWidget(field, 1)
        if field.echoMode() == QLineEdit.Password:
            # Keep the eye as a separate button at the far right, with no
            # overlap with the password text.
            eye_holder = QWidget(container)
            self._size(eye_holder, "setFixedWidth", 42)
            eye_holder.setStyleSheet("background: transparent; border: none;")
            eye = EyeButton(eye_holder)
            self._size(eye, "setFixedSize", 34, 34)
            self._size(eye, "move", 3, 9)
            eye.raise_()
            eye.clicked.connect(
                lambda checked=False, f=field, b=eye:
                self.toggle_field_visibility(f, b)
            )
            row.addWidget(eye_holder)
        layout.addWidget(container)

    # ------------------------------------------------------------ UI size (follows the window)
    def _size(self, obj, method, *args):
        self._sized.append((obj, method, args))
        getattr(obj, method)(*args)

    def _spacing(self, layout, value):
        spacer = QSpacerItem(0, value, QSizePolicy.Minimum, QSizePolicy.Fixed)
        layout.addSpacerItem(spacer)
        self._sized.append((spacer, "changeSize", (0, value, QSizePolicy.Minimum, QSizePolicy.Fixed)))

    def _auto_scale(self):
        """The card, its text, inputs and button grow with the window like the background does (1.0 at the
        1669 x 942 design size, up to 1.8): at 100 % / 125 % Windows scaling it no longer looks tiny."""
        factor = max(1.0, min(1.8, round(min(self.width() / self.reference_width,
                                               self.height() / self.reference_height) * 10) / 10.0))
        if factor == self._scale:
            return
        self._scale = factor

        def k(value):
            return value if type(value) not in (int, float) or value == 0 else max(1, round(value * factor))
        self.setStyleSheet(_PX.sub(lambda m: f"{k(float(m.group(1)))}px", self._qss))
        for obj, method, args in self._sized:
            getattr(obj, method)(*[k(a) for a in args])
        self.panel.layout().invalidate()
        if getattr(self, "_logo_pixmap", None) is not None:
            self.logo.setPixmap(self._logo_pixmap.scaled(k(112), k(78), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        width, height = self.panel.width(), self.panel.height()
        self.panel_shadow.setPixmap(make_shadow_pixmap(width, height, k(20), k(30), QColor(0, 0, 0, 110),
                                                       self.SHADOW_PAD))
        self.panel_shadow.resize(width + 2 * self.SHADOW_PAD, height + 2 * self.SHADOW_PAD)

    def toggle_field_visibility(self, field, eye_button=None):
        if field.echoMode() == QLineEdit.Password:
            field.setEchoMode(QLineEdit.Normal)
            visible = True
        else:
            field.setEchoMode(QLineEdit.Password)
            visible = False
        # Keep the eye icon synchronized with the password state:
        # visible password = no slash, hidden password = slash.
        if eye_button is not None:
            eye_button.set_password_visible(visible)

    def login(self):
        """Validate the two fixed credentials and emit the existing signal."""
        username = self.username_input.text().strip()
        password = self.password_input.text()
        if username == FIXED_USERNAME and password == FIXED_PASSWORD:
            self.login_error_label.clear()
            self.login_successful.emit()
        else:
            self.login_error_label.setText("Incorrect Username or Password")

    def _apply_background(self, smooth=True):
        """Scale the artwork to the window (stretched, as before) - once per size, from a reduced picture."""
        if not self.background_path.exists():
            return
        size = self.size()
        if getattr(self, "_bg_size", None) == size and (self._bg_smooth or not smooth):
            return
        ratio = self.devicePixelRatioF()
        target = QSize(max(1, round(size.width() * ratio)), max(1, round(size.height() * ratio)))
        large = target.width() > BACKGROUND_MEDIUM[0] or target.height() > BACKGROUND_MEDIUM[1]
        key = "_bg_full" if large else "_bg_medium"
        source = getattr(self, key, None)
        if source is None:
            source = image_cache.pixmap(self.background_path, *((0, 0) if large else BACKGROUND_MEDIUM))
            setattr(self, key, source)
        if source.isNull():
            return
        scaled = source.scaled(target, Qt.IgnoreAspectRatio, Qt.SmoothTransformation if smooth else Qt.FastTransformation)
        scaled.setDevicePixelRatio(ratio)
        self.background.setPixmap(scaled)
        self.background.setAlignment(Qt.AlignCenter)
        self._bg_size = size
        self._bg_smooth = smooth

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.background.setGeometry(self.rect())
        # Resize events in quick succession = the window is being dragged: the quick scaling is used
        # meanwhile and the smooth one is made 120 ms after the last event.
        now = time.monotonic()
        dragging = (now - getattr(self, "_last_resize", 0.0)) < 0.15
        self._last_resize = now
        self._apply_background(smooth=not dragging)
        if dragging:
            self._background_timer.start()

        self.overlay.setGeometry(self.rect())
        self._auto_scale()
        # The background is stretched to the window, so the card must follow the same stretch: its
        # centre stays on the same point of the artwork (the empty area right of the devices) at every
        # window size / display size. At the 1669x942 design size this is exactly the old position.
        panel_cx = (1235 + 370 / 2) * self.width() / self.reference_width      # 370 x 360 = card design size
        panel_cy = (292 + 360 / 2) * self.height() / self.reference_height
        panel_x = int(round(panel_cx - self.panel.width() / 2))
        panel_y = int(round(panel_cy - self.panel.height() / 2))
        panel_x = max(0, min(panel_x, self.width() - self.panel.width()))
        panel_y = max(0, min(panel_y, self.height() - self.panel.height()))
        self.panel.move(panel_x, panel_y)
        self.panel_shadow.move(panel_x - self.SHADOW_PAD, panel_y - self.SHADOW_PAD + 7)
        self.background.lower()
        self.overlay.raise_()
        self.panel_shadow.raise_()
        self.panel.raise_()