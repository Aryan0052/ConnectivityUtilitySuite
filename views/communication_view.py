import socket
import struct
import time
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QTimer, QSize, QRectF, QPointF
from PySide6.QtGui import (
    QFont,
    QPainter,
    QPen,
    QBrush,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QWidget,
    QFrame,
    QLabel,
    QPushButton,
    QLineEdit,
    QComboBox,
    QCheckBox,
    QSpinBox,
    QGridLayout,
    QVBoxLayout,
    QHBoxLayout,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QTextEdit,
    QSizePolicy,  # for flexible sizing
    QGroupBox,
)
try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None
try:
    from pymodbus.client import ModbusSerialClient, ModbusTcpClient
    from pymodbus.exceptions import ModbusException
    PYMODBUS_AVAILABLE = True
except ImportError:
    ModbusSerialClient = None
    ModbusTcpClient = None
    ModbusException = Exception
    PYMODBUS_AVAILABLE = False

try:
    from . import ui_theme as ui
except ImportError:
    import ui_theme as ui


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
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(Qt.white, 2))
        painter.setBrush(QBrush(Qt.white))
        painter.drawEllipse(QRectF(1, 1, 52, 52))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush("#17548C"))
        arrow = QPolygonF([
            QPointF(38, 25), QPointF(24, 25), QPointF(31, 18),
            QPointF(27, 14), QPointF(14, 27), QPointF(27, 40),
            QPointF(31, 36), QPointF(24, 29), QPointF(38, 29),
        ])
        painter.drawPolygon(arrow)
        painter.end()

class CommunicationView(QWidget):
    back_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("communicationView")
        # Allow the main widget to expand/shrink with the window
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # =========================================================
        # CONNECTION STATE AND DATA STORAGE
        # =========================================================
        self._serial_connection = None
        self._tcp_socket = None
        self._connected = False
        self._running = False
        self._waiting_response = False
        self._rx_buffer = bytearray()
        self._last_request_time = 0.0
        self._digital_states = {}
        self._selected_coils = set()
        self._register_values = {}
        self._poll_count = 0
        self._valid_responses = 0
        self._exception_responses = 0
        self._timeouts = 0
        # Timers for polling and I/O
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_cycle)
        self._connection_timer = QTimer(self)
        self._connection_timer.timeout.connect(self._check_connection_status)
        self._connection_timer.start(500)
        # =========================================================
        # UI BUILD
        # =========================================================
        self._build_ui()
        self._refresh_ports()
        self._update_data_display()

    def minimumSizeHint(self):
        # Do not let the internal communication layout force the main window
        # to a large minimum size on Windows. The main window can shrink and
        # the internal scrollable areas will handle smaller screen sizes.
        return QSize(0, 0)

    def sizeHint(self):
        # Give Qt a sensible preferred size without imposing a minimum size.
        return QSize(1100, 700)

    def _build_ui(self):
        # Look: shared with the other pages and the Multi Device page (ui_theme.py). Only widgets and
        # styles are built here - every attribute the communication code uses keeps its name.
        ui.install(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # HEADER (logo, back, title, connection status, theme switch)
        header = ui.Header("Modbus Communication", root=self)
        self.back_button = header.back_button
        self.back_button.clicked.connect(self._handle_back_clicked)
        self.status_label = header.status
        self._status_dot = header.status_dot
        root.addWidget(header)

        main = QWidget()
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        def pair(left_text, left_widget, right_text, right_widget):
            box = QWidget()
            row = QHBoxLayout(box)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(10)
            row.addWidget(ui.field(left_text, left_widget), 1)
            row.addWidget(ui.field(right_text, right_widget), 1)
            return box

        # ------------------------------------------------------------ LEFT: communication settings
        left_panel = ui.card()
        ui.sized(left_panel, "setMinimumWidth", 300)
        ui.sized(left_panel, "setMaximumWidth", 370)
        left_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(18, 18, 18, 18)
        left_layout.setSpacing(12)

        left_layout.addWidget(ui.section("Communication Settings"))

        self.connection_type = QComboBox()
        self.connection_type.addItems(["Modbus RTU", "Modbus TCP"])
        self.connection_type.currentIndexChanged.connect(self._connection_type_changed)
        left_layout.addWidget(ui.field("Connection Type", self.connection_type))

        # RTU group
        self.rtu_group = QFrame()
        self.rtu_group.setObjectName("pgBox")
        rtu_layout = QVBoxLayout(self.rtu_group)
        rtu_layout.setContentsMargins(12, 12, 12, 12)
        rtu_layout.setSpacing(10)
        rtu_layout.addWidget(ui.label("MODBUS RTU", "pgSection"))

        self.com_port = QComboBox()
        refresh_button = ui.button("\u21bb", "icon")
        refresh_button.setToolTip("Refresh COM ports")
        refresh_button.clicked.connect(self._refresh_ports)
        com_box = QWidget()
        com_row = QHBoxLayout(com_box)
        com_row.setContentsMargins(0, 0, 0, 0)
        com_row.setSpacing(8)
        com_row.addWidget(self.com_port, 1)
        com_row.addWidget(refresh_button)
        rtu_layout.addWidget(ui.field("COM Port", com_box))

        self.baud_rate = QComboBox()
        self.baud_rate.addItems(["9600", "19200", "38400", "57600", "115200"])
        self.baud_rate.setCurrentText("9600")
        self.data_bits = QComboBox()
        self.data_bits.addItems(["7", "8"])
        self.data_bits.setCurrentText("8")
        rtu_layout.addWidget(pair("Baud Rate", self.baud_rate, "Data Bits", self.data_bits))

        self.parity = QComboBox()
        self.parity.addItems(["None", "Even", "Odd"])
        self.stop_bits = QComboBox()
        self.stop_bits.addItems(["1", "2"])
        rtu_layout.addWidget(pair("Parity", self.parity, "Stop Bits", self.stop_bits))

        self.slave_id = QSpinBox()
        self.slave_id.setRange(1, 247)
        self.slave_id.setValue(1)
        rtu_layout.addWidget(ui.field("Slave ID", self.slave_id))
        left_layout.addWidget(self.rtu_group)

        # TCP group
        self.tcp_group = QFrame()
        self.tcp_group.setObjectName("pgBox")
        tcp_layout = QVBoxLayout(self.tcp_group)
        tcp_layout.setContentsMargins(12, 12, 12, 12)
        tcp_layout.setSpacing(10)
        tcp_layout.addWidget(ui.label("MODBUS TCP", "pgSection"))

        self.ip_address = QLineEdit("192.168.1.100")
        tcp_layout.addWidget(ui.field("IP Address", self.ip_address))

        self.subnet_mask = QLineEdit("255.255.255.0")
        tcp_layout.addWidget(ui.field("Subnet Mask", self.subnet_mask))

        self.tcp_port = QSpinBox()
        self.tcp_port.setRange(1, 65535)
        self.tcp_port.setValue(502)
        self.unit_id = QSpinBox()
        self.unit_id.setRange(1, 247)
        self.unit_id.setValue(1)
        tcp_layout.addWidget(pair("TCP Port", self.tcp_port, "Unit ID", self.unit_id))
        left_layout.addWidget(self.tcp_group)

        self.connect_button = ui.button("CONNECT", "primary", 38, alt={"DISCONNECT": "softdanger"})
        self.connect_button.clicked.connect(self._toggle_connection)
        left_layout.addWidget(self.connect_button)

        left_layout.addSpacing(4)
        left_layout.addWidget(ui.section("Device Terminal"))
        self.terminal = QTextEdit()
        self.terminal.setObjectName("pgTerminal")
        self.terminal.setReadOnly(True)
        ui.sized(self.terminal, "setMinimumHeight", 110)
        self.terminal.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout.addWidget(self.terminal, 1)

        main_layout.addWidget(left_panel)

        # ------------------------------------------------------------ RIGHT: monitor
        right_panel = ui.card()
        right_panel.setMinimumSize(0, 0)
        right_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(22, 20, 22, 20)
        right_layout.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_col.addWidget(ui.label("Modbus Monitor", "pgTitle"))
        title_col.addWidget(ui.label("Read and write coils and registers, live", "pgSub"))
        right_layout.addLayout(title_col)

        config_frame = QFrame()
        config_frame.setObjectName("pgBox")
        config_layout = QGridLayout(config_frame)
        config_layout.setContentsMargins(14, 12, 14, 12)
        config_layout.setHorizontalSpacing(12)
        config_layout.setVerticalSpacing(4)
        for column in range(4):
            config_layout.setColumnStretch(column, 1)

        self.device_id = QSpinBox()
        self.device_id.setRange(1, 247)
        self.device_id.setValue(1)
        config_layout.addWidget(ui.label("Device ID", "pgField"), 0, 0)
        config_layout.addWidget(self.device_id, 1, 0)

        self.start_address = QSpinBox()
        self.start_address.setRange(0, 65535)
        self.start_address.setValue(0)
        config_layout.addWidget(ui.label("Start Address", "pgField"), 0, 1)
        config_layout.addWidget(self.start_address, 1, 1)

        self.length = QSpinBox()
        self.length.setRange(1, 2000)
        self.length.setValue(16)
        self.length.valueChanged.connect(self._update_data_display)
        config_layout.addWidget(ui.label("Length", "pgField"), 0, 2)
        config_layout.addWidget(self.length, 1, 2)

        # Write value (only visible for write function codes)
        self.write_value = QSpinBox()
        self.write_value.setRange(0, 65535)
        self.write_value.setValue(1)
        self.write_value_label = ui.label("Write Value", "pgField")
        config_layout.addWidget(self.write_value_label, 0, 3)
        config_layout.addWidget(self.write_value, 1, 3)
        self.write_value.setVisible(False)
        self.write_value_label.setVisible(False)

        config_layout.setRowMinimumHeight(2, 8)

        self.point_type = QComboBox()
        self.point_type.addItems([
            "01 - READ COILS",
            "02 - READ DISCRETE INPUTS",
            "03 - READ HOLDING REGISTERS",
            "04 - READ INPUT REGISTERS",
            "05 - WRITE SINGLE COIL",
            "06 - WRITE SINGLE REGISTER",
            "15 - WRITE MULTIPLE COILS",
            "16 - WRITE MULTIPLE REGISTERS",
        ])
        self.point_type.currentIndexChanged.connect(self._point_type_changed)
        config_layout.addWidget(ui.label("Point Type", "pgField"), 3, 0, 1, 2)
        config_layout.addWidget(self.point_type, 4, 0, 1, 2)

        self.poll_interval = QSpinBox()
        self.poll_interval.setRange(10, 60000)
        self.poll_interval.setValue(500)
        self.poll_interval.valueChanged.connect(self._poll_interval_changed)
        config_layout.addWidget(ui.label("Poll Interval (ms)", "pgField"), 3, 2)
        config_layout.addWidget(self.poll_interval, 4, 2)

        self.timeout = QSpinBox()
        self.timeout.setRange(10, 60000)
        self.timeout.setValue(1000)
        config_layout.addWidget(ui.label("Timeout (ms)", "pgField"), 3, 3)
        config_layout.addWidget(self.timeout, 4, 3)
        right_layout.addWidget(config_frame)

        # Action buttons (Run, Stop, Reset, Apply)
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.run_button = ui.button("\u25b6 RUN", "primary", 36, alt={"RUNNING": "success"})
        ui.sized(self.run_button, "setMinimumWidth", 120)
        self.run_button.clicked.connect(self._toggle_run)
        action_row.addWidget(self.run_button)

        self.stop_button = ui.button("\u25a0 STOP", "danger", 36)
        ui.sized(self.stop_button, "setMinimumWidth", 100)
        self.stop_button.clicked.connect(self._stop_polling)
        action_row.addWidget(self.stop_button)

        reset_button = ui.button("RESET COUNTERS", "secondary", 36)
        reset_button.clicked.connect(self._reset_counters)
        action_row.addWidget(reset_button)

        apply_button = ui.button("APPLY", "secondary", 36)
        apply_button.clicked.connect(self._apply_settings)
        action_row.addWidget(apply_button)
        action_row.addStretch()
        right_layout.addLayout(action_row)

        # Data area
        right_layout.addWidget(ui.section("Modbus Data"))
        self.data_scroll = QScrollArea()
        self.data_scroll.setObjectName("dataScroll")
        self.data_scroll.setWidgetResizable(True)
        self.data_scroll.setFrameShape(QFrame.NoFrame)
        self.data_scroll.setMinimumHeight(0)
        ui.sized(self.data_scroll, "setMaximumHeight", 400)
        self.data_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.data_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.data_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        ui.tss(self.data_scroll, "QScrollArea#dataScroll { background:@sunken; border:1px solid @border; border-radius:10px; } "
                                 "QScrollArea#dataScroll > QWidget > QWidget { background:@sunken; }")

        self.data_container = QWidget()
        self.data_container.setObjectName("dataContainer")
        self.data_container.setMinimumSize(0, 0)
        self.data_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._register_table = None
        self.data_layout = QGridLayout(self.data_container)
        self.data_layout.setContentsMargins(10, 10, 10, 10)
        self.data_layout.setHorizontalSpacing(8)
        self.data_layout.setVerticalSpacing(8)
        self.data_layout.setRowStretch(0, 1)
        self.data_layout.setColumnStretch(0, 1)
        self.data_scroll.setWidget(self.data_container)
        right_layout.addWidget(self.data_scroll, 0)

        # Bottom TX/RX log and statistics
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(12)

        tx_frame = QFrame()
        tx_frame.setObjectName("pgBox")
        ui.sized(tx_frame, "setMinimumHeight", 220)
        ui.sized(tx_frame, "setMaximumHeight", 220)
        tx_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        tx_layout = QVBoxLayout(tx_frame)
        tx_layout.setContentsMargins(12, 10, 12, 12)
        tx_layout.setSpacing(8)
        tx_layout.addWidget(ui.label("TX / RX", "pgSection"))
        self.tx_rx_terminal = QTextEdit()
        self.tx_rx_terminal.setObjectName("pgTerminal")
        self.tx_rx_terminal.setReadOnly(True)
        self.tx_rx_terminal.setMinimumSize(0, 0)
        self.tx_rx_terminal.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        tx_layout.addWidget(self.tx_rx_terminal, 1)
        bottom_layout.addWidget(tx_frame, 1)

        stats_frame = QFrame()
        stats_frame.setObjectName("pgBox")
        ui.sized(stats_frame, "setMinimumWidth", 255)
        ui.sized(stats_frame, "setMaximumWidth", 290)
        ui.sized(stats_frame, "setMinimumHeight", 220)
        ui.sized(stats_frame, "setMaximumHeight", 220)
        stats_frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        stats_layout = QVBoxLayout(stats_frame)
        stats_layout.setContentsMargins(14, 10, 14, 12)
        stats_layout.setSpacing(6)
        stats_layout.addWidget(ui.label("STATISTICS", "pgSection"))
        self.poll_count_label = ui.label("Poll Count: 0", "pgValue")
        self.valid_response_label = ui.label("Valid Responses: 0", "pgValue")
        self.exception_label = ui.label("Exception Responses: 0", "pgValue")
        self.timeout_label = ui.label("Timeouts: 0", "pgValue")
        self.last_response_label = ui.label("Last Response: --", "pgValue")
        for label in (
            self.poll_count_label,
            self.valid_response_label,
            self.exception_label,
            self.timeout_label,
            self.last_response_label,
        ):
            stats_layout.addWidget(label)
        stats_layout.addStretch(1)
        bottom_layout.addWidget(stats_frame)
        right_layout.addLayout(bottom_layout)
        right_layout.addStretch(1)

        main_layout.addWidget(right_panel, 1)

        # Header stays fixed; only the page body scrolls when the window is small / DPI is high.
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setWidget(main)
        root.addWidget(scroll_area, 1)

        self._connection_type_changed()
    # -- Helper methods --

    def _field_label(self, text):
        label = QLabel(text)
        label.setProperty("class", "fieldLabel")
        return label

    def _set_status(self, text, color):
        self.status_label.setText(text)
        ui.set_status(self.status_label, getattr(self, "_status_dot", None), color)

    def _terminal(self, message):
        timestamp = time.strftime("%H:%M:%S")
        self.terminal.append(f"[{timestamp}] {message}")

    def _txrx(self, direction, data):
        timestamp = time.strftime("%H:%M:%S")
        if isinstance(data, bytes):
            text = data.hex(" ").upper()
        else:
            text = str(data)
        self.tx_rx_terminal.append(f"[{timestamp}] {direction}: {text}")
    # -- Back button / page reset --

    def _handle_back_clicked(self):
        # Always stop polling and close the active communication before
        # returning to the previous page.
        self._stop_polling()
        try:
            if self._serial_connection is not None:
                self._serial_connection.close()
        except Exception:
            pass
        try:
            if self._tcp_socket is not None:
                self._tcp_socket.close()
        except Exception:
            pass
        self._serial_connection = None
        self._tcp_socket = None
        self._connected = False
        self._waiting_response = False
        self._rx_buffer.clear()
        self._digital_states.clear()
        self._selected_coils.clear()
        self._register_values.clear()
        # Restore the same values the page has when it is first opened.
        self.connection_type.setCurrentText("Modbus RTU")
        self.baud_rate.setCurrentText("9600")
        self.data_bits.setCurrentText("8")
        self.parity.setCurrentText("None")
        self.stop_bits.setCurrentText("1")
        self.slave_id.setValue(1)
        self.ip_address.setText("192.168.1.100")
        self.subnet_mask.setText("255.255.255.0")
        self.tcp_port.setValue(502)
        self.unit_id.setValue(1)
        self.device_id.setValue(1)
        self.start_address.setValue(0)
        self.length.setValue(16)
        self.point_type.setCurrentIndex(0)
        self.poll_interval.setValue(500)
        self.timeout.setValue(1000)
        self.write_value.setValue(1)
        self.write_value.setVisible(False)
        self.write_value_label.setVisible(False)
        self._reset_counters()
        self.terminal.clear()
        self.tx_rx_terminal.clear()
        self._set_status("NOT CONNECTED", "#777777")
        self.connect_button.setText("CONNECT")
        self.run_button.setText("▶ RUN")
        self._connection_type_changed()
        self._update_data_display()
        self._refresh_ports()
        # Tell app.py to return to the previous page.
        self.back_clicked.emit()
    # -- Connection type handling --

    def _connection_type_changed(self):
        is_rtu = (self.connection_type.currentText() == "Modbus RTU")
        self.rtu_group.setVisible(is_rtu)
        self.tcp_group.setVisible(not is_rtu)

    def _refresh_ports(self):
        if list_ports is None:
            return
        current = self.com_port.currentText()
        self.com_port.clear()
        try:
            for port in list_ports.comports():
                self.com_port.addItem(port.device)
            if current:
                index = self.com_port.findText(current)
                if index >= 0:
                    self.com_port.setCurrentIndex(index)
        except Exception as exc:
            self._terminal(f"COM refresh error: {exc}")

    def _toggle_connection(self):
        if self._connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        if self.connection_type.currentText() == "Modbus RTU":
            self._connect_rtu()
        else:
            self._connect_tcp()

    def _connect_rtu(self):
        if not PYMODBUS_AVAILABLE:
            self._set_status("PYMODBUS NOT INSTALLED", "#D00000")
            self._terminal("Install PyModbus with: pip install pymodbus")
            return
        if list_ports is None:
            self._set_status("PYSerial NOT INSTALLED", "#D00000")
            return
        port = self.com_port.currentText().strip()
        if not port:
            self._set_status("SELECT COM PORT", "#D00000")
            return
        try:
            parity_map = {
                "None": "N",
                "Even": "E",
                "Odd": "O",
            }
            self._serial_connection = ModbusSerialClient(
                port=port,
                baudrate=int(self.baud_rate.currentText()),
                bytesize=int(self.data_bits.currentText()),
                parity=parity_map[self.parity.currentText()],
                stopbits=int(self.stop_bits.currentText()),
                timeout=self.timeout.value() / 1000.0,
                retries=0,
            )
            if not self._serial_connection.connect():
                self._serial_connection.close()
                self._serial_connection = None
                self._set_status("RTU CONNECTION ERROR", "#D00000")
                self._terminal(f"RTU connection failed: {port}")
                return
            self._connected = True
            self.device_id.setValue(self.slave_id.value())
            self.connect_button.setText("DISCONNECT")
            self._set_status("RTU CONNECTED", "#00A83B")
            self._terminal(f"RTU Connected: {port} | Slave ID: {self.slave_id.value()}")
        except Exception as exc:
            self._serial_connection = None
            self._connected = False
            self._set_status("RTU CONNECTION ERROR", "#D00000")
            self._terminal(f"RTU connection error: {exc}")

    def _connect_tcp(self):
        if not PYMODBUS_AVAILABLE:
            self._set_status("PYMODBUS NOT INSTALLED", "#D00000")
            self._terminal("Install PyModbus with: pip install pymodbus")
            return
        host = self.ip_address.text().strip()
        port = self.tcp_port.value()
        if not host:
            self._set_status("IP ADDRESS REQUIRED", "#D00000")
            return
        try:
            self._tcp_socket = ModbusTcpClient(
                host,
                port=port,
                timeout=self.timeout.value() / 1000.0,
                retries=0,
            )
            if not self._tcp_socket.connect():
                self._tcp_socket.close()
                self._tcp_socket = None
                self._set_status("TCP CONNECTION ERROR", "#D00000")
                self._terminal(f"TCP connection failed: {host}:{port}")
                return
            self._connected = True
            self.device_id.setValue(self.unit_id.value())
            self.connect_button.setText("DISCONNECT")
            self._set_status("TCP CONNECTED", "#00A83B")
            self._terminal(f"TCP Connected: {host}:{port} | Unit ID: {self.unit_id.value()}")
        except Exception as exc:
            self._tcp_socket = None
            self._connected = False
            self._set_status("TCP CONNECTION ERROR", "#D00000")
            self._terminal(f"TCP connection error: {exc}")

    def _disconnect(self):
        self._stop_polling()
        try:
            if self._serial_connection is not None:
                self._serial_connection.close()
        except Exception:
            pass
        try:
            if self._tcp_socket is not None:
                self._tcp_socket.close()
        except Exception:
            pass
        self._serial_connection = None
        self._tcp_socket = None
        self._connected = False
        self._waiting_response = False
        self.connect_button.setText("CONNECT")
        self._set_status("NOT CONNECTED", "#777777")
        self._terminal("Communication disconnected")

    def _apply_settings(self):
        was_running = self._running
        self._stop_polling()
        self._update_data_display()
        self._terminal("Communication settings applied")
        if was_running and self._connected:
            self._start_polling()

    def _toggle_run(self):
        if self._running:
            self._stop_polling()
        else:
            self._start_polling()

    def _start_polling(self):
        if not self._connected:
            self._set_status("CONNECT DEVICE FIRST", "#D00000")
            return
        if self._function_code() == 15:
            self._write_multiple_coils()
            return
        self._running = True
        self.run_button.setText("RUNNING")
        self._poll_timer.setInterval(self.poll_interval.value())
        self._poll_timer.start()
        self._terminal("Polling started")
        self._poll_cycle()

    def _poll_interval_changed(self, value):
        if self._running:
            self._poll_timer.setInterval(int(value))

    def _stop_polling(self):
        self._running = False
        self._poll_timer.stop()
        self._waiting_response = False
        if hasattr(self, "run_button"):
            self.run_button.setText("▶ RUN")

    def _point_type_changed(self):
        self._stop_polling()
        self._selected_coils.clear()
        is_write = self._function_code() in (5, 6, 15, 16)
        if hasattr(self, "write_value"):
            self.write_value.setVisible(is_write)
            self.write_value_label.setVisible(is_write)
        self._update_data_display()

    def _function_code(self):
        return [1, 2, 3, 4, 5, 6, 15, 16][self.point_type.currentIndex()]

    def _device_id_for_request(self):
        return self.device_id.value()

    def _pymodbus_call(self, method_name, address, *, count=None, device_id=None, values=None, value=None):
        if self.connection_type.currentText() == "Modbus RTU":
            client = self._serial_connection
        else:
            client = self._tcp_socket
        if client is None:
            raise ConnectionError("Modbus client is not connected")
        method = getattr(client, method_name)
        kwargs = {"device_id": device_id}
        if count is not None:
            kwargs["count"] = count
        if values is not None:
            kwargs["values"] = values
        if value is not None:
            kwargs["value"] = value
        try:
            return method(address, **kwargs)
        except TypeError:
            # Compatibility with older PyModbus releases using slave=.
            kwargs.pop("device_id", None)
            kwargs["slave"] = device_id
            return method(address, **kwargs)

    def _build_read_request(self, device_id, function, address, length):
        payload = bytes([
            device_id,
            function,
            (address >> 8) & 0xFF,
            address & 0xFF,
            (length >> 8) & 0xFF,
            length & 0xFF,
        ])
        if self.connection_type.currentText() == "Modbus TCP":
            self._last_transaction_id = (int(time.time() * 1000) & 0xFFFF)
            return (
                self._last_transaction_id.to_bytes(2, "big")
                + b"\x00\x00"
                + len(payload).to_bytes(2, "big")
                + payload
            )
        return payload + self._modbus_crc(payload)

    def _build_write_display_frame(self, device_id, function, address, value=None, count=1, values=None):
        if function == 5:
            payload = bytes([
                device_id, function,
                (address >> 8) & 0xFF, address & 0xFF,
                0xFF if value else 0x00, 0x00
            ])
        elif function == 6:
            payload = bytes([
                device_id, function,
                (address >> 8) & 0xFF, address & 0xFF,
                (value >> 8) & 0xFF, value & 0xFF
            ])
        elif function == 15:
            coil_values = list(values or [])
            byte_count = (len(coil_values) + 7) // 8
            packed = bytearray(byte_count)
            for i, state in enumerate(coil_values):
                if state:
                    packed[i // 8] |= 1 << (i % 8)
            payload = bytes([
                device_id, function,
                (address >> 8) & 0xFF, address & 0xFF,
                (len(coil_values) >> 8) & 0xFF, len(coil_values) & 0xFF,
                byte_count
            ]) + bytes(packed)
        else:
            register_values = list(values or [])
            raw = bytearray()
            for register in register_values:
                raw.extend([(register >> 8) & 0xFF, register & 0xFF])
            payload = bytes([
                device_id, function,
                (address >> 8) & 0xFF, address & 0xFF,
                (len(register_values) >> 8) & 0xFF, len(register_values) & 0xFF,
                len(raw)
            ]) + bytes(raw)
        if self.connection_type.currentText() == "Modbus TCP":
            self._last_transaction_id = (int(time.time() * 1000) & 0xFFFF)
            return (
                self._last_transaction_id.to_bytes(2, "big")
                + b"\x00\x00"
                + len(payload).to_bytes(2, "big")
                + payload
            )
        return payload + self._modbus_crc(payload)

    def _build_response_display_frame(self, device_id, function, bits=None, registers=None, address=0, count=0, write_values=None):
        if function in (5, 6, 15, 16):
            if function in (5, 6):
                values = write_values or [0]
                if function == 5:
                    payload = bytes([
                        device_id, function,
                        (address >> 8) & 0xFF, address & 0xFF,
                        0xFF if values[0] else 0x00, 0x00
                    ])
                else:
                    value = values[0]
                    payload = bytes([
                        device_id, function,
                        (address >> 8) & 0xFF, address & 0xFF,
                        (value >> 8) & 0xFF, value & 0xFF
                    ])
            else:
                payload = bytes([
                    device_id, function,
                    (address >> 8) & 0xFF, address & 0xFF,
                    (count >> 8) & 0xFF, count & 0xFF
                ])
        elif function in (1, 2):
            logical_bits = list(bits or [])[:count]
            byte_count = (len(logical_bits) + 7) // 8
            raw = bytearray(byte_count)
            for i, state in enumerate(logical_bits):
                if state:
                    raw[i // 8] |= 1 << (i % 8)
            payload = bytes([device_id, function, byte_count]) + bytes(raw)
        else:
            logical_registers = list(registers or [])[:count]
            raw = bytearray()
            for register in logical_registers:
                raw.extend([(register >> 8) & 0xFF, register & 0xFF])
            payload = bytes([device_id, function, len(raw)]) + bytes(raw)
        if self.connection_type.currentText() == "Modbus TCP":
            transaction = getattr(self, "_last_transaction_id", 0)
            return (
                transaction.to_bytes(2, "big")
                + b"\x00\x00"
                + len(payload).to_bytes(2, "big")
                + payload
            )
        return payload + self._modbus_crc(payload)

    def _poll_cycle(self):
        if not self._running or not self._connected:
            return
        function = self._function_code()
        address = self.start_address.value()
        length = self.length.value()
        # Function 04 AI: each displayed float uses two 16-bit registers.
        request_length = length * 2 if function == 4 else length
        device_id = self._device_id_for_request()
        self._poll_count += 1
        self._update_statistics()
        try:
            if function in (1, 2, 3, 4):
                request = self._build_read_request(device_id, function, address, request_length)
                self._txrx("TX", request)
                method = {
                    1: "read_coils",
                    2: "read_discrete_inputs",
                    3: "read_holding_registers",
                    4: "read_input_registers",
                }[function]
                response = self._pymodbus_call(
                    method,
                    address,
                    count=request_length,
                    device_id=device_id,
                )
                if response is None:
                    raise TimeoutError("No Modbus response")
                if response.isError():
                    self._exception_responses += 1
                    self._terminal(f"Modbus Exception: {response}")
                    self._update_statistics()
                    return
                self._valid_responses += 1
                if function in (1, 2):
                    bits = list(response.bits or [])[:length]
                    for i, state in enumerate(bits):
                        self._digital_states[address + i] = bool(state)
                    response_frame = self._build_response_display_frame(
                        device_id, function, bits=bits, count=length, address=address
                    )
                else:
                    registers = list(response.registers or [])[:length]
                    for i, value in enumerate(registers):
                        self._register_values[address + i] = int(value)
                    response_frame = self._build_response_display_frame(
                        device_id, function, registers=registers, count=request_length, address=address
                    )
                self._txrx("RX", response_frame)
                self.last_response_label.setText("Last Response: " + time.strftime("%H:%M:%S"))
                self._update_statistics()
                self._update_data_display()
            else:
                # Write functions are sent once from the UI. RUN does not
                # repeatedly write to the device.
                self._terminal("Write function selected. Use the point WRITE button.")
                self._stop_polling()
        except Exception as exc:
            self._timeouts += 1
            self._update_statistics()
            self._terminal(f"Modbus communication error: {exc}")
            if self.connection_type.currentText() == "Modbus RTU":
                if list_ports is not None:
                    try:
                        current_port = self.com_port.currentText()
                        available_ports = {p.device for p in list_ports.comports()}
                        if current_port not in available_ports:
                            self._handle_connection_lost("COM Port Not Found")
                    except Exception:
                        pass
            else:
                if self._tcp_socket is None or not getattr(self._tcp_socket, "connected", False):
                    self._handle_connection_lost("TCP connection lost")

    def _set_coil_selection(self, address, checked):
        if checked:
            self._selected_coils.add(address)
        else:
            self._selected_coils.discard(address)

    def _write_multiple_coils(self):
        if not self._connected:
            self._set_status("CONNECT DEVICE FIRST", "#D00000")
            return
        if not self._selected_coils:
            self._set_status("SELECT COILS FIRST", "#D00000")
            self._terminal("Select at least one coil")
            return
        start = self.start_address.value()
        length = self.length.value()
        address = start
        values = [index in self._selected_coils for index in range(start, start + length)]
        device_id = self._device_id_for_request()
        try:
            request_frame = self._build_write_display_frame(
                device_id, 15, address, values=values
            )
            self._txrx("TX", request_frame)
            response = self._pymodbus_call(
                "write_coils",
                address,
                device_id=device_id,
                values=values,
            )
            if response is None or response.isError():
                self._exception_responses += 1
                self._terminal(f"Multiple coil write error: {response}")
                self._update_statistics()
                return
            self._valid_responses += 1
            for index, state in enumerate(values):
                self._digital_states[address + index] = bool(state)
            response_frame = self._build_response_display_frame(
                device_id,
                15,
                address=address,
                count=len(values),
                write_values=values,
            )
            self._txrx("RX", response_frame)
            self._terminal(f"Multiple coils written: Address {address} - {address + len(values) - 1}")
            self.last_response_label.setText(
                "Last Response: " + time.strftime("%H:%M:%S")
            )
            self._update_statistics()
            self._stop_polling()
            self._update_data_display()
        except Exception as exc:
            self._timeouts += 1
            self._terminal(f"Multiple coil write error: {exc}")
            self._update_statistics()

    def _write_coil(self, channel):
        if not self._connected:
            self._set_status("CONNECT DEVICE FIRST", "#D00000")
            return
        address = self.start_address.value() + channel - 1
        current = self._digital_states.get(address, False)
        new_state = not current
        if self._function_code() == 15:
            self._digital_states[address] = new_state
            self._update_data_display()
            return
        device_id = self._device_id_for_request()
        function = self._function_code()
        try:
            use_single_coil = function == 5 or (
                function == 1
                and self.connection_type.currentText() == "Modbus TCP"
            )
            if use_single_coil:
                actual_function = 5
                request_frame = self._build_write_display_frame(
                    device_id, actual_function, address, value=new_state
                )
                self._txrx("TX", request_frame)
                response = self._pymodbus_call(
                    "write_coil",
                    address,
                    device_id=device_id,
                    value=new_state,
                )
            else:
                actual_function = 15
                request_frame = self._build_write_display_frame(
                    device_id, actual_function, address, values=[new_state]
                )
                self._txrx("TX", request_frame)
                response = self._pymodbus_call(
                    "write_coils",
                    address,
                    device_id=device_id,
                    values=[new_state],
                )
            if response is None or response.isError():
                self._exception_responses += 1
                self._terminal(f"DO write error: {response}")
                self._update_statistics()
                return
            self._valid_responses += 1
            self._digital_states[address] = new_state
            response_frame = self._build_response_display_frame(
                device_id,
                actual_function,
                address=address,
                count=1,
                write_values=[new_state],
            )
            self._txrx("RX", response_frame)
            self._terminal(f"DO Address {address}: {'ON' if new_state else 'OFF'}")
            self.last_response_label.setText("Last Response: " + time.strftime("%H:%M:%S"))
            self._update_statistics()
            self._update_data_display()
        except Exception as exc:
            self._timeouts += 1
            self._terminal(f"DO write error: {exc}")
            self._update_statistics()

    def _write_register(self, address):
        if not self._connected:
            self._set_status("CONNECT DEVICE FIRST", "#D00000")
            return
        device_id = self._device_id_for_request()
        function = self._function_code()
        value = self.write_value.value()
        try:
            if function == 6:
                request_frame = self._build_write_display_frame(
                    device_id, 6, address, value=value
                )
                self._txrx("TX", request_frame)
                response = self._pymodbus_call(
                    "write_register",
                    address,
                    device_id=device_id,
                    value=value,
                )
            else:
                values = [value] * self.length.value()
                request_frame = self._build_write_display_frame(
                    device_id, 16, address, values=values
                )
                self._txrx("TX", request_frame)
                response = self._pymodbus_call(
                    "write_registers",
                    address,
                    device_id=device_id,
                    values=values,
                )
            if response is None or response.isError():
                self._exception_responses += 1
                self._terminal(f"Register write error: {response}")
                self._update_statistics()
                return
            self._valid_responses += 1
            write_count = 1 if function == 6 else self.length.value()
            for i in range(write_count):
                self._register_values[address + i] = value
            response_frame = self._build_response_display_frame(
                device_id,
                function,
                address=address,
                count=write_count,
                write_values=[value],
            )
            self._txrx("RX", response_frame)
            self._terminal(f"Register write Address {address}: {value}")
            self.last_response_label.setText("Last Response: " + time.strftime("%H:%M:%S"))
            self._update_statistics()
            self._update_data_display()
        except Exception as exc:
            self._timeouts += 1
            self._terminal(f"Register write error: {exc}")
            self._update_statistics()
    # -- Connection monitoring --

    def _check_connection_status(self):
        if not self._connected:
            return
        if self.connection_type.currentText() == "Modbus RTU":
            # PyModbus exposes the active state through ``connected``.
            # Also verify the physical COM port is still present.
            if self._serial_connection is None or not getattr(self._serial_connection, "connected", False):
                self._handle_connection_lost("COM Port Not Found")
                return
            if list_ports is not None:
                try:
                    current_port = self.com_port.currentText()
                    available_ports = {port.device for port in list_ports.comports()}
                    if current_port not in available_ports:
                        self._handle_connection_lost("COM Port Not Found")
                except Exception:
                    pass
        else:
            if self._tcp_socket is None or not getattr(self._tcp_socket, "connected", False):
                self._handle_connection_lost("TCP connection lost")

    def _handle_connection_lost(self, message):
        self._stop_polling()
        try:
            if self._serial_connection is not None:
                self._serial_connection.close()
        except Exception:
            pass
        try:
            if self._tcp_socket is not None:
                self._tcp_socket.close()
        except Exception:
            pass
        self._serial_connection = None
        self._tcp_socket = None
        self._connected = False
        self._waiting_response = False
        self.connect_button.setText("CONNECT")
        self._set_status(message, "#D00000")
        self._terminal(message)
    # -- Update display --

    def _clear_data_layout(self):
        while self.data_layout.count():
            item = self.data_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _update_data_display(self):
        if not hasattr(self, "data_layout"):
            return
        self._clear_data_layout()
        if self._function_code() in (1, 2, 5, 15):
            self._build_digital_grid()
            rows = (self.length.value() + 7) // 8
            row_h = 118 if self._function_code() == 15 else 96
            desired_height = 20 + (rows * row_h) + 20
            # Keep the normal 8/16/32-point views comfortably visible,
            # but cap the viewport so the lower TX/RX and Statistics panels
            # never get pushed off the page.
            self.data_scroll.setFixedHeight(ui.px(min(400, max(250, desired_height))))
        else:
            self._build_register_table()
            self.data_scroll.setFixedHeight(ui.px(400))

    def _build_digital_grid(self):
        start = self.start_address.value()
        length = self.length.value()
        for index in range(length):
            address = start + index
            state = self._digital_states.get(address, False)
            card_h = ui.px(110 if self._function_code() == 15 else 88)
            card = ui.tile()
            ui.set_state(card, "on" if state else "")
            card.setMinimumSize(0, card_h)
            card.setMaximumHeight(card_h)
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(ui.px(10), ui.px(8), ui.px(10), ui.px(8))
            card_layout.setSpacing(ui.px(3))
            top_row = QHBoxLayout()
            top_row.setSpacing(ui.px(6))
            indicator = ui.led()
            ui.set_state(indicator, "on" if state else "")
            title = ui.label(f"CH-{index + 1}", "pgValue")
            state_label = QLabel("ON" if state else "OFF")
            ui.tss(state_label,
                   "QLabel { color:@ok; font-size:12px; font-weight:700; background:transparent; }" if state else
                   "QLabel { color:@muted; font-size:12px; font-weight:600; background:transparent; }")
            top_row.addWidget(indicator)
            top_row.addWidget(title)
            top_row.addStretch()
            top_row.addWidget(state_label)
            card_layout.addLayout(top_row)
            address_label = ui.label(f"Address: {address:05d}", "pgSub")
            card_layout.addWidget(address_label)
            card_layout.addStretch(1)
            if self._function_code() in (1, 5, 15):
                toggle = QPushButton("ON" if state else "OFF")
                toggle.setObjectName("pgToggle")
                toggle.setProperty("state", "on" if state else "")
                toggle.setCursor(Qt.PointingHandCursor)
                toggle.setFocusPolicy(Qt.NoFocus)
                toggle.setFixedHeight(ui.px(24))
                toggle.clicked.connect(lambda checked=False, ch=index + 1: self._write_coil(ch))
                card_layout.addWidget(toggle)
                if self._function_code() == 15:
                    select = QCheckBox("SELECT")
                    select.setChecked(address in self._selected_coils)
                    select.setFixedHeight(ui.px(18))
                    select.stateChanged.connect(
                        lambda checked, addr=address: self._set_coil_selection(addr, checked)
                    )
                    card_layout.addWidget(select)
            row = index // 8
            column = index % 8
            self.data_layout.addWidget(card, row, column)
        for column in range(8):
            self.data_layout.setColumnStretch(column, 1)
        rows = (length + 7) // 8
        # Cards keep their size; the free space goes below the last row.
        self.data_layout.setContentsMargins(ui.px(10), ui.px(10), ui.px(10), ui.px(10))
        self.data_layout.setHorizontalSpacing(ui.px(8))
        self.data_layout.setVerticalSpacing(ui.px(8))
        for r in range(self.data_layout.rowCount()):
            self.data_layout.setRowStretch(r, 0)
        self.data_layout.setRowStretch(rows, 1)
        card_h = 110 if self._function_code() == 15 else 88
        content_height = ui.px(rows * card_h + max(0, rows - 1) * 8 + 20)
        self.data_container.setMinimumHeight(content_height)

    def _build_register_table(self):
        start = self.start_address.value()
        length = self.length.value()
        table = QTableWidget()
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["POINT", "ADDRESS", "DECIMAL", "HEX", "ACTION"])
        table.setRowCount(length)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(ui.px(34))
        table.setShowGrid(False)
        table.setAlternatingRowColors(False)
        table.setSelectionMode(QTableWidget.NoSelection)
        for i in range(length):
            # Function 04: one displayed point = two consecutive registers.
            address = start + (i * 2 if self._function_code() == 4 else i)
            value = self._register_values.get(address, 0)
            table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            table.setItem(i, 1, QTableWidgetItem(f"{address:05d}"))
            table.setItem(i, 2, QTableWidgetItem(str(value)))
            table.setItem(i, 3, QTableWidgetItem(f"{value:04X}"))
            # Function 04 AI display: two 16-bit Modbus registers form
            # one IEEE-754 32-bit big-endian float, matching Test View.
            if self._function_code() == 4:
                first_register = self._register_values.get(address, 0)
                second_register = self._register_values.get(address + 1, 0)
                float_bytes = bytes([
                    (first_register >> 8) & 0xFF,
                    first_register & 0xFF,
                    (second_register >> 8) & 0xFF,
                    second_register & 0xFF,
                ])
                try:
                    float_value = struct.unpack(">f", float_bytes)[0]
                    if float_value == float_value and abs(float_value) != float("inf"):
                        table.setItem(i, 4, QTableWidgetItem(f"{float_value:.3f}"))
                except (struct.error, ValueError, OverflowError):
                    pass
            if self._function_code() in (6, 16):
                write_button = QPushButton("WRITE")
                write_button.setObjectName("pgMini")
                write_button.setCursor(Qt.PointingHandCursor)
                write_button.setFixedHeight(ui.px(26))
                write_button.clicked.connect(
                    lambda checked=False, addr=address: self._write_register(addr)
                )
                holder = QWidget()
                holder_layout = QHBoxLayout(holder)
                holder_layout.setContentsMargins(10, 4, 10, 4)
                holder_layout.addWidget(write_button)
                table.setCellWidget(i, 4, holder)
        table.setMinimumSize(0, 0)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # Fill the complete MODBUS DATA viewport instead of keeping
        # the QTableWidget at its small default size.
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setStretchLastSection(False)
        self.data_layout.setContentsMargins(0, 0, 0, 0)
        self.data_layout.setHorizontalSpacing(0)
        self.data_layout.setVerticalSpacing(0)
        self.data_layout.setColumnStretch(0, 1)
        self.data_layout.setRowStretch(0, 1)
        self.data_layout.addWidget(table, 0, 0, 1, 1)
        self._register_table = table
        self._fit_register_table()
        QTimer.singleShot(0, self._fit_register_table)

    def retheme_page(self):
        """Theme / UI size changed (ui_theme.apply_theme): the MODBUS DATA cards are built with sizes of the
        moment, so they are built again."""
        if hasattr(self, "data_layout"):
            self._update_data_display()

    def _fit_register_table(self):
        """Keep the register table the same size as the MODBUS DATA viewport."""
        if not hasattr(self, "_register_table") or self._register_table is None:
            return
        if not hasattr(self, "data_scroll") or not hasattr(self, "data_container"):
            return
        viewport = self.data_scroll.viewport()
        if viewport is None:
            return
        width = max(0, viewport.width())
        height = max(0, viewport.height())
        # The container and table must both be at least the viewport size;
        # this prevents the table from collapsing to its contents/default size.
        self.data_container.setMinimumWidth(width)
        self.data_container.setMinimumHeight(height)
        self._register_table.setMinimumWidth(width)
        self._register_table.setMinimumHeight(height)
    # -- Statistics --

    def _reset_counters(self):
        self._poll_count = 0
        self._valid_responses = 0
        self._exception_responses = 0
        self._timeouts = 0
        self.last_response_label.setText("Last Response: --")
        self._update_statistics()
        self._terminal("Counters reset")

    def _update_statistics(self):
        self.poll_count_label.setText(f"Poll Count: {self._poll_count}")
        self.valid_response_label.setText(f"Valid Responses: {self._valid_responses}")
        self.exception_label.setText(f"Exception Responses: {self._exception_responses}")
        self.timeout_label.setText(f"Timeouts: {self._timeouts}")

    @staticmethod
    def _modbus_crc(data):
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 1:
                    crc >>= 1
                    crc ^= 0xA001
                else:
                    crc >>= 1
        return bytes([crc & 0xFF, (crc >> 8) & 0xFF])

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_register_table"):
            QTimer.singleShot(0, self._fit_register_table)

    def closeEvent(self, event):
        self._stop_polling()
        try: self._connection_timer.stop()
        except Exception: pass
        try: self._poll_timer.stop()
        except Exception: pass
        try:
            if self._serial_connection:
                self._serial_connection.close()
        except Exception:
            pass
        try:
            if self._tcp_socket:
                self._tcp_socket.close()
        except Exception:
            pass
        self._serial_connection = None
        self._tcp_socket = None
        event.accept()