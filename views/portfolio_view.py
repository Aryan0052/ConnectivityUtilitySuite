from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QHBoxLayout,
)


class PortfolioBackground(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.lower()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Light PDF-style page background.
        painter.fillRect(self.rect(), Qt.white)

        width = self.width()
        height = self.height()

        # Very subtle pale decorative curves.
        pen = QPen("#E8F1EB")
        pen.setWidth(2)
        painter.setPen(pen)

        painter.drawArc(
            int(-width * 0.18),
            int(-height * 0.22),
            int(width * 0.48),
            int(height * 0.62),
            15 * 16,
            80 * 16,
        )

        painter.drawArc(
            int(width * 0.70),
            int(-height * 0.10),
            int(width * 0.45),
            int(height * 0.70),
            95 * 16,
            80 * 16,
        )

        painter.drawArc(
            int(-width * 0.12),
            int(height * 0.68),
            int(width * 0.55),
            int(height * 0.42),
            170 * 16,
            65 * 16,
        )

        # Faint secondary curves.
        pen = QPen("#F0F6F1")
        pen.setWidth(1)
        painter.setPen(pen)

        painter.drawArc(
            int(-width * 0.10),
            int(-height * 0.08),
            int(width * 0.38),
            int(height * 0.48),
            10 * 16,
            95 * 16,
        )

        painter.drawArc(
            int(width * 0.76),
            int(height * 0.42),
            int(width * 0.30),
            int(height * 0.45),
            90 * 16,
            95 * 16,
        )

        painter.end()


class PortfolioView(QWidget):

    digital_input_clicked = Signal()
    digital_output_clicked = Signal()
    analog_input_clicked = Signal()
    analog_output_clicked = Signal()
    modbus_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("portfolioView")

        self.setStyleSheet("""
            QWidget#portfolioView {
                background: white;
            }

            QFrame#portfolioCard {
                background: qlineargradient(
                    x1: 0,
                    y1: 0,
                    x2: 1,
                    y2: 1,
                    stop: 0 #18B2BE,
                    stop: 1 #20598F
                );

                border: 2px solid #19C63A;
                border-radius: 22px;
            }

            QLabel#portfolioTitle {
                color: white;
                background: transparent;
                font-family: "Times New Roman";
                font-size: 27px;
                font-weight: normal;
            }

            QPushButton#moduleButton {
                color: white;
                background: rgba(20, 102, 128, 190);
                border: 1px solid #159E78;
                border-radius: 9px;

                font-family: "Times New Roman";
                font-size: 18px;
                font-weight: normal;

                text-align: left;
                padding-left: 15px;
            }

            QPushButton#moduleButton:hover {
                background: rgba(16, 92, 117, 220);
            }

            QPushButton#moduleButton:pressed {
                background: rgba(12, 78, 100, 240);
            }

            QLabel#portfolioFooter {
                color: #3C93A0;
                background: transparent;
                font-family: "Times New Roman";
                font-size: 10px;
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Page-2 style background behind the existing blue card.
        self.background = PortfolioBackground(self)
        self.background.setGeometry(self.rect())
        self.background.lower()

        root.addStretch()

        card = QFrame()
        card.setObjectName("portfolioCard")
        card.setFixedSize(550, 480)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(
            135,
            65,
            135,
            55
        )
        card_layout.setSpacing(0)

        title = QLabel("Remote I/O Modules")
        title.setObjectName("portfolioTitle")
        title.setAlignment(Qt.AlignCenter)

        card_layout.addWidget(title)

        # Green divider exactly below title.
        divider = QFrame()
        divider.setFixedHeight(2)

        divider.setStyleSheet("""
            QFrame {
                background: #18C63B;
                border: none;
            }
        """)

        card_layout.addSpacing(7)
        card_layout.addWidget(divider)
        card_layout.addSpacing(25)

        self.digital_input_button = self.create_button(
            "•  Digital Input"
        )

        self.digital_output_button = self.create_button(
            "•  Digital Output"
        )

        self.analog_input_button = self.create_button(
            "•  Analog Input"
        )

        self.analog_output_button = self.create_button(
            "•  Analog Output"
        )

        self.modbus_button = self.create_button(
            "•  Modbus to TCP Gateway"
        )

        card_layout.addWidget(self.digital_input_button)
        card_layout.addSpacing(18)

        card_layout.addWidget(self.digital_output_button)
        card_layout.addSpacing(18)

        card_layout.addWidget(self.analog_input_button)
        card_layout.addSpacing(18)

        card_layout.addWidget(self.analog_output_button)
        card_layout.addSpacing(18)

        card_layout.addWidget(self.modbus_button)

        root.addWidget(
            card,
            alignment=Qt.AlignCenter
        )

        # Page-2 footer outside the blue card.
        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(0, 0, 18, 8)
        footer_row.addStretch()

        footer_text = QVBoxLayout()
        footer_text.setSpacing(0)

        product_portfolio = QLabel("Product Portfolio")
        product_portfolio.setObjectName("portfolioFooter")
        product_portfolio.setAlignment(Qt.AlignRight)

        contact_us = QLabel("Contact Us")
        contact_us.setObjectName("portfolioFooter")
        contact_us.setAlignment(Qt.AlignRight)

        footer_text.addWidget(product_portfolio)
        footer_text.addWidget(contact_us)

        footer_row.addLayout(footer_text)
        root.addLayout(footer_row)

        root.addStretch()

        # Navigation.
        self.digital_input_button.clicked.connect(
            self.digital_input_clicked.emit
        )

        self.digital_output_button.clicked.connect(
            self.digital_output_clicked.emit
        )

        self.analog_input_button.clicked.connect(
            self.analog_input_clicked.emit
        )

        self.analog_output_button.clicked.connect(
            self.analog_output_clicked.emit
        )

        self.modbus_button.clicked.connect(
            self.modbus_clicked.emit
        )

    def resizeEvent(self, event):
        # Keep the decorative background behind the full page.
        self.background.setGeometry(self.rect())
        self.background.lower()
        super().resizeEvent(event)

    def create_button(self, text):
        button = QPushButton(text)

        button.setObjectName("moduleButton")

        button.setFixedHeight(35)

        button.setCursor(
            Qt.PointingHandCursor
        )

        return button