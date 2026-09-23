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


VALID_USERNAME = "nelumbo"
VALID_PASSWORD = "Nelumbo123"


class UserIcon(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(38, 38)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        pen = QPen(Qt.black)
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

        pen = QPen(Qt.black)
        pen.setWidth(2)
        painter.setPen(pen)

        painter.drawArc(11, 4, 17, 18, 0, 180 * 16)
        painter.drawRect(8, 16, 23, 20)

        painter.end()


class EyeButton(QToolButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(42, 42)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        pen = QPen(Qt.black)
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        # Slightly organic Instagram-style visibility icon: almond eye + iris
        # with a diagonal slash rather than a perfectly geometric outline.
        painter.drawArc(7, 13, 28, 16, 20 * 16, 140 * 16)
        painter.drawArc(7, 13, 28, 16, 200 * 16, 140 * 16)
        painter.drawEllipse(17, 17, 8, 8)
        painter.drawLine(9, 29, 34, 9)

        painter.end()


class LoginView(QWidget):
    login_successful = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.project_root = Path(__file__).resolve().parents[1]

        self.background_path = (
            self.project_root
            / "assets"
            / "Nelumbo_Remote_IO_Module_System.png"
        )

        self.build_ui()

    def build_ui(self):

        self.setObjectName("loginView")

        self.setStyleSheet(
            """
            QWidget#loginView {
                background: #EAF3FB;
            }

            QWidget#loginPanel {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 #079DB1,
                    stop: 0.52 #087FAF,
                    stop: 1 #075B8D
                );
                border: 2px solid #19C4D1;
                border-radius: 24px;
            }

            QLabel#loginTitle {
                background: transparent;
                border: none;
                color: #FFFFFF;

                font-family: Cambria;
                font-size: 32px;
                font-weight: bold;
            }

            QLineEdit {
                background: #FFFFFF;
                color: #123B5D;

                border: 2px solid #D3E5F2;
                border-radius: 14px;

                padding-left: 52px;
                padding-right: 52px;

                font-family: Cambria;
                font-size: 24px;
            }

            QLineEdit:focus {
                background: #FFFFFF;
                border: 2px solid #19A9C6;
            }

            QLineEdit::placeholder {
                color: #7891A5;
            }

            QPushButton#loginButton {
                background: #1677B8;
                color: white;

                border: 2px solid #4AB7E8;
                border-radius: 14px;

                font-family: Cambria;
                font-size: 22px;
                font-weight: bold;
            }

            QPushButton#loginButton:hover {
                background: #0F679F;
            }

            QPushButton#loginButton:pressed {
                background: #0A527F;
            }
            """
        )

        # Background
        self.background = QLabel(self)
        self.background.setAlignment(Qt.AlignCenter)

        # Soft dark overlay keeps the product visible while improving login readability.
        self.overlay = QWidget(self)
        self.overlay.setAttribute(
            Qt.WA_TransparentForMouseEvents,
            True,
        )
        self.overlay.setStyleSheet(
            """
            QWidget {
                background-color: rgba(0, 0, 0, 225);
                border: none;
            }
            """
        )

        # Smaller centered panel
        self.panel = QWidget(self)
        self.panel.setObjectName("loginPanel")
        self.panel.setFixedSize(520, 400)

        # Soft blue-grey shadow gives the white login card depth without
        # changing any login functionality.
        self.panel_shadow = QGraphicsDropShadowEffect(self.panel)
        self.panel_shadow.setBlurRadius(38)
        self.panel_shadow.setOffset(0, 12)
        self.panel_shadow.setColor(QColor(0, 54, 86, 125))
        self.panel.setGraphicsEffect(self.panel_shadow)

        panel_layout = QVBoxLayout(self.panel)

        panel_layout.setContentsMargins(
            38,
            30,
            38,
            30,
        )

        panel_layout.setSpacing(0)

        # Title
        title = QLabel(
            "Dashboard Access Login"
        )

        title.setObjectName("loginTitle")
        title.setAlignment(Qt.AlignCenter)
        title.setMinimumHeight(45)

        panel_layout.addWidget(title)

        panel_layout.addSpacing(30)

        # Username
        username_container = QWidget()

        username_layout = QHBoxLayout(
            username_container
        )

        username_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        self.username_input = QLineEdit()

        self.username_input.setPlaceholderText(
            "Username"
        )

        self.username_input.clear()

        self.username_input.setFixedHeight(58)

        username_layout.addWidget(
            self.username_input
        )

        user_icon = UserIcon(
            username_container
        )

        user_icon.move(
            17,
            10,
        )

        user_icon.raise_()

        panel_layout.addWidget(
            username_container
        )

        panel_layout.addSpacing(20)

        # Password
        password_container = QWidget()

        password_layout = QHBoxLayout(
            password_container
        )

        password_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        self.password_input = QLineEdit()

        self.password_input.setPlaceholderText(
            "Password"
        )

        self.password_input.setEchoMode(
            QLineEdit.Password
        )

        self.password_input.setFixedHeight(58)

        password_layout.addWidget(
            self.password_input
        )

        lock_icon = LockIcon(
            password_container
        )

        lock_icon.move(
            17,
            10,
        )

        lock_icon.raise_()

        # Password eye button
        self.password_eye_button = EyeButton(
            password_container
        )

        self.password_eye_button.setStyleSheet(
            """
            QToolButton {
                background: transparent;
                border: none;
            }
            """
        )

        self.password_eye_button.move(
            406,
            8,
        )

        self.password_eye_button.raise_()

        self.password_eye_button.clicked.connect(
            self.toggle_password_visibility
        )

        panel_layout.addWidget(
            password_container
        )

        panel_layout.addSpacing(28)

        # Login button
        self.login_button = QPushButton(
            "LOGIN"
        )

        self.login_button.setObjectName(
            "loginButton"
        )

        self.login_button.setFixedSize(
            135,
            50,
        )

        self.login_button.setCursor(
            Qt.PointingHandCursor
        )

        button_layout = QHBoxLayout()

        button_layout.addStretch()
        button_layout.addWidget(
            self.login_button
        )
        button_layout.addStretch()

        panel_layout.addLayout(
            button_layout
        )

        # Events
        self.login_button.clicked.connect(
            self.login
        )

        self.username_input.returnPressed.connect(
            self.login
        )

        self.password_input.returnPressed.connect(
            self.login
        )

    def toggle_password_visibility(self):

        if (
            self.password_input.echoMode()
            == QLineEdit.Password
        ):
            self.password_input.setEchoMode(
                QLineEdit.Normal
            )
        else:
            self.password_input.setEchoMode(
                QLineEdit.Password
            )

    def login(self):

        username = (
            self.username_input
            .text()
            .strip()
        )

        password = (
            self.password_input
            .text()
        )

        if (
            username == VALID_USERNAME
            and password == VALID_PASSWORD
        ):
            self.login_successful.emit()

        else:
            self.show_login_error()

    def show_login_error(self):

        error_label = getattr(
            self,
            "login_error_label",
            None,
        )

        if error_label is None:

            self.login_error_label = QLabel(
                "Incorrect username or password"
            )

            self.login_error_label.setAlignment(
                Qt.AlignCenter
            )

            self.login_error_label.setStyleSheet(
                """
                QLabel {
                    color: #FF3333;
                    background: transparent;
                    border: none;
                    font-family: Cambria;
                    font-size: 16px;
                    font-weight: bold;
                }
                """
            )

            self.panel.layout().insertWidget(
                5,
                self.login_error_label,
            )

        self.login_error_label.show()

    def resizeEvent(self, event):

        super().resizeEvent(event)

        # Background
        self.background.setGeometry(
            self.rect()
        )

        if self.background_path.exists():

            pixmap = QPixmap(
                str(self.background_path)
            )

            if not pixmap.isNull():

                # Use a tight crop around the complete device so the
                # hardware stays clearly visible without showing excessive
                # empty photograph background or cutting off any module.
                left = 215
                top = 65
                right = min(1465, pixmap.width())
                bottom = min(925, pixmap.height())

                crop_width = max(1, right - left)
                crop_height = max(1, bottom - top)
                cropped = pixmap.copy(left, top, crop_width, crop_height)

                # Slightly zoom the device while keeping the same fullscreen behavior.
                # The crop already contains a small safety margin around the hardware.
                zoom = 1.10
                target_width = int(self.width() * zoom)
                target_height = int(self.height() * zoom)
                scaled = cropped.scaled(
                    target_width,
                    target_height,
                    Qt.IgnoreAspectRatio,
                    Qt.SmoothTransformation,
                )

                self.background.setPixmap(scaled)

                self.background.setAlignment(
                    Qt.AlignCenter
                )

        # Overlay
        self.overlay.setGeometry(
            self.rect()
        )

        # Always center panel
        self.panel.move(
            (
                self.width()
                - self.panel.width()
            ) // 2,
            (
                self.height()
                - self.panel.height()
            ) // 2,
        )

        self.background.lower()
        self.overlay.raise_()
        self.panel.raise_()