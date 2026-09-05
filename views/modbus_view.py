import os
from ipaddress import ip_address, ip_network

from PySide6.QtCore import Signal, Qt, QPoint, QTimer
from PySide6.QtGui import QFont, QPixmap, QPainter, QPen
from serial.tools import list_ports
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
    QPlainTextEdit,
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
                font-size: 18px;
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
                font-family: Cambria;
                font-size: 18px;
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

        # COM Port selection box.
        com_port_label = QLabel("COM Port")
        com_port_label.setObjectName("smallLabel")

        com_port = QComboBox()
        com_port.setFixedHeight(36)
        com_port.setPlaceholderText("Select COM Port")
        com_port.setVisible(True)
        com_port_label.setVisible(True)

        self.com_port_label = com_port_label
        self.com_port = com_port

        valid_ids = QLabel("Valid Slave IDs: 1 to 63")
        valid_ids.setStyleSheet("""
            color: #555555;
            font-size: 16px;
        """)

        baud_label = QLabel("RTU Baud Rate")
        baud_label.setObjectName("smallLabel")

        baud = QComboBox()
        baud.addItems([
            "1200",
            "2400",
            "4800",
            "9600",
            "19200",
            "38400",
            "57600",
            "115200",
            "230400"
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
                font-family: Cambria;
                font-size: 16px;
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
                font-family: Cambria;
                font-size: 18px;
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

        refresh.clicked.connect(self.handle_refresh)

        self.com_port_refresh_timer = QTimer(self)
        self.com_port_refresh_timer.timeout.connect(self.refresh_com_ports)
        self.com_port_refresh_timer.start(1000)
        self.refresh_com_ports()

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

        terminal_layout = QVBoxLayout(terminal)
        terminal_layout.setContentsMargins(6, 6, 6, 6)
        terminal_layout.setSpacing(0)

        terminal_message = QPlainTextEdit()
        terminal_message.setReadOnly(True)
        terminal_message.setFocusPolicy(Qt.NoFocus)
        terminal_message.setPlainText("Device Terminal Ready")
        terminal_message.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        terminal_message.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        terminal_message.setStyleSheet("""
            QPlainTextEdit {
                background: #F0F5F2;
                color: #111111;
                border: none;
                padding: 2px 4px;
                font-family: Cambria;
                font-size: 16px;
            }
            QScrollBar:vertical {
                width: 10px;
                margin: 0px;
            }
        """)

        self.terminal_message = terminal_message
        self.terminal_messages = ["Device Terminal Ready"]
        terminal_layout.addWidget(terminal_message)

        left_layout.addWidget(connect)
        left_layout.addWidget(status)
        left_layout.addWidget(protocol_label)
        left_layout.addWidget(protocol)
        left_layout.addWidget(rtu_title)
        left_layout.addWidget(slave_label)
        left_layout.addWidget(slave_id)
        left_layout.addWidget(com_port_label)
        left_layout.addWidget(com_port)
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
        right_layout.setContentsMargins(26, 20, 26, 20)
        right_layout.setSpacing(10)

        tcp_title = QLabel("TCP/IP Communication")
        tcp_title.setObjectName("sectionTitle")

        ip_label = QLabel("IP Address")
        ip_label.setObjectName("smallLabel")

        ip_address = QLineEdit()
        ip_address.setPlaceholderText("192.168.1.100")
        ip_address.setFixedHeight(40)

        subnet_label = QLabel("Subnet Mask")
        subnet_label.setObjectName("smallLabel")

        subnet = QLineEdit("255.255.255.0")
        subnet.setFixedHeight(40)

        port_label = QLabel("TCP Port")
        port_label.setObjectName("smallLabel")

        tcp_port = QLineEdit("502")
        tcp_port.setFixedHeight(40)

        apply_tcp = QPushButton("APPLY")
        apply_tcp.setObjectName("applyButton")
        apply_tcp.setFixedSize(100, 42)
        apply_tcp.setVisible(True)
        apply_tcp.show()
        apply_tcp.setStyleSheet("""
            QPushButton {
                background: #1884A1;
                color: white;
                border: none;
                border-radius: 7px;
                font-family: Cambria;
                font-size: 18px;
                font-weight: bold;
            }
            QPushButton:hover { background: #14758F; }
            QPushButton:pressed { background: #105F75; }
        """)

        port_title = QLabel("Port Settings")
        port_title.setObjectName("sectionTitle")

        port1_label = QLabel("Port 1")
        port1_label.setObjectName("smallLabel")
        port1_label.setAlignment(Qt.AlignCenter)

        port2_label = QLabel("Port 2")
        port2_label.setObjectName("smallLabel")
        port2_label.setAlignment(Qt.AlignCenter)

        port1 = QComboBox()
        port1.addItems([
            "1200",
            "2400",
            "4800",
            "9600",
            "19200",
            "38400",
            "57600",
            "115200",
            "230400"
        ])
        port1.setCurrentText("9600")
        port1.setFixedSize(115, 40)

        port2 = QComboBox()
        port2.addItems([
            "1200",
            "2400",
            "4800",
            "9600",
            "19200",
            "38400",
            "57600",
            "115200",
            "230400"
        ])
        port2.setCurrentText("9600")
        port2.setFixedSize(115, 40)

        apply_port1 = QPushButton("APPLY")
        apply_port1.setObjectName("applyButton")
        apply_port1.setFixedSize(100, 42)
        apply_port1.setVisible(True)
        apply_port1.show()
        apply_port1.setStyleSheet("""
            QPushButton {
                background: #1884A1;
                color: white;
                border: none;
                border-radius: 7px;
                font-family: Cambria;
                font-size: 18px;
                font-weight: bold;
            }
            QPushButton:hover { background: #14758F; }
            QPushButton:pressed { background: #105F75; }
        """)

        apply_port2 = QPushButton("APPLY")
        apply_port2.setObjectName("applyButton")
        apply_port2.setFixedSize(100, 42)
        apply_port2.setVisible(True)
        apply_port2.show()
        apply_port2.setStyleSheet("""
            QPushButton {
                background: #1884A1;
                color: white;
                border: none;
                border-radius: 7px;
                font-family: Cambria;
                font-size: 18px;
                font-weight: bold;
            }
            QPushButton:hover { background: #14758F; }
            QPushButton:pressed { background: #105F75; }
        """)

        port_grid = QGridLayout()
        port_grid.setHorizontalSpacing(80)
        port_grid.setVerticalSpacing(10)

        # Keep Port 1 aligned directly with the right-panel left margin.
        port_grid.setColumnStretch(0, 0)
        port_grid.setColumnStretch(1, 1)

        port_grid.addWidget(port1_label, 0, 0, Qt.AlignLeft)
        port_grid.addWidget(port2_label, 0, 1, Qt.AlignCenter)
        port_grid.addWidget(port1, 1, 0, Qt.AlignLeft)
        port_grid.addWidget(port2, 1, 1, Qt.AlignCenter)
        port_grid.addWidget(apply_port1, 2, 0, Qt.AlignLeft)
        port_grid.addWidget(apply_port2, 2, 1, Qt.AlignCenter)

        right_layout.addWidget(tcp_title)
        right_layout.addWidget(ip_label)
        right_layout.addWidget(ip_address)
        right_layout.addWidget(subnet_label)
        right_layout.addWidget(subnet)
        right_layout.addWidget(port_label)
        right_layout.addWidget(tcp_port)
        tcp_apply_row = QHBoxLayout()
        tcp_apply_row.addWidget(apply_tcp)
        tcp_apply_row.addStretch()

        right_layout.addLayout(tcp_apply_row)
        right_layout.addSpacing(14)
        right_layout.addWidget(port_title)
        right_layout.addLayout(port_grid)
        right_layout.addStretch()

        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_panel, 1)

        root.addWidget(main, 1)

        # Keep references for UI actions.
        self._status = status
        self._connect_button = connect
        self._protocol = protocol
        self._slave_id = slave_id
        self._baud = baud
        self._com_port = com_port
        self._ip_address = ip_address
        self._subnet = subnet
        self._tcp_port = tcp_port
        self._port1 = port1
        self._port2 = port2

        # Connect every action button after all widgets are created.
        connect.clicked.connect(self.handle_connect)
        apply_rtu.clicked.connect(self.handle_apply_rtu)
        apply_tcp.clicked.connect(self.handle_apply_tcp)
        apply_port1.clicked.connect(self.handle_apply_port1)
        apply_port2.clicked.connect(self.handle_apply_port2)

    def add_terminal_message(self, message):
        self.terminal_messages.append(str(message))
        self.terminal_message.setPlainText(
            "\n".join(self.terminal_messages)
        )
        scrollbar = self.terminal_message.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def handle_connect(self):
        if self._connect_button.text() == "DISCONNECT":
            self._status.setText("● Not Connected")
            self._connect_button.setText("CONNECT")
            self.add_terminal_message("Disconnected")
            return

        if self._com_port.count() == 0:
            self._status.setText("● Not Connected")
            self._connect_button.setText("CONNECT")
            self.add_terminal_message("COM Port not connected")
            return

        selected_port = self._com_port.currentText().strip()
        if not selected_port:
            self._status.setText("● Not Connected")
            self._connect_button.setText("CONNECT")
            self.add_terminal_message("COM Port not connected")
            return

        self._status.setText("● Connected")
        self._connect_button.setText("DISCONNECT")
        self.add_terminal_message("Connected successfully")
        self.add_terminal_message(f"COM Port connected: {selected_port}")
        self.add_terminal_message(
            f"Protocol: {self._protocol.currentText()}"
        )

    def handle_apply_rtu(self):
        # RTU settings can only be applied after a COM port is connected.
        if (
            self._connect_button.text() != "DISCONNECT"
            or not self._com_port.currentText().strip()
        ):
            self.add_terminal_message("COM Port not connected")
            return

        slave_text = self._slave_id.text().strip()

        try:
            slave_id = int(slave_text)
        except ValueError:
            self.add_terminal_message("Slave ID must be 1 to 63")
            return

        if not 1 <= slave_id <= 63:
            self.add_terminal_message("Slave ID must be 1 to 63")
            return

        self.add_terminal_message(
            f"RTU settings applied | Slave ID: {slave_id} | "
            f"Baud Rate: {self._baud.currentText()}"
        )

        self.add_terminal_message(
            f"COM Port: {self._com_port.currentText()}"
        )

    def handle_apply_tcp(self):
        ip_text = self._ip_address.text().strip()
        subnet_text = self._subnet.text().strip()
        tcp_port_text = self._tcp_port.text().strip()

        # Validate IPv4 address.
        try:
            ip_address(ip_text)
        except ValueError:
            self.add_terminal_message("Invalid IP Address")
            return

        # Validate subnet mask as a valid IPv4 netmask.
        try:
            ip_network(f"0.0.0.0/{subnet_text}", strict=False)
        except ValueError:
            self.add_terminal_message("Invalid Subnet Mask")
            return

        try:
            tcp_port = int(tcp_port_text)
        except ValueError:
            self.add_terminal_message("TCP Port must be between 1 and 65535")
            return

        if not 1 <= tcp_port <= 65535:
            self.add_terminal_message("TCP Port must be between 1 and 65535")
            return

        command = (
            f"ETH,IP={self._ip_address.text().strip()},"
            f"MASK={self._subnet.text().strip()},"
            f"PORT={tcp_port}\n"
        )

        # Send the TCP/IP command to the selected COM port when connected.
        if (
            self._connect_button.text() == "DISCONNECT"
            and self._com_port.currentText().strip()
        ):
            try:
                import serial

                with serial.Serial(
                    self._com_port.currentText().strip(),
                    int(self._baud.currentText()),
                    timeout=1
                ) as ser:
                    ser.write(command.encode("ascii"))
                self.add_terminal_message("Settings applied")
            except Exception as exc:
                self.add_terminal_message(f"Failed to send settings: {exc}")
        else:
            self.add_terminal_message("COM Port not connected")

    def handle_apply_port1(self):
        command = f"UART,CH=1,BAUD={self._port1.currentText()}\n"

        if (
            self._connect_button.text() == "DISCONNECT"
            and self._com_port.currentText().strip()
        ):
            try:
                import serial

                with serial.Serial(
                    self._com_port.currentText().strip(),
                    int(self._baud.currentText()),
                    timeout=1
                ) as ser:
                    ser.write(command.encode("ascii"))
                self.add_terminal_message("Settings applied")
            except Exception as exc:
                self.add_terminal_message(f"Failed to send settings: {exc}")
        else:
            self.add_terminal_message("COM Port not connected")

    def handle_apply_port2(self):
        command = f"UART,CH=2,BAUD={self._port2.currentText()}\n"

        if (
            self._connect_button.text() == "DISCONNECT"
            and self._com_port.currentText().strip()
        ):
            try:
                import serial

                with serial.Serial(
                    self._com_port.currentText().strip(),
                    int(self._baud.currentText()),
                    timeout=1
                ) as ser:
                    ser.write(command.encode("ascii"))
                self.add_terminal_message("Settings applied")
            except Exception as exc:
                self.add_terminal_message(f"Failed to send settings: {exc}")
        else:
            self.add_terminal_message("COM Port not connected")

    def handle_refresh(self):
        self.refresh_com_ports()

        self.terminal_messages.clear()
        self.terminal_message.setPlainText("Device Terminal Ready")

        ports = [
            self._com_port.itemText(i)
            for i in range(self._com_port.count())
        ]

        if ports:
            self.add_terminal_message(
                "Refresh completed | COM Port detected: " + ", ".join(ports)
            )
        else:
            self.add_terminal_message(
                "Refresh completed | COM Port not connected"
            )

    def refresh_com_ports(self):
        ports = sorted(
            [port.device for port in list_ports.comports()],
            key=lambda value: (
                not value.upper().startswith("COM"),
                int(value[3:])
                if value.upper().startswith("COM")
                and value[3:].isdigit()
                else value.upper()
            )
        )

        current_port = self.com_port.currentText()

        self.com_port.blockSignals(True)
        self.com_port.clear()
        self.com_port.addItems(ports)

        if current_port in ports:
            self.com_port.setCurrentText(current_port)

        self.com_port.blockSignals(False)

        # Always show the COM Port box so the user can manually select
        # any currently connected COM port.
        self.com_port_label.setVisible(True)
        self.com_port.setVisible(True)

