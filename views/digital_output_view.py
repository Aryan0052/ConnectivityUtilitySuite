from pathlib import Path

from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import (
    QPainter,
    QPen,
    QBrush,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class PdfBackButton(QPushButton):

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setFixedSize(54, 54)
        self.setCursor(Qt.PointingHandCursor)

        self.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                padding: 0;
            }
        """)

    def paintEvent(self, event):
        painter = QPainter(self)

        painter.setRenderHint(
            QPainter.Antialiasing
        )

        painter.setPen(
            QPen(Qt.white, 2)
        )

        painter.setBrush(
            QBrush(Qt.white)
        )

        painter.drawEllipse(
            QRectF(1, 1, 52, 52)
        )

        painter.setPen(Qt.NoPen)

        painter.setBrush(
            QBrush("#17548C")
        )

        arrow = QPolygonF([
            QPointF(38, 25),
            QPointF(24, 25),
            QPointF(31, 18),
            QPointF(27, 14),
            QPointF(14, 27),
            QPointF(27, 40),
            QPointF(31, 36),
            QPointF(24, 29),
            QPointF(38, 29),
        ])

        painter.drawPolygon(arrow)

        painter.end()


class DigitalOutputView(QWidget):

    back_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName(
            "digitalOutputView"
        )

        self.root = (
            Path(__file__)
            .resolve()
            .parents[1]
        )

        self.logo_path = (
            self.root
            / "assets"
            / "NelumboLogo.png"
        )

        self.build_ui()

    def build_ui(self):

        self.setStyleSheet("""
            QWidget#digitalOutputView {
                background: #F5FAEF;
            }

            QFrame#header {
                background: qlineargradient(
                    x1: 0,
                    y1: 0,
                    x2: 1,
                    y2: 0,
                    stop: 0 #18A9B5,
                    stop: 1 #19518D
                );

                border: none;
            }

            QLabel#company {
                color: white;
                background: transparent;
                font-family: Cambria;
                font-size: 20px;
                font-weight: bold;
            }

            QLabel#suite {
                color: white;
                background: transparent;
                font-family: Cambria;
                font-size: 16px;
            }

            QFrame#leftPanel,
            QFrame#rightPanel {
                background: white;
                border: 1px solid #70D58A;
                border-radius: 8px;
            }

            QLabel#label {
                color: #202020;
                background: transparent;
                font-family: Cambria;
                font-size: 16px;
            }

            QLabel#sectionTitle {
                color: #222222;
                background: transparent;
                font-family: Cambria;
                font-size: 16px;
                font-weight: bold;
            }

            QLabel#status {
                color: #10C51F;
                background: transparent;
                font-family: Cambria;
                font-size: 16px;
                font-weight: bold;
            }

            QLineEdit,
            QComboBox {
                background: #F1F5F2;
                color: #333333;
                border: 1px solid #C8CFCC;
                border-radius: 7px;
                padding-left: 8px;
                font-family: Cambria;
                font-size: 16px;
                min-height: 27px;
            }

            /* Keep the baud-rate dropdown white instead of the dark
               native popup shown by Fusion on some Windows setups. */
            QComboBox QAbstractItemView {
                background: #F1F5F2;
                color: #333333;
                border: 1px solid #C8CFCC;
                selection-background-color: #DDEBE6;
                selection-color: #222222;
                font-family: Cambria;
                font-size: 12px;
                outline: none;
            }

            QComboBox QAbstractItemView::item {
                background: #F1F5F2;
                color: #333333;
                padding: 4px 8px;
                min-height: 20px;
            }

            QComboBox QAbstractItemView::item:hover {
                background: #E5EFEB;
                color: #222222;
            }

            QPushButton#connect {
                background: #16839F;
                color: white;
                border: none;
                border-radius: 7px;
                font-family: Cambria;
                font-size: 18px;
                font-weight: bold;
            }

            QPushButton#apply {
                background: qlineargradient(
                    x1: 0,
                    y1: 0,
                    x2: 1,
                    y2: 0,
                    stop: 0 #13A9B6,
                    stop: 1 #18548D
                );

                color: white;
                border: none;
                border-radius: 7px;
                font-family: Cambria;
                font-size: 18px;
                font-weight: bold;
            }

            QPushButton#refresh {
                background: white;
                color: #16BD34;
                border: 2px solid #48D45C;
                border-radius: 9px;
                font-family: Cambria;
                font-size: 13px;
                font-weight: bold;
            }
        """)

        root_layout = QVBoxLayout(self)

        root_layout.setContentsMargins(
            0, 0, 0, 0
        )

        root_layout.setSpacing(0)

        # HEADER
        header = QFrame()

        header.setObjectName(
            "header"
        )

        header.setFixedHeight(88)

        header_layout = QHBoxLayout(
            header
        )

        header_layout.setContentsMargins(
            20,
            5,
            20,
            5
        )

        # LOGO
        logo = QLabel()

        if self.logo_path.exists():

            pixmap = QPixmap(
                str(self.logo_path)
            )

            logo.setPixmap(
                pixmap.scaled(
                    62,
                    68,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
            )

        else:
            logo.setText("Nelumbo")

        logo.setFixedWidth(62)

        logo.setAlignment(
            Qt.AlignCenter
        )

        header_layout.addWidget(
            logo
        )

        # HEADER TEXT
        text_layout = QVBoxLayout()

        text_layout.setSpacing(0)

        company = QLabel(
            "Nelumbo Automation Pvt Ltd"
        )

        company.setObjectName(
            "company"
        )

        suite = QLabel(
            "Connectivity Utility Suite"
        )

        suite.setObjectName(
            "suite"
        )

        text_layout.addStretch()
        text_layout.addWidget(company)
        text_layout.addWidget(suite)
        text_layout.addStretch()

        header_layout.addLayout(
            text_layout
        )

        header_layout.addStretch()

        # BACK BUTTON
        self.back_button = PdfBackButton()

        header_layout.addWidget(
            self.back_button
        )

        root_layout.addWidget(
            header
        )

        # CONTENT
        content = QHBoxLayout()

        content.setContentsMargins(
            27,
            27,
            20,
            20
        )

        content.setSpacing(20)

        # LEFT PANEL
        left = QFrame()

        left.setObjectName(
            "leftPanel"
        )

        left.setFixedWidth(358)

        left_layout = QVBoxLayout(
            left
        )

        left_layout.setContentsMargins(
            14,
            18,
            14,
            14
        )

        left_layout.setSpacing(0)

        # CONNECT
        self.connect_button = QPushButton(
            "CONNECT"
        )

        self.connect_button.setObjectName(
            "connect"
        )

        self.connect_button.setFixedHeight(
            31
        )

        left_layout.addWidget(
            self.connect_button
        )

        left_layout.addSpacing(25)

        # STATUS
        status_layout = QHBoxLayout()

        status_dot = QLabel("●")

        status_dot.setStyleSheet("""
            QLabel {
                color: #13D324;
                background: transparent;
                font-family: Cambria;
                font-size: 16px;
            }
        """)

        status = QLabel(
            "Not Connected"
        )

        status.setObjectName(
            "status"
        )

        status_layout.addWidget(
            status_dot
        )

        status_layout.addWidget(
            status
        )

        status_layout.addStretch()

        left_layout.addLayout(
            status_layout
        )

        left_layout.addSpacing(25)

        # PROTOCOL
        protocol_label = QLabel(
            "Protocol"
        )

        protocol_label.setObjectName(
            "label"
        )

        left_layout.addWidget(
            protocol_label
        )

        left_layout.addSpacing(5)

        self.protocol = QComboBox()

        self.protocol.addItem(
            "Digital Output"
        )

        left_layout.addWidget(
            self.protocol
        )

        left_layout.addSpacing(27)

        # RTU TITLE
        rtu_title = QLabel(
            "RTU Slave Settings"
        )

        rtu_title.setObjectName(
            "sectionTitle"
        )

        left_layout.addWidget(
            rtu_title
        )

        separator = QFrame()

        separator.setFrameShape(
            QFrame.HLine
        )

        separator.setStyleSheet("""
            QFrame {
                color: #BFC4C1;
                background: #BFC4C1;
                border: none;
                min-height: 1px;
            }
        """)

        left_layout.addWidget(
            separator
        )

        left_layout.addSpacing(25)

        # SLAVE ID
        slave_label = QLabel(
            "Slave ID (1-63)"
        )

        slave_label.setObjectName(
            "label"
        )

        left_layout.addWidget(
            slave_label
        )

        left_layout.addSpacing(5)

        self.slave_id = QLineEdit()

        self.slave_id.setText(
            "1"
        )

        left_layout.addWidget(
            self.slave_id
        )

        valid = QLabel(
            "Valid Slave IDs: 1 to 63"
        )

        valid.setObjectName(
            "label"
        )

        valid.setStyleSheet("""
            QLabel {
                color: #555555;
                background: transparent;
                font-size: 10px;
            }
        """)

        left_layout.addWidget(
            valid
        )

        left_layout.addSpacing(24)

        # BAUD RATE
        baud_label = QLabel(
            "RTU Baud Rate"
        )

        baud_label.setObjectName(
            "label"
        )

        left_layout.addWidget(
            baud_label
        )

        left_layout.addSpacing(5)

        self.baud_rate = QComboBox()

        self.baud_rate.addItems([
            "9600",
            "19200",
            "38400",
            "57600",
            "115200"
        ])

        self.baud_rate.setCurrentText(
            "9600"
        )

        self.baud_rate.view().setStyleSheet("""
            QAbstractItemView {
                background: #F1F5F2;
                color: #333333;
                border: 1px solid #C8CFCC;
                selection-background-color: #DDEBE6;
                selection-color: #222222;
                font-family: Cambria;
                font-size: 12px;
            }

            QAbstractItemView::item {
                background: #F1F5F2;
                color: #333333;
                padding: 4px 8px;
                min-height: 20px;
            }

            QAbstractItemView::item:hover {
                background: #E5EFEB;
                color: #222222;
            }
        """)

        left_layout.addWidget(
            self.baud_rate
        )

        left_layout.addSpacing(21)

        # APPLY
        apply_layout = QHBoxLayout()

        apply_layout.addStretch()

        self.apply_button = QPushButton(
            "APPLY"
        )

        self.apply_button.setObjectName(
            "apply"
        )

        self.apply_button.setFixedSize(
            135,
            31
        )

        apply_layout.addWidget(
            self.apply_button
        )

        apply_layout.addStretch()

        left_layout.addLayout(
            apply_layout
        )

        left_layout.addSpacing(17)

        # DEVICE TERMINAL
        terminal_heading = QHBoxLayout()

        terminal_title = QLabel(
            "Device Terminal"
        )

        terminal_title.setObjectName(
            "sectionTitle"
        )

        self.refresh_button = QPushButton(
            "Refresh"
        )

        self.refresh_button.setObjectName(
            "refresh"
        )

        self.refresh_button.setFixedSize(
            68,
            27
        )

        terminal_heading.addWidget(
            terminal_title
        )

        terminal_heading.addStretch()

        terminal_heading.addWidget(
            self.refresh_button
        )

        left_layout.addLayout(
            terminal_heading
        )

        left_layout.addSpacing(7)

        terminal = QFrame()

        terminal.setStyleSheet("""
            QFrame {
                background: #F1F5F2;
                border: 1px solid #E0E5E1;
                border-radius: 7px;
            }
        """)

        terminal.setFixedHeight(
            75
        )

        left_layout.addWidget(
            terminal
        )

        left_layout.addStretch()

        # RIGHT PANEL
        right = QFrame()

        right.setObjectName(
            "rightPanel"
        )

        right_layout = QVBoxLayout(
            right
        )

        right_layout.setContentsMargins(
            15,
            13,
            15,
            13
        )

        # Blank exactly as requested.
        right_layout.setSpacing(0)

        content.addWidget(
            left
        )

        content.addWidget(
            right,
            1
        )

        root_layout.addLayout(
            content,
            1
        )

        # BACK NAVIGATION
        self.back_button.clicked.connect(
            self.back_clicked.emit
        )