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

        self.build_ui()

    def build_ui(self):

        self.setStyleSheet("""
            QWidget#digitalOutputView {
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

            /* Keep the baud-rate dropdown white instead of the dark
               native popup shown by Fusion on some Windows setups. */
            QComboBox QAbstractItemView {
                background: #F1F5F2;
                color: #333333;
                border: 1px solid #C8CFCC;
                selection-background-color: #DDEBE6;
                selection-color: #222222;
                font-family: Cambria;
                font-size: 12px;
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
            0, 0, 0, 0
        )

        root_layout.setSpacing(0)

        # HEADER
        header = QFrame()

        header.setObjectName(
            "header"
        )

        header.setFixedHeight(88)

        header_layout = QHBoxLayout(
            header
        )

        header_layout.setContentsMargins(
            20,
            5,
            20,
            5
        )

        # LOGO
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

        header_layout.addWidget(
            logo
        )

        # HEADER TEXT
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

        # BACK BUTTON
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

        left_layout = QVBoxLayout(
            left
        )

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

        left_layout.addSpacing(25)

        # STATUS
        status_layout = QHBoxLayout()

        status_dot = QLabel("●")

        status_dot.setStyleSheet("""
            QLabel {
                color: #13D324;
                background: transparent;
                font-family: Cambria;
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
            "Digital Output"
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
                font-size: 10px;
            }
        """)

        left_layout.addWidget(
            valid
        )

        left_layout.addSpacing(24)

        # BAUD RATE
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
                font-size: 12px;
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

        # Blank exactly as requested.
        right_layout.setSpacing(0)

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
        self._connect_button = self.connect_button
        self._slave_id = self.slave_id
        self._baud = self.baud_rate

        # BACK NAVIGATION
        self.back_button.clicked.connect(
            self.handle_back
        )
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

            # Wait for the complete response because serial data can arrive
            # in multiple chunks.
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
        self.back_clicked.emit()
