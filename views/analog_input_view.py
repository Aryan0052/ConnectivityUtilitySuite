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
    QScrollArea,
    QPlainTextEdit,
)

try:
    from . import ui_theme as ui
except ImportError:
    import ui_theme as ui



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

        # Left RTU Settings communication.
        self._rtu_serial_connection = None
        self._rtu_connected_port = None
        self._rtu_com_port_monitor_timer = QTimer(self)
        self._rtu_com_port_monitor_timer.timeout.connect(
            self._check_rtu_com_port_connection
        )
        self._rtu_com_port_monitor_timer.start(1000)

        # Right Analog Input communication.
        self._serial_connection = None
        self._connected_port = None
        self._com_port_monitor_timer = QTimer(self)
        self._com_port_monitor_timer.timeout.connect(
            self._check_com_port_connection
        )
        self._com_port_monitor_timer.start(1000)

        self._apply_pending = False
        self._apply_buffer = bytearray()
        self._apply_timer = QTimer(self)
        self._apply_timer.timeout.connect(self._check_apply_response)
        self._apply_elapsed = 0

        self._connected_baud_rate = None
        self._rtu_connected_baud_rate = None
        self._apply_target_baud_rate = None
        self._apply_baud_timer = QTimer(self)
        self._apply_baud_timer.setSingleShot(True)
        self._apply_baud_timer.timeout.connect(self._switch_to_applied_baud)

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

        # Min/Max Offset Modbus state for Channels 1-8.
        self._channel_offset_pending = {channel: False for channel in range(1, 9)}
        self._channel_offset_buffer = {channel: bytearray() for channel in range(1, 9)}
        self._channel_offset_received_value = {
            channel: {"min": None, "max": None}
            for channel in range(1, 9)
        }
        self._channel_offset_timer = QTimer(self)
        self._channel_offset_timer.timeout.connect(
            self._check_channel_offset_response
        )
        self._channel_offset_elapsed = 0
        self._channel_offset_active_channel = None
        self._channel_offset_type = None
        self._selected_channel = None

        # Keep the original Channel 1 state names available.
        self._channel1_offset_pending = False
        self._channel1_offset_buffer = self._channel_offset_buffer[1]
        self._channel1_offset_timer = self._channel_offset_timer
        self._channel1_offset_elapsed = 0
        self._channel1_min_offset_received_value = None
        self._channel1_max_offset_received_value = None
        self._channel1_offset_type = None

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

        self.build_ui()

    def build_ui(self):
        # Look: shared with the other pages and the Multi Device page (ui_theme.py). Only widgets and
        # styles are built here - every attribute the communication code uses keeps its name.
        ui.install(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = ui.Header("Analog Input", root=self)
        back = header.back_button
        status = header.status
        self._status_dot = header.status_dot
        root.addWidget(header)

        main = QWidget()
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        # ------------------------------------------------------------ LEFT: RTU settings + terminal
        panel = ui.rtu_panel("Analog Input", id_label="Device ID (1-63)",
                             id_hint="Valid Device IDs: 1 to 63", section_title="RTU Device Settings")
        left_panel = panel.card
        connect, slave_id, baud = panel.connect, panel.id_edit, panel.baud
        apply_button, refresh = panel.apply, panel.refresh
        self.terminal_message = panel.terminal
        ui.sized(self.terminal_message, "setMinimumHeight", 180)

        # ------------------------------------------------------------ RIGHT: communication + channels
        right_panel = ui.card()
        right_layout = QVBoxLayout(right_panel)
        self.right_layout = right_layout
        right_layout.setContentsMargins(22, 20, 22, 20)
        right_layout.setSpacing(0)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_col.addWidget(ui.label("Analog Input", "pgTitle"))
        title_col.addWidget(ui.label("8 channels \u00b7 pick a channel to set input type, zero and span", "pgSub"))
        right_layout.addLayout(title_col)
        right_layout.addSpacing(14)

        # Analog Input communication settings (separate from the RTU settings on the left).
        comm_box = QFrame()
        comm_box.setObjectName("pgBox")
        communication_row = QHBoxLayout(comm_box)
        communication_row.setContentsMargins(14, 10, 14, 10)
        communication_row.setSpacing(10)

        analog_slave_id = QLineEdit("1")
        ui.sized(analog_slave_id, "setFixedWidth", 84)
        analog_slave_id.setValidator(QIntValidator(1, 63, self))
        analog_baud = QComboBox()
        analog_baud.addItems(["9600", "19200", "38400", "57600", "115200"])
        ui.sized(analog_baud, "setMinimumWidth", 110)
        analog_connect = ui.button("CONNECT", "primary", 36, alt={"DISCONNECT": "softdanger"})
        ui.sized(analog_connect, "setMinimumWidth", 130)

        communication_row.addWidget(ui.label("Device ID", "pgField"))
        communication_row.addWidget(analog_slave_id)
        communication_row.addSpacing(6)
        communication_row.addWidget(ui.label("Baud Rate", "pgField"))
        communication_row.addWidget(analog_baud)
        communication_row.addSpacing(6)
        communication_row.addWidget(analog_connect)
        communication_row.addStretch()
        right_layout.addWidget(comm_box)
        right_layout.addSpacing(16)

        # ANALOG INPUT CHANNELS (config box is inserted under the clicked channel by channel_selected)
        right_layout.addWidget(ui.section("Analog Input Channel"))
        right_layout.addSpacing(10)

        self._channel_selectors = []
        self._channel_rows = []

        for channel in range(1, 9):
            channel_button = QPushButton(f"Analog Input Channel - {channel}")
            channel_button.setObjectName("pgChannel")
            channel_button.setProperty("selected", False)
            channel_button.setCursor(Qt.PointingHandCursor)
            channel_button.setFocusPolicy(Qt.NoFocus)
            ui.sized(channel_button, "setMinimumWidth", 380)
            ui.sized(channel_button, "setMaximumWidth", 560)
            ui.sized(channel_button, "setFixedHeight", 42)
            channel_button.clicked.connect(
                lambda checked=False, ch=channel: self.channel_selected(ch)
            )

            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(channel_button, 1)
            row.addStretch(1)
            right_layout.addLayout(row)
            right_layout.addSpacing(8)
            self._channel_selectors.append(channel_button)
            self._channel_rows.append(row)

        # CHANNEL CONFIGURATION BOX
        self._channel_config_frame = QFrame()
        self._channel_config_frame.setObjectName("pgBox")
        ui.sized(self._channel_config_frame, "setMinimumWidth", 380)
        ui.sized(self._channel_config_frame, "setMaximumWidth", 560)
        self._channel_config_frame.setVisible(False)

        config_layout = QVBoxLayout(self._channel_config_frame)
        config_layout.setContentsMargins(14, 12, 14, 12)
        config_layout.setSpacing(10)

        def mini_apply():
            b = ui.button("APPLY", "primary", 30)
            b.setObjectName("pgMini")
            ui.sized(b, "setFixedWidth", 70)
            return b

        input_row = QHBoxLayout()
        input_row.setSpacing(10)
        input_label = ui.label("I/P Type", "pgField")
        ui.sized(input_label, "setMinimumWidth", 80)
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
        ui.sized(self._input_type, "setMinimumWidth", 190)
        input_ok = mini_apply()
        input_row.addWidget(input_label)
        input_row.addWidget(self._input_type, 1)
        input_row.addWidget(input_ok)
        input_ok.clicked.connect(self.handle_channel1_input_type_ok)
        config_layout.addLayout(input_row)

        min_row = QHBoxLayout()
        min_row.setSpacing(10)
        min_label = ui.label("Zero Value", "pgField")
        ui.sized(min_label, "setMinimumWidth", 80)
        self._min_offset = QLineEdit("-20000")
        self._min_offset.setValidator(QIntValidator(-20000, 20000, self))
        min_ok = mini_apply()
        min_row.addWidget(min_label)
        min_row.addWidget(self._min_offset, 1)
        min_row.addWidget(min_ok)
        min_ok.clicked.connect(self.handle_channel1_min_offset_ok)
        config_layout.addLayout(min_row)

        max_row = QHBoxLayout()
        max_row.setSpacing(10)
        max_label = ui.label("Span Value", "pgField")
        ui.sized(max_label, "setMinimumWidth", 80)
        self._max_offset = QLineEdit("+20000")
        self._max_offset.setValidator(QIntValidator(-20000, 20000, self))
        max_ok = mini_apply()
        max_row.addWidget(max_label)
        max_row.addWidget(self._max_offset, 1)
        max_row.addWidget(max_ok)
        max_ok.clicked.connect(self.handle_channel1_max_offset_ok)
        config_layout.addLayout(max_row)

        # Channel configuration refresh button.
        channel_refresh = ui.button("\u27f3  Refresh", "ghost")
        channel_refresh.setVisible(False)
        channel_refresh.clicked.connect(self.handle_channel_refresh)

        channel_refresh_row = QHBoxLayout()
        channel_refresh_row.setContentsMargins(0, 0, 0, 0)
        channel_refresh_row.addStretch()
        channel_refresh_row.addWidget(channel_refresh)
        config_layout.addLayout(channel_refresh_row)

        self._channel_refresh_button = channel_refresh

        # Test Mode button.
        test_mode_button = ui.button("TEST MODE", "secondary", 36)
        ui.sized(test_mode_button, "setMinimumWidth", 130)
        self._test_mode_button = test_mode_button

        config_row = QHBoxLayout()
        config_row.setContentsMargins(0, 4, 0, 0)
        config_row.addWidget(self._channel_config_frame, 1)
        config_row.addStretch(1)
        self._channel_config_row = config_row
        right_layout.addLayout(config_row)

        right_layout.addStretch()

        test_mode_row = QHBoxLayout()
        test_mode_row.setContentsMargins(0, 10, 0, 0)
        test_mode_row.addStretch()
        test_mode_row.addWidget(test_mode_button)
        right_layout.addLayout(test_mode_row)

        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_panel, 1)

        # Header stays fixed; only the main area scrolls when the window is small / DPI is high.
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setWidget(main)

        root.addWidget(scroll_area, 1)

        self._status = status

        # Left-side RTU Settings controls.
        self._rtu_connect_button = connect
        self._rtu_slave_id = slave_id
        self._rtu_baud = baud

        self.connect_button = connect
        self.slave_id = slave_id
        self.baud_rate = baud
        self.apply_button = apply_button
        self.refresh_button = refresh
        self.back_button = back

        # Right-side Analog Input communication controls.
        self._connect_button = analog_connect
        self._slave_id = analog_slave_id
        self._baud = analog_baud
        self.analog_connect_button = analog_connect
        self.analog_slave_id = analog_slave_id
        self.analog_baud_rate = analog_baud

        self.back_button.clicked.connect(self.handle_back)
        self._rtu_connect_button.clicked.connect(self.handle_connect)
        self._connect_button.clicked.connect(self.handle_analog_connect)
        self.apply_button.clicked.connect(self.handle_apply_rtu)
        self.refresh_button.clicked.connect(self.handle_refresh)

    def _set_status_color(self, color):
        ui.set_status(self._status, getattr(self, "_status_dot", None), color)

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
            self._set_status_color("#D00000")
            return

        from PySide6.QtWidgets import QDialog

        dialog = QDialog(self)
        dialog.setWindowTitle("COM Port")
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        title = QLabel("Select COM Port")
        layout.addWidget(title)

        port_box = QComboBox()
        port_box.addItems(ports)
        port_box.setFixedHeight(40)
        layout.addWidget(port_box)

        button_row = QHBoxLayout()
        connect_button = QPushButton("CONNECT")
        cancel_button = QPushButton("CANCEL")

        ui.skin_dialog(dialog, title, port_box, connect_button, cancel_button)

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

                self._rtu_serial_connection = serial.Serial(
                    selected_port,
                    int(self._rtu_baud.currentText()),
                    timeout=1
                )

                self._rtu_connected_port = selected_port
                self._rtu_connected_baud_rate = int(self._rtu_baud.currentText())
                self._status.setText("Connected")
                self._set_status_color("#00C928")
                self._rtu_connect_button.setText("DISCONNECT")
                dialog.accept()

            except Exception:
                self._rtu_serial_connection = None
                self._rtu_connected_port = None
                self._status.setText("Connection Error")
                self._set_status_color("#D00000")
                self._rtu_connect_button.setText("CONNECT")
                dialog.reject()

        connect_button.clicked.connect(connect_selected)
        cancel_button.clicked.connect(dialog.reject)
        dialog.exec()

    def _check_rtu_com_port_connection(self):
        if (
            self._rtu_serial_connection is None
            or not self._rtu_serial_connection.is_open
            or self._rtu_connected_port is None
        ):
            return

        try:
            available_ports = {
                port.device for port in list_ports.comports()
            }

            if self._rtu_connected_port not in available_ports:
                self._apply_baud_timer.stop()
                self._apply_target_baud_rate = None
                self._rtu_connected_baud_rate = None
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

                for channel in range(1, 9):
                    self._channel_offset_pending[channel] = False
                    self._channel_offset_buffer[channel].clear()
                self._channel_offset_timer.stop()
                self._channel_offset_active_channel = None
                self._channel_offset_type = None

                try:
                    self._rtu_serial_connection.close()
                finally:
                    self._rtu_serial_connection = None
                    self._rtu_connected_port = None

                self._status.setText("COM Port Disconnected")
                self._set_status_color("#D00000")
                self._rtu_connect_button.setText("CONNECT")

        except Exception as exc:
            print("COM Port Monitor Error:", exc)

    def handle_connect(self):
        if self._rtu_connect_button.text() == "DISCONNECT":
            self._apply_baud_timer.stop()
            self._apply_target_baud_rate = None
            self._rtu_connected_baud_rate = None
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
                if self._rtu_serial_connection is not None:
                    self._rtu_serial_connection.close()
            finally:
                self._rtu_serial_connection = None
                self._rtu_connected_port = None

            self._status.setText("Not Connected")
            self._set_status_color("#00C928")
            self._rtu_connect_button.setText("CONNECT")
            return

        self.show_com_port_popup()


    def show_analog_com_port_popup(self):
        ports = [port.device for port in list_ports.comports()]

        if not ports:
            self._status.setText("COM Port Not Found")
            self._set_status_color("#D00000")
            return

        from PySide6.QtWidgets import QDialog

        dialog = QDialog(self)
        dialog.setWindowTitle("Analog Input COM Port")
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        title = QLabel("Select COM Port")
        layout.addWidget(title)

        port_box = QComboBox()
        port_box.addItems(ports)
        port_box.setFixedHeight(40)
        layout.addWidget(port_box)

        button_row = QHBoxLayout()
        connect_button = QPushButton("CONNECT")
        cancel_button = QPushButton("CANCEL")

        ui.skin_dialog(dialog, title, port_box, connect_button, cancel_button)

        button_row.addWidget(connect_button)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)

        def connect_selected():
            selected_port = port_box.currentText().strip()

            if not selected_port:
                dialog.reject()
                return

            try:
                import serial

                self._serial_connection = serial.Serial(
                    selected_port,
                    int(self._baud.currentText()),
                    timeout=1,
                )

                self._connected_port = selected_port
                self._connected_baud_rate = int(self._baud.currentText())
                self._connect_button.setText("DISCONNECT")
                dialog.accept()

            except Exception as exc:
                print("Analog Input Connection Error:", exc)
                self._serial_connection = None
                self._connected_port = None
                self._connect_button.setText("CONNECT")
                self._status.setText("Connection Error")
                self._set_status_color("#D00000")
                dialog.reject()

        connect_button.clicked.connect(connect_selected)
        cancel_button.clicked.connect(dialog.reject)
        dialog.exec()

    def handle_analog_connect(self):
        if self._connect_button.text() == "DISCONNECT":
            self._clear_analog_pending_states()

            try:
                if self._serial_connection is not None:
                    self._serial_connection.close()
            except Exception:
                pass
            finally:
                self._serial_connection = None
                self._connected_port = None

            self._connect_button.setText("CONNECT")
            self._status.setText("Not Connected")
            self._set_status_color("#00C928")
            return

        self.show_analog_com_port_popup()

    def _clear_analog_pending_states(self):
        self._refresh_pending = False
        self._refresh_timer.stop()
        self._refresh_buffer.clear()

        self._channel1_iptype_pending = False
        self._channel1_iptype_timer.stop()
        self._channel1_iptype_buffer.clear()

        for channel in range(1, 9):
            self._channel_iptype_pending[channel] = False
            self._channel_iptype_buffer[channel].clear()

            self._channel_offset_pending[channel] = False
            self._channel_offset_buffer[channel].clear()

            self._channel_get_pending[channel] = False
            self._channel_get_buffer[channel].clear()

        self._channel_offset_timer.stop()
        self._channel_offset_active_channel = None
        self._channel_offset_type = None

        self._channel_get_timer.stop()
        self._channel_get_active_channel = None

    def _sync_analog_baud_rate(self):
        """Use the currently selected Analog Input baud rate on the
        already-open right-side COM port without reconnecting.
        """
        if self._serial_connection is None or not self._serial_connection.is_open:
            return False

        try:
            selected_baud = int(self._baud.currentText())
            if self._serial_connection.baudrate != selected_baud:
                self._serial_connection.baudrate = selected_baud
                self._serial_connection.reset_input_buffer()
                self._serial_connection.reset_output_buffer()
                self._connected_baud_rate = selected_baud
                print(f"Analog Input Baud Rate changed to: {selected_baud}")
            return True
        except Exception as exc:
            print(f"Analog Input Baud Rate change error: {exc}")
            return False

    def _check_com_port_connection(self):
        if (
            self._serial_connection is None
            or not self._serial_connection.is_open
            or self._connected_port is None
        ):
            return

        try:
            available_ports = {
                port.device for port in list_ports.comports()
            }

            if self._connected_port not in available_ports:
                self._clear_analog_pending_states()

                try:
                    self._serial_connection.close()
                finally:
                    self._serial_connection = None
                    self._connected_port = None

                self._connect_button.setText("CONNECT")
                self._status.setText("COM Port Disconnected")
                self._set_status_color("#D00000")

        except Exception as exc:
            print("Analog Input COM Port Monitor Error:", exc)

    def handle_apply_rtu(self):
        if (
            self._rtu_connect_button.text() != "DISCONNECT"
            or self._rtu_serial_connection is None
            or not self._rtu_serial_connection.is_open
        ):
            self._status.setText("COM Port not connected")
            self._set_status_color("#D00000")
            return

        slave_text = self._rtu_slave_id.text().strip()

        try:
            slave_id = int(slave_text)
        except ValueError:
            self._status.setText("Device ID must be 1 to 63")
            self._set_status_color("#D00000")
            return

        if not 1 <= slave_id <= 63:
            self._status.setText("Device ID must be 1 to 63")
            self._set_status_color("#D00000")
            return

        baud_rate = self._rtu_baud.currentText()
        target_baud_rate = int(baud_rate)
        command = f"SID={slave_id},MBD_BAUD={baud_rate}\n"

        if self._apply_pending:
            return

        try:
            self._rtu_serial_connection.reset_input_buffer()
            self._apply_buffer.clear()
            # Send using the currently active device baud; switch the local
            # serial port after the device has had time to process the command.
            self._rtu_serial_connection.write(command.encode("ascii"))
            self._rtu_serial_connection.flush()
            print(f"RTU SETTINGS TX: SID={slave_id}, BAUD={baud_rate}")

            self._apply_target_baud_rate = target_baud_rate
            self._apply_pending = True
            self._apply_elapsed = 0
            self._apply_timer.start(20)


        except Exception:
            self._apply_baud_timer.stop()
            self._apply_target_baud_rate = None
            self._apply_pending = False
            self._apply_timer.stop()
            self._apply_buffer.clear()
            self._status.setText("RTU Settings Not Applied")
            self._set_status_color("#D00000")

    def _switch_to_applied_baud(self):
        if (
            self._rtu_serial_connection is None
            or not self._rtu_serial_connection.is_open
            or self._apply_target_baud_rate is None
        ):
            return

        try:
            self._rtu_serial_connection.baudrate = self._apply_target_baud_rate
            self._connected_baud_rate = self._apply_target_baud_rate
        except Exception:
            pass

    def _check_apply_response(self):
        if not self._apply_pending:
            self._apply_timer.stop()
            return

        if (
            self._rtu_serial_connection is None
            or not self._rtu_serial_connection.is_open
        ):
            self._apply_baud_timer.stop()
            self._apply_target_baud_rate = None
            self._apply_pending = False
            self._apply_timer.stop()
            self._apply_buffer.clear()
            return

        try:
            waiting = self._rtu_serial_connection.in_waiting

            if waiting > 0:
                chunk = self._rtu_serial_connection.read(waiting)
                self._apply_buffer.extend(chunk)
                print(f"RTU SETTINGS RX: {chunk!r}")

            if b"\r\n" in self._apply_buffer:
                response, _, remaining = self._apply_buffer.partition(b"\r\n")
                complete_response = response + b"\r\n"
                self._apply_buffer = bytearray(remaining)

                if complete_response == b"OK:Settings Updated\r\n":
                    self._apply_baud_timer.stop()
                    if (
                        self._apply_target_baud_rate is not None
                        and self._rtu_connected_baud_rate != self._apply_target_baud_rate
                    ):
                        self._switch_to_applied_baud()
                    self._apply_target_baud_rate = None
                    self._apply_pending = False
                    self._apply_timer.stop()
                    self._apply_buffer.clear()

                    self.add_terminal_message("OK: Settings Applied")

                    self._status.setText("RTU Settings Applied")
                    self._set_status_color("#00C928")
                    return

                self._apply_baud_timer.stop()
                self._apply_target_baud_rate = None
                self._apply_pending = False
                self._apply_timer.stop()
                self._apply_buffer.clear()
                self._status.setText("RTU Settings Not Applied")
                self._set_status_color("#D00000")
                return

            self._apply_elapsed += 20

            if self._apply_elapsed >= 2000:
                self._apply_baud_timer.stop()
                self._apply_target_baud_rate = None
                self._apply_pending = False
                self._apply_timer.stop()
                self._apply_buffer.clear()
                self._status.setText("RTU Settings Not Applied")
                self._set_status_color("#D00000")

        except Exception:
            self._apply_baud_timer.stop()
            self._apply_target_baud_rate = None
            self._apply_pending = False
            self._apply_timer.stop()
            self._apply_buffer.clear()
            self._status.setText("RTU Settings Not Applied")
            self._set_status_color("#D00000")

    def handle_refresh(self):
        if (
            self._rtu_serial_connection is None
            or not self._rtu_serial_connection.is_open
        ):
            self._status.setText("COM Port Not Connected")
            self._set_status_color("#D00000")
            return

        if self._refresh_pending:
            return

        try:
            self._rtu_serial_connection.reset_input_buffer()
            self._refresh_buffer.clear()
            self._rtu_serial_connection.write(b"GETCFG\n")
            self._rtu_serial_connection.flush()

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
            self._rtu_serial_connection is None
            or not self._rtu_serial_connection.is_open
        ):
            self._refresh_pending = False
            self._refresh_timer.stop()
            self._refresh_buffer.clear()
            self._status.setText("COM Port Not Connected")
            self._set_status_color("#D00000")
            return

        try:
            waiting = self._rtu_serial_connection.in_waiting

            if waiting > 0:
                self._refresh_buffer.extend(
                    self._rtu_serial_connection.read(waiting)
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
                                and self._rtu_baud.findText(baud_text) >= 0
                            ):
                                self._rtu_slave_id.setText(slave_text)
                                self._rtu_baud.setCurrentText(baud_text)

                                self._refresh_pending = False
                                self._refresh_timer.stop()
                                self._refresh_buffer.clear()

                                self._status.setText(
                                    "Configuration Refreshed"
                                )
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
            self._set_status_color("#D00000")
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
            self._set_status_color("#D00000")
            self._set_status_color("#D00000")
            return

        # --------------------------------------------------------
        # STEP 3: Read and validate Slave ID.
        # --------------------------------------------------------
        slave_text = self._slave_id.text().strip()

        try:
            slave_id = int(slave_text)
        except ValueError:
            print("FAILED: Invalid Device ID")
            self._status.setText("Device ID must be 1 to 63")
            self._set_status_color("#D00000")
            return

        if not 1 <= slave_id <= 63:
            print("FAILED: Slave ID must be 1 to 63")
            self._status.setText("Device ID must be 1 to 63")
            self._set_status_color("#D00000")
            return

        # --------------------------------------------------------
        # STEP 4: Read selected I/P Type and map to protocol value.
        # --------------------------------------------------------
        input_type = self._input_type.currentText().strip()

        if input_type not in CHANNEL1_INPUT_TYPE_VALUES:
            print("FAILED: Unknown I/P Type:", input_type)
            self._status.setText("Invalid I/P Type")
            self._set_status_color("#D00000")
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

        if not self._sync_analog_baud_rate():
            self._status.setText("Baud Rate Error")
            self._set_status_color("#D00000")
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
            self._set_status_color("#D00000")

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
            self._set_status_color("#D00000")
            self._set_status_color("#D00000")
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
                self._set_status_color("#00C928")
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
        self._set_status_color("#D00000")

    # Keep the original Channel 1 helper name available.
    def _finish_channel1_iptype_failure(self, status_text):
        self._finish_channel_iptype_failure(1, status_text)

    # ============================================================
    # CHANNEL 1-8 - ZERO / SPAN FUNCTION CODE 06
    # ============================================================

    def build_channel1_offset_frame(self, slave_id, address, offset_value):
        """
        Build: Slave ID | FC 06 | Address | 2-byte signed value | CRC.
        Function Code 06 is the same for Channels 1-8.
        """
        if offset_value < 0:
            offset_value = offset_value & 0xFFFF

        data = bytes([
            slave_id,
            0x06,
            (address >> 8) & 0xFF,
            address & 0xFF,
            (offset_value >> 8) & 0xFF,
            offset_value & 0xFF,
        ])

        crc = self.calculate_modbus_crc(data)
        return data + bytes([crc & 0xFF, (crc >> 8) & 0xFF])

    def _get_selected_channel(self):
        if self._selected_channel in range(1, 9):
            return self._selected_channel

        for channel in range(1, 9):
            if self._channel_selectors[channel - 1].isVisible():
                return channel
        return None

    def _handle_channel_offset_ok(self, offset_type):
        selected_channel = self._get_selected_channel()

        print("\n============================================================")
        print(
            f"CHANNEL {selected_channel if selected_channel else 'UNKNOWN'} "
            f"{offset_type.upper()} OFFSET - OK BUTTON PRESSED"
        )
        print("============================================================")

        if selected_channel is None:
            print("FAILED: No analog input channel selected")
            self._status.setText("Channel Not Selected")
            self._set_status_color("#D00000")
            return

        if (
            self._connect_button.text() != "DISCONNECT"
            or self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            print("FAILED: COM Port Not Connected")
            self._status.setText("COM Port Not Connected")
            self._set_status_color("#D00000")
            self._set_status_color("#D00000")
            return

        try:
            slave_id = int(self._slave_id.text().strip())
        except ValueError:
            print("FAILED: Invalid Device ID")
            self._status.setText("Device ID must be 1 to 63")
            self._set_status_color("#D00000")
            return

        if not 1 <= slave_id <= 63:
            print("FAILED: Slave ID must be 1 to 63")
            self._status.setText("Device ID must be 1 to 63")
            self._set_status_color("#D00000")
            return

        field = self._min_offset if offset_type == "min" else self._max_offset
        try:
            offset_value = int(field.text().strip())
        except ValueError:
            print(f"FAILED: Invalid {offset_type} offset value")
            self._status.setText("Invalid Offset Value")
            self._set_status_color("#D00000")
            return

        if not -20000 <= offset_value <= 20000:
            print(f"FAILED: {offset_type} offset value out of UI range")
            self._status.setText("Offset must be -20000 to 20000")
            self._set_status_color("#D00000")
            return

        # Zero: CH1=0014, CH2=0015 ... CH8=001B.
        # Span: CH1=001E, CH2=001F ... CH8=0025.
        if offset_type == "min":
            address = 0x0014 + (selected_channel - 1)
        else:
            address = 0x001E + (selected_channel - 1)

        unsigned_value = offset_value & 0xFFFF

        print("Selected Channel:", selected_channel)
        print("Function Code: 06")
        print("Address:", f"{address:04X}")
        print("Signed Offset Value:", offset_value)
        print("2-byte Value:", f"{unsigned_value:04X}")

        if self._channel_offset_pending[selected_channel]:
            print(
                f"FAILED: Channel {selected_channel} "
                "Zero/Span request already pending"
            )
            return

        frame = self.build_channel1_offset_frame(
            slave_id, address, offset_value
        )

        print("TX FRAME HEX:", frame.hex(" ").upper())
        print("TX FRAME BYTES:", frame)

        if not self._sync_analog_baud_rate():
            self._status.setText("Baud Rate Error")
            self._set_status_color("#D00000")
            return

        try:
            self._serial_connection.reset_input_buffer()
            self._channel_offset_buffer[selected_channel].clear()
            self._serial_connection.write(frame)
            self._serial_connection.flush()

            print("TX SUCCESS: Raw binary frame sent")

            self._channel_offset_pending[selected_channel] = True
            self._channel_offset_active_channel = selected_channel
            self._channel_offset_type = offset_type
            self._channel_offset_elapsed = 0
            self._channel_offset_timer.start(20)

            # Keep original Channel 1 state synchronized.
            if selected_channel == 1:
                self._channel1_offset_pending = True
                self._channel1_offset_type = offset_type
                self._channel1_offset_elapsed = 0

        except Exception as exc:
            print("FAILED: TX Exception:", exc)
            self._finish_channel_offset_failure(
                selected_channel,
                "Min Offset Not Applied" if offset_type == "min"
                else "Max Offset Not Applied"
            )

    def handle_channel1_min_offset_ok(self):
        self._handle_channel_offset_ok("min")

    def handle_channel1_max_offset_ok(self):
        self._handle_channel_offset_ok("max")

    def _check_channel_offset_response(self):
        if self._channel_offset_active_channel is None:
            self._channel_offset_timer.stop()
            return

        channel = self._channel_offset_active_channel
        offset_type = self._channel_offset_type
        expected_address = (
            0x0014 + (channel - 1)
            if offset_type == "min"
            else 0x001E + (channel - 1)
        )
        buffer = self._channel_offset_buffer[channel]

        if not self._channel_offset_pending[channel]:
            self._channel_offset_timer.stop()
            return

        if (
            self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            print(
                f"FAILED: COM Port disconnected while waiting for "
                f"Channel {channel} Offset RX"
            )
            self._finish_channel_offset_failure(
                channel, "COM Port Not Connected"
            )
            return

        try:
            waiting = self._serial_connection.in_waiting

            if waiting > 0:
                received = self._serial_connection.read(waiting)
                buffer.extend(received)
                print(
                    f"RX OFFSET CH{channel} CHUNK HEX:",
                    received.hex(" ").upper(),
                )
                print(
                    f"RX OFFSET CH{channel} BUFFER HEX:",
                    bytes(buffer).hex(" ").upper(),
                )

            if len(buffer) >= 8:
                response = bytes(buffer[:8])
                del buffer[:8]

                print(
                    f"RX OFFSET CH{channel} FRAME HEX:",
                    response.hex(" ").upper(),
                )

                rx_slave_id = response[0]
                rx_function = response[1]
                rx_address = (response[2] << 8) | response[3]
                rx_raw_value = (response[4] << 8) | response[5]
                rx_value = (
                    rx_raw_value - 0x10000
                    if rx_raw_value & 0x8000
                    else rx_raw_value
                )
                rx_crc_received = response[6] | (response[7] << 8)
                rx_crc_calculated = self.calculate_modbus_crc(response[:6])

                print("RX Slave ID:", rx_slave_id)
                print("RX Function Code:", f"{rx_function:02X}")
                print("RX Address:", f"{rx_address:04X}")
                print("RX Raw Value:", f"{rx_raw_value:04X}")
                print("RX Signed Value:", rx_value)
                print("RX CRC Received:", f"{rx_crc_received:04X}")
                print("RX CRC Calculated:", f"{rx_crc_calculated:04X}")

                try:
                    expected_slave_id = int(self._slave_id.text().strip())
                except ValueError:
                    print("FAILED: Invalid Slave ID during Offset RX validation")
                    self._finish_channel_offset_failure(
                        channel, "Offset Response Error"
                    )
                    return

                if rx_slave_id != expected_slave_id:
                    print("FAILED: Offset RX Slave ID mismatch")
                    self._finish_channel_offset_failure(
                        channel, "Offset Response Error"
                    )
                    return

                if rx_function != 0x06:
                    print("FAILED: Offset RX Function Code mismatch")
                    self._finish_channel_offset_failure(
                        channel, "Offset Response Error"
                    )
                    return

                if rx_address != expected_address:
                    print("FAILED: Offset RX Address mismatch")
                    self._finish_channel_offset_failure(
                        channel, "Offset Response Error"
                    )
                    return

                if rx_crc_received != rx_crc_calculated:
                    print("FAILED: Offset RX CRC mismatch")
                    self._finish_channel_offset_failure(
                        channel, "Offset Response Error"
                    )
                    return

                self._channel_offset_received_value[channel][offset_type] = rx_value

                if channel == self._get_selected_channel():
                    if offset_type == "min":
                        self._min_offset.setText(str(rx_value))
                    else:
                        self._max_offset.setText(str(rx_value))

                if offset_type == "min":
                    status_text = f"CH{channel} Zero Value Applied"
                else:
                    status_text = f"CH{channel} Span Value Applied"

                print("RX VALIDATION: SUCCESS")
                print("Validated Signed Offset Value:", rx_value)

                self._channel_offset_pending[channel] = False
                self._channel_offset_active_channel = None
                self._channel_offset_type = None
                self._channel_offset_timer.stop()
                buffer.clear()

                if channel == 1:
                    self._channel1_offset_pending = False
                    self._channel1_offset_type = None
                    if offset_type == "min":
                        self._channel1_min_offset_received_value = rx_value
                    else:
                        self._channel1_max_offset_received_value = rx_value

                self._status.setText(status_text)
                self._set_status_color("#00C928")
                return

            self._channel_offset_elapsed += 20

            if self._channel_offset_elapsed >= 2000:
                print(f"FAILED: Channel {channel} Offset response timeout")
                print(
                    "RX BUFFER AT TIMEOUT:",
                    bytes(buffer).hex(" ").upper(),
                )
                self._finish_channel_offset_failure(
                    channel, "Offset Response Timeout"
                )

        except Exception as exc:
            print("FAILED: Offset RX Exception:", exc)
            self._finish_channel_offset_failure(
                channel, "Offset Response Error"
            )

    def _finish_channel_offset_failure(self, channel, status_text):
        self._channel_offset_pending[channel] = False
        self._channel_offset_timer.stop()
        self._channel_offset_buffer[channel].clear()
        self._channel_offset_active_channel = None
        self._channel_offset_type = None

        if channel == 1:
            self._channel1_offset_pending = False
            self._channel1_offset_type = None

        self._status.setText(status_text)
        self._set_status_color("#D00000")

    # Keep the original Channel 1 helper name available.
    def _check_channel1_offset_response(self):
        self._check_channel_offset_response()

    def _finish_channel1_offset_failure(self, status_text):
        channel = self._channel_offset_active_channel or 1
        self._finish_channel_offset_failure(channel, status_text)

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
            self._set_status_color("#D00000")
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
            self._set_status_color("#D00000")
            self._set_status_color("#D00000")
            return

        # --------------------------------------------------------
        # STEP 3: Read and validate Slave ID.
        # --------------------------------------------------------
        slave_text = self._slave_id.text().strip()

        try:
            slave_id = int(slave_text)
        except ValueError:
            print("FAILED: Invalid Device ID")
            self._status.setText("Device ID must be 1 to 63")
            self._set_status_color("#D00000")
            return

        if not 1 <= slave_id <= 63:
            print("FAILED: Slave ID must be 1 to 63")
            self._status.setText("Device ID must be 1 to 63")
            self._set_status_color("#D00000")
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
        if not self._sync_analog_baud_rate():
            self._status.setText("Baud Rate Error")
            self._set_status_color("#D00000")
            return

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
            self._set_status_color("#D00000")

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
                self._set_status_color("#00C928")
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
        self._set_status_color("#D00000")

    # Keep the original Channel 1 refresh helper name available.
    def handle_channel1_refresh(self):
        self.handle_channel_refresh()

    def channel_selected(self, channel):
        # Clicking the same channel again hides its configuration.
        if (
            getattr(self, "_selected_channel", None) == channel
            and self._channel_config_frame.isVisible()
        ):
            self._channel_config_frame.setVisible(False)
            self._channel_refresh_button.setVisible(False)
            self._selected_channel = None

            config_index = self.right_layout.indexOf(self._channel_config_row)
            if config_index >= 0:
                self.right_layout.takeAt(config_index)

            for button in self._channel_selectors:
                button.setProperty("selected", False)
                button.style().unpolish(button)
                button.style().polish(button)
            return

        # Keep all channel buttons visible and show the configuration
        # directly below the channel that was clicked.
        config_index = self.right_layout.indexOf(self._channel_config_row)
        if config_index >= 0:
            self.right_layout.takeAt(config_index)

        self._selected_channel = channel
        self._channel_config_frame.setVisible(True)
        self._channel_refresh_button.setVisible(True)

        for index, button in enumerate(self._channel_selectors, start=1):
            button.setProperty("selected", index == channel)
            button.style().unpolish(button)
            button.style().polish(button)
            button.setVisible(True)

        channel_row_index = self.right_layout.indexOf(
            self._channel_rows[channel - 1]
        )
        if channel_row_index >= 0:
            self.right_layout.insertLayout(
                channel_row_index + 1,
                self._channel_config_row,
            )

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and obj in self._channel_selectors:
            channel = self._channel_selectors.index(obj) + 1

            if (
                getattr(self, "_selected_channel", None) == channel
                and self._channel_config_frame.isVisible()
            ):
                self.reset_channel_view()
            else:
                self.show_channel_config(
                    f"Analog Input Channel - {channel}"
                )
            return True

        return super().eventFilter(obj, event)

    def show_channel_config(self, channel_name):
        selected_box = None
        for box in self._channel_selectors:
            if box.text() == channel_name:
                selected_box = box
                break

        if selected_box is None:
            return

        self._selected_channel = self._channel_selectors.index(selected_box) + 1

        # Keep all channel buttons visible, like Analog Output.
        for box in self._channel_selectors:
            box.setVisible(True)
            box.setProperty("selected", box is selected_box)
            box.style().unpolish(box)
            box.style().polish(box)

        # Show the stored Zero/Span values for the selected channel.
        zero_value = self._channel_offset_received_value[self._selected_channel]["min"]
        span_value = self._channel_offset_received_value[self._selected_channel]["max"]
        self._min_offset.setText(
            str(zero_value) if zero_value is not None else "-20000"
        )
        self._max_offset.setText(
            str(span_value) if span_value is not None else "+20000"
        )

        self._channel_config_frame.setVisible(True)
        self._channel_refresh_button.setVisible(True)

        # Move the configuration box directly below the selected channel.
        config_index = self.right_layout.indexOf(self._channel_config_row)
        if config_index >= 0:
            self.right_layout.takeAt(config_index)

        channel_row_index = self.right_layout.indexOf(
            self._channel_rows[self._selected_channel - 1]
        )
        if channel_row_index >= 0:
            self.right_layout.insertLayout(
                channel_row_index + 1,
                self._channel_config_row,
            )

    def reset_channel_view(self):
        for box in self._channel_selectors:
            box.setVisible(True)
            box.setProperty("selected", False)
            box.style().unpolish(box)
            box.style().polish(box)

        self._channel_config_frame.setVisible(False)
        self._channel_refresh_button.setVisible(False)
        self._selected_channel = None

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
            self._channel_offset_pending[channel] = False
            self._channel_offset_buffer[channel].clear()
        self._channel_offset_timer.stop()
        self._channel_offset_active_channel = None
        self._channel_offset_type = None

        self._channel1_offset_pending = False
        self._channel1_offset_timer.stop()
        self._channel1_offset_buffer.clear()
        self._channel1_offset_type = None

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

        if self._rtu_serial_connection is not None:
            try:
                self._rtu_serial_connection.close()
            except Exception:
                pass
            finally:
                self._rtu_serial_connection = None

        self._connected_port = None
        self._rtu_connected_port = None
        self._connect_button.setText("CONNECT")
        self._rtu_connect_button.setText("CONNECT")

        self.reset_channel_view()

        self._connect_button.setText("CONNECT")
        self._status.setText("Not Connected")
        self._set_status_color("#00C928")

        self.terminal_messages = ["Device Terminal Ready"]
        self.terminal_message.setPlainText("Device Terminal Ready")
        # Reset the Analog Input page first, then navigate back.
        self.back_clicked.emit()