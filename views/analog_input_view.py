import os

from PySide6.QtCore import Signal, Qt, QPoint, QTimer, QEvent
from PySide6.QtGui import QFont, QPixmap, QPainter, QPen, QIntValidator
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



# ============================================================
# CHANNEL 1 - ANALOG INPUT TYPE
# ============================================================
CHANNEL1_FUNCTION_CODE = 0x06
CHANNEL1_ADDRESS = 0x0000

# Channel 1 to Channel 8 Modbus addresses.
CHANNEL_INPUT_TYPE_ADDRESSES = {
    1: 0x0000,
    2: 0x0001,
    3: 0x0002,
    4: 0x0003,
    5: 0x0004,
    6: 0x0005,
    7: 0x0006,
    8: 0x0007,
}

CHANNEL1_INPUT_TYPE_VALUES = {
    "0-50mV": 0,
    "0-100mV": 1,
    "0-250mV": 2,
    "0-5V": 3,
    "0-10V": 4,
    "4-20mA": 5,
    "0-20mA": 6,
    "-250mV to +250mV": 7,
    "-10V to +10V": 8,
}

CHANNEL1_INPUT_TYPE_NAMES = {
    value: name for name, value in CHANNEL1_INPUT_TYPE_VALUES.items()
}

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

        # Channel 1 I/P Type Modbus state.
        self._channel1_iptype_pending = False
        self._channel1_iptype_buffer = bytearray()
        self._channel1_iptype_timer = QTimer(self)
        self._channel1_iptype_timer.timeout.connect(
            self._check_channel1_iptype_response
        )
        self._channel1_iptype_elapsed = 0
        self._channel1_iptype_received_value = None

        # I/P Type Modbus state for Channels 1-8.
        self._channel_iptype_pending = {channel: False for channel in range(1, 9)}
        self._channel_iptype_buffer = {channel: bytearray() for channel in range(1, 9)}
        self._channel_iptype_received_value = {channel: None for channel in range(1, 9)}

        # I/P Type GET/Refresh state for Channels 1-8.
        self._channel_get_pending = {channel: False for channel in range(1, 9)}
        self._channel_get_buffer = {channel: bytearray() for channel in range(1, 9)}
        self._channel_get_timer = QTimer(self)
        self._channel_get_timer.timeout.connect(self._check_channel_get_response)
        self._channel_get_elapsed = 0
        self._channel_get_active_channel = None

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
        self._channel_config_frame.setFixedSize(330, 150)
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
        self._input_type.setFixedWidth(175)
        self._input_type.setFixedHeight(30)
        self._input_type.setStyleSheet("""
            QComboBox {
                padding-right: 2px;
            }
            QComboBox QAbstractItemView {
                min-width: 240px;
            }
        """)
        input_row.addWidget(input_label)
        input_row.addWidget(self._input_type)
        input_ok = QPushButton("OK")
        input_ok.setObjectName("okButton")
        input_ok.setFixedSize(45, 28)
        input_ok.setStyleSheet("""
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
        input_row.addWidget(input_ok)
        input_ok.clicked.connect(self.handle_channel1_input_type_ok)
        config_layout.addLayout(input_row)

        min_row = QHBoxLayout()
        min_label = QLabel("Min off set range")
        min_label.setObjectName("smallLabel")
        self._min_offset = QLineEdit("-20000")
        self._min_offset.setFixedWidth(75)
        self._min_offset.setFixedHeight(28)
        self._min_offset.setValidator(QIntValidator(-20000, 20000, self))
        min_row.addWidget(min_label)
        min_row.addStretch()
        min_row.addWidget(self._min_offset)
        min_ok = QPushButton("OK")
        min_ok.setObjectName("okButton")
        min_ok.setFixedSize(45, 28)
        min_ok.setStyleSheet("""
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
        min_row.addWidget(min_ok)
        config_layout.addLayout(min_row)

        max_row = QHBoxLayout()
        max_label = QLabel("Max off set range")
        max_label.setObjectName("smallLabel")
        self._max_offset = QLineEdit("+20000")
        self._max_offset.setFixedWidth(75)
        self._max_offset.setFixedHeight(28)
        self._max_offset.setValidator(QIntValidator(-20000, 20000, self))
        max_row.addWidget(max_label)
        max_row.addStretch()
        max_row.addWidget(self._max_offset)
        max_ok = QPushButton("OK")
        max_ok.setObjectName("okButton")
        max_ok.setFixedSize(45, 28)
        max_ok.setStyleSheet("""
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
        max_row.addWidget(max_ok)
        config_layout.addLayout(max_row)

        # Channel 1 configuration refresh button.
        channel_refresh = QPushButton("Refresh")
        channel_refresh.setObjectName("okButton")
        channel_refresh.setFixedSize(82, 28)
        channel_refresh.setStyleSheet("""
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
        channel_refresh.setVisible(False)
        channel_refresh.clicked.connect(self.handle_channel_refresh)

        channel_refresh_row = QHBoxLayout()
        channel_refresh_row.setContentsMargins(0, 0, 0, 0)
        channel_refresh_row.addStretch()
        channel_refresh_row.addWidget(channel_refresh)
        channel_refresh_row.addStretch()
        config_layout.addLayout(channel_refresh_row)

        self._channel_refresh_button = channel_refresh


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

            self._channel_get_timer.stop()
            self._channel_get_active_channel = None
            for channel in range(1, 9):
                self._channel_get_pending[channel] = False
                self._channel_get_buffer[channel].clear()

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

    # ============================================================
    # CHANNEL 1 - MODBUS CRC
    # ============================================================

    def calculate_modbus_crc(self, data):
        """Calculate standard Modbus CRC-16. Returned as an integer."""
        crc = 0xFFFF

        for byte in data:
            crc ^= byte

            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1

        return crc & 0xFFFF

    # ============================================================
    # CHANNEL 1-8 - BUILD FUNCTION CODE 06 FRAME
    # ============================================================

    def build_channel1_frame(self, slave_id, input_type_value, address=None):
        """
        Build:
        Slave ID | FC 06 | Channel Address | Value | CRC
        """
        if address is None:
            address = CHANNEL1_ADDRESS

        data = bytes([
            slave_id,
            CHANNEL1_FUNCTION_CODE,
            (address >> 8) & 0xFF,
            address & 0xFF,
            (input_type_value >> 8) & 0xFF,
            input_type_value & 0xFF,
        ])

        crc = self.calculate_modbus_crc(data)
        crc_low = crc & 0xFF
        crc_high = (crc >> 8) & 0xFF

        return data + bytes([crc_low, crc_high])

    # ============================================================
    # CHANNEL 1-8 - I/P TYPE OK BUTTON
    # ============================================================

    def handle_channel1_input_type_ok(self):
        print("\n============================================================")
        print("I/P TYPE - OK BUTTON PRESSED")
        print("============================================================")

        # --------------------------------------------------------
        # STEP 1: Find the selected channel.
        # --------------------------------------------------------
        selected_channel = None
        for channel in range(1, 9):
            if self._channel_selectors[channel - 1].isVisible():
                selected_channel = channel
                break

        if selected_channel is None:
            print("FAILED: No analog input channel selected")
            self._status.setText("Channel Not Selected")
            return

        channel_address = CHANNEL_INPUT_TYPE_ADDRESSES[selected_channel]

        print("Selected Channel:", selected_channel)
        print("Function Code:", f"{CHANNEL1_FUNCTION_CODE:02X}")
        print("Address:", f"{channel_address:04X}")

        # --------------------------------------------------------
        # STEP 2: Check COM/device connection.
        # --------------------------------------------------------
        if (
            self._connect_button.text() != "DISCONNECT"
            or self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            print("FAILED: COM Port Not Connected")
            self._status.setText("COM Port Not Connected")
            self._status.setStyleSheet(
                "color: #D00000; font-weight: bold; font-size: 16px;"
            )
            return

        # --------------------------------------------------------
        # STEP 3: Read and validate Slave ID.
        # --------------------------------------------------------
        slave_text = self._slave_id.text().strip()

        try:
            slave_id = int(slave_text)
        except ValueError:
            print("FAILED: Invalid Slave ID")
            self._status.setText("Slave ID must be 1 to 63")
            return

        if not 1 <= slave_id <= 63:
            print("FAILED: Slave ID must be 1 to 63")
            self._status.setText("Slave ID must be 1 to 63")
            return

        # --------------------------------------------------------
        # STEP 4: Read selected I/P Type and map to protocol value.
        # --------------------------------------------------------
        input_type = self._input_type.currentText().strip()

        if input_type not in CHANNEL1_INPUT_TYPE_VALUES:
            print("FAILED: Unknown I/P Type:", input_type)
            self._status.setText("Invalid I/P Type")
            return

        input_type_value = CHANNEL1_INPUT_TYPE_VALUES[input_type]

        print("Slave ID:", slave_id)
        print("I/P Type:", input_type)
        print("I/P Type Value:", input_type_value)

        # --------------------------------------------------------
        # STEP 5: Build exact binary Modbus frame.
        # --------------------------------------------------------
        frame = self.build_channel1_frame(
            slave_id,
            input_type_value,
            channel_address,
        )

        print("TX FRAME HEX:", frame.hex(" ").upper())
        print("TX FRAME BYTES:", frame)

        # --------------------------------------------------------
        # STEP 6: Send RAW BINARY bytes.
        # --------------------------------------------------------
        if self._channel_iptype_pending[selected_channel]:
            print(
                f"FAILED: Channel {selected_channel} I/P Type request already pending"
            )
            return

        try:
            self._serial_connection.reset_input_buffer()
            self._channel_iptype_buffer[selected_channel].clear()

            self._serial_connection.write(frame)
            self._serial_connection.flush()

            print("TX SUCCESS: Raw binary frame sent")

            self._channel_iptype_pending[selected_channel] = True
            self._channel1_iptype_pending = True
            self._channel1_iptype_elapsed = 0
            self._channel1_iptype_timer.start(20)

        except Exception as exc:
            print("FAILED: TX Exception:", exc)

            self._channel_iptype_pending[selected_channel] = False
            self._channel1_iptype_pending = False
            self._channel1_iptype_timer.stop()
            self._channel_iptype_buffer[selected_channel].clear()

            self._status.setText("I/P Type Not Applied")
            self._status.setStyleSheet(
                "color: #D00000; font-weight: bold; font-size: 16px;"
            )

    # ============================================================
    # CHANNEL 1-8 - CHECK MODBUS RESPONSE
    # ============================================================

    def _check_channel1_iptype_response(self):
        if not self._channel1_iptype_pending:
            self._channel1_iptype_timer.stop()
            return

        # --------------------------------------------------------
        # Find which channel currently has a pending request.
        # --------------------------------------------------------
        selected_channel = None
        for channel in range(1, 9):
            if self._channel_iptype_pending[channel]:
                selected_channel = channel
                break

        if selected_channel is None:
            print("FAILED: No pending I/P Type channel found")
            self._channel1_iptype_pending = False
            self._channel1_iptype_timer.stop()
            return

        channel_address = CHANNEL_INPUT_TYPE_ADDRESSES[selected_channel]
        channel_buffer = self._channel_iptype_buffer[selected_channel]

        # --------------------------------------------------------
        # STEP 1: Check connection while waiting for response.
        # --------------------------------------------------------
        if (
            self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            print(
                f"FAILED: Channel {selected_channel} COM Port disconnected while waiting for RX"
            )

            self._channel_iptype_pending[selected_channel] = False
            self._channel1_iptype_pending = False
            self._channel1_iptype_timer.stop()
            channel_buffer.clear()

            self._status.setText("COM Port Not Connected")
            self._status.setStyleSheet(
                "color: #D00000; font-weight: bold; font-size: 16px;"
            )
            return

        try:
            # ----------------------------------------------------
            # STEP 2: Accumulate RX bytes.
            # ----------------------------------------------------
            waiting = self._serial_connection.in_waiting

            if waiting > 0:
                received = self._serial_connection.read(waiting)
                channel_buffer.extend(received)

                print(
                    f"RX CH{selected_channel} CHUNK HEX:",
                    received.hex(" ").upper(),
                )
                print(
                    f"RX CH{selected_channel} BUFFER HEX:",
                    bytes(channel_buffer).hex(" ").upper(),
                )

            # ----------------------------------------------------
            # STEP 3: Exact response size is 8 bytes.
            # ----------------------------------------------------
            if len(channel_buffer) >= 8:
                response = bytes(channel_buffer[:8])
                del channel_buffer[:8]

                print(
                    f"RX CH{selected_channel} FRAME HEX:",
                    response.hex(" ").upper(),
                )

                # ------------------------------------------------
                # STEP 4: Split RX frame.
                # ------------------------------------------------
                rx_slave_id = response[0]
                rx_function = response[1]
                rx_address = (response[2] << 8) | response[3]
                rx_value = (response[4] << 8) | response[5]

                rx_crc_received = response[6] | (response[7] << 8)
                rx_crc_calculated = self.calculate_modbus_crc(
                    response[:6]
                )

                print("RX Slave ID:", rx_slave_id)
                print("RX Function Code:", f"{rx_function:02X}")
                print("RX Address:", f"{rx_address:04X}")
                print("RX Value:", f"{rx_value:04X}")
                print(
                    "RX CRC Received:",
                    f"{rx_crc_received:04X}",
                )
                print(
                    "RX CRC Calculated:",
                    f"{rx_crc_calculated:04X}",
                )

                # ------------------------------------------------
                # STEP 5: Validate all response fields.
                # ------------------------------------------------
                expected_slave_id = int(
                    self._slave_id.text().strip()
                )

                if rx_slave_id != expected_slave_id:
                    print(
                        f"FAILED: Channel {selected_channel} RX Slave ID mismatch"
                    )
                    self._finish_channel_iptype_failure(
                        selected_channel,
                        "I/P Type Response Error",
                    )
                    return

                if rx_function != CHANNEL1_FUNCTION_CODE:
                    print(
                        f"FAILED: Channel {selected_channel} RX Function Code mismatch"
                    )
                    self._finish_channel_iptype_failure(
                        selected_channel,
                        "I/P Type Response Error",
                    )
                    return

                if rx_address != channel_address:
                    print(
                        f"FAILED: Channel {selected_channel} RX Address mismatch"
                    )
                    self._finish_channel_iptype_failure(
                        selected_channel,
                        "I/P Type Response Error",
                    )
                    return

                if rx_value not in CHANNEL1_INPUT_TYPE_NAMES:
                    print(
                        f"FAILED: Channel {selected_channel} RX I/P Type Value invalid:",
                        rx_value,
                    )
                    self._finish_channel_iptype_failure(
                        selected_channel,
                        "I/P Type Response Error",
                    )
                    return

                if rx_crc_received != rx_crc_calculated:
                    print(
                        f"FAILED: Channel {selected_channel} RX CRC mismatch"
                    )
                    self._finish_channel_iptype_failure(
                        selected_channel,
                        "I/P Type Response Error",
                    )
                    return

                # ------------------------------------------------
                # STEP 6: Store validated received configuration.
                # ------------------------------------------------
                self._channel_iptype_received_value[selected_channel] = rx_value

                if selected_channel == 1:
                    self._channel1_iptype_received_value = rx_value

                received_name = CHANNEL1_INPUT_TYPE_NAMES[rx_value]

                print("RX VALIDATION: SUCCESS")
                print("Validated I/P Type Value:", rx_value)
                print("Validated I/P Type:", received_name)
                print(f"Channel {selected_channel} I/P Type stored successfully")

                # Keep the validated RX value stored for this channel.
                # The value will be shown in the I/P Type dropdown only when
                # that channel's Refresh button is pressed.
                self._channel_iptype_pending[selected_channel] = False
                self._channel1_iptype_pending = False
                self._channel1_iptype_timer.stop()
                channel_buffer.clear()

                self._status.setText("I/P Type Applied")
                self._status.setStyleSheet(
                    "color: #00C928; font-weight: bold; font-size: 16px;"
                )
                return

            # ----------------------------------------------------
            # STEP 7: Response timeout.
            # ----------------------------------------------------
            self._channel1_iptype_elapsed += 20

            if self._channel1_iptype_elapsed >= 2000:
                print(
                    f"FAILED: Channel {selected_channel} I/P Type response timeout"
                )
                print(
                    "RX BUFFER AT TIMEOUT:",
                    bytes(channel_buffer).hex(" ").upper(),
                )

                self._finish_channel_iptype_failure(
                    selected_channel,
                    "I/P Type Response Timeout",
                )

        except Exception as exc:
            print(f"FAILED: Channel {selected_channel} RX Exception:", exc)
            self._finish_channel_iptype_failure(
                selected_channel,
                "I/P Type Response Error",
            )

    def _finish_channel_iptype_failure(self, channel, status_text):
        self._channel_iptype_pending[channel] = False
        self._channel1_iptype_pending = False
        self._channel1_iptype_timer.stop()
        self._channel_iptype_buffer[channel].clear()

        self._status.setText(status_text)
        self._status.setStyleSheet(
            "color: #D00000; font-weight: bold; font-size: 16px;"
        )

    # Keep the original Channel 1 helper name available.
    def _finish_channel1_iptype_failure(self, status_text):
        self._finish_channel_iptype_failure(1, status_text)

    # ============================================================
    # CHANNEL 1-8 - BUILD FUNCTION CODE 03 GET FRAME
    # ============================================================

    def build_channel_get_frame(self, slave_id, address):
        """
        Build:
        Slave ID | FC 03 | Channel Address | Length 0001 | CRC
        """
        data = bytes([
            slave_id,
            0x03,
            (address >> 8) & 0xFF,
            address & 0xFF,
            0x00,
            0x01,
        ])

        crc = self.calculate_modbus_crc(data)
        crc_low = crc & 0xFF
        crc_high = (crc >> 8) & 0xFF

        return data + bytes([crc_low, crc_high])

    # ============================================================
    # CHANNEL 1-8 - REFRESH FROM DEVICE
    # ============================================================

    def handle_channel_refresh(self):
        print("\n============================================================")
        print("CHANNEL I/P TYPE - REFRESH BUTTON PRESSED")
        print("============================================================")

        # --------------------------------------------------------
        # STEP 1: Find the selected channel.
        # --------------------------------------------------------
        selected_channel = None
        for channel in range(1, 9):
            if self._channel_selectors[channel - 1].isVisible():
                selected_channel = channel
                break

        if selected_channel is None:
            print("FAILED: No analog input channel selected")
            self._status.setText("Channel Not Selected")
            return

        channel_address = CHANNEL_INPUT_TYPE_ADDRESSES[selected_channel]

        print("Selected Channel:", selected_channel)
        print("Function Code: 03")
        print("Address:", f"{channel_address:04X}")
        print("Length: 0001")

        # --------------------------------------------------------
        # STEP 2: Check COM/device connection.
        # --------------------------------------------------------
        if (
            self._connect_button.text() != "DISCONNECT"
            or self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            print("FAILED: COM Port Not Connected")
            self._status.setText("COM Port Not Connected")
            self._status.setStyleSheet(
                "color: #D00000; font-weight: bold; font-size: 16px;"
            )
            return

        # --------------------------------------------------------
        # STEP 3: Read and validate Slave ID.
        # --------------------------------------------------------
        slave_text = self._slave_id.text().strip()

        try:
            slave_id = int(slave_text)
        except ValueError:
            print("FAILED: Invalid Slave ID")
            self._status.setText("Slave ID must be 1 to 63")
            return

        if not 1 <= slave_id <= 63:
            print("FAILED: Slave ID must be 1 to 63")
            self._status.setText("Slave ID must be 1 to 63")
            return

        print("Slave ID:", slave_id)

        # --------------------------------------------------------
        # STEP 4: Check whether this channel already has a GET.
        # --------------------------------------------------------
        if self._channel_get_pending[selected_channel]:
            print(
                f"FAILED: Channel {selected_channel} I/P Type GET request already pending"
            )
            return

        # --------------------------------------------------------
        # STEP 5: Build exact binary Modbus FC03 GET frame.
        # --------------------------------------------------------
        frame = self.build_channel_get_frame(
            slave_id,
            channel_address,
        )

        print("TX GET FRAME HEX:", frame.hex(" ").upper())
        print("TX GET FRAME BYTES:", frame)

        # --------------------------------------------------------
        # STEP 6: Send RAW BINARY bytes.
        # --------------------------------------------------------
        try:
            self._serial_connection.reset_input_buffer()
            self._channel_get_buffer[selected_channel].clear()

            self._serial_connection.write(frame)
            self._serial_connection.flush()

            print("TX GET SUCCESS: Raw binary frame sent")

            self._channel_get_pending[selected_channel] = True
            self._channel_get_active_channel = selected_channel
            self._channel_get_elapsed = 0
            self._channel_get_timer.start(20)

        except Exception as exc:
            print("FAILED: GET TX Exception:", exc)

            self._channel_get_pending[selected_channel] = False
            self._channel_get_active_channel = None
            self._channel_get_timer.stop()
            self._channel_get_buffer[selected_channel].clear()

            self._status.setText("I/P Type Refresh Failed")
            self._status.setStyleSheet(
                "color: #D00000; font-weight: bold; font-size: 16px;"
            )

    def _check_channel_get_response(self):
        selected_channel = self._channel_get_active_channel

        if selected_channel is None or not self._channel_get_pending[selected_channel]:
            self._channel_get_timer.stop()
            return

        channel_address = CHANNEL_INPUT_TYPE_ADDRESSES[selected_channel]
        channel_buffer = self._channel_get_buffer[selected_channel]

        # --------------------------------------------------------
        # STEP 1: Check connection while waiting for response.
        # --------------------------------------------------------
        if (
            self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            print(
                f"FAILED: Channel {selected_channel} GET COM Port disconnected while waiting for RX"
            )

            self._finish_channel_get_failure(
                selected_channel,
                "COM Port Not Connected",
            )
            return

        try:
            # ----------------------------------------------------
            # STEP 2: Accumulate RX bytes.
            # ----------------------------------------------------
            waiting = self._serial_connection.in_waiting

            if waiting > 0:
                received = self._serial_connection.read(waiting)
                channel_buffer.extend(received)

                print(
                    f"RX GET CH{selected_channel} CHUNK HEX:",
                    received.hex(" ").upper(),
                )
                print(
                    f"RX GET CH{selected_channel} BUFFER HEX:",
                    bytes(channel_buffer).hex(" ").upper(),
                )

            # ----------------------------------------------------
            # STEP 3: GET RX response is 7 bytes:
            # SID | FC | Byte Count | Value | CRC
            # Example: 02 03 02 00 02 7D 85
            # ----------------------------------------------------
            if len(channel_buffer) >= 7:
                response = bytes(channel_buffer[:7])
                del channel_buffer[:7]

                print(
                    f"RX GET CH{selected_channel} FRAME HEX:",
                    response.hex(" ").upper(),
                )

                # ------------------------------------------------
                # STEP 4: Split RX frame.
                # ------------------------------------------------
                rx_slave_id = response[0]
                rx_function = response[1]
                rx_byte_count = response[2]
                rx_value = (response[3] << 8) | response[4]

                rx_crc_received = response[5] | (response[6] << 8)
                rx_crc_calculated = self.calculate_modbus_crc(
                    response[:5]
                )

                print("RX GET Slave ID:", rx_slave_id)
                print("RX GET Function Code:", f"{rx_function:02X}")
                print("RX GET Byte Count:", rx_byte_count)
                print("RX GET Value:", f"{rx_value:04X}")
                print(
                    "RX GET CRC Received:",
                    f"{rx_crc_received:04X}",
                )
                print(
                    "RX GET CRC Calculated:",
                    f"{rx_crc_calculated:04X}",
                )

                # ------------------------------------------------
                # STEP 5: Validate all response fields.
                # ------------------------------------------------
                try:
                    expected_slave_id = int(self._slave_id.text().strip())
                except ValueError:
                    print("FAILED: Invalid Slave ID during GET RX validation")
                    self._finish_channel_get_failure(
                        selected_channel,
                        "I/P Type Response Error",
                    )
                    return

                if rx_slave_id != expected_slave_id:
                    print(
                        f"FAILED: Channel {selected_channel} GET RX Slave ID mismatch"
                    )
                    self._finish_channel_get_failure(
                        selected_channel,
                        "I/P Type Response Error",
                    )
                    return

                if rx_function != 0x03:
                    print(
                        f"FAILED: Channel {selected_channel} GET RX Function Code mismatch"
                    )
                    self._finish_channel_get_failure(
                        selected_channel,
                        "I/P Type Response Error",
                    )
                    return

                if rx_byte_count != 0x02:
                    print(
                        f"FAILED: Channel {selected_channel} GET RX Byte Count mismatch"
                    )
                    self._finish_channel_get_failure(
                        selected_channel,
                        "I/P Type Response Error",
                    )
                    return

                if rx_value not in CHANNEL1_INPUT_TYPE_NAMES:
                    print(
                        f"FAILED: Channel {selected_channel} GET RX I/P Type Value invalid:",
                        rx_value,
                    )
                    self._finish_channel_get_failure(
                        selected_channel,
                        "I/P Type Response Error",
                    )
                    return

                if rx_crc_received != rx_crc_calculated:
                    print(
                        f"FAILED: Channel {selected_channel} GET RX CRC mismatch"
                    )
                    self._finish_channel_get_failure(
                        selected_channel,
                        "I/P Type Response Error",
                    )
                    return

                # ------------------------------------------------
                # STEP 6: Store validated device configuration.
                # ------------------------------------------------
                self._channel_iptype_received_value[selected_channel] = rx_value

                if selected_channel == 1:
                    self._channel1_iptype_received_value = rx_value

                received_name = CHANNEL1_INPUT_TYPE_NAMES[rx_value]

                print("RX GET VALIDATION: SUCCESS")
                print("Validated I/P Type Value:", rx_value)
                print("Validated I/P Type:", received_name)
                print(
                    f"Channel {selected_channel} I/P Type retrieved successfully from device"
                )

                # Show the actual device value in the dropdown.
                self._input_type.setCurrentText(received_name)

                self._channel_get_pending[selected_channel] = False
                self._channel_get_active_channel = None
                self._channel_get_timer.stop()
                channel_buffer.clear()

                self._status.setText(
                    f"Channel {selected_channel} I/P Type Refreshed"
                )
                self._status.setStyleSheet(
                    "color: #00C928; font-weight: bold; font-size: 16px;"
                )
                return

            # ----------------------------------------------------
            # STEP 7: Response timeout.
            # ----------------------------------------------------
            self._channel_get_elapsed += 20

            if self._channel_get_elapsed >= 2000:
                print(
                    f"FAILED: Channel {selected_channel} I/P Type GET response timeout"
                )
                print(
                    "RX GET BUFFER AT TIMEOUT:",
                    bytes(channel_buffer).hex(" ").upper(),
                )

                self._finish_channel_get_failure(
                    selected_channel,
                    "I/P Type Refresh Timeout",
                )

        except Exception as exc:
            print(
                f"FAILED: Channel {selected_channel} GET RX Exception:",
                exc,
            )
            self._finish_channel_get_failure(
                selected_channel,
                "I/P Type Response Error",
            )

    def _finish_channel_get_failure(self, channel, status_text):
        self._channel_get_pending[channel] = False
        self._channel_get_active_channel = None
        self._channel_get_timer.stop()
        self._channel_get_buffer[channel].clear()

        self._status.setText(status_text)
        self._status.setStyleSheet(
            "color: #D00000; font-weight: bold; font-size: 16px;"
        )

    # Keep the original Channel 1 refresh helper name available.
    def handle_channel1_refresh(self):
        self.handle_channel_refresh()

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
        self._channel_refresh_button.setVisible(True)

    def reset_channel_view(self):
        for box in self._channel_selectors:
            box.setVisible(True)
        self._channel_config_frame.setVisible(False)
        self._channel_refresh_button.setVisible(False)

    def handle_back(self):
        self._apply_pending = False
        self._apply_timer.stop()
        self._apply_buffer.clear()

        self._refresh_pending = False
        self._refresh_timer.stop()
        self._refresh_buffer.clear()

        self._channel1_iptype_pending = False
        self._channel1_iptype_timer.stop()
        self._channel1_iptype_buffer.clear()

        for channel in range(1, 9):
            self._channel_iptype_pending[channel] = False
            self._channel_iptype_buffer[channel].clear()

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
