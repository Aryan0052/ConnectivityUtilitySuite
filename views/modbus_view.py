import os
import re
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
    QScrollArea,
)

try:
    from . import ui_theme as ui
except ImportError:
    import ui_theme as ui


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
    PROTOCOL_SELECT_TEXT = "Select protocol"
    PROTOCOL_IEC104_TEXT = "IEC 60870-5-104"
    PROTOCOL_MODBUS_TCP_TEXT = "Modbus TCP/IP"
    PROTOCOL_NONE_TEXT = "--"
    # Protocol -> (UART channel command, expected OK reply)
    PROTOCOL_COMMANDS = {
        PROTOCOL_IEC104_TEXT: (b"UART,CH=1\r\n", "OK:IEC104"),
        PROTOCOL_MODBUS_TCP_TEXT: (b"UART,CH=2\r\n", "OK:MODBUS_TCP"),
    }
    # GETCFG ...,CH=n  -> protocol name
    PROTOCOL_BY_CHANNEL = {
        "1": PROTOCOL_IEC104_TEXT,
        "2": PROTOCOL_MODBUS_TCP_TEXT,
    }

    def _set_status_color(self, color):
        ui.set_status(self._status, None, color)

    def __init__(self):
        super().__init__()
        self._serial_connection = None
        self._connected_baud_rate = None
        self._apply_target_baud_rate = None
        self._apply_baud_timer = QTimer(self)
        self._apply_baud_timer.setSingleShot(True)
        self._apply_baud_timer.timeout.connect(self._switch_to_applied_baud)
        self._tcp_apply_pending = False
        self._tcp_apply_buffer = bytearray()
        self._mac_apply_pending = False
        self._mac_apply_buffer = bytearray()
        self._mac_apply_timer = QTimer(self)
        self._mac_apply_timer.timeout.connect(self._check_mac_apply_response)
        self._mac_apply_elapsed = 0
        self._tcp_apply_timer = QTimer(self)
        self._tcp_apply_timer.timeout.connect(self._check_tcp_apply_response)
        self._tcp_apply_elapsed = 0
        self._refresh_pending = False
        self._refresh_buffer = bytearray()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._check_refresh_response)
        self._refresh_elapsed = 0
        # Lock each UART APPLY button until its response or 2-second timeout.
        self._port1_apply_pending = False
        self._port2_apply_pending = False
        self._rtu_apply_pending = False
        self._tcp_apply_pending = False
        # Communication protocol selection (UART,CH=1 -> IEC104, UART,CH=2 -> Modbus TCP).
        self._protocol_apply_pending = False
        self._protocol_apply_buffer = bytearray()
        self._protocol_apply_elapsed = 0
        self._protocol_apply_target = None
        self._protocol_apply_timer = QTimer(self)
        self._protocol_apply_timer.timeout.connect(self._check_protocol_apply_response)
        self.build_ui()

    def build_ui(self):
        # Look: shared with the other pages and the Multi Device page (ui_theme.py). Only widgets and
        # styles are built here - every attribute the communication code uses keeps its name.
        ui.install(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = ui.Header("Modbus TCP Gateway", root=self)
        back = header.back_button
        back.clicked.connect(self.handle_back)
        status = header.status
        status.setText("● Not Connected")
        header.status_dot.hide()          # the status texts already start with their own dot
        root.addWidget(header)

        main = QWidget()
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        def box(title):
            frame = QFrame()
            frame.setObjectName("pgBox")
            lay = QVBoxLayout(frame)
            lay.setContentsMargins(16, 14, 16, 16)
            lay.setSpacing(10)
            lay.addWidget(ui.label(title.upper(), "pgSection"))
            return frame, lay

        def row_of(*pairs):
            holder = QWidget()
            row = QHBoxLayout(holder)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(12)
            for text, widget in pairs:
                row.addWidget(ui.field(text, widget), 1)
            return holder

        # ------------------------------------------------------------ LEFT: RTU connection + terminal
        left_panel = ui.card()
        ui.sized(left_panel, "setMinimumWidth", 330)
        ui.sized(left_panel, "setMaximumWidth", 380)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(18, 18, 18, 18)
        left_layout.setSpacing(12)

        left_layout.addWidget(ui.section("Connection"))
        connect = ui.button("CONNECT", "primary", 38, alt={"DISCONNECT": "softdanger"})
        left_layout.addWidget(connect)

        # Read-only: updated from GETCFG (CH=1 / CH=2) and from the OK reply
        # of the protocol selection on the right panel.
        protocol = QLineEdit(self.PROTOCOL_NONE_TEXT)
        protocol.setReadOnly(True)
        protocol.setFocusPolicy(Qt.NoFocus)
        left_layout.addWidget(ui.field("Active Protocol", protocol))

        left_layout.addSpacing(4)
        left_layout.addWidget(ui.section("RTU Slave Settings"))
        slave_id = QLineEdit("1")
        left_layout.addWidget(ui.field("Slave ID (1-63)", slave_id, "Valid Slave IDs: 1 to 63"))

        # Keep COM Port as an internal connection value; selection is done in the CONNECT popup.
        com_port = QComboBox()
        com_port.setVisible(False)
        self.com_port = com_port

        baud = QComboBox()
        baud.addItems(["9600", "19200", "38400", "115200"])
        baud.setCurrentText("9600")
        left_layout.addWidget(ui.field("RTU Baud Rate", baud))

        apply_rtu = ui.button("APPLY", "secondary", 36)
        left_layout.addWidget(apply_rtu)

        left_layout.addSpacing(4)
        terminal_row = QHBoxLayout()
        terminal_row.setContentsMargins(0, 0, 0, 0)
        terminal_row.addWidget(ui.label("DEVICE TERMINAL", "pgSection"))
        terminal_row.addStretch()
        refresh = ui.button("\u27f3  Refresh", "ghost")
        refresh.clicked.connect(self.handle_refresh)
        terminal_row.addWidget(refresh)
        left_layout.addLayout(terminal_row)

        self.com_port_refresh_timer = QTimer(self)
        self.com_port_refresh_timer.timeout.connect(self.refresh_com_ports)
        self.com_port_refresh_timer.start(1000)
        self.refresh_com_ports()

        # Automatically detect when the connected COM port is removed.
        self._connection_monitor_timer = QTimer(self)
        self._connection_monitor_timer.timeout.connect(self._check_connection_status)
        self._connection_monitor_timer.start(500)

        terminal_message = ui.terminal("Device Terminal Ready")
        ui.sized(terminal_message, "setMinimumHeight", 140)
        self.terminal_message = terminal_message
        self.terminal_messages = ["Device Terminal Ready"]
        left_layout.addWidget(terminal_message, 1)

        # ------------------------------------------------------------ RIGHT: gateway configuration
        right_panel = ui.card()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(22, 20, 22, 20)
        right_layout.setSpacing(14)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_col.addWidget(ui.label("Gateway Configuration", "pgTitle"))
        title_col.addWidget(ui.label("Protocol, TCP/IP, MAC address and serial port settings of the device", "pgSub"))
        right_layout.addLayout(title_col)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        # --- Communication protocol (UART,CH=1 / UART,CH=2) - selection only, APPLY sends it
        protocol_box, protocol_lay = box("Communication Protocol")
        comm_protocol = QComboBox()
        comm_protocol.addItems([
            self.PROTOCOL_SELECT_TEXT,
            self.PROTOCOL_IEC104_TEXT,
            self.PROTOCOL_MODBUS_TCP_TEXT,
        ])
        comm_protocol.setCurrentIndex(0)
        apply_protocol = ui.button("APPLY", "primary", 36)
        ui.sized(apply_protocol, "setMinimumWidth", 100)
        protocol_row = QHBoxLayout()
        protocol_row.setSpacing(10)
        protocol_row.addWidget(comm_protocol, 1)
        protocol_row.addWidget(apply_protocol)
        protocol_holder = QWidget()
        protocol_holder.setLayout(protocol_row)
        protocol_row.setContentsMargins(0, 0, 0, 0)
        protocol_lay.addWidget(ui.field("Protocol", protocol_holder))
        grid.addWidget(protocol_box, 0, 0)

        # --- TCP/IP
        tcp_box, tcp_lay = box("TCP/IP Communication")
        ip_address = QLineEdit()
        ip_address.setPlaceholderText("192.168.1.100")
        subnet = QLineEdit()
        subnet.setPlaceholderText("255.255.255.0")
        tcp_port = QLineEdit("502")
        tcp_lay.addWidget(row_of(("IP Address", ip_address), ("Subnet Mask", subnet)))
        port_row_holder = QWidget()
        port_row = QHBoxLayout(port_row_holder)
        port_row.setContentsMargins(0, 0, 0, 0)
        port_row.setSpacing(12)
        port_row.addWidget(ui.field("TCP Port", tcp_port), 1)
        apply_tcp = ui.button("APPLY", "primary", 36)
        ui.sized(apply_tcp, "setMinimumWidth", 100)
        port_row.addStretch(1)
        port_row.addWidget(apply_tcp, 0, Qt.AlignBottom)
        tcp_lay.addWidget(port_row_holder)
        grid.addWidget(tcp_box, 1, 0)

        # --- MAC address
        mac_box, mac_lay = box("MAC Address")
        current_mac = QLineEdit()
        current_mac.setReadOnly(True)
        current_mac.setPlaceholderText("02:B5:18:3D:15:5F")
        current_mode = QLineEdit("--")
        current_mode.setReadOnly(True)
        ui.sized(current_mode, "setMaximumWidth", 150)
        mac_lay.addWidget(row_of(("Current MAC Address", current_mac), ("Current Mode", current_mode)))
        mac_mode = QComboBox()
        mac_mode.addItems(["Keep current", "Manual", "Random"])
        mac_mode.setCurrentText("Keep current")
        manual_mac = QLineEdit()
        manual_mac.setPlaceholderText("02:B5:18:3D:15:5F")
        manual_mac.setEnabled(False)
        mac_lay.addWidget(row_of(("MAC Address Mode", mac_mode), ("Manual MAC Address", manual_mac)))
        apply_mac = ui.button("APPLY MAC", "primary", 36)
        ui.sized(apply_mac, "setMinimumWidth", 130)
        mac_apply_row = QHBoxLayout()
        mac_apply_row.addWidget(apply_mac)
        mac_apply_row.addStretch()
        mac_lay.addLayout(mac_apply_row)
        mac_lay.addStretch(1)
        mac_mode.currentTextChanged.connect(
            lambda value: manual_mac.setEnabled(value == "Manual")
        )
        grid.addWidget(mac_box, 0, 1, 2, 1)

        # --- Serial port baud rates
        port_box, port_lay = box("Port Settings")
        port1 = QComboBox()
        port1.addItems(["9600", "19200", "38400", "115200"])
        port1.setCurrentText("9600")
        port2 = QComboBox()
        port2.addItems(["9600", "19200", "38400", "115200"])
        port2.setCurrentText("9600")
        apply_port1 = ui.button("APPLY", "primary", 36)
        ui.sized(apply_port1, "setMinimumWidth", 90)
        apply_port2 = ui.button("APPLY", "primary", 36)
        ui.sized(apply_port2, "setMinimumWidth", 90)

        def port_row_of(text, combo, button):
            holder = QWidget()
            lay = QHBoxLayout(holder)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(10)
            lay.addWidget(ui.field(text, combo), 1)
            lay.addWidget(button, 0, Qt.AlignBottom)
            return holder

        ports_holder = QWidget()
        ports_lay = QHBoxLayout(ports_holder)
        ports_lay.setContentsMargins(0, 0, 0, 0)
        ports_lay.setSpacing(16)
        ports_lay.addWidget(port_row_of("Port 1 Baud Rate", port1, apply_port1), 1)
        ports_lay.addWidget(port_row_of("Port 2 Baud Rate", port2, apply_port2), 1)
        port_lay.addWidget(ports_holder)
        grid.addWidget(port_box, 2, 0, 1, 2)

        right_layout.addLayout(grid)
        right_layout.addStretch()

        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_panel, 1)

        # Header stays fixed; only the main content scrolls when the window is small / DPI is high.
        main_scroll = QScrollArea()
        main_scroll.setWidgetResizable(True)
        main_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        main_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        main_scroll.setFrameShape(QFrame.NoFrame)
        main_scroll.setWidget(main)
        root.addWidget(main_scroll, 1)

        # Keep references for UI actions.
        self._status = status
        self._connect_button = connect
        self._protocol = protocol
        self._active_protocol = protocol
        self._comm_protocol = comm_protocol
        self._apply_protocol_button = apply_protocol
        self._slave_id = slave_id
        self._baud = baud
        self._com_port = com_port
        self._ip_address = ip_address
        self._subnet = subnet
        self._tcp_port = tcp_port
        self._current_mac = current_mac
        self._current_mac_mode = current_mode
        self._mac_mode = mac_mode
        self._manual_mac = manual_mac
        self._port1 = port1
        self._port2 = port2
        self._apply_port1_button = apply_port1
        self._apply_port2_button = apply_port2
        self._apply_rtu_button = apply_rtu
        self._apply_tcp_button = apply_tcp
        self._apply_mac_button = apply_mac

        # Connect every action button after all widgets are created.
        connect.clicked.connect(self.handle_connect)
        apply_rtu.clicked.connect(self.handle_apply_rtu)
        apply_tcp.clicked.connect(self.handle_apply_tcp)
        apply_mac.clicked.connect(self.handle_apply_mac)
        apply_port1.clicked.connect(self.handle_apply_port1)
        apply_port2.clicked.connect(self.handle_apply_port2)

        # Selecting in the dropdown only changes the choice; APPLY sends UART,CH=n.
        apply_protocol.clicked.connect(self.handle_apply_protocol)
    # ---------------------------------------------------------
    # SERIAL BUFFER LOG -> VS Code / cmd terminal only (not the app Device Terminal)
    # Format same as the reference tool:  TX > <Buffer 47 45 54 43 46 47 0a>
    # ---------------------------------------------------------

    @staticmethod
    def _log_buffer(direction, data):
        if isinstance(data, str):
            data = data.encode("ascii", errors="replace")
        data = bytes(data)
        text = data.decode("ascii", errors="replace").strip()
        print(f"{direction} > <Buffer {data.hex(' ')}>   {text}", flush=True)
    # ---------------------------------------------------------
    # COMMUNICATION PROTOCOL  (UART,CH=1 -> OK:IEC104 / UART,CH=2 -> OK:MODBUS_TCP)
    # ---------------------------------------------------------

    def _set_active_protocol(self, name):
        name = name or self.PROTOCOL_NONE_TEXT
        self._active_protocol.setText(name)
        index = self._comm_protocol.findText(name)
        self._comm_protocol.setCurrentIndex(index if index >= 0 else 0)

    def _restore_protocol_selection(self):
        index = self._comm_protocol.findText(self._active_protocol.text())
        self._comm_protocol.setCurrentIndex(index if index >= 0 else 0)

    def _stop_protocol_apply(self):
        self._protocol_apply_pending = False
        self._protocol_apply_timer.stop()
        self._protocol_apply_buffer.clear()
        self._protocol_apply_target = None
        self._comm_protocol.setEnabled(True)
        self._apply_protocol_button.setEnabled(True)

    def _protocol_apply_failed(self, reason="Protocol change failed"):
        self._stop_protocol_apply()
        self._restore_protocol_selection()
        self._status.setText(f"● {reason}")
        self._set_status_color("#D00000")

    def handle_apply_protocol(self):
        name = self._comm_protocol.currentText()
        if name not in self.PROTOCOL_COMMANDS:
            # "Select protocol" chosen: nothing to send.
            self._status.setText("● Select a protocol first")
            self._set_status_color("#D00000")
            return
        if (
            self._connect_button.text() != "DISCONNECT"
            or self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            self._status.setText("● COM Port not connected")
            self._set_status_color("#D00000")
            return
        if self._protocol_apply_pending:
            return
        # Do not clear the input buffer while another command is waiting for its reply.
        if (
            self._refresh_pending
            or self._tcp_apply_pending
            or self._mac_apply_pending
            or self._rtu_apply_pending
            or self._port1_apply_pending
            or self._port2_apply_pending
        ):
            self._status.setText("● Device busy, try again")
            self._set_status_color("#D00000")
            return
        command, _expected = self.PROTOCOL_COMMANDS[name]
        try:
            # Clean RX buffer before TX so an old reply is never taken as this answer.
            self._serial_connection.reset_input_buffer()
            self._protocol_apply_buffer.clear()
            self._log_buffer("TX", command)
            self._serial_connection.write(command)
            self._serial_connection.flush()
            self._protocol_apply_pending = True
            self._protocol_apply_target = name
            self._protocol_apply_elapsed = 0
            self._comm_protocol.setEnabled(False)
            self._apply_protocol_button.setEnabled(False)
            self._status.setText(f"● Switching to {name}...")
            self._set_status_color("#00C928")
            self._protocol_apply_timer.start(20)
        except Exception:
            self._protocol_apply_failed()

    def _check_protocol_apply_response(self):
        if not self._protocol_apply_pending:
            self._protocol_apply_timer.stop()
            return
        if (
            self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            self._protocol_apply_failed("COM Port Not Connected")
            return
        try:
            waiting = self._serial_connection.in_waiting
            if waiting > 0:
                chunk = self._serial_connection.read(waiting)
                self._log_buffer("RX", chunk)
                self._protocol_apply_buffer.extend(chunk)
            # Work on complete lines only (device ends replies with \n / \r\n).
            while b"\n" in self._protocol_apply_buffer:
                line_bytes, _, remaining = self._protocol_apply_buffer.partition(b"\n")
                self._protocol_apply_buffer = bytearray(remaining)
                line = line_bytes.decode("ascii", errors="replace").strip()
                if not line:
                    continue
                target = self._protocol_apply_target
                _command, expected = self.PROTOCOL_COMMANDS.get(target, (b"", ""))
                if line.upper() == expected:
                    self._stop_protocol_apply()
                    self._set_active_protocol(target)
                    self._status.setText(f"● Protocol: {target}")
                    self._set_status_color("#00C928")
                    # Read back the config (GETCFG ... ,CH=n) to confirm.
                    if not self._refresh_pending:
                        QTimer.singleShot(300, self.handle_refresh)
                    return
                if line.upper().startswith("ERR"):
                    self._protocol_apply_failed()
                    return
                if line.upper().startswith("OK:"):
                    # OK for the other protocol = device did not take this one.
                    self._protocol_apply_failed()
                    return
                # Any other line (echo / leftover) is ignored (already printed in the VS Code terminal).
            self._protocol_apply_elapsed += 20
            if self._protocol_apply_elapsed >= 2000:
                pending_text = self._protocol_apply_buffer.decode("ascii", errors="replace").strip()
                if pending_text:
                    print(f"RX > incomplete reply at timeout: {pending_text!r}", flush=True)
                self._protocol_apply_failed("Protocol change failed (no reply)")
        except Exception:
            self._protocol_apply_failed()

    def handle_back(self):
        self._connection_monitor_timer.stop()
        self._stop_protocol_apply()
        self._set_active_protocol(None)
        self._tcp_apply_pending = False
        self._tcp_apply_timer.stop()
        self._tcp_apply_buffer.clear()
        self._mac_apply_pending = False
        self._mac_apply_timer.stop()
        self._mac_apply_buffer.clear()
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
        self._current_mac.clear()
        self._current_mac_mode.setText("--")
        self._mac_mode.setCurrentText("Keep current")
        self._manual_mac.clear()
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
            self._set_status_color("#D00000")
            return
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
                self._status.setText("● COM Port Not Found")
                self._set_status_color("#D00000")
                return
            self._com_port.setCurrentText(selected_port)
            try:
                import serial
                self._serial_connection = serial.Serial(
                    selected_port,
                    int(self._baud.currentText()),
                    timeout=1
                )
                self._connected_baud_rate = int(self._baud.currentText())
                self._status.setText("● Connected")
                self._set_status_color("#00C928")
                self._set_status_color("#00C928")
                self._connect_button.setText("DISCONNECT")
                # Same as the reference tool: send a single newline first so any
                # half-received command inside the device is closed. Its reply is
                # thrown away by reset_input_buffer() before GETCFG.
                try:
                    self._log_buffer("TX", b"\n")
                    self._serial_connection.write(b"\n")
                    self._serial_connection.flush()
                except Exception:
                    pass
                dialog.accept()
                # Give the device time to stabilize after the COM port opens.
                # Only after this delay should the existing Refresh/GETCFG flow run.
                def refresh_after_connection():
                    if (
                        self._serial_connection is not None
                        and self._serial_connection.is_open
                        and self._connect_button.text() == "DISCONNECT"
                    ):
                        self.handle_refresh()
                QTimer.singleShot(1500, refresh_after_connection)
            except Exception:
                self._serial_connection = None
                self._status.setText("● Connection Error")
                self._set_status_color("#D00000")
                self._connect_button.setText("CONNECT")
                dialog.reject()
        connect_button.clicked.connect(connect_selected)
        cancel_button.clicked.connect(dialog.reject)
        dialog.exec()

    def handle_connect(self):
        if self._connect_button.text() == "DISCONNECT":
            self._stop_protocol_apply()
            self._set_active_protocol(None)
            self._tcp_apply_pending = False
            self._tcp_apply_timer.stop()
            self._tcp_apply_buffer.clear()
            self._mac_apply_pending = False
            self._mac_apply_timer.stop()
            self._mac_apply_buffer.clear()
            self._apply_baud_timer.stop()
            self._apply_target_baud_rate = None
            self._refresh_pending = False
            self._refresh_timer.stop()
            self._refresh_buffer.clear()
            try:
                if self._serial_connection is not None:
                    self._serial_connection.close()
            finally:
                self._serial_connection = None
            self._status.setText("● Not Connected")
            self._set_status_color("#00C928")
            self._connect_button.setText("CONNECT")
            return
        self.show_com_port_popup()

    def handle_apply_rtu(self):
        if self._rtu_apply_pending:
            return
        # RTU settings can only be applied after a COM port is connected.
        if (
            self._connect_button.text() != "DISCONNECT"
            or not self._com_port.currentText().strip()
        ):
            self._status.setText("● COM Port not connected")
            self._set_status_color("#D00000")
            return
        slave_text = self._slave_id.text().strip()
        try:
            slave_id = int(slave_text)
        except ValueError:
            self._status.setText("● Slave ID must be 1 to 63")
            self._set_status_color("#D00000")
            return
        if not 1 <= slave_id <= 63:
            self._status.setText("● Slave ID must be 1 to 63")
            self._set_status_color("#D00000")
            return
        baud_rate = self._baud.currentText()
        target_baud_rate = int(baud_rate)
        command = f"SID={slave_id},MBD_BAUD={baud_rate}\n"
        try:
            if (
                self._serial_connection is None
                or not self._serial_connection.is_open
            ):
                self._status.setText("● COM Port not connected")
                self._set_status_color("#D00000")
                return
            self._serial_connection.reset_input_buffer()
            self._log_buffer("TX", command)
            self._serial_connection.write(command.encode("ascii"))
            self._serial_connection.flush()
            self._apply_target_baud_rate = target_baud_rate
            self._rtu_apply_pending = True
            self._apply_rtu_button.setEnabled(False)
            response_buffer = bytearray()
            elapsed = [0]
            def set_failed():
                self._status.setText("● RTU Settings Not Applied")
                self._set_status_color("#D00000")
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
                        chunk = self._serial_connection.read(waiting)
                        self._log_buffer("RX", chunk)
                        response_buffer.extend(chunk)
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
                            self._rtu_apply_pending = False
                            self._apply_baud_timer.stop()
                            if (
                                self._apply_target_baud_rate is not None
                                and self._connected_baud_rate != self._apply_target_baud_rate
                            ):
                                self._switch_to_applied_baud()
                            self._apply_target_baud_rate = None
                            self._apply_rtu_button.setEnabled(True)
                            self._status.setText("● RTU Settings Applied")
                            self._set_status_color("#00C928")
                            self._set_status_color("#00C928")
                            return
                        self._rtu_apply_pending = False
                        self._apply_baud_timer.stop()
                        self._apply_target_baud_rate = None
                        self._apply_rtu_button.setEnabled(True)
                        set_failed()
                        return
                    elapsed[0] += 20
                    # Wait for RX for a maximum of 2 seconds only.
                    # If RX arrives earlier, it is processed immediately.
                    if elapsed[0] >= 2000:
                        response_buffer.clear()
                        self._apply_baud_timer.stop()
                        self._apply_target_baud_rate = None
                        set_failed()
                        return
                    QTimer.singleShot(20, check_rtu_response)
                except Exception:
                    self._rtu_apply_pending = False
                    self._apply_baud_timer.stop()
                    self._apply_target_baud_rate = None
                    self._apply_rtu_button.setEnabled(True)
                    set_failed()
            QTimer.singleShot(20, check_rtu_response)
        except Exception:
            self._rtu_apply_pending = False
            self._apply_baud_timer.stop()
            self._apply_target_baud_rate = None
            self._apply_rtu_button.setEnabled(True)
            self._status.setText("● RTU Settings Not Applied")
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

    def _is_valid_mac(self, mac):
        return bool(re.fullmatch(r"[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}", mac.strip()))

    def handle_apply_mac(self):
        if (
            self._connect_button.text() != "DISCONNECT"
            or self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            self._status.setText("● COM Port not connected")
            self._set_status_color("#D00000")
            return
        if self._mac_apply_pending:
            return
        mode = self._mac_mode.currentText()
        manual_mac = self._manual_mac.text().strip().upper()
        if mode == "Manual":
            if not self._is_valid_mac(manual_mac):
                self._status.setText("● Invalid MAC Address")
                self._set_status_color("#D00000")
                return
            command = f"SETMAC={manual_mac}\n"
        elif mode == "Random":
            command = "SETMAC=AUTO\n"
        else:
            self._status.setText("● Keep current selected")
            self._set_status_color("#00C928")
            return
        try:
            self._serial_connection.reset_input_buffer()
            self._mac_apply_buffer.clear()
            self._log_buffer("TX", command)
            self._serial_connection.write(command.encode("ascii"))
            self._serial_connection.flush()
            self._mac_apply_pending = True
            self._mac_apply_elapsed = 0
            self._apply_mac_button.setEnabled(False)
            self._mac_apply_timer.start(20)
        except Exception:
            self._mac_apply_pending = False
            self._mac_apply_timer.stop()
            self._apply_mac_button.setEnabled(True)
            self._status.setText("● MAC Configuration failed")
            self._set_status_color("#D00000")

    def _check_mac_apply_response(self):
        if not self._mac_apply_pending:
            self._mac_apply_timer.stop()
            return
        if (
            self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            self._mac_apply_pending = False
            self._mac_apply_timer.stop()
            self._apply_mac_button.setEnabled(True)
            return
        try:
            waiting = self._serial_connection.in_waiting
            if waiting > 0:
                chunk = self._serial_connection.read(waiting)
                self._log_buffer("RX", chunk)
                self._mac_apply_buffer.extend(chunk)
            buffer_text = self._mac_apply_buffer.decode("ascii", errors="replace")
            if "OK:MAC" in buffer_text:
                self._mac_apply_pending = False
                self._mac_apply_timer.stop()
                self._apply_mac_button.setEnabled(True)
                self._mac_apply_buffer.clear()
                self.add_terminal_message("OK:MAC")
                self._status.setText("● MAC Configuration applied")
                self._set_status_color("#00C928")
                # Read the new MAC back automatically (GETCFG = REFRESH). The device needs a moment after
                # changing its MAC, so the refresh is sent after 500 ms and repeated (up to 3 times) if no
                # valid configuration comes back.
                self.add_terminal_message("Refreshing configuration...")
                QTimer.singleShot(500, lambda: self._refresh_after_mac(3))
                return
            if "ERR:CMD" in buffer_text:
                self._mac_apply_pending = False
                self._mac_apply_timer.stop()
                self._apply_mac_button.setEnabled(True)
                self._mac_apply_buffer.clear()
                self._status.setText("● MAC Configuration failed")
                self._set_status_color("#D00000")
                return
            self._mac_apply_elapsed += 20
            if self._mac_apply_elapsed >= 2000:
                self._mac_apply_pending = False
                self._mac_apply_timer.stop()
                self._apply_mac_button.setEnabled(True)
                self._mac_apply_buffer.clear()
                self._status.setText("● MAC Configuration failed")
                self._set_status_color("#D00000")
        except Exception:
            self._mac_apply_pending = False
            self._mac_apply_timer.stop()
            self._apply_mac_button.setEnabled(True)
            self._mac_apply_buffer.clear()
            self._status.setText("● MAC Configuration failed")
            self._set_status_color("#D00000")

    def _refresh_after_mac(self, tries):
        if self._serial_connection is None or not self._serial_connection.is_open:
            return
        if self._refresh_pending or self._mac_apply_pending:
            QTimer.singleShot(100, lambda: self._refresh_after_mac(tries))      # wait for the running request
            return
        self.handle_refresh()
        QTimer.singleShot(100, lambda: self._wait_mac_refresh(tries))

    def _wait_mac_refresh(self, tries):
        if self._refresh_pending:
            QTimer.singleShot(100, lambda: self._wait_mac_refresh(tries))
            return
        if "Refreshed" not in self._status.text() and tries > 1:
            QTimer.singleShot(1000, lambda: self._refresh_after_mac(tries - 1))

    def handle_apply_tcp(self):
        ip_text = self._ip_address.text().strip()
        subnet_text = self._subnet.text().strip()
        tcp_port_text = self._tcp_port.text().strip()
        try:
            ip_address(ip_text)
        except ValueError:
            self._status.setText("● Invalid IP Address")
            self._set_status_color("#D00000")
            return
        try:
            ip_network(f"0.0.0.0/{subnet_text}", strict=False)
        except ValueError:
            self._status.setText("● Invalid Subnet Mask")
            self._set_status_color("#D00000")
            return
        try:
            tcp_port = int(tcp_port_text)
        except ValueError:
            self._status.setText("● TCP Port must be between 1 and 65535")
            self._set_status_color("#D00000")
            return
        if not 1 <= tcp_port <= 65535:
            self._status.setText("● TCP Port must be between 1 and 65535")
            self._set_status_color("#D00000")
            return
        if (
            self._connect_button.text() != "DISCONNECT"
            or self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            self._status.setText("● COM Port not connected")
            self._set_status_color("#D00000")
            self._set_status_color("#D00000")
            return
        mode = self._mac_mode.currentText()
        if mode == "Manual":
            apply_mac = self._manual_mac.text().strip().upper()
            if not self._is_valid_mac(apply_mac):
                self._status.setText("● Invalid MAC Address")
                self._set_status_color("#D00000")
                return
        else:
            apply_mac = self._current_mac.text().strip().upper()
            if not self._is_valid_mac(apply_mac):
                self._status.setText("● Current MAC Address not available")
                self._set_status_color("#D00000")
                return
        # Every APPLY starts as a fresh request, so APPLY can be pressed
        # repeatedly after success or timeout.
        self._tcp_apply_pending = False
        self._tcp_apply_timer.stop()
        self._tcp_apply_buffer.clear()
        command = (
            f"ETH,IP={ip_text},"
            f"MASK={subnet_text},"
            f"PORT={tcp_port},"
            f"MAC={apply_mac}\n"
        )
        try:
            self._serial_connection.reset_input_buffer()
            self._tcp_apply_buffer.clear()
            self._log_buffer("TX", command)
            self._serial_connection.write(command.encode("ascii"))
            self._serial_connection.flush()
            self._tcp_apply_pending = True
            self._tcp_apply_elapsed = 0
            self._tcp_apply_timer.start(20)
        except Exception as exc:
            self._tcp_apply_pending = False
            self._tcp_apply_timer.stop()
            self._status.setText("● TCP/IP Configuration failed")
            self._set_status_color("#D00000")
            self._set_status_color("#D00000")

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
                chunk = self._serial_connection.read(waiting)
                self._log_buffer("RX", chunk)
                self._tcp_apply_buffer.extend(chunk)
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
                self._set_status_color("#00C928")
                self._set_status_color("#00C928")
                return
            if "ERR:CMD" in buffer_text:
                self._tcp_apply_pending = False
                self._tcp_apply_timer.stop()
                self._tcp_apply_buffer.clear()
                self._status.setText("● TCP/IP Configuration failed")
                self._set_status_color("#D00000")
                self._set_status_color("#D00000")
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
                    self._set_status_color("#D00000")
                    self._set_status_color("#D00000")
                    return
            # Wait only 2 seconds for the device response.
            self._tcp_apply_elapsed += 20
            if self._tcp_apply_elapsed >= 2000:
                self._tcp_apply_pending = False
                self._apply_tcp_button.setEnabled(True)
                self._tcp_apply_timer.stop()
                self._tcp_apply_buffer.clear()
                self._status.setText("● TCP/IP Configuration failed")
                self._set_status_color("#D00000")
                self._set_status_color("#D00000")
        except Exception as exc:
            self._tcp_apply_pending = False
            self._apply_tcp_button.setEnabled(True)
            self._tcp_apply_timer.stop()
            self._tcp_apply_buffer.clear()
            self._status.setText("● TCP/IP Configuration failed")
            self._set_status_color("#D00000")
            self._set_status_color("#D00000")

    def handle_apply_port1(self):
        if self._port1_apply_pending:
            return
        command = f"UART,CH=1,BAUD={self._port1.currentText()}\n"
        if (
            self._connect_button.text() != "DISCONNECT"
            or self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            self._status.setText("● COM Port not connected")
            self._set_status_color("#D00000")
            self._set_status_color("#D00000")
            return
        try:
            self._serial_connection.reset_input_buffer()
            self._log_buffer("TX", command)
            self._serial_connection.write(command.encode("ascii"))
            self._serial_connection.flush()
            self._port1_apply_pending = True
            self._apply_port1_button.setEnabled(False)
            response_buffer = bytearray()
            elapsed = [0]
            def set_port1_failed():
                self._status.setText("● Port 1 Settings Not Applied")
                self._set_status_color("#D00000")
                self._set_status_color("#D00000")
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
                        chunk = self._serial_connection.read(waiting)
                        self._log_buffer("RX", chunk)
                        response_buffer.extend(chunk)
                    # RX may arrive in multiple chunks.
                    if b"OK:UART" in response_buffer:
                        self.add_terminal_message("OK:UART")
                        self._port1_apply_pending = False
                        self._apply_port1_button.setEnabled(True)
                        self._status.setText("● Port 1 Settings Applied")
                        self._set_status_color("#00C928")
                        self._set_status_color("#00C928")
                        return
                    if b"\n" in response_buffer:
                        self._port1_apply_pending = False
                        self._apply_port1_button.setEnabled(True)
                        set_port1_failed()
                        return
                    elapsed[0] += 20
                    # Wait for RX for a maximum of 2 seconds only.
                    # If RX arrives earlier, it is processed immediately.
                    if elapsed[0] >= 2000:
                        self._port1_apply_pending = False
                        self._apply_port1_button.setEnabled(True)
                        set_port1_failed()
                        return
                    QTimer.singleShot(20, check_port1_response)
                except Exception:
                    self._port1_apply_pending = False
                    self._apply_port1_button.setEnabled(True)
                    set_port1_failed()
            QTimer.singleShot(20, check_port1_response)
        except Exception:
            self._port1_apply_pending = False
            self._apply_port1_button.setEnabled(True)
            set_port1_failed()

    def handle_apply_port2(self):
        if self._port2_apply_pending:
            return
        command = f"UART,CH=2,BAUD={self._port2.currentText()}\n"
        if (
            self._connect_button.text() != "DISCONNECT"
            or self._serial_connection is None
            or not self._serial_connection.is_open
        ):
            self._status.setText("● COM Port not connected")
            self._set_status_color("#D00000")
            self._set_status_color("#D00000")
            return
        try:
            self._serial_connection.reset_input_buffer()
            self._log_buffer("TX", command)
            self._serial_connection.write(command.encode("ascii"))
            self._serial_connection.flush()
            self._port2_apply_pending = True
            self._apply_port2_button.setEnabled(False)
            response_buffer = bytearray()
            elapsed = [0]
            def set_port2_failed():
                self._status.setText("● Port 2 Settings Not Applied")
                self._set_status_color("#D00000")
                self._set_status_color("#D00000")
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
                        chunk = self._serial_connection.read(waiting)
                        self._log_buffer("RX", chunk)
                        response_buffer.extend(chunk)
                    # RX may arrive in multiple chunks.
                    if b"OK:UART" in response_buffer:
                        self.add_terminal_message("OK:UART")
                        self._port2_apply_pending = False
                        self._apply_port2_button.setEnabled(True)
                        self._status.setText("● Port 2 Settings Applied")
                        self._set_status_color("#00C928")
                        self._set_status_color("#00C928")
                        return
                    if b"\n" in response_buffer:
                        self._port2_apply_pending = False
                        self._apply_port2_button.setEnabled(True)
                        set_port2_failed()
                        return
                    elapsed[0] += 20
                    # Wait for RX for a maximum of 2 seconds only.
                    # If RX arrives earlier, it is processed immediately.
                    if elapsed[0] >= 2000:
                        self._port2_apply_pending = False
                        self._apply_port2_button.setEnabled(True)
                        set_port2_failed()
                        return
                    QTimer.singleShot(20, check_port2_response)
                except Exception:
                    self._port2_apply_pending = False
                    self._apply_port2_button.setEnabled(True)
                    set_port2_failed()
            QTimer.singleShot(20, check_port2_response)
        except Exception:
            self._port2_apply_pending = False
            self._apply_port2_button.setEnabled(True)
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
            self._set_status_color("#D00000")
            return
        # Do not send another GETCFG while one is already waiting.
        # This prevents overlapping GETCFG requests after CONNECT/APPLY.
        if self._refresh_pending:
            return
        self._refresh_buffer.clear()
        try:
            self._serial_connection.reset_input_buffer()
            self._refresh_buffer.clear()
            self._log_buffer("TX", b"GETCFG\n")
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
            self._set_status_color("#D00000")
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
            self._status.setText("● COM Port Not Connected")
            self._set_status_color("#D00000")
            return
        try:
            waiting = self._serial_connection.in_waiting
            if waiting > 0:
                chunk = self._serial_connection.read(waiting)
                self._log_buffer("RX", chunk)
                self._refresh_buffer.extend(chunk)
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
                    if parts and parts[0].strip().startswith("ETH,"):
                        parts[0] = parts[0].strip()[4:]
                    # TCP/IP GETCFG response:
                    # IP=...,MASK=...,PORT=...,MAC=...,MACMODE=...
                    if (
                        len(parts) >= 3
                        and parts[0].strip().startswith("IP=")
                        and parts[1].strip().startswith("MASK=")
                        and parts[2].strip().startswith("PORT=")
                    ):
                        ip_text = parts[0].strip()[3:].strip()
                        mask_text = parts[1].strip()[5:].strip()
                        port_text = parts[2].strip()[5:].strip()
                        mac_text = ""
                        mac_mode_text = ""
                        channel_text = ""
                        for part in parts[3:]:
                            part = part.strip()
                            if part.startswith("MAC="):
                                mac_text = part[4:].strip()
                            elif part.startswith("MACMODE="):
                                mac_mode_text = part[8:].strip().upper()
                            elif part.startswith("CH="):
                                channel_text = part[3:].strip()
                        try:
                            parsed_ip = ip_address(ip_text)
                            ip_network(f"0.0.0.0/{mask_text}", strict=False)
                            parsed_port = int(port_text)
                        except ValueError:
                            parsed_ip = None
                            parsed_port = None
                        mac_valid = not mac_text or self._is_valid_mac(mac_text)
                        mode_valid = not mac_mode_text or mac_mode_text in (
                            "KEEP_CURRENT", "KEEP CURRENT", "MANUAL", "RANDOM"
                        )
                        if (
                            parsed_ip is not None
                            and parsed_ip.version == 4
                            and parsed_port is not None
                            and 1 <= parsed_port <= 65535
                            and mac_valid
                            and mode_valid
                        ):
                            self._ip_address.setText(ip_text)
                            self._subnet.setText(mask_text)
                            self._tcp_port.setText(port_text)
                            if mac_text:
                                self._current_mac.setText(mac_text.upper())
                                self._manual_mac.setText(mac_text.upper())
                            if channel_text:
                                # CH=1 -> IEC 60870-5-104, CH=2 -> Modbus TCP/IP
                                self._set_active_protocol(
                                    self.PROTOCOL_BY_CHANNEL.get(channel_text)
                                )
                            if mac_mode_text:
                                self._current_mac_mode.setText(mac_mode_text)
                                if mac_mode_text == "RANDOM":
                                    self._mac_mode.setCurrentText("Random")
                                elif mac_mode_text == "MANUAL":
                                    self._mac_mode.setCurrentText("Manual")
                                else:
                                    self._mac_mode.setCurrentText("Keep current")
                            self._refresh_pending = False
                            self._refresh_timer.stop()
                            self._refresh_buffer.clear()
                            self._status.setText("● Configuration Refreshed")
                            self._set_status_color("#00C928")
                            self._status.setStyleSheet(
                                "color: #00C928; font-weight: bold; font-size: 16px;"
                            )
                            return
                    # UART GETCFG response from the device:
                    # UART,CH=1,BAUD=9600
                    # UART,CH=2,BAUD=19200
                    if len(parts) == 3 and parts[0] == "UART":
                        channel_part = parts[1]
                        baud_part = parts[2]
                        if (
                            channel_part.startswith("CH=")
                            and baud_part.startswith("BAUD=")
                        ):
                            channel_text = channel_part[3:].strip()
                            uart_baud_text = baud_part[5:].strip()
                            try:
                                channel = int(channel_text)
                                uart_baud = int(uart_baud_text)
                            except ValueError:
                                channel = None
                                uart_baud = None
                            if (
                                channel in (1, 2)
                                and uart_baud is not None
                                and (
                                    (channel == 1 and self._port1.findText(uart_baud_text) >= 0)
                                    or
                                    (channel == 2 and self._port2.findText(uart_baud_text) >= 0)
                                )
                            ):
                                if channel == 1:
                                    self._port1.setCurrentText(uart_baud_text)
                                else:
                                    self._port2.setCurrentText(uart_baud_text)
                                self._refresh_pending = False
                                self._refresh_timer.stop()
                                self._refresh_buffer.clear()
                                self._status.setText(
                                    "● Configuration Refreshed"
                                )
                                self._set_status_color("#00C928")
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
                                self._set_status_color("#00C928")
                                self._status.setStyleSheet(
                                    "color: #00C928; font-weight: bold; "
                                    "font-size: 16px;"
                                )
                                return
                    self._refresh_pending = False
                    self._refresh_timer.stop()
                    self._refresh_buffer.clear()
                    self._status.setText("● Refresh Error")
                    self._set_status_color("#D00000")
                    self._set_status_color("#D00000")
                    return
            self._refresh_elapsed += 20
            if self._refresh_elapsed >= 3000:
                # RX not received within 2 seconds: completely exit this
                # Refresh request so the next command can run independently.
                self._refresh_pending = False
                self._refresh_timer.stop()
                self._refresh_buffer.clear()
                self._status.setText("● Refresh Error")
                self._set_status_color("#D00000")
                self._set_status_color("#D00000")
        except Exception:
            self._refresh_pending = False
            self._refresh_timer.stop()
            self._refresh_buffer.clear()
            self._status.setText("● Refresh Error")
            self._set_status_color("#D00000")
            self._set_status_color("#D00000")

    def _check_connection_status(self):
        if (
            self._serial_connection is None
            or self._connect_button.text() != "DISCONNECT"
        ):
            return
        try:
            if not self._serial_connection.is_open:
                self._handle_unexpected_disconnect()
                return
            connected_port = self._serial_connection.port
            available_ports = {
                port.device for port in list_ports.comports()
            }
            if connected_port not in available_ports:
                self._handle_unexpected_disconnect()
        except Exception:
            self._handle_unexpected_disconnect()

    def _handle_unexpected_disconnect(self):
        self._stop_protocol_apply()
        self._set_active_protocol(None)
        self._tcp_apply_pending = False
        self._tcp_apply_timer.stop()
        self._tcp_apply_buffer.clear()
        self._rtu_apply_pending = False
        self._apply_baud_timer.stop()
        self._apply_target_baud_rate = None
        self._apply_rtu_button.setEnabled(True)
        self._port1_apply_pending = False
        self._apply_port1_button.setEnabled(True)
        self._port2_apply_pending = False
        self._apply_port2_button.setEnabled(True)
        self._refresh_pending = False
        self._refresh_timer.stop()
        self._refresh_buffer.clear()
        try:
            if self._serial_connection is not None:
                self._serial_connection.close()
        except Exception:
            pass
        finally:
            self._serial_connection = None
        self._connect_button.setText("CONNECT")
        self._status.setText("● COM Port Disconnected")
        self._set_status_color("#D00000")
        self._set_status_color("#D00000")

    def refresh_com_ports(self):
        # The 1 s timer only refreshes while this page is on screen (listing the COM ports takes time on
        # Windows); the CONNECT popup always reads the current list itself.
        if self.sender() is self.com_port_refresh_timer and not self.isVisible():
            return
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