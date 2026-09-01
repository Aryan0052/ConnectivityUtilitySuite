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


class ModbusView(QWidget):

    back_clicked = Signal()

    def __init__(self):
        super().__init__()

        self.setStyleSheet("""
            QWidget {
                background: #F5FAEF;
                color: #111111;
                font-family: "Times New Roman";
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
                font-family: "Times New Roman";
                font-size: 20px;
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
                font-size: 16px;
                font-weight: bold;
            }

            QPushButton#refreshButton {
                background: white;
                color: #18C53D;
                border: 2px solid #35D65A;
                border-radius: 12px;
                font-size: 14px;
                font-weight: bold;
            }

            QComboBox,
            QLineEdit {
                background: #F0F5F2;
                border: 1px solid #C7D0CD;
                border-radius: 8px;
                padding: 5px 10px;
                font-family: "Times New Roman";
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
                font-size: 17px;
            }

            QLabel#sectionTitle {
                font-size: 20px;
                font-weight: bold;
                border-bottom: 3px solid #BFC5C3;
                padding-bottom: 5px;
            }

            QLabel#mainTitle {
                font-size: 20px;
                font-weight: bold;
            }

            QLabel#channelTitle {
                font-size: 20px;
                font-weight: bold;
            }

            QLabel#smallLabel {
                font-size: 16px;
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
        company.setFixedHeight(25)
        company.setStyleSheet("""
            color: white;
            font-family: "Times New Roman";
            font-size: 17px;
            font-weight: bold;
        """)

        subtitle = QLabel("Connectivity Utility Suite")
        subtitle.setFixedHeight(17)
        subtitle.setStyleSheet("""
            color: white;
            font-family: "Times New Roman";
            font-size: 11px;
        """)

        title_layout.addWidget(company)
        title_layout.addWidget(subtitle)

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
        # LEFT CONNECT PANEL
        # ---------------------------------------------------------

        left_panel = QFrame()
        left_panel.setObjectName("leftPanel")
        left_panel.setMinimumWidth(355)
        left_panel.setMaximumWidth(390)

        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(20, 14, 20, 14)
        left_layout.setSpacing(7)

        connect = QPushButton("CONNECT")
        connect.setObjectName("connectButton")
        connect.setFixedSize(330, 44)
        connect.setEnabled(True)
        connect.setVisible(True)
        connect.setStyleSheet("""
            QPushButton {
                background: #1884A1;
                color: white;
                border: none;
                border-radius: 7px;
                font-family: "Times New Roman";
                font-size: 20px;
                font-weight: bold;
            }
            QPushButton:hover { background: #14758F; }
            QPushButton:pressed { background: #105F75; }
        """)
        connect.show()

        status = QLabel("● Not Connected")
        status.setObjectName("status")

        protocol_label = QLabel("Protocol")
        protocol_label.setObjectName("smallLabel")

        protocol = QComboBox()
        protocol.addItem("Modbus RTU & TCP /IP")
        protocol.setCurrentIndex(0)
        protocol.setFixedHeight(36)

        rtu_title = QLabel("RTU Slave Settings")
        rtu_title.setObjectName("sectionTitle")

        slave_label = QLabel("Slave ID (1-63)")
        slave_label.setObjectName("smallLabel")

        slave_id = QLineEdit("1")
        slave_id.setFixedHeight(36)

        valid_ids = QLabel("Valid Slave IDs: 1 to 63")
        valid_ids.setStyleSheet("""
            color: #555555;
            font-size: 13px;
        """)

        baud_label = QLabel("RTU Baud Rate")
        baud_label.setObjectName("smallLabel")

        baud = QComboBox()
        baud.addItems([
            "9600",
            "19200",
            "38400",
            "57600",
            "115200"
        ])
        baud.setCurrentText("9600")
        baud.setFixedHeight(36)

        # Keep the dropdown light, matching the other pages.
        baud.view().setStyleSheet("""
            QAbstractItemView {
                background: #F0F5F2;
                color: #333333;
                border: 1px solid #C7D0CD;
                selection-background-color: #DDEBE6;
                selection-color: #222222;
                font-family: "Times New Roman";
                font-size: 15px;
                outline: none;
            }

            QAbstractItemView::item {
                background: #F0F5F2;
                color: #333333;
                padding: 4px 10px;
                min-height: 20px;
            }

            QAbstractItemView::item:hover {
                background: #E5EFEB;
                color: #222222;
            }
        """)

        apply_rtu = QPushButton("APPLY")
        apply_rtu.setObjectName("applyButton")
        apply_rtu.setFixedSize(130, 42)
        apply_rtu.setVisible(True)
        apply_rtu.show()
        apply_rtu.setStyleSheet("""
            QPushButton {
                background: #1884A1;
                color: white;
                border: none;
                border-radius: 7px;
                font-family: "Times New Roman";
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover { background: #14758F; }
            QPushButton:pressed { background: #105F75; }
        """)

        apply_row = QHBoxLayout()
        apply_row.addStretch()
        apply_row.addWidget(apply_rtu)
        apply_row.addStretch()

        terminal_row = QHBoxLayout()

        terminal_title = QLabel("Device Terminal")
        terminal_title.setObjectName("mainTitle")

        refresh = QPushButton("Refresh")
        refresh.setObjectName("refreshButton")
        refresh.setFixedSize(82, 40)

        terminal_row.addWidget(terminal_title)
        terminal_row.addStretch()
        terminal_row.addWidget(refresh)

        terminal = QFrame()
        terminal.setStyleSheet("""
            QFrame {
                background: #F0F5F2;
                border: 1px solid #D2D9D6;
                border-radius: 8px;
            }
        """)
        terminal.setMinimumHeight(70)

        left_layout.addWidget(connect)
        left_layout.addWidget(status)
        left_layout.addWidget(protocol_label)
        left_layout.addWidget(protocol)
        left_layout.addWidget(rtu_title)
        left_layout.addWidget(slave_label)
        left_layout.addWidget(slave_id)
        left_layout.addWidget(valid_ids)
        left_layout.addWidget(baud_label)
        left_layout.addWidget(baud)
        left_layout.addLayout(apply_row)
        left_layout.addSpacing(8)
        left_layout.addLayout(terminal_row)
        left_layout.addWidget(terminal)
        # Do not add a stretch here; keep all controls visible.

        # ---------------------------------------------------------
        # RIGHT TCP/IP PANEL
        # ---------------------------------------------------------

        right_panel = QFrame()
        right_panel.setObjectName("rightPanel")

        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(24, 18, 24, 16)
        right_layout.setSpacing(7)

        tcp_title = QLabel("TCP/IP Communication")
        tcp_title.setObjectName("sectionTitle")

        ip_label = QLabel("IP Address")
        ip_label.setObjectName("smallLabel")

        ip_address = QLineEdit("192.168.1.100")
        ip_address.setFixedHeight(36)

        subnet_label = QLabel("Subnet Mask")
        subnet_label.setObjectName("smallLabel")

        subnet = QLineEdit("255.255.255.0")
        subnet.setFixedHeight(36)

        port_label = QLabel("TCP Port")
        port_label.setObjectName("smallLabel")

        tcp_port = QLineEdit("502")
        tcp_port.setFixedHeight(36)

        apply_tcp = QPushButton("APPLY")
        apply_tcp.setObjectName("applyButton")
        apply_tcp.setFixedSize(82, 40)
        apply_tcp.setVisible(True)
        apply_tcp.show()
        apply_tcp.setStyleSheet("""
            QPushButton {
                background: #1884A1;
                color: white;
                border: none;
                border-radius: 7px;
                font-family: "Times New Roman";
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover { background: #14758F; }
            QPushButton:pressed { background: #105F75; }
        """)

        port_title = QLabel("Port Settings")
        port_title.setObjectName("sectionTitle")

        port1_label = QLabel("Port 1")
        port1_label.setObjectName("smallLabel")

        port2_label = QLabel("Port 2")
        port2_label.setObjectName("smallLabel")

        port1 = QComboBox()
        port1.addItems(["9600"])
        port1.setCurrentIndex(0)
        port1.setFixedHeight(36)

        port2 = QComboBox()
        port2.addItems(["9600"])
        port2.setCurrentIndex(0)
        port2.setFixedHeight(36)

        apply_port1 = QPushButton("APPLY")
        apply_port1.setObjectName("applyButton")
        apply_port1.setFixedSize(82, 40)
        apply_port1.setVisible(True)
        apply_port1.show()
        apply_port1.setStyleSheet("""
            QPushButton {
                background: #1884A1;
                color: white;
                border: none;
                border-radius: 7px;
                font-family: "Times New Roman";
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover { background: #14758F; }
            QPushButton:pressed { background: #105F75; }
        """)

        apply_port2 = QPushButton("APPLY")
        apply_port2.setObjectName("applyButton")
        apply_port2.setFixedSize(82, 40)
        apply_port2.setVisible(True)
        apply_port2.show()
        apply_port2.setStyleSheet("""
            QPushButton {
                background: #1884A1;
                color: white;
                border: none;
                border-radius: 7px;
                font-family: "Times New Roman";
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover { background: #14758F; }
            QPushButton:pressed { background: #105F75; }
        """)

        port_grid = QGridLayout()
        port_grid.setHorizontalSpacing(28)
        port_grid.setVerticalSpacing(8)

        port_grid.addWidget(port1_label, 0, 0)
        port_grid.addWidget(port2_label, 0, 1)
        port_grid.addWidget(port1, 1, 0)
        port_grid.addWidget(port2, 1, 1)
        port_grid.addWidget(apply_port1, 2, 0)
        port_grid.addWidget(apply_port2, 2, 1)

        right_layout.addWidget(tcp_title)
        right_layout.addWidget(ip_label)
        right_layout.addWidget(ip_address)
        right_layout.addWidget(subnet_label)
        right_layout.addWidget(subnet)
        right_layout.addWidget(port_label)
        right_layout.addWidget(tcp_port)
        right_layout.addWidget(apply_tcp)
        right_layout.addSpacing(12)
        right_layout.addWidget(port_title)
        right_layout.addLayout(port_grid)
        right_layout.addStretch()

        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_panel, 1)

        root.addWidget(main, 1)