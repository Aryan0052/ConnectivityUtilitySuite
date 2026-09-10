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
    QDialog,
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

        self._serial_connection = None
        self._tcp_apply_pending = False
        self._tcp_apply_buffer = bytearray()
        self._tcp_apply_timer = QTimer(self)
        self._tcp_apply_timer.timeout.connect(self._check_tcp_apply_response)
        self._tcp_apply_elapsed = 0

        self._refresh_pending = False
        self._refresh_buffer = bytearray()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._check_refresh_response)
        self._refresh_elapsed = 0

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
        back.clicked.connect(self.handle_back)

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

        # Keep COM Port as an internal connection value; selection is done in the CONNECT popup.
        com_port = QComboBox()
        com_port.setVisible(False)

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
        left_layout.addWidget(valid_ids)
        left_layout.addWidget(baud_label)
        left_layout.addWidget(baud)
        left_layout.addLayout(apply_row)
        left_layout.addSpacing(8)
        left_layout.addLayout(terminal_row)
        left_layout.addWidget(terminal, 1)

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

        subnet = QLineEdit()
        subnet.setPlaceholderText("255.255.255.0")
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

    def handle_back(self):
        self._tcp_apply_pending = False
        self._tcp_apply_timer.stop()
        self._tcp_apply_buffer.clear()

        self._refresh_pending = False
        self._refresh_timer.stop()
        self._refresh_buffer.clear()

        if self._serial_connection is not None:
            try:
                self._serial_connection.close()
            except Exception:
                pass
            finally:
                self._serial_connection = None

        self._connect_button.setText("CONNECT")
        self._status.setText("● Not Connected")

        self._slave_id.setText("1")
        self._baud.setCurrentText("9600")
        self._ip_address.clear()
        self._subnet.clear()
        self._tcp_port.setText("502")
        self._port1.setCurrentText("9600")
        self._port2.setCurrentText("9600")

        self.terminal_messages = ["Device Terminal Ready"]
        self.terminal_message.setPlainText("Device Terminal Ready")

        self.back_clicked.emit()

    def add_terminal_message(self, message):
        self.terminal_messages.append(str(message))
        self.terminal_message.setPlainText(
            "\n".join(self.terminal_messages)
        )
        scrollbar = self.terminal_message.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def show_com_port_popup(self):
        ports = [port.device for port in list_ports.comports()]

        if not ports:
            self._status.setText("● COM Port Not Found")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("COM Port")
        dialog.setFixedSize(360, 190)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        title = QLabel("Select COM Port")
        title.setFont(QFont("Cambria", 16))
        layout.addWidget(title)

        port_box = QComboBox()
        port_box.addItems(ports)
        port_box.setFont(QFont("Cambria", 16))
        port_box.setFixedHeight(40)
        layout.addWidget(port_box)

        button_row = QHBoxLayout()
        connect_button = QPushButton("CONNECT")
        cancel_button = QPushButton("CANCEL")

        for button in (connect_button, cancel_button):
            button.setFont(QFont("Cambria", 16))
            button.setFixedHeight(38)

        button_row.addWidget(connect_button)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)

        def connect_selected():
            selected_port = port_box.currentText().strip()
            if not selected_port:
                dialog.reject()
                self._status.setText("● COM Port Not Found")
                return

            self._com_port.setCurrentText(selected_port)

            try:
                import serial

                self._serial_connection = serial.Serial(
                    selected_port,
                    int(self._baud.currentText()),
                    timeout=1
                )
                self._status.setText("● Connected")
                self._status.setStyleSheet(
                    "color: #00C928; font-weight: bold; font-size: 16px;"
                )
                self._connect_button.setText("DISCONNECT")
                dialog.accept()
            except Exception:
                self._serial_connection = None
                self._status.setText("● Connection Error")
                self._connect_button.setText("CONNECT")
                dialog.reject()

        connect_button.clicked.connect(connect_selected)
        cancel_button.clicked.connect(dialog.reject)
        dialog.exec()

    def handle_connect(self):
        if self._connect_button.text() == "DISCONNECT":
            self._tcp_apply_pending = False
            self._tcp_apply_timer.stop()
            self._tcp_apply_buffer.clear()

            self._refresh_pending = False
            self._refresh_timer.stop()
            self._refresh_buffer.clear()

            try:
                if self._serial_connection is not None:
                    self._serial_connection.close()
            finally:
                self._serial_connection = None

            self._status.setText("● Not Connected")
            self._status.setStyleSheet(
                "color: #00C928; font-weight: bold; font-size: 16px;"
            )
            self._connect_button.setText("CONNECT")
            return

        self.show_com_port_popup()

    def handle_apply_rtu(self):
        # RTU settings can only be applied after a COM port is connected.
        if (
            self._connect_button.text() != "DISCONNECT"
            or not self._com_port.currentText().strip()
        ):
            self._status.setText("● COM Port not connected")
            return

        slave_text = self._slave_id.text().strip()

        try:
            slave_id = int(slave_text)
        except ValueError:
            self._status.setText("● Slave ID must be 1 to 63")
            return

        if not 1 <= slave_id <= 63:
            self._status.setText("● Slave ID must be 1 to 63")
            return

        baud_rate = self._baud.currentText()
        command = f"SID={slave_id},MBD_BAUD={baud_rate}\n"

        try:
            if (
                self._serial_connection is None
                or not self._serial_connection.is_open
            ):
                self._status.setText("● COM Port not connected")
                return

            self._serial_connection.reset_input_buffer()
            self._serial_connection.write(command.encode("ascii"))
            self._serial_connection.flush()

            response_buffer = bytearray()
            elapsed = [0]

            def set_failed():
                self._status.setText("● RTU Settings Not Applied")
                self._status.setStyleSheet(
                    "color: #D00000; font-weight: bold; font-size: 16px;"
                )

            def check_rtu_response():
                if (
                    self._serial_connection is None
                    or not self._serial_connection.is_open
                ):
                    set_failed()
                    return

                try:
                    waiting = self._serial_connection.in_waiting
                    if waiting > 0:
                        response_buffer.extend(
                            self._serial_connection.read(waiting)
                        )

                    # Wait for the complete device response. Serial data
                    # may arrive in multiple reads/chunks.
                    if b"\r\n" in response_buffer:
                        response, _, remaining = response_buffer.partition(
                            b"\r\n"
                        )
                        complete_response = response + b"\r\n"
                        response_buffer.clear()
                        response_buffer.extend(remaining)

                        # The actual RTU APPLY confirmation from the device is:
                        # OK:Settings Updated\r\n
                        if complete_response == b"OK:Settings Updated\r\n":
                            self.add_terminal_message("OK: Settings Applied")
                            self._status.setText("● RTU Settings Applied")
                            self._status.setStyleSheet(
                                "color: #00C928; font-weight: bold; font-size: 16px;"
                            )
                            return

                        set_failed()
                        return

                    elapsed[0] += 20
                    if elapsed[0] >= 2000:
                        set_failed()
                        return

                    QTimer.singleShot(20, check_rtu_response)

                except Exception:
                    set_failed()

            QTimer.singleShot(20, check_rtu_response)

        except Exception:
            self._status.setText("● RTU Settings Not Applied")
            self._status.setStyleSheet(
                "color: #D00000; font-weight: bold; font-size: 16px;"
            )


    def handle_apply_tcp(self):
        ip_text = self._ip_address.text().strip()
        subnet_text = self._subnet.text().strip()
        tcp_port_text = self._tcp_port.text().strip()

        try:
            ip_address(ip_text)
        except ValueError:
            self._status.setText("● Invalid IP Address")
            return

        try:
            ip_network(f"0.0.0.0/{subnet_text}", strict=False)
        except ValueError:
            self._status.setText("● Invalid Subnet Mask")
            return

        try:
            tcp_port = int(tcp_port_text)
        except ValueError:
            self._status.setText("● TCP Port must be between 1 and 65535")
            return

        if not 1 <= tcp_port <= 65535:
            self._status.setText("● TCP Port must be between 1 and 65535")
            return

        if (
            self._connect_button.text() != "DISCONNECT"
            or self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            self._status.setText("● COM Port not connected")
            self._status.setStyleSheet(
                "color: #D00000; font-weight: bold; font-size: 16px;"
            )
            return

        if self._tcp_apply_pending:
            return

        command = (
            f"ETH,IP={ip_text},"
            f"MASK={subnet_text},"
            f"PORT={tcp_port}\n"
        )

        try:
            self._serial_connection.reset_input_buffer()
            self._tcp_apply_buffer.clear()
            self._serial_connection.write(command.encode("ascii"))
            self._serial_connection.flush()

            self._tcp_apply_pending = True
            self._tcp_apply_elapsed = 0
            self._tcp_apply_timer.start(20)
        except Exception as exc:
            self._tcp_apply_pending = False
            self._tcp_apply_timer.stop()
            self._status.setText("● TCP/IP Configuration failed")
            self._status.setStyleSheet(
                "color: #D00000; font-weight: bold; font-size: 16px;"
            )

    def _check_tcp_apply_response(self):
        if not self._tcp_apply_pending:
            self._tcp_apply_timer.stop()
            return

        if (
            self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            # Disconnect must cancel a pending APPLY, not report a fake failure.
            self._tcp_apply_pending = False
            self._tcp_apply_timer.stop()
            self._tcp_apply_buffer.clear()
            return

        try:
            waiting = self._serial_connection.in_waiting

            if waiting > 0:
                self._tcp_apply_buffer.extend(
                    self._serial_connection.read(waiting)
                )

            buffer_text = self._tcp_apply_buffer.decode(
                "ascii", errors="replace"
            )

            # Device confirmation can arrive in chunks and does not have to
            # be received in exactly one serial read.
            if "OK:ETH" in buffer_text:
                self._tcp_apply_pending = False
                self._tcp_apply_timer.stop()
                self._tcp_apply_buffer.clear()

                self.add_terminal_message("OK:ETH")
                self._status.setText("● TCP/IP Configuration applied")
                self._status.setStyleSheet(
                    "color: #00C928; font-weight: bold; font-size: 16px;"
                )
                return

            if "ERR:CMD" in buffer_text:
                self._tcp_apply_pending = False
                self._tcp_apply_timer.stop()
                self._tcp_apply_buffer.clear()

                self._status.setText("● TCP/IP Configuration failed")
                self._status.setStyleSheet(
                    "color: #D00000; font-weight: bold; font-size: 16px;"
                )
                return

            # Also accept a complete non-empty device response.
            if b"\n" in self._tcp_apply_buffer:
                response_bytes, _, remaining = (
                    self._tcp_apply_buffer.partition(b"\n")
                )
                self._tcp_apply_buffer = bytearray(remaining)
                response = response_bytes.decode(
                    "ascii", errors="replace"
                ).strip()

                if response:
                    self._tcp_apply_pending = False
                    self._tcp_apply_timer.stop()

                    self._status.setText("● TCP/IP Configuration failed")
                    self._status.setStyleSheet(
                        "color: #D00000; font-weight: bold; font-size: 16px;"
                    )
                    return

            # Wait only 2 seconds for the device response.
            self._tcp_apply_elapsed += 20
            if self._tcp_apply_elapsed >= 2000:
                self._tcp_apply_pending = False
                self._tcp_apply_timer.stop()
                self._tcp_apply_buffer.clear()

                self._status.setText("● TCP/IP Configuration failed")
                self._status.setStyleSheet(
                    "color: #D00000; font-weight: bold; font-size: 16px;"
                )

        except Exception as exc:
            self._tcp_apply_pending = False
            self._tcp_apply_timer.stop()
            self._tcp_apply_buffer.clear()
            self._status.setText("● TCP/IP Configuration failed")
            self._status.setStyleSheet(
                "color: #D00000; font-weight: bold; font-size: 16px;"
            )

    def handle_apply_port1(self):
        command = f"UART,CH=1,BAUD={self._port1.currentText()}\\n"

        if (
            self._connect_button.text() != "DISCONNECT"
            or self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            self._status.setText("● COM Port not connected")
            self._status.setStyleSheet(
                "color: #D00000; font-weight: bold; font-size: 16px;"
            )
            return

        try:
            self._serial_connection.reset_input_buffer()
            self._serial_connection.write(command.encode("ascii"))
            self._serial_connection.flush()

            response_buffer = bytearray()
            elapsed = [0]

            def set_port1_failed():
                self._status.setText("● Port 1 Settings Not Applied")
                self._status.setStyleSheet(
                    "color: #D00000; font-weight: bold; font-size: 16px;"
                )

            def check_port1_response():
                if (
                    self._serial_connection is None
                    or not self._serial_connection.is_open
                ):
                    set_port1_failed()
                    return

                try:
                    waiting = self._serial_connection.in_waiting
                    if waiting > 0:
                        response_buffer.extend(
                            self._serial_connection.read(waiting)
                        )

                    # RX may arrive in multiple chunks.
                    if b"OK:ETH" in response_buffer:
                        self.add_terminal_message("OK:ETH")
                        self._status.setText("● Port 1 Settings Applied")
                        self._status.setStyleSheet(
                            "color: #00C928; font-weight: bold; font-size: 16px;"
                        )
                        return

                    if b"\\n" in response_buffer:
                        set_port1_failed()
                        return

                    elapsed[0] += 20
                    if elapsed[0] >= 2000:
                        set_port1_failed()
                        return

                    QTimer.singleShot(20, check_port1_response)

                except Exception:
                    set_port1_failed()

            QTimer.singleShot(20, check_port1_response)

        except Exception:
            set_port1_failed()

    def handle_apply_port2(self):
        command = f"UART,CH=2,BAUD={self._port2.currentText()}\\n"

        if (
            self._connect_button.text() != "DISCONNECT"
            or self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            self._status.setText("● COM Port not connected")
            self._status.setStyleSheet(
                "color: #D00000; font-weight: bold; font-size: 16px;"
            )
            return

        try:
            self._serial_connection.reset_input_buffer()
            self._serial_connection.write(command.encode("ascii"))
            self._serial_connection.flush()

            response_buffer = bytearray()
            elapsed = [0]

            def set_port2_failed():
                self._status.setText("● Port 2 Settings Not Applied")
                self._status.setStyleSheet(
                    "color: #D00000; font-weight: bold; font-size: 16px;"
                )

            def check_port2_response():
                if (
                    self._serial_connection is None
                    or not self._serial_connection.is_open
                ):
                    set_port2_failed()
                    return

                try:
                    waiting = self._serial_connection.in_waiting
                    if waiting > 0:
                        response_buffer.extend(
                            self._serial_connection.read(waiting)
                        )

                    # RX may arrive in multiple chunks.
                    if b"OK:ETH" in response_buffer:
                        self.add_terminal_message("OK:ETH")
                        self._status.setText("● Port 2 Settings Applied")
                        self._status.setStyleSheet(
                            "color: #00C928; font-weight: bold; font-size: 16px;"
                        )
                        return

                    if b"\\n" in response_buffer:
                        set_port2_failed()
                        return

                    elapsed[0] += 20
                    if elapsed[0] >= 2000:
                        set_port2_failed()
                        return

                    QTimer.singleShot(20, check_port2_response)

                except Exception:
                    set_port2_failed()

            QTimer.singleShot(20, check_port2_response)

        except Exception:
            set_port2_failed()

    def handle_refresh(self):
        if (
            self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            self._refresh_pending = False
            self._refresh_timer.stop()
            self._refresh_buffer.clear()
            self._status.setText("● COM Port Not Connected")
            return

        if self._refresh_pending:
            return

        try:
            self._serial_connection.reset_input_buffer()
            self._refresh_buffer.clear()

            self._serial_connection.write(b"GETCFG\n")
            self._serial_connection.flush()

            self._refresh_pending = True
            self._refresh_elapsed = 0
            self._refresh_timer.start(20)
        except Exception:
            self._refresh_pending = False
            self._refresh_timer.stop()
            self._refresh_buffer.clear()
            self._status.setText("● Refresh Error")
            self._status.setStyleSheet(
                "color: #D00000; font-weight: bold; font-size: 16px;"
            )

    def _check_refresh_response(self):
        if not self._refresh_pending:
            self._refresh_timer.stop()
            return

        if (
            self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            self._refresh_pending = False
            self._refresh_timer.stop()
            self._refresh_buffer.clear()
            self._status.setText("● COM Port Not Connected")
            return

        try:
            waiting = self._serial_connection.in_waiting

            if waiting > 0:
                self._refresh_buffer.extend(
                    self._serial_connection.read(waiting)
                )

            if b"\n" in self._refresh_buffer:
                response_bytes, _, remaining = (
                    self._refresh_buffer.partition(b"\n")
                )
                self._refresh_buffer = bytearray(remaining)

                response = response_bytes.decode(
                    "ascii", errors="replace"
                ).strip()

                if response:
                    # Keep the actual device RX visible exactly as received.
                    self.add_terminal_message(response)

                    parts = response.split(",")

                    # TCP/IP GETCFG response:
                    # IP=...,MASK=...,PORT=...
                    if len(parts) == 3:
                        ip_part = parts[0]
                        mask_part = parts[1]
                        port_part = parts[2]

                        if (
                            ip_part.startswith("IP=")
                            and mask_part.startswith("MASK=")
                            and port_part.startswith("PORT=")
                        ):
                            ip_text = ip_part[3:].strip()
                            mask_text = mask_part[5:].strip()
                            port_text = port_part[5:].strip()

                            try:
                                parsed_ip = ip_address(ip_text)
                                ip_network(
                                    f"0.0.0.0/{mask_text}",
                                    strict=False
                                )
                                parsed_port = int(port_text)
                            except ValueError:
                                parsed_ip = None
                                parsed_port = None

                            if (
                                parsed_ip is not None
                                and parsed_ip.version == 4
                                and parsed_port is not None
                                and 1 <= parsed_port <= 65535
                            ):
                                self._ip_address.setText(ip_text)
                                self._subnet.setText(mask_text)
                                self._tcp_port.setText(port_text)

                                self._refresh_pending = False
                                self._refresh_timer.stop()
                                self._refresh_buffer.clear()
                                self._status.setText(
                                    "● Configuration Refreshed"
                                )
                                self._status.setStyleSheet(
                                    "color: #00C928; font-weight: bold; "
                                    "font-size: 16px;"
                                )
                                return

                    # RTU GETCFG response from the device:
                    # SID=...,BAUD=...
                    if len(parts) == 2:
                        sid_part = parts[0]
                        baud_part = parts[1]

                        if (
                            sid_part.startswith("SID=")
                            and baud_part.startswith("BAUD=")
                        ):
                            slave_text = sid_part[4:].strip()
                            baud_text = baud_part[5:].strip()

                            try:
                                parsed_slave_id = int(slave_text)
                                parsed_baud = int(baud_text)
                            except ValueError:
                                parsed_slave_id = None
                                parsed_baud = None

                            if (
                                parsed_slave_id is not None
                                and 1 <= parsed_slave_id <= 63
                                and parsed_baud is not None
                                and self._baud.findText(baud_text) >= 0
                            ):
                                self._slave_id.setText(slave_text)
                                self._baud.setCurrentText(baud_text)

                                self._refresh_pending = False
                                self._refresh_timer.stop()
                                self._refresh_buffer.clear()
                                self._status.setText(
                                    "● Configuration Refreshed"
                                )
                                self._status.setStyleSheet(
                                    "color: #00C928; font-weight: bold; "
                                    "font-size: 16px;"
                                )
                                return

                    self._refresh_pending = False
                    self._refresh_timer.stop()
                    self._refresh_buffer.clear()
                    self._status.setText("● Refresh Error")
                    self._status.setStyleSheet(
                        "color: #D00000; font-weight: bold; font-size: 16px;"
                    )
                    return

            self._refresh_elapsed += 20
            if self._refresh_elapsed >= 2000:
                self._refresh_pending = False
                self._refresh_timer.stop()
                self._refresh_buffer.clear()
                self._status.setText("● Refresh Error")
                self._status.setStyleSheet(
                    "color: #D00000; font-weight: bold; font-size: 16px;"
                )

        except Exception:
            self._refresh_pending = False
            self._refresh_timer.stop()
            self._refresh_buffer.clear()
            self._status.setText("● Refresh Error")
            self._status.setStyleSheet(
                "color: #D00000; font-weight: bold; font-size: 16px;"
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

        # COM Port selection is handled from the CONNECT popup.
        self.com_port.setVisible(False)