import os

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QPainter, QPen, QPixmap, QDesktopServices
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

        self.pixmap = QPixmap(
            os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "assets",
                "portfolio_BG.png"
            )
        )

        self.lower()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        if not self.pixmap.isNull():
            scaled = self.pixmap.scaled(
                self.size(),
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation
            )

            painter.drawPixmap(0, 0, scaled)

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
                background: transparent;
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
                font-family: Cambria;
                font-size: 29px;
                font-weight: normal;
            }

            QPushButton#moduleButton {
                color: white;
                background: rgba(20, 102, 128, 190);
                border: 1px solid #159E78;
                border-radius: 9px;

                font-family: Cambria;
                font-size: 23px;
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
                font-family: Cambria;
                font-size: 23px;
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Portfolio background image.
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

        # Make footer labels clickable without changing their appearance.
        product_portfolio.setCursor(Qt.PointingHandCursor)
        contact_us.setCursor(Qt.PointingHandCursor)

        product_portfolio.mousePressEvent = lambda event: QDesktopServices.openUrl(
            QUrl("https://nelumbo.in/product-portfolio")
        )

        contact_us.mousePressEvent = lambda event: QDesktopServices.openUrl(
            QUrl("https://nelumbo.in/contact-us")
        )

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
        # Keep the background image behind the full page.
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