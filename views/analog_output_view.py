import os

from PySide6.QtCore import Signal, Qt, QPoint, QTimer
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


class AnalogOutputView(QWidget):

    back_clicked = Signal()

    def __init__(self):
        super().__init__()

        self._serial_connection = None
        self._connected_port = None
        self._connection_monitor_timer = QTimer(self)
        self._connection_monitor_timer.setInterval(500)
        self._connection_monitor_timer.timeout.connect(self._check_connection_status)
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

        self.terminal_messages = ["Device Terminal Ready"]


        self.build_ui()

    def build_ui(self):
        # Look: shared with the other pages and the Multi Device page (ui_theme.py). Only widgets and
        # styles are built here - every attribute the communication code uses keeps its name.
        ui.install(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = ui.Header("Analog Output", root=self)
        back = header.back_button
        status = header.status
        self._status_dot = header.status_dot
        root.addWidget(header)

        main = QWidget()
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)
        main.setMinimumHeight(620)

        # ------------------------------------------------------------ LEFT: RTU settings + terminal
        panel = ui.rtu_panel("Analog Output")
        left_panel = panel.card
        connect, slave_id, baud = panel.connect, panel.id_edit, panel.baud
        apply_button, refresh = panel.apply, panel.refresh
        self.terminal_message = panel.terminal
        ui.sized(self.terminal_message, "setMinimumHeight", 180)

        # ------------------------------------------------------------ RIGHT: channels
        right_panel = ui.card()
        right_layout = QVBoxLayout(right_panel)
        self.right_layout = right_layout
        right_layout.setContentsMargins(22, 20, 22, 20)
        right_layout.setSpacing(0)
        right_layout.setAlignment(Qt.AlignTop)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_col.addWidget(ui.label("Analog Output", "pgTitle"))
        title_col.addWidget(ui.label("4 channels \u00b7 pick a channel to set output type, zero and span", "pgSub"))
        right_layout.addLayout(title_col)
        right_layout.addSpacing(16)

        right_layout.addWidget(ui.section("Analog Output Channel"))
        right_layout.addSpacing(10)

        self.channel_boxes = []
        self._channel_row_layouts = []

        for channel in range(1, 5):
            channel_button = QPushButton(f"Analog Output Channel - {channel}")
            channel_button.setObjectName("pgChannel")
            channel_button.setProperty("selected", False)
            channel_button.setCursor(Qt.PointingHandCursor)
            channel_button.setFocusPolicy(Qt.NoFocus)
            ui.sized(channel_button, "setMinimumWidth", 380)
            ui.sized(channel_button, "setMaximumWidth", 560)
            ui.sized(channel_button, "setFixedHeight", 42)
            channel_button.clicked.connect(lambda checked=False, ch=channel: self.channel_selected(ch))

            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(channel_button, 1)
            row.addStretch(1)
            right_layout.addLayout(row)
            right_layout.addSpacing(8)
            self._channel_row_layouts.append(row)
            self.channel_boxes.append(channel_button)

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
            b.setEnabled(True)
            return b

        output_row = QHBoxLayout()
        output_row.setSpacing(10)
        output_label = ui.label("O/P Type", "pgField")
        ui.sized(output_label, "setMinimumWidth", 80)
        self._output_type = QComboBox()
        self._output_type.addItems([
            "0-50mV", "0-100mV", "0-250mV", "0-5V", "0-10V",
            "-250mV to +250mV", "-10V to +10V", "4-20mA", "0-20mA"
        ])
        ui.sized(self._output_type, "setMinimumWidth", 190)
        output_ok = mini_apply()
        output_row.addWidget(output_label)
        output_row.addWidget(self._output_type, 1)
        output_row.addWidget(output_ok)
        config_layout.addLayout(output_row)

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
        config_layout.addLayout(max_row)

        channel_refresh = ui.button("\u27f3  Refresh", "ghost")
        channel_refresh.setVisible(True)
        channel_refresh_row = QHBoxLayout()
        channel_refresh_row.setContentsMargins(0, 0, 0, 0)
        channel_refresh_row.addStretch()
        channel_refresh_row.addWidget(channel_refresh)
        config_layout.addLayout(channel_refresh_row)
        self._channel_refresh_button = channel_refresh

        config_row = QHBoxLayout()
        config_row.setContentsMargins(0, 4, 0, 0)
        config_row.addWidget(self._channel_config_frame, 1)
        config_row.addStretch(1)
        self._channel_config_row = config_row
        right_layout.addStretch()

        test_mode_button = ui.button("TEST MODE", "secondary", 36)
        ui.sized(test_mode_button, "setMinimumWidth", 130)
        self._test_mode_button = test_mode_button
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
        self._connect_button = connect
        self._slave_id = slave_id
        self._baud = baud
        self.connect_button = connect
        self.slave_id = slave_id
        self.baud_rate = baud
        self.apply_button = apply_button
        self.refresh_button = refresh
        self.back_button = back

        self.back_button.clicked.connect(self.back_clicked.emit)
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

                self._serial_connection = serial.Serial(
                    selected_port,
                    int(self._baud.currentText()),
                    timeout=1
                )
                self._connected_baud_rate = int(self._baud.currentText())
                self._connected_port = selected_port
                self._connection_monitor_timer.start()

                self._status.setText("Connected")
                self._status.setStyleSheet(
                    "color: #00C928; font-weight: bold; font-size: 16px;"
                )
                self._connect_button.setText("DISCONNECT")
                dialog.accept()

            except Exception:
                self._serial_connection = None
                self._connected_port = None
                self._connection_monitor_timer.stop()
                self._status.setText("Connection Error")
                self._connect_button.setText("CONNECT")
                dialog.reject()

        connect_button.clicked.connect(connect_selected)
        cancel_button.clicked.connect(dialog.reject)
        dialog.exec()

    def handle_connect(self):
        if self._connect_button.text() == "DISCONNECT":
            self._connection_monitor_timer.stop()
            self._connected_port = None
            self._apply_pending = False
            self._apply_timer.stop()
            self._apply_baud_timer.stop()
            self._apply_target_baud_rate = None
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

    def _check_connection_status(self):
        if (
            self._connect_button.text() != "DISCONNECT"
            or self._serial_connection is None
            or self._connected_port is None
        ):
            return

        try:
            available_ports = {port.device for port in list_ports.comports()}
            if self._connected_port not in available_ports:
                self.handle_connect()
        except Exception:
            pass

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
        target_baud_rate = int(baud_rate)
        command = f"SID={slave_id},MBD_BAUD={baud_rate}\n"

        if self._apply_pending:
            return

        try:
            self._serial_connection.reset_input_buffer()
            self._apply_buffer.clear()
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
            self._status.setStyleSheet(
                "color: #D00000; font-weight: bold; font-size: 16px;"
            )

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
                    self._status.setStyleSheet(
                        "color: #00C928; font-weight: bold; font-size: 16px;"
                    )
                    return

                self._apply_pending = False
                self._apply_timer.stop()
                self._apply_baud_timer.stop()
                self._apply_target_baud_rate = None
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
                self._apply_baud_timer.stop()
                self._apply_target_baud_rate = None
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

        self._connect_button.setText("CONNECT")
        self._status.setText("Not Connected")
        self._status.setStyleSheet(
            "color: #10C51F; font-weight: bold; font-size: 16px;"
        )

        self.terminal_messages = ["Device Terminal Ready"]
        self.terminal_message.setPlainText("Device Terminal Ready")

    def channel_selected(self, channel):
        # Clicking the same channel again hides its configuration.
        if (
            getattr(self, "selected_channel", None) == channel
            and self._channel_config_frame.isVisible()
        ):
            self._channel_config_frame.setVisible(False)
            self.selected_channel = None

            config_index = self.right_layout.indexOf(self._channel_config_row)
            if config_index >= 0:
                self.right_layout.takeAt(config_index)

            for button in self.channel_boxes:
                button.setProperty("selected", False)
                button.style().unpolish(button)
                button.style().polish(button)
            return

        # Keep all channel buttons visible and show the configuration
        # directly below the channel that was clicked.
        config_index = self.right_layout.indexOf(self._channel_config_row)
        if config_index >= 0:
            self.right_layout.takeAt(config_index)

        self.selected_channel = channel
        self._channel_config_frame.setVisible(True)
        self._channel_refresh_button.setVisible(True)

        for index, button in enumerate(self.channel_boxes, start=1):
            button.setProperty("selected", index == channel)
            button.style().unpolish(button)
            button.style().polish(button)
            button.setVisible(True)

        channel_row_index = self.right_layout.indexOf(
            self._channel_row_layouts[channel - 1]
        )
        if channel_row_index >= 0:
            self.right_layout.insertLayout(
                channel_row_index + 1,
                self._channel_config_row,
            )