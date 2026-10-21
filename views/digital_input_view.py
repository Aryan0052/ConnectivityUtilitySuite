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
    QGridLayout,

    QHBoxLayout,

    QLabel,

    QLineEdit,

    QPushButton,

    QPlainTextEdit,
    QSizePolicy,

    QVBoxLayout,

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

        self._di_serial_connection = None

        self._rtu_serial_connection = None

        self._di_connected_baud_rate = None

        self._rtu_connected_baud_rate = None

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
        # Look: shared with the other pages and the Multi Device page (ui_theme.py). Only widgets and
        # styles are built here - every attribute the communication code uses keeps its name.
        ui.install(self)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # HEADER (logo, back, title, connection status, theme switch)
        header = ui.Header("Digital Input", root=self)
        self.back_button = header.back_button
        status = header.status
        status_dot = header.status_dot
        root_layout.addWidget(header)

        content = QHBoxLayout()
        content.setContentsMargins(20, 20, 20, 20)
        content.setSpacing(16)

        # ------------------------------------------------------------ LEFT: RTU settings + terminal
        panel = ui.rtu_panel("Digital Input")
        left = panel.card
        left_layout = panel.layout
        self.connect_button = panel.connect
        self.protocol = panel.protocol
        self.slave_id = panel.id_edit
        self.baud_rate = panel.baud
        self.apply_button = panel.apply
        self.refresh_button = panel.refresh
        self.terminal_message = panel.terminal

        # Digital Input timeout message shown directly below CONNECT.
        self.digital_input_timeout_label = ui.label("Digital Input Timeout", "pgBad")
        self.digital_input_timeout_label.setAlignment(Qt.AlignCenter)
        self.digital_input_timeout_label.hide()
        left_layout.insertWidget(2, self.digital_input_timeout_label)

        # ------------------------------------------------------------ RIGHT: Digital Input channels
        right = ui.card()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(22, 20, 22, 20)
        right_layout.setSpacing(14)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_col.addWidget(ui.label("Digital Input", "pgTitle"))
        title_col.addWidget(ui.label("16 channels \u00b7 live ON / OFF state read from the module", "pgSub"))
        right_layout.addLayout(title_col)

        # Digital Input communication settings (separate from the RTU settings on the left).
        # Order: Device ID -> Baud Rate -> CONNECT ... RUN
        # Keep the existing internal variable name di_slave_id so that
        # communication logic remains unchanged.
        di_settings = QFrame()
        di_settings.setObjectName("pgBox")
        di_settings_layout = QHBoxLayout(di_settings)
        di_settings_layout.setContentsMargins(14, 10, 14, 10)
        di_settings_layout.setSpacing(10)

        self.di_slave_id = QLineEdit()
        self.di_slave_id.setText("1")
        ui.sized(self.di_slave_id, "setFixedWidth", 84)
        self.di_baud_rate = QComboBox()
        self.di_baud_rate.addItems(["9600", "19200", "38400", "57600", "115200"])
        self.di_baud_rate.setCurrentText("9600")
        ui.sized(self.di_baud_rate, "setMinimumWidth", 110)
        di_connect = ui.button("CONNECT", "primary", 36, alt={"DISCONNECT": "softdanger"})
        ui.sized(di_connect, "setMinimumWidth", 120)
        self.run_button = ui.button("RUN", "success", 36, alt={"STOP": "danger"})
        ui.sized(self.run_button, "setMinimumWidth", 110)

        di_settings_layout.addWidget(ui.label("Device ID", "pgField"))
        di_settings_layout.addWidget(self.di_slave_id)
        di_settings_layout.addSpacing(6)
        di_settings_layout.addWidget(ui.label("Baud Rate", "pgField"))
        di_settings_layout.addWidget(self.di_baud_rate)
        di_settings_layout.addSpacing(6)
        di_settings_layout.addWidget(di_connect)
        di_settings_layout.addStretch()
        di_settings_layout.addWidget(self.run_button)
        right_layout.addWidget(di_settings)

        # Two independent COM connections:
        # left CONNECT -> RTU Settings
        # right CONNECT -> Digital Input TX/RX
        self._di_connect_button = di_connect
        self._rtu_connect_button = self.connect_button
        di_connect.clicked.connect(self.handle_connect)
        self.connect_button.clicked.connect(self.handle_rtu_connect)

        # 16 channel tiles, 4 per row: LED + name + ON / OFF
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        self._di_buttons = []
        self._di_tiles = []
        self._di_state_labels = []
        for index in range(16):
            tile = ui.tile()
            ui.sized(tile, "setMinimumHeight", 96)
            tile.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(14, 10, 14, 10)
            tile_layout.setSpacing(2)
            top = QHBoxLayout()
            top.setSpacing(8)
            led = ui.led()
            top.addWidget(led)
            top.addWidget(ui.label(f"DI-{index + 1}", "pgValue"))
            top.addStretch()
            tile_layout.addLayout(top)
            tile_layout.addStretch()
            state_label = ui.label("OFF")
            tile_layout.addWidget(state_label)
            grid.addWidget(tile, index // 4, index % 4)
            self._di_buttons.append(led)
            self._di_tiles.append(tile)
            self._di_state_labels.append(state_label)
        for column in range(4):
            grid.setColumnStretch(column, 1)
        self._reset_di_leds()
        right_layout.addLayout(grid, 1)

        content.addWidget(left)
        content.addWidget(right, 1)
        root_layout.addLayout(content, 1)

        # Keep references for both independent communication paths.
        self._status = status
        self._status_dot = status_dot
        self._connect_button = self._di_connect_button

        # RTU Settings (left side)
        self._rtu_slave_id = self.slave_id
        self._rtu_baud = self.baud_rate

        # Digital Input (right side)
        self._slave_id = self.di_slave_id
        self._baud = self.di_baud_rate

        # BACK NAVIGATION
        self.back_button.clicked.connect(self.handle_back)
        self.apply_button.clicked.connect(self.handle_apply_rtu)
        self.refresh_button.clicked.connect(self.handle_refresh)
        self.run_button.clicked.connect(self.handle_run)

    # ---- channel indicator (look only) -------------------------------------------------
    def _set_di_led(self, index, is_on):
        """Show one channel as ON (green) or OFF (grey)."""
        state = "on" if is_on else ""
        ui.set_state(self._di_buttons[index], state)
        ui.set_state(self._di_tiles[index], state)
        self._di_state_labels[index].setText("ON" if is_on else "OFF")
        ui.tss(self._di_state_labels[index],
               "QLabel { color:@ok; font-size:22px; font-weight:700; background:transparent; }" if is_on else
               "QLabel { color:@faint; font-size:22px; font-weight:600; background:transparent; }")

    def _reset_di_leds(self):
        for index in range(len(self._di_buttons)):
            self._set_di_led(index, False)

    def _is_raw_tx_rx_message(self, message):

        """Return True for low-level TX/RX protocol dumps not meant for the UI."""

        text = str(message).strip().upper()

        return (

            " TX:" in text

            or text.startswith("TX:")

            or " RX:" in text

            or text.startswith("RX:")

            or "TX =" in text

            or "RX =" in text

        )

    def _update_status_message(self, message):

        """Show user-facing status only; hide raw TX/RX protocol messages."""

        if self._is_raw_tx_rx_message(message):

            return

        self._status.setText(str(message))

    def add_terminal_message(self, message):

        # Raw TX/RX protocol dumps are intentionally not displayed.

        if self._is_raw_tx_rx_message(message):

            return

        self.terminal_messages.append(str(message))

        self._update_status_message(message)

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

                self._di_serial_connection = serial.Serial(

                    selected_port,

                    int(self._baud.currentText()),

                    timeout=1

                )

                self._di_connected_baud_rate = int(self._baud.currentText())

                self._status.setText("Connected")

                self._set_status_color("#00C928")

                self._connect_button.setText("DISCONNECT")

                dialog.accept()

            except Exception:

                self._di_serial_connection = None

                self._status.setText("Connection Error")

                self._set_status_color("#D00000")

                self._connect_button.setText("CONNECT")

                dialog.reject()

        connect_button.clicked.connect(connect_selected)

        cancel_button.clicked.connect(dialog.reject)

        dialog.exec()

    def _check_connection_status(self):

        # Monitor Digital Input COM connection.

        if self._di_serial_connection is not None:

            try:

                current_port = self._di_serial_connection.port

                available_ports = {port.device for port in list_ports.comports()}

                port_is_missing = current_port not in available_ports

                disconnected = (

                    not self._di_serial_connection.is_open

                    or port_is_missing

                )

                if disconnected:

                    print("COM Port disconnected:", current_port)

                    self._stop_run()

                    self._apply_pending = False

                    self._apply_timer.stop()

                    self._apply_buffer.clear()

                    self._refresh_pending = False

                    self._refresh_timer.stop()

                    self._refresh_buffer.clear()

                    try:

                        self._di_serial_connection.close()

                    except Exception:

                        pass

                    self._di_serial_connection = None

                    self._connect_button.setText("CONNECT")

                    self._status.setText("COM Port Not Found")

                    self._set_status_color("#D00000")

            except Exception as exc:

                print("DI COM Port Monitor Error:", repr(exc))

                if (

                    self._di_serial_connection is None

                    or not self._di_serial_connection.is_open

                ):

                    self._di_serial_connection = None

                    self._stop_run()

                    self._connect_button.setText("CONNECT")

                    self._status.setText("COM Port Not Found")

                    self._set_status_color("#D00000")

        # Monitor RTU Settings COM connection.

        if self._rtu_serial_connection is not None:

            try:

                current_port = self._rtu_serial_connection.port

                available_ports = {port.device for port in list_ports.comports()}

                port_is_missing = current_port not in available_ports

                disconnected = (

                    not self._rtu_serial_connection.is_open

                    or port_is_missing

                )

                if disconnected:

                    print("RTU Settings COM Port disconnected:", current_port)

                    self._apply_pending = False

                    self._apply_timer.stop()

                    self._apply_baud_timer.stop()

                    self._apply_buffer.clear()

                    self._apply_target_baud_rate = None

                    self._refresh_pending = False

                    self._refresh_timer.stop()

                    self._refresh_buffer.clear()

                    try:

                        self._rtu_serial_connection.close()

                    except Exception:

                        pass

                    self._rtu_serial_connection = None

                    self._rtu_connected_baud_rate = None

                    self._rtu_connect_button.setText("CONNECT")

                    self._status.setText("COM Port Not Found")

                    self._set_status_color("#D00000")

            except Exception as exc:

                print("RTU COM Port Monitor Error:", repr(exc))

                if (

                    self._rtu_serial_connection is None

                    or not self._rtu_serial_connection.is_open

                ):

                    self._rtu_serial_connection = None

                    self._rtu_connected_baud_rate = None

                    self._rtu_connect_button.setText("CONNECT")

                    self._status.setText("COM Port Not Found")

                    self._set_status_color("#D00000")

    def handle_rtu_connect(self):

        if self._rtu_connect_button.text() == "DISCONNECT":

            self._apply_pending = False

            self._apply_timer.stop()

            self._apply_baud_timer.stop()

            self._apply_buffer.clear()

            self._apply_target_baud_rate = None

            self._refresh_pending = False

            self._refresh_timer.stop()

            self._refresh_buffer.clear()

            try:

                if self._rtu_serial_connection is not None:

                    self._rtu_serial_connection.close()

            except Exception:

                pass

            finally:

                self._rtu_serial_connection = None

            self._rtu_connected_baud_rate = None

            self._rtu_connect_button.setText("CONNECT")

            return

        self.show_rtu_com_port_popup()

    def show_rtu_com_port_popup(self):

        ports = [port.device for port in list_ports.comports()]

        if not ports:

            self._status.setText("COM Port Not Found")

            self._set_status_color("#D00000")

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

                self._rtu_serial_connection = serial.Serial(

                    selected_port,

                    int(self._rtu_baud.currentText()),

                    timeout=1

                )

                self._rtu_serial_connection.reset_input_buffer()

                self._rtu_serial_connection.reset_output_buffer()

                self._rtu_connected_baud_rate = int(self._rtu_baud.currentText())

                self._rtu_connect_button.setText("DISCONNECT")

                self._status.setText("RTU Settings Connected")

                self._set_status_color("#00C928")

                dialog.accept()

            except Exception:

                self._rtu_serial_connection = None

                self._rtu_connected_baud_rate = None

                self._rtu_connect_button.setText("CONNECT")

                self._status.setText("RTU Settings Connection Error")

                self._set_status_color("#D00000")

                dialog.reject()

        connect_button.clicked.connect(connect_selected)

        cancel_button.clicked.connect(dialog.reject)

        dialog.exec()

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

                if self._di_serial_connection is not None:

                    self._di_serial_connection.close()

            finally:

                self._di_serial_connection = None

            self._status.setText("Not Connected")

            self._set_status_color("#10C51F")

            self._di_connected_baud_rate = None

            self._connect_button.setText("CONNECT")

            return

        self.show_com_port_popup()

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

            self._status.setText("Slave ID must be 1 to 63")

            return

        if not 1 <= slave_id <= 63:

            self._status.setText("Slave ID must be 1 to 63")

            return

        baud_rate = self._rtu_baud.currentText()

        target_baud_rate = int(baud_rate)

        command = f"SID={slave_id},MBD_BAUD={baud_rate}\n"

        if self._apply_pending:

            return

        try:

            self._rtu_serial_connection.reset_input_buffer()

            self._apply_buffer.clear()

            # Send the settings command using the baud rate currently

            # active on the device. The local baud rate is changed only

            # after the device has had time to process the command.

            self._rtu_serial_connection.write(command.encode("ascii"))

            self._rtu_serial_connection.flush()

            message = f"RTU SETTINGS TX: SID={slave_id}, BAUD={baud_rate}"

            self._update_status_message(message)

            print(message)

            self._apply_target_baud_rate = target_baud_rate

            self._apply_pending = True

            self._apply_elapsed = 0

            self._apply_timer.start(20)


        except Exception:

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

            self._rtu_connected_baud_rate = self._apply_target_baud_rate

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

            self._apply_pending = False

            self._apply_timer.stop()

            self._apply_buffer.clear()

            return

        try:

            waiting = self._rtu_serial_connection.in_waiting

            if waiting > 0:

                chunk = self._rtu_serial_connection.read(waiting)

                self._apply_buffer.extend(chunk)

                message = f"RTU SETTINGS RX: {chunk!r}"

                self._update_status_message(message)

                print(message)

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

                    if (

                        self._apply_target_baud_rate is not None

                        and self._rtu_connected_baud_rate != self._apply_target_baud_rate

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

            self._rtu_serial_connection is None

            or not self._rtu_serial_connection.is_open

        ):

            self._status.setText("COM Port Not Connected")

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

            return

        try:

            waiting = self._rtu_serial_connection.in_waiting

            if waiting > 0:

                self._refresh_buffer.extend(

                    self._rtu_serial_connection.read(waiting)

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

                                and self._rtu_baud.findText(baud_text) >= 0

                            ):

                                self._rtu_slave_id.setText(slave_text)

                                self._rtu_baud.setCurrentText(baud_text)

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

            self._di_serial_connection is None

            or not self._di_serial_connection.is_open

        ):

            print("DI RUN: COM Port Not Found")

            self._status.setText("COM Port Not Found")

            return

        self._status.setText("DI RUNNING")

        self._set_status_color("#00C928")

        print("DI RUN: STARTED")

        print("DI RUN: COM Port:", self._di_serial_connection.port)

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

        self._status.setText("DI STOPPED")

        self._set_status_color("#D00000")

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

            if self._di_serial_connection is not None:

                self._di_serial_connection.close()

        except Exception:

            pass

        finally:

            self._di_serial_connection = None

        self._connect_button.setText("CONNECT")

        self._status.setText("COM Port Not Found")

        self._set_status_color("#D00000")

    def _sync_di_baud_rate(self):

        """Apply the currently selected Digital Input baud rate to the

        already-open DI serial port without reconnecting it.

        """

        if self._di_serial_connection is None or not self._di_serial_connection.is_open:

            return False

        try:

            selected_baud = int(self._baud.currentText())

            if self._di_serial_connection.baudrate != selected_baud:

                self._di_serial_connection.baudrate = selected_baud

                self._di_serial_connection.reset_input_buffer()

                self._di_serial_connection.reset_output_buffer()

                self._di_connected_baud_rate = selected_baud

                print(f"DI Baud Rate changed to: {selected_baud}")

            return True

        except Exception as exc:

            print(f"DI Baud Rate change error: {exc}")

            return False

    def _run_tx_rx_cycle(self):

        if not self._run_active:

            self._run_timer.stop()

            return

        if (

            self._di_serial_connection is None

            or not self._di_serial_connection.is_open

        ):

            self._handle_run_com_port_lost()

            return

        try:

            # Do not treat a missing RX response as a COM disconnect.

            # The connection monitor handles real physical disconnects.

            # RUN must remain active when the selected Slave ID is wrong or

            # the device simply does not respond.

            # Always read the current Digital Input Slave ID.

            slave_text = self._slave_id.text().strip()

            try:

                slave_id = int(slave_text)

            except ValueError:

                self._run_waiting_rx = False

                self._run_buffer.clear()

                self._run_elapsed = 0

                self._status.setText("Slave ID must be 1 to 63")

                self._set_status_color("#D00000")

                return

            if not 1 <= slave_id <= 63:

                self._run_waiting_rx = False

                self._run_buffer.clear()

                self._run_elapsed = 0

                self._status.setText("Slave ID must be 1 to 63")

                self._set_status_color("#D00000")

                return

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

                # Pick up the latest Digital Input baud-rate selection before every RUN TX.

                if not self._sync_di_baud_rate():

                    self._status.setText("DI Baud Rate Error")

                    self._set_status_color("#D00000")

                    return

                self._di_serial_connection.reset_input_buffer()

                self._run_buffer.clear()

                self._di_serial_connection.write(command)

                self._di_serial_connection.flush()

                message = f"DI RUN TX: {command.hex(' ').upper()}"

                self._update_status_message(message)

                print(message)

                self._run_waiting_rx = True

                self._run_elapsed = 0

                return

            waiting = self._di_serial_connection.in_waiting

            if waiting > 0:

                self._run_buffer.extend(

                    self._di_serial_connection.read(waiting)

                )

            # Digital Input RUN response for 16 inputs:

            # Slave ID + 01 + 02 + DATA1 + DATA2 + Modbus CRC

            expected_length = 7

            if len(self._run_buffer) >= expected_length:

                response = bytes(self._run_buffer[:expected_length])

                message = f"DI RUN RX: {response.hex(' ').upper()}"

                self._update_status_message(message)

                print(message)

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

                            self._set_di_led(index, is_on)

                        for index in range(8):

                            is_on = bool(

                                di_data_2 & (1 << index)

                            )

                            self._set_di_led(index + 8, is_on)

                        self._run_waiting_rx = False

                        self._run_buffer.clear()

                        self._run_elapsed = 0

                        self._status.setText("DI RUNNING")

                        self._set_status_color("#00C928")

                        return

                message = (

                    "DI RUN RX: INVALID/UNEXPECTED RESPONSE: "

                    f"{response.hex(' ').upper()}"

                )

                self._update_status_message(message)

                print(message)

                self._run_waiting_rx = False

                self._run_buffer.clear()

                self._run_elapsed = 0

            if self._run_waiting_rx:

                self._run_elapsed += 20

            # If no valid RX is received within 2 seconds, timeout only

            # the current request. Keep RUN active and keep the COM port

            # open so the next RUN cycle can send a fresh TX automatically.

            if self._run_elapsed >= 2000:

                message = "DI RUN TIMEOUT: No RX received within 2 seconds"

                self._update_status_message(message)

                print(message)

                self._run_waiting_rx = False

                self._run_buffer.clear()

                self._run_elapsed = 0

                self.digital_input_timeout_label.hide()

                self._status.setText("DI Refresh Timeout")

                self._set_status_color("#D00000")

                self.add_terminal_message("DI Refresh Timeout")

                # Do NOT stop _run_timer, _run_active, or the COM port.

                # The next timer cycle will send the next TX.

                return

        except Exception as error:

            # An RX/read/response error is NOT treated as a COM disconnect.

            # Clear only the current request and allow the next RUN cycle to

            # send a fresh TX while keeping the COM connection and RUN active.

            message = f"DI RUN ERROR: {error!r}"

            self._update_status_message(message)

            print(message)

            self._run_waiting_rx = False

            self._run_buffer.clear()

            self._run_elapsed = 0

            if (

                self._di_serial_connection is None

                or not self._di_serial_connection.is_open

            ):

                self._handle_run_com_port_lost()

                return

            self._status.setText("DI Refresh Error")

            self._set_status_color("#D00000")

            self.add_terminal_message(f"DI Refresh Error: {error}")

            return

    def handle_back(self):

        self._connection_monitor_timer.stop()

        self._stop_run()

        self._apply_pending = False

        self._apply_timer.stop()

        self._apply_baud_timer.stop()

        self._apply_buffer.clear()

        self._apply_target_baud_rate = None

        self._refresh_pending = False

        self._refresh_timer.stop()

        self._refresh_buffer.clear()

        # Close Digital Input COM.

        if self._di_serial_connection is not None:

            try:

                self._di_serial_connection.close()

            except Exception:

                pass

            finally:

                self._di_serial_connection = None

        # Close RTU Settings COM.

        if self._rtu_serial_connection is not None:

            try:

                self._rtu_serial_connection.close()

            except Exception:

                pass

            finally:

                self._rtu_serial_connection = None

        # Reset complete page to initial state.

        self._di_connect_button.setText("CONNECT")

        self._rtu_connect_button.setText("CONNECT")

        self.di_slave_id.setText("1")

        self.di_baud_rate.setCurrentText("9600")

        self.slave_id.setText("1")

        self.baud_rate.setCurrentText("9600")

        self._di_connected_baud_rate = None

        self._rtu_connected_baud_rate = None

        self._reset_di_leds()

        self.digital_input_timeout_label.hide()

        self._status.setText("Not Connected")

        self._set_status_color("#10C51F")

        self.terminal_messages = ["Device Terminal Ready"]

        self.terminal_message.setPlainText("Device Terminal Ready")

        self.back_clicked.emit()