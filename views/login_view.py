from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
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


class LoginView(QWidget):
    login_successful = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.project_root = Path(__file__).resolve().parents[1]

        self.background_path = (
            self.project_root
            / "assets"
            / "login_background.png"
        )

        self.build_ui()

    def build_ui(self):

        self.setObjectName("loginView")

        self.setStyleSheet(
            """
            QWidget#loginView {
                background: #777777;
            }

            QWidget#loginPanel {
                background: qlineargradient(
                    x1: 0,
                    y1: 0,
                    x2: 1,
                    y2: 1,
                    stop: 0 #10A9B8,
                    stop: 0.50 #087EA9,
                    stop: 1 #15558F
                );

                border: 2px solid #12C92A;
                border-radius: 24px;
            }

            QLabel#loginTitle {
                background: transparent;
                border: none;
                color: white;

                font-family:
                    Georgia,
                    "Times New Roman",
                    serif;

                font-size: 27px;
                font-weight: bold;
            }

            QLineEdit {
                background: #DCE4E2;
                color: #222222;

                border: 2px solid white;
                border-radius: 15px;

                padding-left: 52px;
                padding-right: 12px;

                font-family:
                    Georgia,
                    "Times New Roman",
                    serif;

                font-size: 20px;
            }

            QLineEdit::placeholder {
                color: #777777;
            }

            QPushButton#loginButton {
                background: #16D322;
                color: white;

                border: 2px solid #A8F2A8;
                border-radius: 14px;

                font-family:
                    Georgia,
                    "Times New Roman",
                    serif;

                font-size: 21px;
                font-weight: bold;
            }

            QPushButton#loginButton:hover {
                background: #19D827;
            }

            QPushButton#loginButton:pressed {
                background: #12BD20;
            }
            """
        )

        # Background
        self.background = QLabel(self)
        self.background.setAlignment(Qt.AlignCenter)

        # Dark transparent overlay over the background image.
        self.overlay = QWidget(self)
        self.overlay.setAttribute(
            Qt.WA_TransparentForMouseEvents,
            True,
        )
        self.overlay.setStyleSheet(
            """
            QWidget {
                background-color: rgba(0, 0, 0, 145);
                border: none;
            }
            """
        )

        # Smaller centered panel
        self.panel = QWidget(self)
        self.panel.setObjectName("loginPanel")
        self.panel.setFixedSize(520, 400)

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
            145,
            52,
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

                scaled = pixmap.scaled(
                    self.size(),
                    Qt.KeepAspectRatioByExpanding,
                    Qt.SmoothTransformation,
                )

                self.background.setPixmap(
                    scaled
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
