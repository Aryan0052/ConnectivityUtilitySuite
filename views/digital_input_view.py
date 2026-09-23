from pathlib import Path

from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QTimer
from PySide6.QtGui import (
    QPainter,
    QPen,
    QBrush,
    QPixmap,
    QPolygonF,
    QFont,
)
from serial.tools import list_ports

from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QPlainTextEdit,
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


class DigitalInputView(QWidget):

    back_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName(
            "digitalInputView"
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

        self._serial_connection = None
        self._connected_baud_rate = None
        self._apply_target_baud_rate = None
        self._apply_baud_timer = QTimer(self)
        self._apply_baud_timer.setSingleShot(True)
        self._apply_baud_timer.timeout.connect(self._switch_to_applied_baud)
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

        self._run_active = False
        self._run_waiting_rx = False
        self._run_buffer = bytearray()
        self._run_elapsed = 0
        self._run_timer = QTimer(self)
        self._run_timer.timeout.connect(self._run_tx_rx_cycle)

        self._connection_monitor_timer = QTimer(self)
        self._connection_monitor_timer.timeout.connect(
            self._check_connection_status
        )
        self._connection_monitor_timer.start(500)

        self.terminal_messages = ["Device Terminal Ready"]

        self.build_ui()

    def build_ui(self):

        self.setStyleSheet("""
            QWidget#digitalInputView {
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

            QComboBox QAbstractItemView {
                background: #F1F5F2;
                color: #333333;
                border: 1px solid #C8CFCC;
                selection-background-color: #DDEBE6;
                selection-color: #222222;
                font-family: Cambria;
                font-size: 16px;
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

            QPushButton#run {
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

            QPushButton#run:hover {
                background: #16839F;
            }

            QPushButton#run:pressed {
                background: #14738A;
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
            0,
            0,
            0,
            0
        )

        root_layout.setSpacing(0)

        # HEADER
        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(88)

        header_layout = QHBoxLayout(header)

        header_layout.setContentsMargins(
            20,
            5,
            20,
            5
        )

        header_layout.setSpacing(0)

        # Logo
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

        header_layout.addWidget(logo)

        # Header text
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

        # Back
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

        left_layout = QVBoxLayout(left)

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

        # Digital Input timeout message shown directly below CONNECT.
        self.digital_input_timeout_label = QLabel("Digital Input Timeout")
        self.digital_input_timeout_label.setAlignment(Qt.AlignCenter)
        self.digital_input_timeout_label.setStyleSheet(
            "color: #D00000; background: transparent; font-family: Cambria; font-size: 15px; font-weight: bold;"
        )
        self.digital_input_timeout_label.hide()
        left_layout.addWidget(self.digital_input_timeout_label)

        left_layout.addSpacing(25)

        # STATUS
        status_layout = QHBoxLayout()

        status_dot = QLabel("●")

        status_dot.setStyleSheet("""
            QLabel {
                color: #13D324;
                background: transparent;
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
            "Digital Input"
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
                font-size: 16px;
            }
        """)

        left_layout.addWidget(
            valid
        )

        left_layout.addSpacing(24)

        # BAUD
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
                font-size: 16px;
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
            180
        )

        terminal_layout = QVBoxLayout(terminal)
        terminal_layout.setContentsMargins(6, 6, 6, 6)
        terminal_layout.setSpacing(0)

        self.terminal_message = QPlainTextEdit()
        self.terminal_message.setReadOnly(True)
        self.terminal_message.setFocusPolicy(Qt.NoFocus)
        self.terminal_message.setPlainText("Device Terminal Ready")
        self.terminal_message.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.terminal_message.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.terminal_message.setStyleSheet("""
            QPlainTextEdit {
                background: #F1F5F2;
                color: #111111;
                border: none;
                padding: 2px 4px;
                font-family: Cambria;
                font-size: 12px;
            }
        """)
        terminal_layout.addWidget(self.terminal_message)

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

        # DIGITAL INPUT CHANNELS
        right_layout.setSpacing(0)

        channel_title = QLabel("Digital Input")
        channel_title.setAlignment(Qt.AlignCenter)
        channel_title.setFixedSize(265, 30)
        channel_title.setStyleSheet("""
            QLabel {
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
                border-radius: 6px;
                font-family: Cambria;
                font-size: 22px;
                font-weight: normal;
            }
        """)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.addStretch()
        title_row.addWidget(channel_title)
        title_row.addStretch()
        right_layout.addLayout(title_row)
        right_layout.addSpacing(20)

        channel_columns = QHBoxLayout()
        channel_columns.setContentsMargins(48, 0, 48, 0)
        channel_columns.setSpacing(55)

        left_channels = QVBoxLayout()
        left_channels.setSpacing(30)
        right_channels = QVBoxLayout()
        right_channels.setSpacing(30)

        self._di_buttons = []

        def add_channel_row(layout, channel):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(44)

            led = QLabel()
            led.setFixedSize(41, 41)
            led.setStyleSheet("""
                QLabel {
                    background: #E00000;
                    border: 1px solid #222222;
                    border-radius: 11px;
                }
            """)

            label = QLabel(f"DI-{channel}")
            label.setAlignment(Qt.AlignCenter)
            label.setFixedSize(83, 30)
            label.setStyleSheet("""
                QLabel {
                    background: #F1F5F2;
                    color: #111111;
                    border: 1px solid #BFC4C1;
                    border-radius: 8px;
                    font-family: Cambria;
                    font-size: 15px;
                }
            """)

            row.addWidget(led)
            row.addWidget(label)
            row.addStretch()
            layout.addLayout(row)
            self._di_buttons.append(led)

        for channel in range(1, 9):
            add_channel_row(left_channels, channel)

        for channel in range(9, 17):
            add_channel_row(right_channels, channel)

        channel_columns.addLayout(left_channels)
        channel_columns.addLayout(right_channels)
        right_layout.addLayout(channel_columns)
        right_layout.addStretch()

        run_layout = QHBoxLayout()
        run_layout.addStretch()

        self.run_button = QPushButton("RUN")
        self.run_button.setObjectName("run")
        self.run_button.setFixedSize(135, 31)
        self.run_button.setCursor(Qt.PointingHandCursor)

        run_layout.addWidget(self.run_button)
        run_layout.addStretch()

        right_layout.addLayout(run_layout)
        right_layout.addSpacing(20)

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

        # Keep references for RTU actions.
        self._status = status
        self._status_dot = status_dot
        self._connect_button = self.connect_button
        self._slave_id = self.slave_id
        self._baud = self.baud_rate

        # BACK NAVIGATION
        self.back_button.clicked.connect(
            self.handle_back
        )
        self.connect_button.clicked.connect(
            self.handle_connect
        )
        self.apply_button.clicked.connect(
            self.handle_apply_rtu
        )
        self.refresh_button.clicked.connect(
            self.handle_refresh
        )
        self.run_button.clicked.connect(
            self.handle_run
        )

    def add_terminal_message(self, message):
        self.terminal_messages.append(str(message))
        self.terminal_message.setPlainText(
            "\n".join(self.terminal_messages)
        )
        scrollbar = self.terminal_message.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    
    def _set_status_color(self, color):
        self._status.setStyleSheet(
            f"color: {color}; font-weight: bold; font-size: 16px;"
        )
        if hasattr(self, "_status_dot"):
            self._status_dot.setStyleSheet(
                f"color: {color}; background: transparent; font-size: 16px;"
            )

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
                self._connected_baud_rate = int(self._baud.currentText())
                self._status.setText("Connected")
                self._set_status_color("#00C928")
                self._connect_button.setText("DISCONNECT")
                dialog.accept()
            except Exception:
                self._serial_connection = None
                self._status.setText("Connection Error")
                self._set_status_color("#D00000")
                self._connect_button.setText("CONNECT")
                dialog.reject()

        connect_button.clicked.connect(connect_selected)
        cancel_button.clicked.connect(dialog.reject)
        dialog.exec()

    def _check_connection_status(self):
        if self._serial_connection is None:
            return

        try:
            current_port = self._serial_connection.port

            if (
                not self._serial_connection.is_open
                or current_port not in {
                    port.device for port in list_ports.comports()
                }
            ):
                print("COM Port disconnected:", current_port)

                self._stop_run()

                self._apply_pending = False
                self._apply_timer.stop()
                self._apply_buffer.clear()

                self._refresh_pending = False
                self._refresh_timer.stop()
                self._refresh_buffer.clear()

                try:
                    self._serial_connection.close()
                except Exception:
                    pass

                self._serial_connection = None
                self._connect_button.setText("CONNECT")
                self._status.setText("COM Port Not Found")
                self._set_status_color("#D00000")

        except Exception:
            self._serial_connection = None
            self._stop_run()
            self._connect_button.setText("CONNECT")
            self._status.setText("COM Port Not Found")
            self._set_status_color("#D00000")

    def handle_connect(self):
        if self._connect_button.text() == "DISCONNECT":
            self._stop_run()
            self._apply_pending = False
            self._apply_timer.stop()
            self._apply_baud_timer.stop()
            self._apply_buffer.clear()
            self._apply_target_baud_rate = None
            self._refresh_pending = False
            self._refresh_timer.stop()
            self._refresh_buffer.clear()

            try:
                if self._serial_connection is not None:
                    self._serial_connection.close()
            finally:
                self._serial_connection = None

            self._status.setText("Not Connected")
            self._set_status_color("#10C51F")
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
            self._set_status_color("#D00000")
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
        target_baud_rate = int(baud_rate)
        command = f"SID={slave_id},MBD_BAUD={baud_rate}\n"

        if self._apply_pending:
            return

        try:
            self._serial_connection.reset_input_buffer()
            self._apply_buffer.clear()

            # Send the settings command using the baud rate currently
            # active on the device. The local baud rate is changed only
            # after the device has had time to process the command.
            self._serial_connection.write(command.encode("ascii"))
            self._serial_connection.flush()
            print(f"RTU SETTINGS TX: SID={slave_id}, BAUD={baud_rate}")

            self._apply_target_baud_rate = target_baud_rate
            self._apply_pending = True
            self._apply_elapsed = 0
            self._apply_timer.start(20)

            if (
                self._connected_baud_rate is not None
                and target_baud_rate != self._connected_baud_rate
            ):
                self._apply_baud_timer.start(150)
        except Exception:
            self._apply_pending = False
            self._apply_timer.stop()
            self._apply_buffer.clear()
            self._status.setText("RTU Settings Not Applied")
            self._set_status_color("#D00000")

    def _switch_to_applied_baud(self):
        if (
            self._serial_connection is None
            or not self._serial_connection.is_open
            or self._apply_target_baud_rate is None
        ):
            return

        try:
            self._serial_connection.baudrate = self._apply_target_baud_rate
            self._connected_baud_rate = self._apply_target_baud_rate
        except Exception:
            pass

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
                chunk = self._serial_connection.read(waiting)
                self._apply_buffer.extend(chunk)
                print(f"RTU SETTINGS RX: {chunk!r}")

            # Wait for the complete response because serial data can arrive
            # in multiple chunks.
            if b"\r\n" in self._apply_buffer:
                response, _, remaining = self._apply_buffer.partition(b"\r\n")
                complete_response = response + b"\r\n"
                self._apply_buffer = bytearray(remaining)

                if complete_response == b"OK:Settings Updated\r\n":
                    self._apply_pending = False
                    self._apply_timer.stop()
                    self._apply_baud_timer.stop()
                    self._apply_target_baud_rate = None
                    self._apply_buffer.clear()
                    self.add_terminal_message("OK: Settings Applied")
                    self._status.setText("RTU Settings Applied")
                    self._set_status_color("#00C928")
                    return

                self._apply_pending = False
                self._apply_timer.stop()
                self._apply_baud_timer.stop()
                self._apply_target_baud_rate = None
                self._apply_buffer.clear()
                self._status.setText("RTU Settings Not Applied")
                self._set_status_color("#D00000")
                return

            self._apply_elapsed += 20
            if self._apply_elapsed >= 2000:
                self._apply_pending = False
                self._apply_timer.stop()
                self._apply_baud_timer.stop()
                self._apply_target_baud_rate = None
                self._apply_buffer.clear()
                self._status.setText("RTU Settings Not Applied")
                self._set_status_color("#D00000")
        except Exception:
            self._apply_pending = False
            self._apply_timer.stop()
            self._apply_baud_timer.stop()
            self._apply_target_baud_rate = None
            self._apply_buffer.clear()
            self._status.setText("RTU Settings Not Applied")
            self._set_status_color("#D00000")

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
            self._set_status_color("#D00000")

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
                response_bytes, _, remaining = self._refresh_buffer.partition(b"\r\n")
                self._refresh_buffer = bytearray(remaining)
                response = (response_bytes + b"\r\n").decode(
                    "ascii", errors="replace"
                ).strip()

                if response:
                    self.add_terminal_message(response)
                    parts = response.split(",")

                    if len(parts) == 2:
                        sid_part, baud_part = parts
                        if sid_part.startswith("SID=") and baud_part.startswith("BAUD="):
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
                                self._status.setText("Configuration Refreshed")
                                self._set_status_color("#00C928")
                                return

                self._refresh_pending = False
                self._refresh_timer.stop()
                self._refresh_buffer.clear()
                self._status.setText("Refresh Error")
                self._set_status_color("#D00000")
                return

            self._refresh_elapsed += 20
            if self._refresh_elapsed >= 2000:
                self._refresh_pending = False
                self._refresh_timer.stop()
                self._refresh_buffer.clear()
                self._status.setText("Refresh Error")
                self._set_status_color("#D00000")
        except Exception:
            self._refresh_pending = False
            self._refresh_timer.stop()
            self._refresh_buffer.clear()
            self._status.setText("Refresh Error")
            self._set_status_color("#D00000")

    def _modbus_crc(self, data):
        crc = 0xFFFF

        for byte in data:
            crc ^= byte

            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1

        return bytes([
            crc & 0xFF,
            (crc >> 8) & 0xFF
        ])

    def handle_run(self):
        if self._run_active:
            print("DI RUN: STOP requested")
            self._stop_run()
            return

        if (
            self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            print("DI RUN: COM Port Not Found")
            self._status.setText("COM Port Not Found")
            return

        print("DI RUN: STARTED")
        print("DI RUN: COM Port:", self._serial_connection.port)
        print("DI RUN: Baud Rate:", self._baud.currentText())

        self.digital_input_timeout_label.hide()
        self._run_active = True
        self._run_waiting_rx = False
        self._run_buffer.clear()
        self._run_elapsed = 0
        self.run_button.setText("STOP")
        self._run_timer.start(20)

    def _stop_run(self):
        print("DI RUN: TX/RX STOPPED")
        self._run_active = False
        self._run_waiting_rx = False
        self._run_buffer.clear()
        self._run_elapsed = 0
        self._run_timer.stop()

        if hasattr(self, "run_button"):
            self.run_button.setText("RUN")

    def _handle_run_com_port_lost(self):
        print("DI RUN: COM PORT LOST - STOPPING")
        self._stop_run()

        try:
            if self._serial_connection is not None:
                self._serial_connection.close()
        except Exception:
            pass
        finally:
            self._serial_connection = None

        self._connect_button.setText("CONNECT")
        self._status.setText("COM Port Not Found")
        self._set_status_color("#D00000")

    def _run_tx_rx_cycle(self):
        if not self._run_active:
            self._run_timer.stop()
            return

        if (
            self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            self._handle_run_com_port_lost()
            return

        try:
            current_port = self._serial_connection.port
            available_ports = {
                port.device for port in list_ports.comports()
            }

            if current_port not in available_ports:
                print("DI RUN: COM Port disappeared:", current_port)
                self._handle_run_com_port_lost()
                return

            # Always read the current Slave ID from RTU Settings.
            slave_id = int(self._slave_id.text().strip())

            if not self._run_waiting_rx:
                # Confirmed Digital Input RUN request:
                # 02 01 00 00 00 10 + Modbus CRC
                request = bytes([
                    slave_id,
                    0x01,
                    0x00, 0x00,
                    0x00, 0x10,
                ])
                command = request + self._modbus_crc(request)

                self._serial_connection.reset_input_buffer()
                self._run_buffer.clear()
                self._serial_connection.write(command)
                self._serial_connection.flush()

                print(
                    "DI RUN TX:",
                    command.hex(" ").upper()
                )

                self._run_waiting_rx = True
                self._run_elapsed = 0
                return

            waiting = self._serial_connection.in_waiting

            if waiting > 0:
                self._run_buffer.extend(
                    self._serial_connection.read(waiting)
                )

            # Digital Input RUN response for 16 inputs:
            # Slave ID + 01 + 02 + DATA1 + DATA2 + Modbus CRC
            expected_length = 7

            if len(self._run_buffer) >= expected_length:
                response = bytes(self._run_buffer[:expected_length])

                print(
                    "DI RUN RX:",
                    response.hex(" ").upper()
                )

                # Validate Slave ID and Modbus function/byte count.
                expected_header = bytes([
                    slave_id,
                    0x01,
                    0x02,
                ])

                if response[:3] == expected_header:
                    response_without_crc = response[:-2]
                    expected_crc = self._modbus_crc(response_without_crc)
                    received_crc = response[-2:]

                    if received_crc == expected_crc:
                        # DATA1 = DI1-DI8, DATA2 = DI9-DI16
                        di_data_1 = response[3]
                        di_data_2 = response[4]

                        print(
                            "DI RUN STATUS:",
                            f"DATA1=0x{di_data_1:02X}, DATA2=0x{di_data_2:02X}"
                        )

                        for index in range(8):
                            is_on = bool(
                                di_data_1 & (1 << index)
                            )
                            self._di_buttons[index].setStyleSheet(
                                f"""
                                QLabel {{
                                    background: {"#00C928" if is_on else "#E00000"};
                                    border: 1px solid #222222;
                                    border-radius: 11px;
                                }}
                                """
                            )

                        for index in range(8):
                            is_on = bool(
                                di_data_2 & (1 << index)
                            )
                            self._di_buttons[index + 8].setStyleSheet(
                                f"""
                                QLabel {{
                                    background: {"#00C928" if is_on else "#E00000"};
                                    border: 1px solid #222222;
                                    border-radius: 11px;
                                }}
                                """
                            )

                        self._run_waiting_rx = False
                        self._run_buffer.clear()
                        self._run_elapsed = 0
                        return

                print(
                    "DI RUN RX: INVALID/UNEXPECTED RESPONSE:",
                    response.hex(" ").upper()
                )
                self._run_waiting_rx = False
                self._run_buffer.clear()
                self._run_elapsed = 0

            self._run_elapsed += 20

            # If no valid RX is received within 2 seconds, stop this
            # Digital Input request and report a timeout.
            if self._run_elapsed >= 2000:
                print("DI RUN TIMEOUT: No RX received within 2 seconds")
                self._run_waiting_rx = False
                self._run_buffer.clear()
                self._run_elapsed = 0
                self._run_timer.stop()
                self._run_active = False
                self.run_button.setText("RUN")
                self.digital_input_timeout_label.show()
                self._status.setText("Digital Input Timeout")
                self._set_status_color("#D00000")
                self.add_terminal_message("Digital Input Timeout")
                return

        except Exception as error:
            print("DI RUN ERROR:", repr(error))
            self._handle_run_com_port_lost()

    def handle_back(self):
        self._connection_monitor_timer.stop()
        self._stop_run()
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

        self._connect_button.setText("CONNECT")
        self._status.setText("Not Connected")
        self._set_status_color("#10C51F")
        self.terminal_messages = ["Device Terminal Ready"]
        self.terminal_message.setPlainText("Device Terminal Ready")
        self.back_clicked.emit()
