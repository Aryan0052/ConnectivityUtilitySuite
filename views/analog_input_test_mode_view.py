import os
import struct
from datetime import datetime, timezone
from database.mongodb import MongoDB
from PySide6.QtCore import Signal, Qt, QPoint, QTimer
from PySide6.QtGui import QFont, QPixmap, QPainter, QPen, QImage
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QDoubleSpinBox,
    QSlider,
    QFrame,
    QPlainTextEdit,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
)

try:
    from . import ui_theme as ui
except ImportError:
    import ui_theme as ui

# Test-mode specific widgets (colours are @tokens of the shared light / dark palette)
TEST_MODE_QSS = """
QFrame#tmCard { background:@surface; border:1px solid @border; border-radius:12px; }
QLabel#tmChannel { color:@text; font-size:14px; font-weight:700; }
QLabel#tmCaption { color:@muted; font-size:11px; font-weight:700; letter-spacing:1px; }
QFrame#tmTypeChip { background:@accent_soft; border:1px solid @accent; border-radius:10px; }
QLabel#tmTypeValue { color:@accent_text; font-size:11px; font-weight:700; }
QDoubleSpinBox#tmValue { background:@sunken; border:1px solid @border; border-radius:8px; color:@text;
    font-family:"Segoe UI"; font-size:18px; font-weight:700; padding:0 10px; }
QSlider#tmBar::groove:horizontal { height:6px; background:@sunken; border:1px solid @border; border-radius:3px; }
QSlider#tmBar::sub-page:horizontal { background:@accent; border-radius:3px; }
QSlider#tmBar::handle:horizontal { width:12px; height:12px; margin:-4px 0; background:@accent;
    border:2px solid @surface; border-radius:7px; }
"""

class BackButton(QPushButton):
    """White circular back button matching the main application header."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(58, 58)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
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
        painter.setPen(Qt.NoPen)
        painter.setBrush(Qt.white)
        painter.drawEllipse(0, 0, 58, 58)
        pen = QPen("#155B91")
        pen.setWidth(6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(QPoint(19, 29), QPoint(43, 29))
        painter.drawLine(QPoint(19, 29), QPoint(31, 17))
        painter.drawLine(QPoint(19, 29), QPoint(31, 41))
        painter.end()
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
CHANNEL_INPUT_TYPE_VALUES = {
    0: "0-50mV",
    1: "0-100mV",
    2: "0-250mV",
    3: "0-5V",
    4: "0-10V",
    5: "4-20mA",
    6: "0-20mA",
    7: "-250mV to +250mV",
    8: "-10V to +10V",
}

class AnalogInputTestModeView(QWidget):
    """UI-only Analog Input Test Mode view.
    Communication/protocol logic is intentionally not included yet.
    """
    back_clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Connectivity Utility Suite")
        self.setMinimumSize(1100, 870)
        self._serial_connection_provider = None
        self._slave_id_provider = None
        self._refresh_buffer = bytearray()
        self._refresh_expected_length = 21
        self._refresh_timer = None
        self._refresh_timeout_timer = None
        self._run_buffer = bytearray()
        self._run_timer = None
        self._run_timeout_timer = None
        self._run_active = False
        self._com_port_monitor_timer = QTimer(self)
        self._com_port_monitor_timer.timeout.connect(self._check_com_port_connection)
        self._com_port_monitor_timer.start(500)
        # ---------------------------------------------------------
        # MONGODB
        # ---------------------------------------------------------
        self._mongo = None
        self._mongo_collection = None
        self._channel_cards = []
        # Build the UI first; connect to MongoDB after the page is visible.
        self._build_ui()
        QTimer.singleShot(100, self._init_mongodb)

    def set_connection_context(self, serial_connection_provider, slave_id_provider):
        self._serial_connection_provider = serial_connection_provider
        self._slave_id_provider = slave_id_provider
        print("[TEST MODE] Connection context set")
        try:
            serial_connection = (
                self._serial_connection_provider()
                if self._serial_connection_provider is not None
                else None
            )
        except Exception:
            serial_connection = None
        if serial_connection is not None and serial_connection.is_open:
            self._append_terminal("Connection context ready")

    def _build_ui(self):
        # Look: shared with the other pages and the Multi Device page (ui_theme.py). Only widgets and
        # styles are built here - every attribute the Refresh / Run / database code uses keeps its name.
        ui.install(self)
        ui.tss(self, ui.PAGE_QSS + TEST_MODE_QSS)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = ui.Header("Analog Input  ·  Test Mode", root=self)
        back = header.back_button
        back.clicked.connect(self.back_clicked.emit)
        header.status.setText("Test Mode")
        ui.set_status(header.status, header.status_dot, "#1684BE")
        root.addWidget(header)

        # ---------------------------------------------------------
        # MAIN AREA
        # ---------------------------------------------------------
        main = QWidget()
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(20, 18, 20, 18)
        main_layout.setSpacing(14)

        # Title row: page title on the left, actions on the right.
        top = ui.card()
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(20, 14, 20, 14)
        top_layout.setSpacing(10)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_col.addWidget(ui.label("Analog Input", "pgTitle"))
        title_col.addWidget(ui.label("Simulate and test analog input values for all channels", "pgSub"))
        top_layout.addLayout(title_col)
        top_layout.addStretch(1)

        refresh_button = ui.button("↻  REFRESH", "secondary", 36)
        ui.sized(refresh_button, "setMinimumWidth", 120)
        top_layout.addWidget(refresh_button)
        run_button = ui.button("▶  RUN", "primary", 36, alt={"STOP": "danger", "RUN": "primary"})
        ui.sized(run_button, "setMinimumWidth", 120)
        top_layout.addWidget(run_button)
        analysis_button = ui.button("DATA ANALYSIS", "secondary", 36)
        ui.sized(analysis_button, "setMinimumWidth", 140)
        top_layout.addWidget(analysis_button)
        main_layout.addWidget(top)

        # 8 channels in a 4 x 2 grid.
        main_layout.addWidget(ui.section("Channels"))
        channel_grid = QGridLayout()
        channel_grid.setHorizontalSpacing(14)
        channel_grid.setVerticalSpacing(14)
        for channel in range(1, 9):
            card = self._create_channel_card(channel)
            row = 0 if channel <= 4 else 1
            column = (channel - 1) % 4
            channel_grid.addWidget(card, row, column)
        for column in range(4):
            channel_grid.setColumnStretch(column, 1)
        main_layout.addLayout(channel_grid)

        # ---------------------------------------------------------
        # TERMINAL
        # ---------------------------------------------------------
        terminal_panel = ui.card()
        terminal_layout = QVBoxLayout(terminal_panel)
        terminal_layout.setContentsMargins(16, 12, 16, 14)
        terminal_layout.setSpacing(8)

        terminal_header = QHBoxLayout()
        terminal_header.setContentsMargins(0, 0, 0, 0)
        terminal_header.setSpacing(8)
        terminal_header.addWidget(ui.label("TEST MODE TERMINAL", "pgSection"))
        terminal_header.addStretch()
        clear_terminal_button = ui.button("Clear Terminal", "ghost")
        clear_terminal_button.clicked.connect(self.clear_terminal)
        terminal_header.addWidget(clear_terminal_button)
        terminal_layout.addLayout(terminal_header)

        self.terminal = ui.terminal()
        # Keep a large terminal history so repeated Refresh operations
        # do not quickly remove older debug output.
        self.terminal.document().setMaximumBlockCount(100000)
        self.terminal.setUndoRedoEnabled(False)
        self.terminal.setPlainText("Test mode ready...")
        ui.sized(self.terminal, "setMinimumHeight", 190)
        terminal_layout.addWidget(self.terminal, 1)
        main_layout.addWidget(terminal_panel, 1)

        # Keep the header fixed. The main content becomes vertically
        # scrollable only when it is taller than the available screen area.
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setFrameShape(QFrame.NoFrame)
        main.setMinimumHeight(700)
        scroll_area.setWidget(main)
        root.addWidget(scroll_area, 1)

        # Refresh uses the existing Analog Input COM connection.
        refresh_button.clicked.connect(self._handle_refresh)
        self._refresh_button = refresh_button

        # RUN uses the same existing Analog Input COM connection.
        run_button.clicked.connect(self._handle_run)
        self._run_button = run_button
        # DATA ANALYSIS is connected by app.py (found by its text).

    def _create_channel_card(self, channel):
        card = ui.card()
        card.setObjectName("tmCard")
        ui.sized(card, "setMinimumHeight", 176)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        # Title row: "Channel N" and the detected input type chip
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        channel_title = ui.label(f"Channel {channel}", "tmChannel")
        title_row.addWidget(channel_title)
        title_row.addStretch(1)
        detected_type_box = QFrame()
        detected_type_box.setObjectName("tmTypeChip")
        detected_type_layout = QHBoxLayout(detected_type_box)
        detected_type_layout.setContentsMargins(10, 3, 10, 3)
        detected_type = ui.label("Not Detected", "tmTypeValue")
        detected_type_layout.addWidget(detected_type)
        title_row.addWidget(detected_type_box)
        layout.addLayout(title_row)

        channel_card = {
            "channel": channel,
            "detected_type": detected_type,
        }

        value_row = QHBoxLayout()
        value_row.setSpacing(8)
        value_label = ui.label("Voltage", "tmCaption")
        value = QDoubleSpinBox()
        value.setObjectName("tmValue")
        value.setRange(-1000000.0, 1000000.0)
        value.setDecimals(3)
        value.setSingleStep(0.10)
        value.setValue(0.00)
        value.setSuffix(" V")
        ui.sized(value, "setMinimumWidth", 130)
        ui.sized(value, "setFixedHeight", 40)
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        value.setReadOnly(True)
        value.setButtonSymbols(QDoubleSpinBox.NoButtons)
        value.setFocusPolicy(Qt.NoFocus)
        value_row.addWidget(value_label)
        value_row.addStretch()
        value_row.addWidget(value)
        layout.addLayout(value_row)

        channel_card["value"] = value
        channel_card["value_label"] = value_label
        self._channel_cards.append(channel_card)

        slider = QSlider(Qt.Horizontal)
        slider.setObjectName("tmBar")
        slider.setRange(0, 1000)
        slider.setValue(0)
        ui.sized(slider, "setFixedHeight", 18)
        slider.setEnabled(False)
        layout.addWidget(slider)
        channel_card["slider"] = slider

        range_row = QHBoxLayout()
        min_label = ui.label("0", "pgHint")
        max_label = ui.label("10", "pgHint")
        range_row.addWidget(min_label)
        range_row.addStretch()
        range_row.addWidget(max_label)
        layout.addLayout(range_row)

        slider.valueChanged.connect(
            lambda raw, spin=value: spin.setValue(raw / 100.0)
        )
        value.valueChanged.connect(
            lambda current, slider_widget=slider: slider_widget.setValue(
                max(0, min(1000, int(round(current * 100))))
            )
        )
        return card

    def calculate_modbus_crc(self, data):
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc & 0xFFFF

    def build_multi_channel_refresh_frame(self, slave_id):
        # Multi-channel GET command supplied by the device protocol:
        # SID | FC=03 | START=0000 | LENGTH=0008 | CRC
        data = bytes([
            slave_id,
            0x03,
            0x00,
            0x00,
            0x00,
            0x08,
        ])
        crc = self.calculate_modbus_crc(data)
        frame = data + bytes([crc & 0xFF, (crc >> 8) & 0xFF])
        print("[REFRESH] TX fields:")
        print(f"  Slave ID : 0x{slave_id:02X}")
        print("  Function : 0x03")
        print("  Address  : 0x0000")
        print("  Length   : 0x0008")
        print(f"  CRC      : 0x{crc:04X} (TX low byte first)")
        print(f"[REFRESH] TX HEX ({len(frame)} bytes): {frame.hex(' ').upper()}")
        return frame

    def _handle_refresh(self):
        print("\n========== TEST MODE REFRESH START ==========")
        if self._serial_connection_provider is None:
            print("[REFRESH] ERROR: Serial connection provider is not set")
            self._append_terminal("ERROR: Connection context not set")
            return
        try:
            serial_connection = self._serial_connection_provider()
        except Exception as exc:
            print(f"[REFRESH] ERROR getting serial connection: {exc}")
            self._append_terminal(f"ERROR: {exc}")
            return
        print(f"[REFRESH] Serial connection object: {serial_connection}")
        if serial_connection is None:
            print("[REFRESH] ERROR: No serial connection")
            self._append_terminal("COM Port Not Connected")
            return
        if not serial_connection.is_open:
            print("[REFRESH] ERROR: Serial connection is closed")
            self._append_terminal("COM Port Not Connected")
            return
        try:
            slave_id = int(str(self._slave_id_provider()).strip())
        except Exception as exc:
            print(f"[REFRESH] ERROR reading Slave ID: {exc}")
            self._append_terminal("ERROR: Invalid Slave ID")
            return
        if not 1 <= slave_id <= 247:
            print(f"[REFRESH] ERROR: Invalid Slave ID {slave_id}")
            self._append_terminal("ERROR: Invalid Slave ID")
            return
        print(f"[REFRESH] Slave ID from Analog Input: {slave_id}")
        print(f"[REFRESH] Expected RX length: {self._refresh_expected_length} bytes")
        try:
            serial_connection.reset_input_buffer()
            print("[REFRESH] Serial input buffer cleared")
        except Exception as exc:
            print(f"[REFRESH] WARNING: Could not clear input buffer: {exc}")
        frame = self.build_multi_channel_refresh_frame(slave_id)
        self._refresh_buffer = bytearray()
        try:
            written = serial_connection.write(frame)
            print(f"[REFRESH] write() returned: {written}")
            print("[REFRESH] Multi-channel request sent")
            self._append_terminal(
                f"TX: {frame.hex(' ').upper()}"
            )
        except Exception as exc:
            print(f"[REFRESH] ERROR sending request: {exc}")
            self._append_terminal(f"TX ERROR: {exc}")
            return
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
        if self._refresh_timeout_timer is not None:
            self._refresh_timeout_timer.stop()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._poll_refresh_response)
        self._refresh_timer.start(20)
        self._refresh_timeout_timer = QTimer(self)
        self._refresh_timeout_timer.setSingleShot(True)
        self._refresh_timeout_timer.timeout.connect(self._refresh_timeout)
        self._refresh_timeout_timer.start(1500)
        print("[REFRESH] Waiting for 21-byte RX...")

    def _poll_refresh_response(self):
        serial_connection = None
        try:
            serial_connection = self._serial_connection_provider()
        except Exception as exc:
            print(f"[REFRESH] ERROR getting connection while polling: {exc}")
            self._finish_refresh()
            return
        if serial_connection is None or not serial_connection.is_open:
            print("[REFRESH] ERROR: Connection lost while waiting for RX")
            self._append_terminal("RX ERROR: Connection lost")
            self._finish_refresh()
            return
        try:
            waiting = serial_connection.in_waiting
        except Exception as exc:
            print(f"[REFRESH] ERROR reading in_waiting: {exc}")
            self._finish_refresh()
            return
        if waiting <= 0:
            return
        try:
            chunk = serial_connection.read(waiting)
        except Exception as exc:
            print(f"[REFRESH] ERROR reading RX: {exc}")
            self._append_terminal(f"RX ERROR: {exc}")
            self._finish_refresh()
            return
        if not chunk:
            return
        print(f"[REFRESH] RX CHUNK ({len(chunk)} bytes): {chunk.hex(' ').upper()}")
        self._refresh_buffer.extend(chunk)
        print(
            f"[REFRESH] RX BUFFER ({len(self._refresh_buffer)} bytes): "
            f"{bytes(self._refresh_buffer).hex(' ').upper()}"
        )
        if len(self._refresh_buffer) >= self._refresh_expected_length:
            response = bytes(self._refresh_buffer[:self._refresh_expected_length])
            extra = bytes(self._refresh_buffer[self._refresh_expected_length:])
            if extra:
                print(
                    f"[REFRESH] Extra RX bytes after expected 21 bytes: "
                    f"{extra.hex(' ').upper()}"
                )
            self._finish_refresh()
            self._process_multi_channel_refresh_response(response)

    def _refresh_timeout(self):
        print(
            f"[REFRESH] TIMEOUT - received {len(self._refresh_buffer)} "
            f"of {self._refresh_expected_length} expected bytes"
        )
        if self._refresh_buffer:
            print(
                f"[REFRESH] Partial RX: "
                f"{bytes(self._refresh_buffer).hex(' ').upper()}"
            )
            self._append_terminal(
                f"RX TIMEOUT: {len(self._refresh_buffer)}/"
                f"{self._refresh_expected_length} bytes"
            )
        else:
            self._append_terminal("RX TIMEOUT: No data received")
        self._finish_refresh()

    def _finish_refresh(self):
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
            self._refresh_timer.deleteLater()
            self._refresh_timer = None
        if self._refresh_timeout_timer is not None:
            self._refresh_timeout_timer.stop()
            self._refresh_timeout_timer.deleteLater()
            self._refresh_timeout_timer = None

    def _process_multi_channel_refresh_response(self, response):
        print("========== TEST MODE REFRESH RX PROCESSING ==========")
        print(f"[REFRESH] RX LENGTH: {len(response)} bytes")
        print(f"[REFRESH] RX HEX: {response.hex(' ').upper()}")
        if len(response) != 21:
            print(f"[REFRESH] ERROR: Expected 21 bytes, got {len(response)}")
            self._append_terminal(
                f"RX ERROR: Expected 21 bytes, got {len(response)}"
            )
            return
        slave_id = response[0]
        function_code = response[1]
        print(f"[REFRESH] RX Slave ID: 0x{slave_id:02X}")
        print(f"[REFRESH] RX Function Code: 0x{function_code:02X}")
        try:
            expected_slave_id = int(str(self._slave_id_provider()).strip())
        except Exception:
            expected_slave_id = None
        if expected_slave_id is not None and slave_id != expected_slave_id:
            print(
                f"[REFRESH] ERROR: Slave ID mismatch. "
                f"Expected {expected_slave_id}, got {slave_id}"
            )
            self._append_terminal("RX ERROR: Slave ID mismatch")
            return
        if function_code != 0x03:
            print(
                f"[REFRESH] ERROR: Function code mismatch. "
                f"Expected 0x03, got 0x{function_code:02X}"
            )
            self._append_terminal("RX ERROR: Function code mismatch")
            return
        # RX layout from the supplied multi-channel protocol:
        # SID | FC | BYTE COUNT | CH1 DATA ... CH8 DATA | CRC
        byte_count = response[2]
        data_bytes = response[3:19]
        received_crc = response[19] | (response[20] << 8)
        calculated_crc = self.calculate_modbus_crc(response[:19])
        print(f"[REFRESH] RX Byte Count: 0x{byte_count:02X} ({byte_count} bytes)")
        if byte_count != 16:
            print(
                f"[REFRESH] ERROR: Byte count mismatch. "
                f"Expected 16, got {byte_count}"
            )
            self._append_terminal("RX ERROR: Byte count mismatch")
            return
        print(
            f"[REFRESH] Channel data bytes (16): "
            f"{data_bytes.hex(' ').upper()}"
        )
        print(
            f"[REFRESH] Received CRC:   0x{received_crc:04X} "
            f"(bytes {response[19]:02X} {response[20]:02X})"
        )
        print(f"[REFRESH] Calculated CRC: 0x{calculated_crc:04X}")
        if received_crc != calculated_crc:
            print("[REFRESH] ERROR: CRC mismatch")
            self._append_terminal("RX ERROR: CRC mismatch")
            return
        print("[REFRESH] CRC OK")
        detected_types = []
        for channel in range(1, 9):
            offset = (channel - 1) * 2
            raw_value = (data_bytes[offset] << 8) | data_bytes[offset + 1]
            input_type_value = raw_value
            type_name = CHANNEL_INPUT_TYPE_VALUES.get(
                input_type_value,
                f"Unknown (0x{raw_value:04X})"
            )
            print(
                f"[REFRESH] CH{channel}: "
                f"raw=0x{raw_value:04X}, "
                f"decimal={raw_value}, "
                f"I/P Type={type_name}"
            )
            detected_types.append(type_name)
        for item in self._channel_cards:
            channel = item["channel"]
            if 1 <= channel <= len(detected_types):
                detected_type = detected_types[channel - 1]
                item["detected_type"].setText(detected_type)
                if "mA" in detected_type:
                    item["value_label"].setText("Current")
                    item["value"].setSuffix(" mA")
                elif "mV" in detected_type:
                    item["value_label"].setText("Voltage")
                    item["value"].setSuffix(" mV")
                elif "V" in detected_type:
                    item["value_label"].setText("Voltage")
                    item["value"].setSuffix(" V")
        self._append_terminal(
            "RX: " + response.hex(" ").upper()
        )
        self._append_terminal("Refresh successful")
        print("[REFRESH] SUCCESS: All 8 channel input types updated")
        print("========== TEST MODE REFRESH END ==========")

    def build_run_frame(self, slave_id):
        # RUN command supplied by the device protocol:
        # SID | FC=04 | START=0000 | LENGTH=0010 | CRC
        data = bytes([
            slave_id,
            0x04,
            0x00,
            0x00,
            0x00,
            0x10,
        ])
        crc = self.calculate_modbus_crc(data)
        frame = data + bytes([
            crc & 0xFF,
            (crc >> 8) & 0xFF
        ])
        print("[RUN] TX fields:")
        print(f"  Slave ID : 0x{slave_id:02X}")
        print("  Function : 0x04")
        print("  Address  : 0x0000")
        print("  Length   : 0x0010")
        print(f"  CRC      : 0x{crc:04X} (TX low byte first)")
        print(f"[RUN] TX HEX ({len(frame)} bytes): {frame.hex(' ').upper()}")
        return frame

    def _check_com_port_connection(self):
        if not self._run_active:
            return
        try:
            serial_connection = (
                self._serial_connection_provider()
                if self._serial_connection_provider is not None
                else None
            )
        except Exception:
            serial_connection = None
        if serial_connection is None or not serial_connection.is_open:
            self._run_active = False
            self._finish_run()
            self._run_button.setText("RUN")
            for card in self._channel_cards:
                card["slider"].setEnabled(False)
            self._append_terminal("RUN stopped: COM Port disconnected")

    def _handle_run(self):
        if self._run_active:
            print("[RUN] STOP requested")
            self._run_active = False
            self._finish_run()
            self._run_button.setText("RUN")
            for card in self._channel_cards:
                card["slider"].setEnabled(False)
            self._append_terminal("RUN stopped")
            return
        print("\n========== TEST MODE RUN START ==========")
        if self._serial_connection_provider is None:
            print("[RUN] ERROR: Serial connection provider is not set")
            self._append_terminal("RUN ERROR: Connection context not set")
            return
        try:
            serial_connection = self._serial_connection_provider()
        except Exception as exc:
            print(f"[RUN] ERROR getting serial connection: {exc}")
            self._append_terminal(f"RUN ERROR: {exc}")
            return
        print(f"[RUN] Serial connection object: {serial_connection}")
        if serial_connection is None:
            print("[RUN] ERROR: No serial connection")
            self._append_terminal("RUN ERROR: COM Port Not Connected")
            return
        if not serial_connection.is_open:
            print("[RUN] ERROR: Serial connection is closed")
            self._append_terminal("RUN ERROR: COM Port Not Connected")
            return
        try:
            slave_id = int(str(self._slave_id_provider()).strip())
        except Exception as exc:
            print(f"[RUN] ERROR reading Slave ID: {exc}")
            self._append_terminal("RUN ERROR: Invalid Slave ID")
            return
        if not 1 <= slave_id <= 247:
            print(f"[RUN] ERROR: Invalid Slave ID {slave_id}")
            self._append_terminal("RUN ERROR: Invalid Slave ID")
            return
        print(f"[RUN] Slave ID from Analog Input: {slave_id}")
        print("[RUN] Expected RX length: 37 bytes")
        self._run_active = True
        self._run_button.setText("STOP")
        for card in self._channel_cards:
            card["slider"].setEnabled(False)
        self._send_run_request()
        if self._run_active:
            print("[RUN] Continuous RUN active - press STOP to stop")
            print("[RUN] Waiting for 37-byte RX...")

    def _poll_run_response(self):
        try:
            serial_connection = self._serial_connection_provider()
        except Exception as exc:
            print(f"[RUN] ERROR getting connection while polling: {exc}")
            self._finish_run()
            return
        if serial_connection is None or not serial_connection.is_open:
            print("[RUN] ERROR: Connection lost while waiting for RX")
            self._append_terminal("RUN RX ERROR: Connection lost")
            self._finish_run()
            return
        try:
            waiting = serial_connection.in_waiting
        except Exception as exc:
            print(f"[RUN] ERROR reading in_waiting: {exc}")
            self._finish_run()
            return
        if waiting <= 0:
            return
        try:
            chunk = serial_connection.read(waiting)
        except Exception as exc:
            print(f"[RUN] ERROR reading RX: {exc}")
            self._append_terminal(f"RUN RX ERROR: {exc}")
            self._finish_run()
            return
        if not chunk:
            return
        print(f"[RUN] RX CHUNK ({len(chunk)} bytes): {chunk.hex(' ').upper()}")
        self._run_buffer.extend(chunk)
        print(
            f"[RUN] RX BUFFER ({len(self._run_buffer)} bytes): "
            f"{bytes(self._run_buffer).hex(' ').upper()}"
        )
        if len(self._run_buffer) >= 37:
            response = bytes(self._run_buffer[:37])
            extra = bytes(self._run_buffer[37:])
            if extra:
                print(
                    f"[RUN] Extra RX bytes after expected 37 bytes: "
                    f"{extra.hex(' ').upper()}"
                )
            self._finish_run()
            self._process_run_response(response)
            if self._run_active:
                QTimer.singleShot(500, self._run_next_cycle)

    def _run_timeout(self):
        print(
            f"[RUN] TIMEOUT - received {len(self._run_buffer)} "
            f"of 37 expected bytes"
        )
        if self._run_buffer:
            print(
                f"[RUN] Partial RX: "
                f"{bytes(self._run_buffer).hex(' ').upper()}"
            )
            self._append_terminal(
                f"RUN RX TIMEOUT: {len(self._run_buffer)}/37 bytes"
            )
        else:
            self._append_terminal("RUN RX TIMEOUT: No data received")
        self._finish_run()
        if self._run_active:
            QTimer.singleShot(500, self._run_next_cycle)

    def _run_next_cycle(self):
        if not self._run_active:
            return
        self._run_button.setText("STOP")
        self._send_run_request()

    def _send_run_request(self):
        try:
            serial_connection = self._serial_connection_provider()
        except Exception as exc:
            print(f"[RUN] ERROR getting serial connection: {exc}")
            self._append_terminal(f"RUN ERROR: {exc}")
            self._run_active = False
            self._run_button.setText("RUN")
            return
        if serial_connection is None or not serial_connection.is_open:
            print("[RUN] ERROR: Serial connection is closed")
            self._append_terminal("RUN ERROR: COM Port Not Connected")
            self._run_active = False
            self._run_button.setText("RUN")
            return
        try:
            slave_id = int(str(self._slave_id_provider()).strip())
        except Exception as exc:
            print(f"[RUN] ERROR reading Slave ID: {exc}")
            self._append_terminal("RUN ERROR: Invalid Slave ID")
            self._run_active = False
            self._run_button.setText("RUN")
            return
        if not 1 <= slave_id <= 247:
            print(f"[RUN] ERROR: Invalid Slave ID {slave_id}")
            self._append_terminal("RUN ERROR: Invalid Slave ID")
            self._run_active = False
            self._run_button.setText("RUN")
            return
        self._run_buffer = bytearray()
        try:
            serial_connection.reset_input_buffer()
        except Exception:
            pass
        frame = self.build_run_frame(slave_id)
        try:
            written = serial_connection.write(frame)
            print(f"[RUN] write() returned: {written}")
            print("[RUN] RUN request sent")
            self._append_terminal(f"TX: {frame.hex(' ').upper()}")
        except Exception as exc:
            print(f"[RUN] ERROR sending request: {exc}")
            self._append_terminal(f"RUN TX ERROR: {exc}")
            self._run_active = False
            self._run_button.setText("RUN")
            return
        self._run_timer = QTimer(self)
        self._run_timer.timeout.connect(self._poll_run_response)
        self._run_timer.start(20)
        self._run_timeout_timer = QTimer(self)
        self._run_timeout_timer.setSingleShot(True)
        self._run_timeout_timer.timeout.connect(self._run_timeout)
        self._run_timeout_timer.start(1500)

    def _finish_run(self):
        if hasattr(self, "_run_timer") and self._run_timer is not None:
            self._run_timer.stop()
            self._run_timer.deleteLater()
            self._run_timer = None
        if hasattr(self, "_run_timeout_timer") and self._run_timeout_timer is not None:
            self._run_timeout_timer.stop()
            self._run_timeout_timer.deleteLater()
            self._run_timeout_timer = None

    def _process_run_response(self, response):
        print("========== TEST MODE RUN RX PROCESSING ==========")
        print(f"[RUN] RX LENGTH: {len(response)} bytes")
        print(f"[RUN] RX HEX: {response.hex(' ').upper()}")
        if len(response) != 37:
            print(f"[RUN] ERROR: Expected 40 bytes, got {len(response)}")
            self._append_terminal(
                f"RUN RX ERROR: Expected 37 bytes, got {len(response)}"
            )
            return
        slave_id = response[0]
        function_code = response[1]
        byte_count = response[2]
        print(f"[RUN] RX Slave ID: 0x{slave_id:02X}")
        print(f"[RUN] RX Function Code: 0x{function_code:02X}")
        print(f"[RUN] RX Byte Count: 0x{byte_count:02X} ({byte_count} bytes)")
        try:
            expected_slave_id = int(str(self._slave_id_provider()).strip())
        except Exception:
            expected_slave_id = None
        if expected_slave_id is not None and slave_id != expected_slave_id:
            print(
                f"[RUN] ERROR: Slave ID mismatch. "
                f"Expected {expected_slave_id}, got {slave_id}"
            )
            self._append_terminal("RUN RX ERROR: Slave ID mismatch")
            return
        if function_code != 0x04:
            print(
                f"[RUN] ERROR: Function code mismatch. "
                f"Expected 0x04, got 0x{function_code:02X}"
            )
            self._append_terminal("RUN RX ERROR: Function code mismatch")
            return
        if byte_count != 0x20:
            print(
                f"[RUN] ERROR: RX byte count mismatch. "
                f"Expected 0x20 (32), got 0x{byte_count:02X} ({byte_count})"
            )
            self._append_terminal("RUN RX ERROR: Byte count mismatch")
            return
        float_data = response[3:35]
        received_crc = response[35] | (response[36] << 8)
        calculated_crc = self.calculate_modbus_crc(response[:35])
        print(
            f"[RUN] FLOAT DATA (32 bytes): "
            f"{float_data.hex(' ').upper()}"
        )
        print(
            f"[RUN] Received CRC:   0x{received_crc:04X} "
            f"(bytes {response[35]:02X} {response[36]:02X})"
        )
        print(f"[RUN] Calculated CRC: 0x{calculated_crc:04X}")
        if received_crc != calculated_crc:
            print("[RUN] ERROR: CRC mismatch")
            self._append_terminal("RUN RX ERROR: CRC mismatch")
            return
        print("[RUN] CRC OK")
        # The protocol specifies 8 channels x 4 bytes.
        # The current implementation uses IEEE-754 32-bit BIG-ENDIAN
        # conversion for each channel.
        voltage_values = []
        for channel in range(1, 9):
            start = (channel - 1) * 4
            channel_bytes = float_data[start:start + 4]
            try:
                value = struct.unpack(">f", channel_bytes)[0]
                rounded_value = round(value, 3)
                voltage_values.append(rounded_value)
                if channel <= len(self._channel_cards):
                    self._channel_cards[channel - 1]["value"].setValue(rounded_value)
                print(
                    f"[RUN] CH{channel} HEX   : "
                    f"{channel_bytes.hex(' ').upper()}"
                )
                print(f"[RUN] CH{channel} FLOAT : {value}")
            except struct.error as exc:
                print(f"[RUN] CH{channel} FLOAT ERROR: {exc}")
        self._append_terminal(
            "RX: " + response.hex(" ").upper()
        )
        self._append_terminal("RUN successful")
        self._save_run_to_mongodb(slave_id, voltage_values, response)
        print("[RUN] SUCCESS: 8 channel FLOAT values received")
        if self._run_active:
            self._run_button.setText("STOP")
        print("========== TEST MODE RUN END ==========")

    def _init_mongodb(self):
        """Connect to the central project MongoDB and prepare the Test Mode collection."""
        try:
            self._mongo = MongoDB()
            self._mongo_collection = self._mongo.get_collection("analog_input_test_data")
            self._mongo_collection.create_index([("timestamp", -1)])
            self._mongo_collection.create_index(
                [("slave_id", 1), ("timestamp", -1)]
            )
            print("[MONGODB] Connected: nelumbo_utility.analog_input_test_data")
            if hasattr(self, "terminal"):
                self._append_terminal("Database: MongoDB connected")
        except Exception as exc:
            self._mongo = None
            self._mongo_collection = None
            print(f"[MONGODB] Connection ERROR: {exc}")
            if hasattr(self, "terminal"):
                self._append_terminal(f"DATABASE ERROR: {exc}")

    def _save_run_to_mongodb(self, slave_id, voltage_values, response):
        """Save one complete 8-channel RUN result to MongoDB."""
        try:
            if self._mongo_collection is None:
                self._init_mongodb()
            if self._mongo_collection is None:
                self._append_terminal("DATABASE ERROR: MongoDB Not Connected")
                return
            # A successful RUN must always contain all 8 channel values.
            if len(voltage_values) != 8:
                print(
                    f"[MONGODB] Save ERROR: Expected 8 channel values, "
                    f"got {len(voltage_values)}"
                )
                self._append_terminal(
                    f"DATABASE ERROR: Expected 8 channel values, got {len(voltage_values)}"
                )
                return
            channels = {}
            input_types = {}
            units = {}
            # Save every channel in the same logical structure as the Excel log:
            # channel -> value + unit + input type.
            for channel in range(1, 9):
                key = f"ch{channel}"
                value = float(voltage_values[channel - 1])
                card = self._channel_cards[channel - 1]
                detected_type = card["detected_type"].text().strip()
                if "mA" in detected_type:
                    unit = "mA"
                elif "mV" in detected_type:
                    unit = "mV"
                else:
                    unit = "V"
                channels[key] = {
                    "value": value,
                    "unit": unit,
                    "input_type": detected_type,
                }
                input_types[key] = detected_type
                units[key] = unit
            document = {
                "timestamp": datetime.now(timezone.utc),
                "device": "Analog Input",
                "mode": "Test Mode",
                "slave_id": int(slave_id),
                "channels": channels,
                "input_types": input_types,
                "units": units,
                "raw_rx": response.hex(" ").upper(),
            }
            result = self._mongo_collection.insert_one(document)
            print(f"[MONGODB] RUN saved: {result.inserted_id}")
            self._append_terminal("Database: RUN data saved (8 channels)")
        except Exception as exc:
            print(f"[MONGODB] Save ERROR: {exc}")
            self._append_terminal(f"DATABASE ERROR: {exc}")

    def _append_terminal(self, message):
        self.terminal.appendPlainText(message)

    def clear_terminal(self):
        self.terminal.clear()
        self.terminal.appendPlainText("Test mode ready...")

    def stop_all_tests(self):
        self._append_terminal("Stop All Tests clicked")

if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    window = AnalogInputTestModeView()
    window.showMaximized()
    sys.exit(app.exec())