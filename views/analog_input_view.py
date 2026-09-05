import os

from PySide6.QtCore import Signal, Qt, QPoint
from PySide6.QtGui import QFont, QPixmap, QPainter, QPen
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QLineEdit,
    QFrame,
)


class BackButton(QPushButton):
    """White circular back button matching the reference image."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setFixedSize(58, 58)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)

        # No text: the arrow is drawn precisely below.
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

        # White circular background.
        painter.setPen(Qt.NoPen)
        painter.setBrush(Qt.white)
        painter.drawEllipse(0, 0, 58, 58)

        # Thick dark-blue arrow.
        pen = QPen("#155B91")
        pen.setWidth(6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)

        # Horizontal shaft.
        painter.drawLine(
            QPoint(19, 29),
            QPoint(43, 29)
        )

        # Large arrow head.
        painter.drawLine(
            QPoint(19, 29),
            QPoint(31, 17)
        )

        painter.drawLine(
            QPoint(19, 29),
            QPoint(31, 41)
        )

        painter.end()


class AnalogInputView(QWidget):

    back_clicked = Signal()

    def __init__(self):
        super().__init__()

        self.setStyleSheet("""
            QWidget {
                background: #F5FAEF;
                color: #111111;
                font-family: Cambria;
            }

            QFrame#header {
                background: qlineargradient(
                    x1: 0, y1: 0,
                    x2: 1, y2: 0,
                    stop: 0 #18AEB5,
                    stop: 1 #19588F
                );
            }

            QFrame#leftPanel,
            QFrame#rightPanel {
                background: white;
                border: 1px solid #35D65A;
                border-radius: 10px;
            }

            QPushButton#connectButton {
                background: #1884A1;
                color: white;
                border: none;
                border-radius: 7px;
                font-family: Cambria;
                font-size: 18px;
                font-weight: bold;
            }

            QPushButton#connectButton:hover {
                background: #14758F;
            }

            QPushButton#applyButton {
                background: qlineargradient(
                    x1: 0, y1: 0,
                    x2: 1, y2: 0,
                    stop: 0 #19B0BA,
                    stop: 1 #185C96
                );
                color: white;
                border: none;
                border-radius: 7px;
                font-size: 18px;
                font-weight: bold;
            }

            QPushButton#refreshButton {
                background: white;
                color: #18C53D;
                border: 2px solid #35D65A;
                border-radius: 12px;
                font-size: 13px;
                font-weight: bold;
            }

            QComboBox,
            QLineEdit {
                background: #F0F5F2;
                border: 1px solid #C7D0CD;
                border-radius: 8px;
                padding: 5px 10px;
                font-family: Cambria;
                font-size: 16px;
            }

            QComboBox:focus,
            QLineEdit:focus {
                border: 1px solid #25BFC8;
            }

            QComboBox::drop-down {
                width: 30px;
                border: none;
            }

            QLabel {
                background: transparent;
            }

            QLabel#status {
                color: #00C928;
                font-weight: bold;
                font-size: 16px;
            }

            QLabel#sectionTitle {
                font-size: 16px;
                font-weight: bold;
                border-bottom: 3px solid #BFC5C3;
                padding-bottom: 5px;
            }

            QLabel#mainTitle {
                font-size: 16px;
                font-weight: bold;
            }

            QLabel#channelTitle {
                font-size: 16px;
                font-weight: bold;
            }

            QLabel#smallLabel {
                font-size: 16px;
            }

            QFrame#configFrame {
                background: white;
                border: 1px solid #222222;
                border-radius: 10px;
            }

            QFrame#rangeFrame {
                background: white;
                border: 1px solid #222222;
                border-radius: 10px;
            }

            QPushButton#okButton {
                background: #168BA4;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 13px;
                font-weight: bold;
            }

            QPushButton#channelButton {
                background: qlineargradient(
                    x1: 0, y1: 0,
                    x2: 1, y2: 0,
                    stop: 0 #A9E0E5,
                    stop: 1 #AEBFD8
                );
                color: #333333;
                border: 1px solid #9AAEBF;
                border-radius: 9px;
                text-align: left;
                padding-left: 18px;
                font-size: 14px;
                font-weight: bold;
            }
        """)

        self.build_ui()

    def build_ui(self):

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---------------------------------------------------------
        # HEADER
        # ---------------------------------------------------------

        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(88)

        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 5, 20, 5)
        header_layout.setSpacing(0)

        logo = QLabel()
        logo.setFixedSize(62, 68)
        logo.setAlignment(Qt.AlignCenter)

        logo_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "assets",
            "NelumboLogo.png"
        )

        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            if not pixmap.isNull():
                logo.setPixmap(
                    pixmap.scaled(
                        62,
                        68,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation
                    )
                )

        header_layout.addWidget(logo)

        title_layout = QVBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)

        company = QLabel("Nelumbo Automation Pvt Ltd")
        company.setFixedHeight(22)
        company.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        company.setStyleSheet("""
            QLabel {
                color: white;
                font-family: Cambria;
                font-size: 20px;
                font-weight: bold;
                padding: 0px;
                margin: 0px;
            }
        """)

        subtitle = QLabel("Connectivity Utility Suite")
        subtitle.setFixedHeight(15)
        subtitle.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        subtitle.setStyleSheet("""
            QLabel {
                color: white;
                font-family: Cambria;
                font-size: 16px;
                padding: 0px;
                margin: 0px;
            }
        """)

        title_layout.addStretch()
        title_layout.addWidget(company)
        title_layout.addWidget(subtitle)
        title_layout.addStretch()

        header_layout.addLayout(title_layout)
        header_layout.addStretch()

        back = BackButton()
        back.setObjectName("backButton")
        back.clicked.connect(self.back_clicked.emit)

        header_layout.addWidget(back)

        root.addWidget(header)

        # ---------------------------------------------------------
        # MAIN AREA
        # ---------------------------------------------------------

        main = QWidget()
        main.setStyleSheet("background: #F5FAEF;")

        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(24, 26, 24, 20)
        main_layout.setSpacing(34)

        # ---------------------------------------------------------
        # LEFT PANEL
        # ---------------------------------------------------------

        left_panel = QFrame()
        left_panel.setObjectName("leftPanel")
        left_panel.setMinimumWidth(355)
        left_panel.setMaximumWidth(390)

        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(20, 18, 20, 18)
        left_layout.setSpacing(10)

        connect = QPushButton("CONNECT")
        connect.setObjectName("connectButton")
        connect.setFixedHeight(48)
        connect.setEnabled(True)
        connect.setVisible(True)
        connect.setStyleSheet("""
            QPushButton {
                background-color: #1884A1;
                color: white;
                border: none;
                border-radius: 7px;
                font-family: Cambria;
                font-size: 18px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #14758F;
            }
            QPushButton:pressed {
                background-color: #126B82;
            }
            QPushButton:disabled {
                background-color: #1884A1;
                color: white;
            }
        """)

        left_layout.addWidget(connect)

        status = QLabel("● Not Connected")
        status.setObjectName("status")
        left_layout.addWidget(status)

        protocol_label = QLabel("Protocol")
        protocol_label.setObjectName("smallLabel")
        left_layout.addWidget(protocol_label)

        protocol = QComboBox()
        protocol.addItem("Analog Input")
        protocol.setFixedHeight(38)
        left_layout.addWidget(protocol)

        section = QLabel("RTU Slave Settings")
        section.setObjectName("sectionTitle")
        left_layout.addWidget(section)

        slave_label = QLabel("Slave ID (1-63)")
        slave_label.setObjectName("smallLabel")
        left_layout.addWidget(slave_label)

        slave_id = QLineEdit("1")
        slave_id.setFixedHeight(38)
        left_layout.addWidget(slave_id)

        valid = QLabel("Valid Slave IDs: 1 to 63")
        valid.setStyleSheet("""
            color: #555555;
            font-family: Cambria;
            font-size: 16px;
        """)
        left_layout.addWidget(valid)

        baud_label = QLabel("RTU Baud Rate")
        baud_label.setObjectName("smallLabel")
        left_layout.addWidget(baud_label)

        baud = QComboBox()
        baud.addItems([
            "9600",
            "19200",
            "38400",
            "57600",
            "115200"
        ])
        baud.setFixedHeight(38)
        left_layout.addWidget(baud)

        apply_button = QPushButton("APPLY")
        apply_button.setObjectName("applyButton")
        apply_button.setFixedSize(136, 44)
        apply_button.setEnabled(True)
        apply_button.setVisible(True)
        apply_button.setStyleSheet("""
            QPushButton {
                background-color: #1884A1;
                color: white;
                border: none;
                border-radius: 7px;
                font-family: Cambria;
                font-size: 18px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #14758F;
            }
            QPushButton:pressed {
                background-color: #126B82;
            }
            QPushButton:disabled {
                background-color: #1884A1;
                color: white;
            }
        """)

        apply_layout = QHBoxLayout()
        apply_layout.addStretch()
        apply_layout.addWidget(apply_button)
        apply_layout.addStretch()

        left_layout.addLayout(apply_layout)

        terminal_header = QHBoxLayout()

        terminal_title = QLabel("Device Terminal")
        terminal_title.setStyleSheet("""
            font-family: Cambria;
            font-size: 16px;
            font-weight: bold;
        """)

        refresh = QPushButton("Refresh")
        refresh.setObjectName("refreshButton")
        refresh.setFixedSize(82, 40)

        terminal_header.addWidget(terminal_title)
        terminal_header.addStretch()
        terminal_header.addWidget(refresh)

        left_layout.addLayout(terminal_header)

        terminal = QLineEdit()
        terminal.setReadOnly(True)
        terminal.setFixedHeight(76)
        left_layout.addWidget(terminal)

        left_layout.addStretch()

        # ---------------------------------------------------------
        # RIGHT PANEL
        # ---------------------------------------------------------
        right_panel = QFrame()
        right_panel.setObjectName("rightPanel")

        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(
            40,
            20,
            40,
            20
        )
        right_layout.setSpacing(0)

        # Right panel intentionally blank.

        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_panel, 1)

        root.addWidget(main, 1)
        main_layout.addWidget(right_panel, 1)

        root.addWidget(main, 1)






