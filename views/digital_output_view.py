from pathlib import Path

from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QTimer
from PySide6.QtGui import (
    QPainter,
    QPen,
    QBrush,
    QPixmap,
    QPolygonF,
    QFont,
    QColor,
    QTextCursor,
    QTextFormat,
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
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QGridLayout,
    QWidget,
)


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


class OutputToggle(QPushButton):
    def __init__(self, is_on=False, parent=None):
        super().__init__(parent)
        self._is_on = is_on
        ui.sized(self, "setFixedSize", 92, 34)
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(self._toggle)
        self._update_style()

    def _toggle(self):
        self.set_on(not self._is_on)

    def set_on(self, is_on):
        self._is_on = bool(is_on)
        self._update_style()

    def is_on(self):
        return self._is_on

    def _update_style(self):
        # The switch is painted in paintEvent() with the theme colours; only the text is kept.
        self.setText("ON" if self._is_on else "OFF")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        radius = rect.height() / 2
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(ui.lc.qc("ok" if self._is_on else "border2")))
        painter.drawRoundedRect(rect, radius, radius)
        knob_d = rect.height() - 8
        knob_y = (self.height() - knob_d) / 2
        knob_x = self.width() - knob_d - 4 if self._is_on else 4
        painter.setBrush(QBrush(QColor("#FFFFFF")))
        painter.drawEllipse(QRectF(knob_x, knob_y, knob_d, knob_d))
        font = QFont("Segoe UI")
        font.setPixelSize(ui.px(13))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(QColor("#FFFFFF") if self._is_on else ui.lc.qc("muted")))
        if self._is_on:
            text_rect = QRectF(10, 0, self.width() - knob_d - 18, self.height())
        else:
            text_rect = QRectF(knob_d + 8, 0, self.width() - knob_d - 18, self.height())
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignCenter, "ON" if self._is_on else "OFF")
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

        self._serial_connection = None
        self._rtu_serial_connection = None

        self._connection_monitor_timer = QTimer(self)
        self._connection_monitor_timer.timeout.connect(self._check_connection_status)
        self._connection_monitor_timer.start(500)

        self._apply_pending = False
        self._apply_buffer = bytearray()
        self._apply_timer = QTimer(self)
        self._apply_timer.timeout.connect(self._check_apply_response)
        self._apply_elapsed = 0
        self._connected_baud_rate = None
        self._apply_target_baud_rate = None
        self._apply_baud_timer = QTimer(self)
        self._apply_baud_timer.setSingleShot(True)
        self._apply_baud_timer.timeout.connect(self._switch_to_applied_baud)

        self._refresh_pending = False
        self._refresh_buffer = bytearray()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._check_refresh_response)
        self._refresh_elapsed = 0

        # DO channel refresh
        self._do_refresh_pending = False
        self._do_refresh_buffer = bytearray()
        self._do_refresh_timer = QTimer(self)
        self._do_refresh_timer.timeout.connect(self._check_do_refresh_response)
        self._do_refresh_elapsed = 0

        # Automatic DO TX/RX while RUN is active
        self._run_output_active = False
        self._run_output_timer = QTimer(self)
        self._run_output_timer.timeout.connect(self._run_output_cycle)

        # DO-1 ON/OFF communication
        self._do1_pending = False
        self._do1_buffer = bytearray()
        self._do1_timer = QTimer(self)
        self._do1_timer.timeout.connect(self._check_do1_response)
        self._do1_elapsed = 0
        self._do1_requested_state = False
        self._do1_requested_channel = 1

        # TURN ALL ON/OFF communication (RX buffered and printed raw only)
        self._all_output_pending = False
        self._all_output_buffer = bytearray()
        self._all_output_timer = QTimer(self)
        self._all_output_timer.timeout.connect(self._check_all_output_response)
        self._all_output_elapsed = 0
        self._all_output_mode = ""

        self.terminal_messages = ["Device Terminal Ready"]

        self.build_ui()

    def build_ui(self):
        # Look: shared with the other pages and the Multi Device page (ui_theme.py). Only widgets and
        # styles are built here - every attribute the communication code uses keeps its name.
        ui.install(self)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # HEADER (logo, back, title, connection status, theme switch)
        header = ui.Header("Digital Output", root=self)
        self.back_button = header.back_button
        status = header.status
        self._status_dot = header.status_dot
        root_layout.addWidget(header)

        content = QHBoxLayout()
        content.setContentsMargins(20, 20, 20, 20)
        content.setSpacing(16)

        # ------------------------------------------------------------ LEFT: RTU settings + terminal
        panel = ui.rtu_panel("Digital Output")
        left = panel.card
        self.connect_button = panel.connect
        self.protocol = panel.protocol
        self.slave_id = panel.id_edit
        self.baud_rate = panel.baud
        self.apply_button = panel.apply
        self.refresh_button = panel.refresh
        self.terminal_message = panel.terminal

        # ------------------------------------------------------------ RIGHT: Digital Output channels
        right = ui.card()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(22, 20, 22, 20)
        right_layout.setSpacing(14)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_col.addWidget(ui.label("Digital Output", "pgTitle"))
        title_col.addWidget(ui.label("16 channels \u00b7 click a switch to turn an output ON / OFF", "pgSub"))
        right_layout.addLayout(title_col)

        # Digital Output communication settings (separate from the RTU settings on the left).
        do_settings = QFrame()
        do_settings.setObjectName("pgBox")
        do_settings_layout = QHBoxLayout(do_settings)
        do_settings_layout.setContentsMargins(14, 10, 14, 10)
        do_settings_layout.setSpacing(10)

        self.do_slave_id = QLineEdit()
        self.do_slave_id.setText("1")
        ui.sized(self.do_slave_id, "setFixedWidth", 84)
        self.do_baud_rate = QComboBox()
        self.do_baud_rate.addItems(["9600", "19200", "38400", "57600", "115200"])
        self.do_baud_rate.setCurrentText("9600")
        ui.sized(self.do_baud_rate, "setMinimumWidth", 110)
        do_connect = ui.button("CONNECT", "primary", 36, alt={"DISCONNECT": "softdanger"})
        ui.sized(do_connect, "setMinimumWidth", 120)
        self.run_output_button = ui.button("RUN", "success", 36, alt={"STOP": "danger"})
        ui.sized(self.run_output_button, "setMinimumWidth", 110)
        self.turn_all_button = ui.button("TURN ON ALL", "secondary", 36, alt={"TURN OFF ALL": "danger"})
        ui.sized(self.turn_all_button, "setMinimumWidth", 140)

        do_settings_layout.addWidget(ui.label("Device ID", "pgField"))
        do_settings_layout.addWidget(self.do_slave_id)
        do_settings_layout.addSpacing(6)
        do_settings_layout.addWidget(ui.label("Baud Rate", "pgField"))
        do_settings_layout.addWidget(self.do_baud_rate)
        do_settings_layout.addSpacing(6)
        do_settings_layout.addWidget(do_connect)
        do_settings_layout.addStretch()
        do_settings_layout.addWidget(self.run_output_button)
        do_settings_layout.addWidget(self.turn_all_button)
        right_layout.addWidget(do_settings)

        # Two independent COM connections:
        # left CONNECT -> RTU Settings
        # right CONNECT -> Digital Output TX/RX
        self._do_connect_button = do_connect
        self._rtu_connect_button = self.connect_button
        do_connect.clicked.connect(self.handle_connect)
        self.connect_button.clicked.connect(self.handle_rtu_connect)

        self._output_states = {channel: False for channel in range(1, 17)}
        self._output_status_buttons = {}

        # 16 channel tiles, 4 per row: name + ON / OFF switch
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        def create_output_status(channel):
            status_button = OutputToggle(False)
            status_button.clicked.disconnect(status_button._toggle)
            status_button.clicked.connect(
                lambda checked=False, ch=channel: self._toggle_output(ch)
            )
            self._output_status_buttons[channel] = status_button
            return status_button

        for index in range(16):
            channel = index + 1
            tile = ui.tile()
            ui.sized(tile, "setMinimumHeight", 96)
            tile.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(14, 10, 14, 12)
            tile_layout.setSpacing(2)
            tile_layout.addWidget(ui.label(f"DO-{channel}", "pgValue"))
            tile_layout.addStretch()
            switch = create_output_status(channel)
            switch.tile = tile
            tile_layout.addWidget(switch, 0, Qt.AlignLeft)
            grid.addWidget(tile, index // 4, index % 4)
        for column in range(4):
            grid.setColumnStretch(column, 1)
        right_layout.addLayout(grid, 1)

        self.run_output_button.clicked.connect(self.handle_run_output)
        self.turn_all_button.clicked.connect(self._toggle_all_outputs)

        content.addWidget(left)
        content.addWidget(right, 1)
        root_layout.addLayout(content, 1)

        # Keep references for RTU actions.
        self._status = status
        self._connect_button = self._do_connect_button

        # RTU Settings (left side)
        self._rtu_slave_id = self.slave_id
        self._rtu_baud = self.baud_rate

        # Digital Output (right side)
        self._slave_id = self.do_slave_id
        self._baud = self.do_baud_rate

        # BACK NAVIGATION
        self.back_button.clicked.connect(self.handle_back)
        self.apply_button.clicked.connect(self.handle_apply_rtu)
        self.refresh_button.clicked.connect(self.handle_refresh)

    def _set_output_status_style(self, button, is_on):
        button.set_on(is_on)
        tile = getattr(button, "tile", None)
        if tile is not None:
            ui.set_state(tile, "on" if is_on else "")

    def _set_output_state(self, channel, is_on):
        self._output_states[channel] = is_on
        button = self._output_status_buttons.get(channel)
        if button is not None:
            self._set_output_status_style(button, is_on)

    def _toggle_output(self, channel):
        if self._serial_connection is None or not self._serial_connection.is_open:
            self._set_error_status("COM Port Not Connected")
            return

        current_state = self._output_states.get(channel, False)
        self._send_do1_command(channel, not current_state)

    def _send_do1_command(self, channel, is_on):
        if (
            self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            self._set_error_status("COM Port Not Connected")
            return

        if self._do1_pending:
            return

        try:
            slave_id = int(self._slave_id.text().strip())
            if not 1 <= slave_id <= 63:
                self._set_error_status("Slave ID must be 1 to 63")
                return

            # Each DO uses the next Modbus address:
            # DO-1 = 0000, DO-2 = 0001, ... DO-16 = 000F
            address = channel - 1

            # Slave ID | 0F | Address | Quantity 0001 |
            # Byte Count 01 | Output Value 01/00 | CRC
            request = bytes([
                slave_id,
                0x0F,
                (address >> 8) & 0xFF,
                address & 0xFF,
                0x00, 0x01,
                0x01,
                0x01 if is_on else 0x00,
            ])
            command = request + self._modbus_crc(request)

            self._sync_do_baud_rate()
            self._serial_connection.reset_input_buffer()
            self._do1_buffer.clear()
            self._serial_connection.write(command)
            self._serial_connection.flush()

            print(
                f"DO-{channel} TX:",
                " ".join(f"{byte:02X}" for byte in command)
            )

            self._do1_requested_channel = channel
            self._do1_requested_state = bool(is_on)
            self._do1_pending = True
            self._do1_elapsed = 0
            self._do1_timer.start(20)

        except Exception as exc:
            self._do1_pending = False
            self._do1_timer.stop()
            self._do1_buffer.clear()
            self._set_error_status(f"DO-{channel} Error")
            self.add_terminal_message(f"DO-{channel} Error: {exc}")

    def _check_do1_response(self):
        if not self._do1_pending:
            self._do1_timer.stop()
            return

        if (
            self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            self._do1_pending = False
            self._do1_timer.stop()
            self._do1_buffer.clear()
            self._set_error_status("COM Port Not Connected")
            return

        try:
            waiting = self._serial_connection.in_waiting
            if waiting > 0:
                self._do1_buffer.extend(
                    self._serial_connection.read(waiting)
                )
                print(
                    f"DO-{self._do1_requested_channel} RX:",
                    " ".join(f"{byte:02X}" for byte in self._do1_buffer)
                )

            # Response is the write echo:
            # Slave ID | 0F | Address | Quantity | CRC
            # The response does not contain a separate ON/OFF status byte.
            if len(self._do1_buffer) >= 8:
                response = bytes(self._do1_buffer)
                crc_received = response[-2:]
                crc_calculated = self._modbus_crc(response[:-2])

                if crc_received != crc_calculated:
                    channel = self._do1_requested_channel
                    self._do1_pending = False
                    self._do1_timer.stop()
                    self._do1_buffer.clear()
                    self._set_error_status(f"DO-{channel} RX CRC Error")
                    self.add_terminal_message(f"DO-{channel} RX CRC Error")
                    return

                slave_id = response[0]
                function_code = response[1]
                response_address = (response[2] << 8) | response[3]
                channel = self._do1_requested_channel
                expected_address = channel - 1

                if (
                    slave_id == int(self._slave_id.text().strip())
                    and function_code == 0x0F
                    and response_address == expected_address
                ):
                    self._set_output_state(
                        channel,
                        self._do1_requested_state
                    )

                    state_text = "01 = ON" if self._do1_requested_state else "00 = OFF"
                    print(f"DO-{channel} STATUS: {state_text}")

                    self._do1_pending = False
                    self._do1_timer.stop()
                    self._do1_elapsed = 0
                    self._do1_buffer.clear()
                    self._status.setText(f"DO-{channel} Status Updated")
                    self._set_status_color("#00C928")
                    return

            self._do1_elapsed += 20
            if self._do1_elapsed >= 2000:
                channel = self._do1_requested_channel
                self._do1_pending = False
                self._do1_timer.stop()
                self._do1_buffer.clear()
                self._set_error_status(f"DO-{channel} Response Timeout")

        except Exception as exc:
            channel = self._do1_requested_channel
            self._do1_pending = False
            self._do1_timer.stop()
            self._do1_buffer.clear()
            self._set_error_status(f"DO-{channel} Error")
            self.add_terminal_message(f"DO-{channel} Error: {exc}")

    def _toggle_all_outputs(self):
        if self.turn_all_button.text() == "TURN ON ALL":
            self._turn_all_on()
        else:
            self._turn_all_off()

    def _update_all_button(self, is_on):
        if is_on:
            self.turn_all_button.setText("TURN OFF ALL")
            self.turn_all_button.setStyleSheet("""
                QPushButton {
                    background: #E52222;
                    color: white;
                    border: none;
                    border-radius: 19px;
                    padding-left: 12px;
                    padding-right: 12px;
                    font-family: Cambria;
                    font-size: 14px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: #CC1D1D;
                }
                QPushButton:pressed {
                    background: #A81717;
                }
            """)
        else:
            self.turn_all_button.setText("TURN ON ALL")
            self.turn_all_button.setStyleSheet("""
                QPushButton {
                    background: #20B83A;
                    color: white;
                    border: none;
                    border-radius: 19px;
                    padding-left: 12px;
                    padding-right: 12px;
                    font-family: Cambria;
                    font-size: 14px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: #19A631;
                }
                QPushButton:pressed {
                    background: #148A28;
                }
            """)

    def _turn_all_on(self):
        if self._serial_connection is None or not self._serial_connection.is_open:
            self._set_error_status("COM Port Not Connected")
            return

        if self._all_output_pending:
            return

        try:
            slave_id = int(self._slave_id.text().strip())
            if not 1 <= slave_id <= 63:
                self._set_error_status("Slave ID must be 1 to 63")
                return

            request = bytes([
                slave_id,
                0x0F,
                0x00, 0x00,
                0x00, 0x10,
                0x02,
                0xFF, 0xFF,
            ])
            command = request + self._modbus_crc(request)

            self._sync_do_baud_rate()
            self._serial_connection.reset_input_buffer()
            self._all_output_buffer.clear()
            self._all_output_elapsed = 0
            self._all_output_mode = "ON"
            self._serial_connection.write(command)
            self._serial_connection.flush()

            print("TURN ALL ON TX:", " ".join(f"{byte:02X}" for byte in command))

            self._all_output_pending = True
            self._all_output_timer.start(20)

            for channel in range(1, 17):
                self._set_output_state(channel, True)
            self._update_all_button(True)
            self._status_dot.setText("●")
            self._status_dot.setStyleSheet("color: #00A000; font-weight: bold; font-size: 16px;")
            self._status.setText("All DO Turned ON")
            self._set_status_color("#00A000")
        except Exception as exc:
            self._all_output_pending = False
            self._all_output_timer.stop()
            self._all_output_buffer.clear()
            print("TURN ALL ON ERROR:", exc)

    def _turn_all_off(self):
        if self._serial_connection is None or not self._serial_connection.is_open:
            self._set_error_status("COM Port Not Connected")
            return

        if self._all_output_pending:
            return

        try:
            slave_id = int(self._slave_id.text().strip())
            if not 1 <= slave_id <= 63:
                self._set_error_status("Slave ID must be 1 to 63")
                return

            request = bytes([
                slave_id,
                0x0F,
                0x00, 0x00,
                0x00, 0x10,
                0x02,
                0x00, 0x00,
            ])
            command = request + self._modbus_crc(request)

            self._serial_connection.reset_input_buffer()
            self._all_output_buffer.clear()
            self._all_output_elapsed = 0
            self._all_output_mode = "OFF"
            self._serial_connection.write(command)
            self._serial_connection.flush()

            print("TURN ALL OFF TX:", " ".join(f"{byte:02X}" for byte in command))

            self._all_output_pending = True
            self._all_output_timer.start(20)

            for channel in range(1, 17):
                self._set_output_state(channel, False)
            self._update_all_button(False)
            self._status_dot.setText("●")
            self._status_dot.setStyleSheet("color: #D00000; font-weight: bold; font-size: 16px;")
            self._status.setText("All DO Turned OFF")
            self._set_status_color("#D00000")
        except Exception as exc:
            self._all_output_pending = False
            self._all_output_timer.stop()
            self._all_output_buffer.clear()
            print("TURN ALL OFF ERROR:", exc)

    def _check_all_output_response(self):
        if not self._all_output_pending:
            self._all_output_timer.stop()
            return

        try:
            if self._serial_connection is None or not self._serial_connection.is_open:
                self._all_output_pending = False
                self._all_output_timer.stop()
                return

            waiting = self._serial_connection.in_waiting
            if waiting > 0:
                chunk = self._serial_connection.read(waiting)
                self._all_output_buffer.extend(chunk)
                print(
                    f"TURN ALL {self._all_output_mode} RX:",
                    " ".join(f"{byte:02X}" for byte in chunk)
                )

            self._all_output_elapsed += 20
            if self._all_output_elapsed >= 2000:
                self._all_output_pending = False
                self._all_output_timer.stop()
                self._all_output_elapsed = 0
        except Exception as exc:
            self._all_output_pending = False
            self._all_output_timer.stop()
            print(f"TURN ALL {self._all_output_mode} RX ERROR:", exc)

    def _set_error_status(self, message):
        self._status.setText(message)
        self._status.setStyleSheet(
            "color: #D00000; font-weight: bold; font-size: 16px;"
        )
        self._status_dot.setStyleSheet(
            "color: #A0A0A0; background: transparent; font-family: Cambria; font-size: 16px;"
        )

    def _set_status_color(self, color):
        self._status.setStyleSheet(
            f"color: {color}; font-weight: bold; font-size: 16px;"
        )
        self._status_dot.setStyleSheet(
            f"color: {color}; background: transparent; font-family: Cambria; font-size: 16px;"
        )

    def _set_status_color(self, color):
        self._status.setStyleSheet(
            f"color: {color}; font-weight: bold; font-size: 16px;"
        )
        self._status_dot.setStyleSheet(
            f"color: {color}; background: transparent; font-family: Cambria; font-size: 16px;"
        )

    def add_terminal_message(self, message):
        raw_message = str(message)
        if "All DO Turned ON" in raw_message:
            plain_message = "● All DO Turned ON"
        elif "All DO Turned OFF" in raw_message:
            plain_message = "● All DO Turned OFF"
        else:
            plain_message = raw_message

        self.terminal_messages.append(plain_message)
        self.terminal_message.setPlainText("\n".join(self.terminal_messages))

        selections = []
        document = self.terminal_message.document()
        for text, color in (("● All DO Turned ON", "#3FB76A"), ("● All DO Turned OFF", "#F06A64")):
            cursor = document.find(text)
            while not cursor.isNull():
                selection = QTextEdit.ExtraSelection()
                selection.cursor = cursor
                selection.format.setForeground(QColor(color))
                selections.append(selection)
                cursor = document.find(text, cursor)

        self.terminal_message.setExtraSelections(selections)
        scrollbar = self.terminal_message.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def show_com_port_popup(self):
        ports = [port.device for port in list_ports.comports()]

        if not ports:
            self._set_error_status("COM Port Not Found")
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
                self._set_error_status("COM Port Not Found")
                return

            try:
                import serial

                self._serial_connection = serial.Serial(
                    selected_port,
                    int(self.do_baud_rate.currentText()),
                    timeout=1
                )

                # Give the USB/serial device a short settling time after
                # opening the COM port. The first configuration command
                # can otherwise be sent while the device is still starting.
                self._serial_connection.reset_input_buffer()
                self._serial_connection.reset_output_buffer()

                self._status.setText("Connected")
                self._set_status_color("#00C928")
                self._connect_button.setText("DISCONNECT")
                dialog.accept()
            except Exception:
                self._serial_connection = None
                self._set_error_status("Connection Error")
                self._connect_button.setText("CONNECT")
                dialog.reject()

        connect_button.clicked.connect(connect_selected)
        cancel_button.clicked.connect(dialog.reject)
        dialog.exec()

    def _check_connection_status(self):
        # Nothing connected: nothing to watch (listing the COM ports takes time on Windows and this
        # runs every 500 ms, even while another page is open).
        if self._serial_connection is None and self._rtu_serial_connection is None:
            return
        available_ports = {port.device for port in list_ports.comports()}

        # DIGITAL OUTPUT COM connection
        if self._serial_connection is not None:
            try:
                current_port = self._serial_connection.port
                if (
                    not self._serial_connection.is_open
                    or current_port not in available_ports
                ):
                    print("Digital Output COM Port disconnected:", current_port)
                    self._disconnect_after_device_loss()
            except Exception:
                self._disconnect_after_device_loss()

        # RTU SETTINGS COM connection is independent from Digital Output.
        if self._rtu_serial_connection is not None:
            try:
                current_port = self._rtu_serial_connection.port
                if (
                    not self._rtu_serial_connection.is_open
                    or current_port not in available_ports
                ):
                    print("RTU Settings COM Port disconnected:", current_port)
                    try:
                        self._rtu_serial_connection.close()
                    except Exception:
                        pass
                    self._rtu_serial_connection = None
                    self._rtu_connect_button.setText("CONNECT")
                    self._apply_pending = False
                    self._apply_timer.stop()
                    self._apply_buffer.clear()
                    self._set_error_status("RTU Settings COM Port Disconnected")
            except Exception:
                self._rtu_serial_connection = None
                self._rtu_connect_button.setText("CONNECT")
                self._apply_pending = False
                self._apply_timer.stop()
                self._apply_buffer.clear()
                self._set_error_status("RTU Settings COM Port Disconnected")

    def handle_rtu_connect(self):
        if self._rtu_connect_button.text() == "DISCONNECT":
            self._apply_pending = False
            self._apply_timer.stop()
            self._apply_baud_timer.stop()
            self._apply_target_baud_rate = None
            self._apply_buffer.clear()
            try:
                if self._rtu_serial_connection is not None:
                    self._rtu_serial_connection.close()
            finally:
                self._rtu_serial_connection = None
            self._connected_baud_rate = None
            self._rtu_connect_button.setText("CONNECT")
            self._set_error_status("RTU Settings COM Disconnected")
            return

        self.show_rtu_com_port_popup()

    def show_rtu_com_port_popup(self):
        ports = [port.device for port in list_ports.comports()]
        if not ports:
            self._set_error_status("COM Port Not Found")
            return

        from PySide6.QtWidgets import QDialog

        dialog = QDialog(self)
        dialog.setWindowTitle("RTU Settings COM Port")
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        title = QLabel("Select RTU Settings COM Port")
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
                self._set_error_status("COM Port Not Found")
                dialog.reject()
                return
            try:
                import serial
                if self._rtu_serial_connection is not None:
                    try:
                        self._rtu_serial_connection.close()
                    except Exception:
                        pass
                connected_baud = int(self._rtu_baud.currentText())
                self._rtu_serial_connection = serial.Serial(
                    selected_port,
                    connected_baud,
                    timeout=1
                )
                self._connected_baud_rate = connected_baud
                self._rtu_serial_connection.reset_input_buffer()
                self._rtu_serial_connection.reset_output_buffer()
                self._rtu_connect_button.setText("DISCONNECT")
                self._status.setText("RTU Settings Connected")
                self._set_status_color("#00C928")
                dialog.accept()
            except Exception:
                self._rtu_serial_connection = None
                self._rtu_connect_button.setText("CONNECT")
                self._set_error_status("RTU Settings Connection Error")
                dialog.reject()

        connect_button.clicked.connect(connect_selected)
        cancel_button.clicked.connect(dialog.reject)
        dialog.exec()

    def handle_connect(self):
        if self._connect_button.text() == "DISCONNECT":
            self._run_output_active = False
            self._run_output_timer.stop()
            self.run_output_button.setText("RUN")

            self._refresh_pending = False
            self._refresh_timer.stop()
            self._refresh_buffer.clear()
            self._do_refresh_pending = False
            self._do_refresh_timer.stop()
            self._do_refresh_buffer.clear()
            self._do1_pending = False
            self._do1_timer.stop()
            self._do1_buffer.clear()

            try:
                if self._serial_connection is not None:
                    self._serial_connection.close()
            finally:
                self._serial_connection = None

            self._set_error_status("Not Connected")
            self._connect_button.setText("CONNECT")
            self.do_slave_id.setText("1")
            self.do_baud_rate.setCurrentText("9600")
            return

        self.show_com_port_popup()

    def handle_apply_rtu(self):
        if self._apply_pending:
            return

        if (
            self._rtu_connect_button.text() != "DISCONNECT"
            or self._rtu_serial_connection is None
            or not self._rtu_serial_connection.is_open
        ):
            self._set_error_status("COM Port not connected")
            return

        slave_text = self._rtu_slave_id.text().strip()

        try:
            slave_id = int(slave_text)
        except ValueError:
            self._set_error_status("Slave ID must be 1 to 63")
            return

        if not 1 <= slave_id <= 63:
            self._set_error_status("Slave ID must be 1 to 63")
            return

        baud_rate = self._rtu_baud.currentText()
        target_baud_rate = int(baud_rate)
        command = f"SID={slave_id},MBD_BAUD={baud_rate}\n"

        try:
            self._apply_target_baud_rate = target_baud_rate
            self._apply_pending = True
            self._apply_elapsed = 0
            self._apply_buffer.clear()
            self._apply_timer.stop()
            QTimer.singleShot(250, lambda cmd=command: self._send_apply_command(cmd))
        except Exception:
            self._apply_pending = False
            self._apply_timer.stop()
            self._apply_baud_timer.stop()
            self._apply_target_baud_rate = None
            self._apply_buffer.clear()
            self._set_error_status("RTU Settings Not Applied")

    def _send_apply_command(self, command):
        if not self._apply_pending:
            return
        if (
            self._rtu_serial_connection is None
            or not self._rtu_serial_connection.is_open
        ):
            self._apply_pending = False
            self._set_error_status("COM Port not connected")
            return
        try:
            self._rtu_serial_connection.reset_input_buffer()
            self._apply_buffer.clear()
            self._rtu_serial_connection.write(command.encode("ascii"))
            self._rtu_serial_connection.flush()
            slave_id = command.split(",")[0].split("=")[1]
            baud_rate = command.split("MBD_BAUD=")[1].strip()
            print(f"RTU SETTINGS TX: SID={slave_id}, BAUD={baud_rate}")
            self._apply_timer.start(20)
        except Exception:
            self._apply_pending = False
            self._apply_timer.stop()
            self._apply_baud_timer.stop()
            self._apply_target_baud_rate = None
            self._apply_buffer.clear()
            self._set_error_status("RTU Settings Not Applied")

    def _check_apply_response(self):
        if not self._apply_pending:
            self._apply_timer.stop()
            return

        if (
            self._rtu_serial_connection is None
            or not self._rtu_serial_connection.is_open
        ):
            self._apply_pending = False
            self._apply_timer.stop()
            self._apply_baud_timer.stop()
            self._apply_target_baud_rate = None
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
                    self._apply_pending = False
                    self._apply_timer.stop()
                    self._apply_baud_timer.stop()
                    if (
                        self._apply_target_baud_rate is not None
                        and self._connected_baud_rate != self._apply_target_baud_rate
                    ):
                        self._switch_to_applied_baud()
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
                self._set_error_status("RTU Settings Not Applied")
                return

            self._apply_elapsed += 20
            if self._apply_elapsed >= 2000:
                self._apply_pending = False
                self._apply_timer.stop()
                self._apply_baud_timer.stop()
                self._apply_target_baud_rate = None
                self._apply_buffer.clear()
                self._set_error_status("RTU Settings Not Applied")
        except Exception:
            self._apply_pending = False
            self._apply_timer.stop()
            self._apply_baud_timer.stop()
            self._apply_target_baud_rate = None
            self._apply_buffer.clear()
            self._set_error_status("RTU Settings Not Applied")

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

    def _modbus_crc(self, data):
        crc = 0xFFFF

        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1

        return crc.to_bytes(2, byteorder="little")

    def handle_run_output(self):
        if (
            self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            self._set_error_status("COM Port Not Connected")
            return

        if self._run_output_active:
            self._run_output_active = False
            self._run_output_timer.stop()
            self._do_refresh_pending = False
            self._do_refresh_timer.stop()
            self._do_refresh_buffer.clear()
            self._do_refresh_elapsed = 0
            self.run_output_button.setText("RUN")
            self._status.setText("DO STOPPED")
            self._set_status_color("#D00000")
            self._status_dot.setStyleSheet("""
                QLabel {
                    color: #D00000;
                    background: transparent;
                    font-family: Cambria;
                    font-size: 16px;
                }
            """)
            return

        self._run_output_active = True
        self.run_output_button.setText("STOP")
        self._status.setText("DO RUNNING")
        self._set_status_color("#13C51F")
        self._run_output_timer.start(500)

        # Start the first TX/RX immediately.
        self.handle_do_refresh()

    def _sync_do_baud_rate(self):
        """Apply the currently selected Digital Output baud rate to the
        already-open DO serial port without reconnecting it.
        """
        if self._serial_connection is None or not self._serial_connection.is_open:
            return False

        try:
            selected_baud = int(self._baud.currentText())
            if self._serial_connection.baudrate != selected_baud:
                self._serial_connection.baudrate = selected_baud
                self._serial_connection.reset_input_buffer()
                self._serial_connection.reset_output_buffer()
                print(f"DO Baud Rate changed to: {selected_baud}")
            return True
        except Exception as exc:
            print(f"DO Baud Rate change error: {exc}")
            return False

    def _run_output_cycle(self):
        if not self._run_output_active:
            self._run_output_timer.stop()
            return

        if (
            self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            self._disconnect_after_device_loss()
            return

        self.handle_do_refresh()

    def _disconnect_after_device_loss(self):
        self._run_output_active = False
        self._run_output_timer.stop()

        self._refresh_pending = False
        self._refresh_timer.stop()
        self._refresh_buffer.clear()

        self._do_refresh_pending = False
        self._do_refresh_timer.stop()
        self._do_refresh_buffer.clear()

        self._do1_pending = False
        self._do1_timer.stop()
        self._do1_buffer.clear()

        self._all_output_pending = False
        self._all_output_timer.stop()
        self._all_output_buffer.clear()
        self._all_output_elapsed = 0

        try:
            if self._serial_connection is not None:
                self._serial_connection.close()
        except Exception:
            pass
        finally:
            self._serial_connection = None

        self._connect_button.setText("CONNECT")
        self.run_output_button.setText("RUN")
        self._set_error_status("COM Port Disconnected")
        self.add_terminal_message("COM Port Disconnected")

    def handle_do_refresh(self):
        if (
            self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            self._set_error_status("COM Port Not Connected")
            return

        if self._do_refresh_pending:
            return

        try:
            slave_id = int(self._slave_id.text().strip())
            if not 1 <= slave_id <= 63:
                self._set_error_status("Slave ID must be 1 to 63")
                return

            # Read 16 DO coils: Slave ID | 01 | 0000 | 0010 | CRC
            request = bytes([
                slave_id,
                0x01,
                0x00, 0x00,
                0x00, 0x10,
            ])
            command = request + self._modbus_crc(request)

            # Pick up the latest baud-rate selection before every RUN TX.
            # This allows baud-rate changes while RUN is already active.
            if not self._sync_do_baud_rate():
                self._set_error_status("DO Baud Rate Error")
                return

            self._serial_connection.reset_input_buffer()
            self._do_refresh_buffer.clear()
            self._serial_connection.write(command)
            self._serial_connection.flush()

            print("DO Refresh TX:", " ".join(f"{byte:02X}" for byte in command))

            self._do_refresh_pending = True
            self._do_refresh_elapsed = 0
            self._do_refresh_timer.start(20)

        except Exception as exc:
            self._do_refresh_pending = False
            self._do_refresh_timer.stop()
            self._do_refresh_buffer.clear()
            self._do_refresh_elapsed = 0

            self._set_error_status("DO Refresh Error")
            self.add_terminal_message(f"DO Refresh Error: {exc}")

    def _check_do_refresh_response(self):
        if not self._do_refresh_pending:
            self._do_refresh_timer.stop()
            return

        if (
            self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            self._do_refresh_pending = False
            self._do_refresh_timer.stop()
            self._do_refresh_buffer.clear()

            if self._run_output_active:
                self._disconnect_after_device_loss()
            else:
                self._set_error_status("COM Port Not Connected")
            return

        try:
            waiting = self._serial_connection.in_waiting
            if waiting > 0:
                self._do_refresh_buffer.extend(
                    self._serial_connection.read(waiting)
                )

                # Print the raw RX buffer while it is being accumulated.
                print(
                    "DO Refresh RX:",
                    " ".join(f"{byte:02X}" for byte in self._do_refresh_buffer)
                )

                # Wait until the complete Modbus payload header + 2 data
                # bytes are available. The device response seen in testing
                # is: 02 01 02 DATA1 DATA2 ...
                if len(self._do_refresh_buffer) < 5:
                    self._do_refresh_elapsed += 20

                    if self._do_refresh_elapsed >= 2000:
                        self._do_refresh_pending = False
                        self._do_refresh_timer.stop()
                        self._do_refresh_buffer.clear()
                        self._do_refresh_elapsed = 0
                        self._set_error_status("DO Refresh Timeout")

                    return

                response = bytes(self._do_refresh_buffer)

                slave_id = response[0]
                function_code = response[1]
                byte_count = response[2]

                if (
                    slave_id == int(self._slave_id.text().strip())
                    and function_code == 0x01
                    and byte_count == 0x02
                ):
                    # Actual device response format:
                    # 02 01 02 DATA1 DATA2 CRC_LO CRC_HI
                    # DATA1 controls DO-1 to DO-8.
                    # DATA2 controls DO-9 to DO-16.
                    data_byte_1 = response[3]
                    data_byte_2 = response[4]

                    # Every bit is applied directly to its channel.
                    # 1 = ON, 0 = OFF.
                    for bit in range(8):
                        self._set_output_state(
                            bit + 1,
                            bool(data_byte_1 & (1 << bit))
                        )

                        self._set_output_state(
                            bit + 9,
                            bool(data_byte_2 & (1 << bit))
                        )

                    if self._run_output_active:
                        self.add_terminal_message(
                            f"DO Running: {data_byte_1:02X}{data_byte_2:02X}"
                        )
                    else:
                        self.add_terminal_message(
                            f"DO Stopped: {data_byte_1:02X}{data_byte_2:02X}"
                        )
                    if self._run_output_active:
                        self._status.setText("DO RUNNING")
                    else:
                        self._status.setText("DO Status Refreshed")
                    self._set_status_color("#00C928")
                else:
                    self._set_error_status("DO Refresh Response Error")

                self._do_refresh_pending = False
                self._do_refresh_timer.stop()
                self._do_refresh_elapsed = 0
                self._do_refresh_buffer.clear()
                return

            self._do_refresh_elapsed += 20
            if self._do_refresh_elapsed >= 2000:
                self._do_refresh_pending = False
                self._do_refresh_timer.stop()
                self._do_refresh_buffer.clear()
                self._do_refresh_elapsed = 0
                self._set_error_status("DO Refresh Timeout")

        except Exception as exc:
            self._do_refresh_pending = False
            self._do_refresh_timer.stop()
            self._do_refresh_buffer.clear()
            self._do_refresh_elapsed = 0

            self._set_error_status("DO Refresh Error")
            self.add_terminal_message(f"DO Refresh Error: {exc}")

    def handle_refresh(self):
        if (
            self._rtu_serial_connection is None
            or not self._rtu_serial_connection.is_open
        ):
            self._set_error_status("COM Port Not Connected")
            return

        if self._refresh_pending:
            return

        try:
            self._rtu_serial_connection.reset_input_buffer()
            self._refresh_buffer.clear()
            print("[TX] GETCFG\n")
            self._rtu_serial_connection.write(b"GETCFG\n")
            self._rtu_serial_connection.flush()

            self._refresh_pending = True
            self._refresh_elapsed = 0
            self._refresh_timer.start(20)
        except Exception:
            self._refresh_pending = False
            self._refresh_timer.stop()
            self._refresh_buffer.clear()
            self._set_error_status("Refresh Error")

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
            self._set_error_status("COM Port Not Connected")
            return

        try:
            waiting = self._rtu_serial_connection.in_waiting
            if waiting > 0:
                chunk = self._rtu_serial_connection.read(waiting)
                print(f"[RX] {chunk!r}")
                self._refresh_buffer.extend(chunk)

            if b"\n" in self._refresh_buffer:
                response_bytes, _, remaining = self._refresh_buffer.partition(b"\n")
                self._refresh_buffer = bytearray(remaining)
                response = response_bytes.decode(
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
                self._set_error_status("Refresh Error")
                return

            self._refresh_elapsed += 20
            if self._refresh_elapsed >= 2000:
                self._refresh_pending = False
                self._refresh_timer.stop()
                self._refresh_buffer.clear()
                self._set_error_status("Refresh Error")
        except Exception:
            self._refresh_pending = False
            self._refresh_timer.stop()
            self._refresh_buffer.clear()
            self._set_error_status("Refresh Error")

    def handle_back(self):
        # Stop every running/pending communication operation first.
        self._connection_monitor_timer.stop()
        self._run_output_active = False
        self._run_output_timer.stop()
        self.run_output_button.setText("RUN")

        self._apply_pending = False
        self._apply_timer.stop()
        self._apply_buffer.clear()

        self._refresh_pending = False
        self._refresh_timer.stop()
        self._refresh_buffer.clear()

        self._do_refresh_pending = False
        self._do_refresh_timer.stop()
        self._do_refresh_buffer.clear()
        self._do_refresh_elapsed = 0

        self._do1_pending = False
        self._do1_timer.stop()
        self._do1_buffer.clear()
        self._all_output_pending = False
        self._all_output_timer.stop()
        self._all_output_buffer.clear()
        self._all_output_elapsed = 0

        # Close both independent COM connections.
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

        # Reset the complete page to its initial/default state so that
        # opening Digital Output again starts exactly like a fresh page.
        self._connect_button.setText("CONNECT")
        self._rtu_connect_button.setText("CONNECT")

        self.do_slave_id.setText("1")
        self.do_baud_rate.setCurrentText("9600")

        self.slave_id.setText("1")
        self.baud_rate.setCurrentText("9600")

        self._connected_baud_rate = None

        for channel in range(1, 17):
            self._output_states[channel] = False
            button = self._output_status_buttons.get(channel)
            if button is not None:
                button.set_on(False)

        self._set_error_status("Not Connected")
        self.terminal_messages = ["Device Terminal Ready"]
        self.terminal_message.setPlainText("Device Terminal Ready")
        self.back_clicked.emit()