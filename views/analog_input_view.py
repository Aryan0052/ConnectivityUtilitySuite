import os

from PySide6.QtCore import Signal, Qt, QPoint, QTimer, QEvent
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


class AnalogInputView(QWidget):

    back_clicked = Signal()

    def __init__(self):
        super().__init__()

        self._serial_connection = None
        self._apply_pending = False
        self._apply_buffer = bytearray()
        self._apply_timer = QTimer(self)
        self._apply_timer.timeout.connect(self._check_apply_response)
        self._apply_elapsed = 0

        self._refresh_pending = False
        self._refresh_buffer = bytearray()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._check_refresh_response)
        self._refresh_elapsed = 0

        self.terminal_messages = ["Device Terminal Ready"]

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

        self.terminal_message = QPlainTextEdit()
        self.terminal_message.setReadOnly(True)
        self.terminal_message.setFixedHeight(180)
        self.terminal_message.setFont(QFont("Cambria", 12))
        self.terminal_message.setPlainText("Device Terminal Ready")
        left_layout.addWidget(self.terminal_message)

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

        # ---------------------------------------------------------
        # ANALOG INPUT CHANNELS
        # ---------------------------------------------------------
        channel_title = QLabel("Analog Input Channel")
        channel_title.setObjectName("channelTitle")
        channel_title.setAlignment(Qt.AlignCenter)
        right_layout.addWidget(channel_title)
        right_layout.addSpacing(10)

        self._channel_selectors = []
        self._channel_rows = []

        for channel in range(1, 9):
            channel_box = QComboBox()
            channel_box.setObjectName("channelButton")
            channel_box.addItem(f"Analog Input Channel - {channel}")
            channel_box.setCurrentIndex(0)
            channel_box.setStyleSheet("font-size: 14px;")
            channel_box.setFixedSize(210, 30)
            channel_box.installEventFilter(self)

            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addStretch()
            row.addWidget(channel_box)
            row.addStretch()
            right_layout.addLayout(row)
            right_layout.addSpacing(7)
            self._channel_selectors.append(channel_box)
            self._channel_rows.append(row)

        # ---------------------------------------------------------
        # CHANNEL CONFIGURATION BOX
        # ---------------------------------------------------------
        self._channel_config_frame = QFrame()
        self._channel_config_frame.setObjectName("configFrame")
        self._channel_config_frame.setFixedSize(230, 150)
        self._channel_config_frame.setVisible(False)

        config_layout = QVBoxLayout(self._channel_config_frame)
        config_layout.setContentsMargins(10, 8, 10, 8)
        config_layout.setSpacing(7)

        input_row = QHBoxLayout()
        input_label = QLabel("I/P Type")
        input_label.setObjectName("smallLabel")

        self._input_type = QComboBox()
        self._input_type.addItems([
            "0-50mV",
            "0-100mV",
            "0-250mV",
            "0-5V",
            "0-10V",
            "-250mV to +250mV",
            "-10V to +10V",
            "4-20mA",
            "0-20mA",
        ])
        self._input_type.setFixedHeight(30)
        input_row.addWidget(input_label)
        input_row.addWidget(self._input_type)
        config_layout.addLayout(input_row)

        min_row = QHBoxLayout()
        min_label = QLabel("Min off set range")
        min_label.setObjectName("smallLabel")
        self._min_offset = QLineEdit()
        self._min_offset.setFixedWidth(75)
        self._min_offset.setFixedHeight(28)
        min_row.addWidget(min_label)
        min_row.addStretch()
        min_row.addWidget(self._min_offset)
        config_layout.addLayout(min_row)

        max_row = QHBoxLayout()
        max_label = QLabel("Max off set range")
        max_label.setObjectName("smallLabel")
        self._max_offset = QLineEdit()
        self._max_offset.setFixedWidth(75)
        self._max_offset.setFixedHeight(28)
        max_row.addWidget(max_label)
        max_row.addStretch()
        max_row.addWidget(self._max_offset)
        config_layout.addLayout(max_row)

        ok_row = QHBoxLayout()
        ok_row.addStretch()
        ok_button = QPushButton("OK")
        ok_button.setObjectName("okButton")
        ok_button.setFixedSize(45, 28)
        ok_button.setStyleSheet("""
            QPushButton {
                background: #168BA4;
                color: white;
                border: none;
                border-radius: 8px;
                font-family: Cambria;
                font-size: 13px;
                font-weight: bold;
            }
        """)
        ok_row.addWidget(ok_button)
        config_layout.addLayout(ok_row)

        config_row = QHBoxLayout()
        config_row.setContentsMargins(0, 0, 0, 0)
        config_row.addStretch()
        config_row.addWidget(self._channel_config_frame)
        config_row.addStretch()
        right_layout.addLayout(config_row)

        right_layout.addStretch()

        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_panel, 1)

        root.addWidget(main, 1)
        main_layout.addWidget(right_panel, 1)

        root.addWidget(main, 1)

        self._status = status
        self._connect_button = connect
        self._slave_id = slave_id
        self._baud = baud
        self.connect_button = connect
        self.slave_id = slave_id
        self.baud_rate = baud
        self.apply_button = apply_button
        self.refresh_button = refresh
        self.back_button = back

        self.back_button.clicked.connect(self.handle_back)
        self.connect_button.clicked.connect(self.handle_connect)
        self.apply_button.clicked.connect(self.handle_apply_rtu)
        self.refresh_button.clicked.connect(self.handle_refresh)

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
            self._status.setText("COM Port Not Found")
            return

        from PySide6.QtWidgets import QDialog

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
                self._status.setText("COM Port Not Found")
                return

            try:
                import serial

                self._serial_connection = serial.Serial(
                    selected_port,
                    int(self._baud.currentText()),
                    timeout=1
                )

                self._status.setText("Connected")
                self._status.setStyleSheet(
                    "color: #00C928; font-weight: bold; font-size: 16px;"
                )
                self._connect_button.setText("DISCONNECT")
                dialog.accept()

            except Exception:
                self._serial_connection = None
                self._status.setText("Connection Error")
                self._connect_button.setText("CONNECT")
                dialog.reject()

        connect_button.clicked.connect(connect_selected)
        cancel_button.clicked.connect(dialog.reject)
        dialog.exec()

    def handle_connect(self):
        if self._connect_button.text() == "DISCONNECT":
            self._apply_pending = False
            self._apply_timer.stop()
            self._apply_buffer.clear()

            self._refresh_pending = False
            self._refresh_timer.stop()
            self._refresh_buffer.clear()

            try:
                if self._serial_connection is not None:
                    self._serial_connection.close()
            finally:
                self._serial_connection = None

            self._status.setText("Not Connected")
            self._status.setStyleSheet(
                "color: #10C51F; font-weight: bold; font-size: 16px;"
            )
            self._connect_button.setText("CONNECT")
            return

        self.show_com_port_popup()

    def handle_apply_rtu(self):
        if (
            self._connect_button.text() != "DISCONNECT"
            or self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            self._status.setText("COM Port not connected")
            return

        slave_text = self._slave_id.text().strip()

        try:
            slave_id = int(slave_text)
        except ValueError:
            self._status.setText("Slave ID must be 1 to 63")
            return

        if not 1 <= slave_id <= 63:
            self._status.setText("Slave ID must be 1 to 63")
            return

        baud_rate = self._baud.currentText()
        command = f"SID={slave_id},MBD_BAUD={baud_rate}\n"

        if self._apply_pending:
            return

        try:
            self._serial_connection.reset_input_buffer()
            self._apply_buffer.clear()
            self._serial_connection.write(command.encode("ascii"))
            self._serial_connection.flush()

            self._apply_pending = True
            self._apply_elapsed = 0
            self._apply_timer.start(20)

        except Exception:
            self._apply_pending = False
            self._apply_timer.stop()
            self._apply_buffer.clear()
            self._status.setText("RTU Settings Not Applied")
            self._status.setStyleSheet(
                "color: #D00000; font-weight: bold; font-size: 16px;"
            )

    def _check_apply_response(self):
        if not self._apply_pending:
            self._apply_timer.stop()
            return

        if (
            self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            self._apply_pending = False
            self._apply_timer.stop()
            self._apply_buffer.clear()
            return

        try:
            waiting = self._serial_connection.in_waiting

            if waiting > 0:
                self._apply_buffer.extend(
                    self._serial_connection.read(waiting)
                )

            if b"\r\n" in self._apply_buffer:
                response, _, remaining = self._apply_buffer.partition(b"\r\n")
                complete_response = response + b"\r\n"
                self._apply_buffer = bytearray(remaining)

                if complete_response == b"OK:Settings Updated\r\n":
                    self._apply_pending = False
                    self._apply_timer.stop()
                    self._apply_buffer.clear()

                    self.add_terminal_message("OK: Settings Applied")

                    self._status.setText("RTU Settings Applied")
                    self._status.setStyleSheet(
                        "color: #00C928; font-weight: bold; font-size: 16px;"
                    )
                    return

                self._apply_pending = False
                self._apply_timer.stop()
                self._apply_buffer.clear()
                self._status.setText("RTU Settings Not Applied")
                self._status.setStyleSheet(
                    "color: #D00000; font-weight: bold; font-size: 16px;"
                )
                return

            self._apply_elapsed += 20

            if self._apply_elapsed >= 2000:
                self._apply_pending = False
                self._apply_timer.stop()
                self._apply_buffer.clear()
                self._status.setText("RTU Settings Not Applied")
                self._status.setStyleSheet(
                    "color: #D00000; font-weight: bold; font-size: 16px;"
                )

        except Exception:
            self._apply_pending = False
            self._apply_timer.stop()
            self._apply_buffer.clear()
            self._status.setText("RTU Settings Not Applied")
            self._status.setStyleSheet(
                "color: #D00000; font-weight: bold; font-size: 16px;"
            )

    def handle_refresh(self):
        if (
            self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            self._status.setText("COM Port Not Connected")
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
            self._status.setText("Refresh Error")
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
            self._status.setText("COM Port Not Connected")
            return

        try:
            waiting = self._serial_connection.in_waiting

            if waiting > 0:
                self._refresh_buffer.extend(
                    self._serial_connection.read(waiting)
                )

            if b"\r\n" in self._refresh_buffer:
                response_bytes, _, remaining = (
                    self._refresh_buffer.partition(b"\r\n")
                )
                self._refresh_buffer = bytearray(remaining)

                response = (
                    response_bytes + b"\r\n"
                ).decode("ascii", errors="replace").strip()

                if response:
                    self.add_terminal_message(response)

                    parts = response.split(",")

                    if len(parts) == 2:
                        sid_part, baud_part = parts

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
                                    "Configuration Refreshed"
                                )
                                self._status.setStyleSheet(
                                    "color: #00C928; font-weight: bold; font-size: 16px;"
                                )
                                return

                self._refresh_pending = False
                self._refresh_timer.stop()
                self._refresh_buffer.clear()
                self._status.setText("Refresh Error")
                self._status.setStyleSheet(
                    "color: #D00000; font-weight: bold; font-size: 16px;"
                )
                return

            self._refresh_elapsed += 20

            if self._refresh_elapsed >= 2000:
                self._refresh_pending = False
                self._refresh_timer.stop()
                self._refresh_buffer.clear()
                self._status.setText("Refresh Error")
                self._status.setStyleSheet(
                    "color: #D00000; font-weight: bold; font-size: 16px;"
                )

        except Exception:
            self._refresh_pending = False
            self._refresh_timer.stop()
            self._refresh_buffer.clear()
            self._status.setText("Refresh Error")
            self._status.setStyleSheet(
                "color: #D00000; font-weight: bold; font-size: 16px;"
            )

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and obj in self._channel_selectors:
            if obj.isVisible() and self._channel_config_frame.isVisible():
                self.reset_channel_view()
            else:
                self.show_channel_config(obj.currentText())
            return True
        return super().eventFilter(obj, event)

    def show_channel_config(self, channel_name):
        selected_box = None
        for box in self._channel_selectors:
            if box.currentText() == channel_name:
                selected_box = box
                break

        if selected_box is None:
            return

        # Keep only the selected channel visible.
        for box in self._channel_selectors:
            box.setVisible(box is selected_box)

        self._channel_config_frame.setVisible(True)

    def reset_channel_view(self):
        for box in self._channel_selectors:
            box.setVisible(True)
        self._channel_config_frame.setVisible(False)

    def handle_back(self):
        self._apply_pending = False
        self._apply_timer.stop()
        self._apply_buffer.clear()

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

        self.reset_channel_view()

        self._connect_button.setText("CONNECT")
        self._status.setText("Not Connected")
        self._status.setStyleSheet(
            "color: #10C51F; font-weight: bold; font-size: 16px;"
        )

        self.terminal_messages = ["Device Terminal Ready"]
        self.terminal_message.setPlainText("Device Terminal Ready")
