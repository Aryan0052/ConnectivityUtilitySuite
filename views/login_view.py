from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QPen, QPixmap, QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QToolButton,
    QGraphicsDropShadowEffect,
)


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
        self.setMinimumSize(self.reference_width, self.reference_height)

        self.build_ui()

    def build_ui(self):
        self.setObjectName("loginView")
        self.setStyleSheet(
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
        self.panel.setFixedSize(370, 360)

        self.panel_shadow = QGraphicsDropShadowEffect(self.panel)
        self.panel_shadow.setBlurRadius(30)
        self.panel_shadow.setOffset(0, 7)
        self.panel_shadow.setColor(QColor(0, 0, 0, 110))
        self.panel.setGraphicsEffect(self.panel_shadow)

        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(28, 24, 28, 24)
        panel_layout.setSpacing(0)

        # Bigger centered Nelumbo logo.
        self.logo = self.create_logo(self.panel)
        self.logo.setFixedHeight(82)
        panel_layout.addWidget(self.logo, alignment=Qt.AlignCenter)
        panel_layout.addSpacing(8)

        # Only username, password and login remain on the card.
        self.username_input = self.make_input("Username")
        self.add_icon_input(panel_layout, self.username_input, "user")
        panel_layout.addSpacing(13)

        self.password_input = self.make_input("Password", password=True)
        self.add_icon_input(panel_layout, self.password_input, "lock")
        panel_layout.addSpacing(12)

        self.login_error_label = QLabel("")
        self.login_error_label.setObjectName("messageLabel")
        self.login_error_label.setAlignment(Qt.AlignCenter)
        self.login_error_label.setFixedHeight(18)
        panel_layout.addWidget(self.login_error_label)
        panel_layout.addSpacing(6)

        self.login_button = QPushButton("LOGIN   →")
        self.login_button.setObjectName("primaryButton")
        self.login_button.setFixedHeight(50)
        self.login_button.setCursor(Qt.PointingHandCursor)
        self.login_button.clicked.connect(self.login)
        panel_layout.addWidget(self.login_button)

        panel_layout.addSpacing(2)

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
        field.setFixedHeight(52)
        if password:
            field.setEchoMode(QLineEdit.Password)
        return field

    def add_icon_input(self, layout, field, icon_type="user"):
        container = QWidget(self.panel)
        container.setFixedHeight(52)
        container.setStyleSheet("background: transparent; border: none;")

        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        # Keep the icon inside the input without absolute coordinates.
        icon = UserIcon(container) if icon_type == "user" else LockIcon(container)
        icon.setFixedSize(38, 38)
        icon_holder = QWidget(container)
        icon_holder.setFixedWidth(48)
        icon_holder.setStyleSheet("background: transparent; border: none;")
        icon.move(5, 0)
        row.addWidget(icon_holder)

        # The line edit fills the remaining width.
        field.setContentsMargins(0, 0, 0, 0)
        row.addWidget(field, 1)

        if field.echoMode() == QLineEdit.Password:
            # Keep the eye as a separate button at the far right, with no
            # overlap with the password text.
            eye_holder = QWidget(container)
            eye_holder.setFixedWidth(42)
            eye_holder.setStyleSheet("background: transparent; border: none;")
            eye = EyeButton(eye_holder)
            eye.move(3, 9)
            eye.raise_()
            eye.clicked.connect(
                lambda checked=False, f=field, b=eye:
                self.toggle_field_visibility(f, b)
            )
            row.addWidget(eye_holder)

        layout.addWidget(container)

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

    def resizeEvent(self, event):
        super().resizeEvent(event)

        self.background.setGeometry(self.rect())

        if self.background_path.exists():
            pixmap = QPixmap(str(self.background_path))
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    self.size(),
                    Qt.KeepAspectRatioByExpanding,
                    Qt.SmoothTransformation,
                )
                self.background.setPixmap(scaled)
                self.background.setAlignment(Qt.AlignCenter)

        self.overlay.setGeometry(self.rect())

        # Keep the composition stable around the supplied 1669x942 artwork.
        canvas_x = max(0, (self.width() - self.reference_width) // 2)
        canvas_y = max(0, (self.height() - self.reference_height) // 2)

        # Smaller card, centered vertically on the right side.
        panel_x = canvas_x + 1235
        panel_y = canvas_y + 292
        self.panel.move(panel_x, panel_y)

        self.background.lower()
        self.overlay.raise_()
        self.panel.raise_()
