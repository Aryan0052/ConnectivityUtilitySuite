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
    QTextEdit,
    QVBoxLayout,
    QGridLayout,
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


class OutputToggle(QPushButton):
    def __init__(self, is_on=False, parent=None):
        super().__init__(parent)
        self._is_on = is_on
        self.setFixedSize(84, 34)
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
        if self._is_on:
            self.setText("ON")
            self.setStyleSheet("""
                QPushButton {
                    background: #8AB3C9;
                    color: white;
                    border: none;
                    border-radius: 17px;
                    padding-left: 7px;
                    padding-right: 28px;
                    font-family: Cambria;
                    font-size: 16px;
                    font-weight: bold;
                    text-align: left;
                }
            """)
        else:
            self.setText("OFF")
            self.setStyleSheet("""
                QPushButton {
                    background: #8AB3C9;
                    color: white;
                    border: none;
                    border-radius: 17px;
                    padding-left: 28px;
                    padding-right: 7px;
                    font-family: Cambria;
                    font-size: 16px;
                    font-weight: bold;
                    text-align: right;
                }
            """)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(0, 0, self.width(), self.height())

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush("#8AB3C9"))
        painter.drawRoundedRect(rect, 17, 17)

        knob_d = 28
        knob_y = (self.height() - knob_d) / 2
        knob_x = self.width() - knob_d - 3 if self._is_on else 3

        painter.setBrush(QBrush("#20D10F" if self._is_on else "#A0A0A0"))
        painter.drawEllipse(QRectF(knob_x, knob_y, knob_d, knob_d))

        painter.setPen(QPen(Qt.white))
        font = QFont("Cambria", 16)
        font.setBold(True)
        painter.setFont(font)

        if self._is_on:
            text_rect = QRectF(8, 0, self.width() - knob_d - 13, self.height())
        else:
            text_rect = QRectF(knob_d + 8, 0, self.width() - knob_d - 13, self.height())

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

            QPushButton#outputRefresh {
                background: white;
                color: #16839F;
                border: 2px solid #16839F;
                border-radius: 19px;
                font-family: Cambria;
                font-size: 14px;
                font-weight: bold;
            }

            QPushButton#runOutput {
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
                border-radius: 19px;
                font-family: Cambria;
                font-size: 14px;
                font-weight: bold;
            }

            QPushButton#outputRefresh:hover {
                background: #EAF6F7;
            }

            QPushButton#runOutput:hover {
                background: #168FA8;
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

        self._status_dot = status_dot

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

        # DIGITAL OUTPUT CHANNEL UI
        title = QLabel("Digital Output")
        title.setAlignment(Qt.AlignCenter)
        title.setFixedSize(240, 28)
        title.setStyleSheet("""
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
                font-size: 18px;
                font-weight: bold;
            }
        """)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.addStretch()
        title_row.addWidget(title)
        title_row.addStretch()
        right_layout.addLayout(title_row)
        right_layout.addSpacing(10)

        # DIGITAL OUTPUT COMMUNICATION SETTINGS
        # Separate from the original RTU Settings controls on the left.
        do_settings = QFrame()
        do_settings.setStyleSheet("""
            QFrame {
                background: #F7FAF8;
                border: 1px solid #BFC4C1;
                border-radius: 8px;
            }
        """)

        do_settings_layout = QHBoxLayout(do_settings)
        do_settings_layout.setContentsMargins(12, 8, 12, 8)
        do_settings_layout.setSpacing(10)

        do_connect = QPushButton("CONNECT")
        do_connect.setObjectName("connect")
        do_connect.setFixedSize(125, 31)
        do_connect.setCursor(Qt.PointingHandCursor)

        do_slave_label = QLabel("Device ID")
        do_slave_label.setObjectName("label")

        self.do_slave_id = QLineEdit()
        self.do_slave_id.setText("1")
        self.do_slave_id.setFixedWidth(75)

        do_baud_label = QLabel("Baud Rate")
        do_baud_label.setObjectName("label")

        self.do_baud_rate = QComboBox()
        self.do_baud_rate.addItems([
            "9600",
            "19200",
            "38400",
            "57600",
            "115200"
        ])
        self.do_baud_rate.setCurrentText("9600")
        self.do_baud_rate.setFixedWidth(105)

        self.do_baud_rate.view().setStyleSheet("""
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

        # Requested order: Device ID -> Baud Rate -> CONNECT
        do_settings_layout.addWidget(do_slave_label)
        do_settings_layout.addWidget(self.do_slave_id)
        do_settings_layout.addSpacing(10)
        do_settings_layout.addWidget(do_baud_label)
        do_settings_layout.addWidget(self.do_baud_rate)
        do_settings_layout.addSpacing(12)
        do_settings_layout.addWidget(do_connect)
        do_settings_layout.addStretch()

        right_layout.addWidget(do_settings)
        right_layout.addSpacing(8)

        # Two independent COM connections:
        # left CONNECT -> RTU Settings
        # right CONNECT -> Digital Output TX/RX
        self._do_connect_button = do_connect
        self._rtu_connect_button = self.connect_button

        do_connect.clicked.connect(self.handle_connect)
        self.connect_button.clicked.connect(self.handle_rtu_connect)

        self._output_states = {channel: False for channel in range(1, 17)}
        self._output_status_buttons = {}

        channel_grid = QGridLayout()
        channel_grid.setContentsMargins(20, 0, 20, 0)
        channel_grid.setHorizontalSpacing(34)
        channel_grid.setVerticalSpacing(23)

        def create_output_status(channel):
            status_button = OutputToggle(False)
            status_button.clicked.disconnect(status_button._toggle)

            status_button.clicked.connect(
                lambda checked=False, ch=channel: self._toggle_output(ch)
            )
            self._output_status_buttons[channel] = status_button
            return status_button

        for index in range(8):
            left_status = create_output_status(index + 1)
            left_label = QLabel(f"DO-{index + 1}")
            left_label.setAlignment(Qt.AlignCenter)
            left_label.setFixedSize(82, 29)
            left_label.setStyleSheet("""
                QLabel {
                    background: #F1F5F2;
                    color: #222222;
                    border: 1px solid #BFC4C1;
                    border-radius: 8px;
                    font-family: Cambria;
                    font-size: 14px;
                }
            """)

            right_status = create_output_status(index + 9)
            right_label = QLabel(f"DO-{index + 9}")
            right_label.setAlignment(Qt.AlignCenter)
            right_label.setFixedSize(82, 29)
            right_label.setStyleSheet("""
                QLabel {
                    background: #F1F5F2;
                    color: #222222;
                    border: 1px solid #BFC4C1;
                    border-radius: 8px;
                    font-family: Cambria;
                    font-size: 14px;
                }
            """)

            channel_grid.addWidget(left_status, index, 0, Qt.AlignLeft)
            channel_grid.addWidget(left_label, index, 1, Qt.AlignLeft)
            channel_grid.addWidget(right_status, index, 2, Qt.AlignLeft)
            channel_grid.addWidget(right_label, index, 3, Qt.AlignLeft)

        right_layout.addLayout(channel_grid)
        right_layout.addStretch()

        # ALL OUTPUT CONTROLS
        all_control_layout = QHBoxLayout()
        all_control_layout.setContentsMargins(20, 0, 20, 0)
        all_control_layout.addStretch()

        self.run_output_button = QPushButton("RUN")
        self.run_output_button.setObjectName("runOutput")
        self.run_output_button.setFixedSize(125, 38)
        self.run_output_button.setCursor(Qt.PointingHandCursor)

        self.turn_all_button = QPushButton("TURN ON ALL")
        self.turn_all_button.setFixedSize(145, 38)
        self.turn_all_button.setCursor(Qt.PointingHandCursor)
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

        all_control_layout.addWidget(self.run_output_button)
        all_control_layout.addSpacing(12)
        all_control_layout.addWidget(self.turn_all_button)
        all_control_layout.addStretch()

        right_layout.addLayout(all_control_layout)

        self.run_output_button.clicked.connect(self.handle_run_output)
        self.turn_all_button.clicked.connect(self._toggle_all_outputs)

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
        self._connect_button = self._do_connect_button

        # RTU Settings (left side)
        self._rtu_slave_id = self.slave_id
        self._rtu_baud = self.baud_rate

        # Digital Output (right side)
        self._slave_id = self.do_slave_id
        self._baud = self.do_baud_rate

        # BACK NAVIGATION
        self.back_button.clicked.connect(
            self.handle_back
        )
        self.apply_button.clicked.connect(self.handle_apply_rtu)
        self.refresh_button.clicked.connect(self.handle_refresh)

    def _set_output_status_style(self, button, is_on):
        button.set_on(is_on)

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
        for text, color in (("● All DO Turned ON", "#00A000"), ("● All DO Turned OFF", "#D00000")):
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
        dialog.setFixedSize(360, 190)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        title = QLabel("Select RTU Settings COM Port")
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
            if (
                self._connected_baud_rate is not None
                and int(baud_rate) != self._connected_baud_rate
            ):
                self._apply_baud_timer.start(150)
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
