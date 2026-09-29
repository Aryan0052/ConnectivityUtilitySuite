import os

from PySide6.QtCore import Qt, Signal, QUrl, QTimer, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup, Property
from PySide6.QtGui import QPainter, QPixmap, QDesktopServices, QColor, QPen, QBrush, QFont, QPainterPath
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QHBoxLayout,
    QMessageBox,
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
                self.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation
            )
            painter.drawPixmap(0, 0, scaled)
        painter.end()


class ModuleButton(QPushButton):
    """Custom painted module card. Click behaviour remains a normal QPushButton."""

    def __init__(self, code, title, description, accent, icon_type, parent=None):
        super().__init__(parent)
        self.code = code
        self.title = title
        self.description = description
        self.accent = QColor(accent)
        self.icon_type = icon_type
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(185)
        self.setFlat(True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = self.rect().adjusted(1, 1, -1, -1)
        radius = 16

        # Card
        painter.setPen(QPen(QColor("#D7E6EA"), 1))
        painter.setBrush(QBrush(QColor(255, 255, 255, 244)))
        painter.drawRoundedRect(rect, radius, radius)

        # Accent bottom bar
        bottom = rect.adjusted(0, rect.height() - 5, 0, 0)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(self.accent))
        painter.drawRoundedRect(bottom, 3, 3)

        # Icon square
        icon_rect = rect.adjusted(28, 28, 0, 0)
        icon_rect.setWidth(62)
        icon_rect.setHeight(62)
        painter.setBrush(QBrush(self.accent))
        painter.drawRoundedRect(icon_rect, 11, 11)

        self._draw_icon(painter, icon_rect)

        # Text
        left = icon_rect.right() + 18
        title_y = rect.top() + 30
        painter.setPen(QColor("#092F49"))
        painter.setFont(QFont("Segoe UI", 15, QFont.Bold))
        painter.drawText(left, title_y + 4, self.code)

        painter.setFont(QFont("Segoe UI", 12, QFont.DemiBold))
        painter.drawText(left, title_y + 27, self.title)

        painter.setPen(QColor("#607986"))
        painter.setFont(QFont("Segoe UI", 10))
        desc_rect = rect.adjusted(28, 103, -18, -35)
        painter.drawText(
            desc_rect,
            Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
            self.description
        )

        painter.setPen(self.accent)
        painter.setFont(QFont("Segoe UI", 10, QFont.Bold))
        painter.drawText(
            rect.adjusted(28, rect.height() - 38, -18, -10),
            Qt.AlignLeft | Qt.AlignVCenter,
            "OPEN MODULE  →"
        )
        painter.end()

    def _draw_icon(self, painter, rect):
        pen = QPen(Qt.white, 3)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        mid_y = y + h // 2

        if self.icon_type == "digital":
            path = QPainterPath()
            path.moveTo(x + 12, mid_y + 9)
            path.lineTo(x + 12, mid_y - 9)
            path.lineTo(x + 25, mid_y - 9)
            path.lineTo(x + 25, mid_y + 9)
            path.lineTo(x + 38, mid_y + 9)
            path.lineTo(x + 38, mid_y - 9)
            path.lineTo(x + 50, mid_y - 9)
            painter.drawPath(path)
        elif self.icon_type == "analog":
            path = QPainterPath()
            path.moveTo(x + 9, mid_y + 4)
            path.cubicTo(x + 18, mid_y - 18, x + 27, mid_y + 18, x + 36, mid_y - 4)
            path.cubicTo(x + 43, mid_y - 18, x + 48, mid_y + 7, x + 53, mid_y - 4)
            painter.drawPath(path)
        else:
            # Simple network icon for Modbus/TCP.
            painter.drawLine(x + 31, y + 18, x + 31, y + 36)
            painter.drawLine(x + 31, y + 36, x + 17, y + 49)
            painter.drawLine(x + 31, y + 36, x + 45, y + 49)
            for cx, cy in ((31, 15), (14, 50), (48, 50)):
                painter.drawEllipse(cx + x - 6, cy + y - 6, 12, 12)


class ProductCarousel(QWidget):
    """Single-product hero carousel with a smooth slide/tilt transition."""

    def __init__(self, image_paths, parent=None):
        super().__init__(parent)
        self.setFixedSize(1160, 470)

        self._paths = image_paths
        self._pixmaps = [QPixmap(path) for path in image_paths]
        self._index = 0

        self._animating = False
        self._direction = 1
        self._progress = 0.0
        self._animation = None
        self._dots = []

        self._create_navigation()
        self._update_dots()

        self._timer = QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self.next_slide)
        self._timer.start()

    def _create_navigation(self):
        # No arrow buttons: the carousel changes automatically.
        self._left_button = QPushButton(self)
        self._right_button = QPushButton(self)
        self._left_button.hide()
        self._right_button.hide()

        for _ in self._pixmaps:
            dot = QLabel(self)
            dot.setFixedSize(14, 14)
            self._dots.append(dot)

    def _update_dots(self):
        if not self._dots:
            return

        total_width = len(self._dots) * 14 + (len(self._dots) - 1) * 10
        start_x = (self.width() - total_width) // 2

        for i, dot in enumerate(self._dots):
            dot.move(start_x + i * 24, 438)

            if i == self._index:
                dot.setFixedSize(18, 14)
                dot.setStyleSheet(
                    "background: #159FC0; border-radius: 7px; border: none;"
                )
            else:
                dot.setFixedSize(14, 14)
                dot.setStyleSheet(
                    "background: #DCE6E8; border-radius: 7px; border: none;"
                )

    @staticmethod
    def _ease(value):
        if value < 0.5:
            return 4 * value * value * value
        return 1 - pow(-2 * value + 2, 3) / 2

    def _draw_product(self, painter, index, cx, cy, scale, rotation, opacity):
        if index < 0 or index >= len(self._pixmaps):
            return

        pixmap = self._pixmaps[index]
        if pixmap.isNull() or opacity <= 0:
            return

        # Large hero product. Only ONE product is painted at a time.
        scaled = pixmap.scaled(
            780,
            410,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )

        painter.save()
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setOpacity(max(0.0, min(1.0, opacity)))
        painter.translate(cx, cy)
        painter.rotate(rotation)
        painter.scale(scale, scale)
        painter.drawPixmap(
            -scaled.width() // 2,
            -scaled.height() // 2,
            scaled,
        )
        painter.restore()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        if not self._pixmaps:
            painter.end()
            return

        progress = self._ease(self._progress) if self._animating else 0.0

        # Normal state: exactly one large product.
        if not self._animating:
            self._draw_product(
                painter,
                self._index,
                self.width() // 2,
                205,
                1.0,
                0,
                1.0,
            )
            painter.end()
            return

        # During the transition, ONLY ONE product is ever painted.
        # Phase 1: current product exits completely.
        # Phase 2: a short empty gap.
        # Phase 3: next product enters.
        if progress < 0.45:
            local = progress / 0.45
            eased = self._ease(local)

            if self._direction > 0:
                cx = (self.width() // 2) - (eased * 520)
                rotation = -8 * eased
            else:
                cx = (self.width() // 2) + (eased * 520)
                rotation = 8 * eased

            scale = 1.0 - (0.08 * eased)
            opacity = 1.0 - eased

            self._draw_product(
                painter, self._index, cx, 205, scale, rotation, opacity
            )

        elif progress < 0.55:
            # Intentional short gap: no product is shown.
            pass

        else:
            local = (progress - 0.55) / 0.45
            eased = self._ease(local)

            next_index = (self._index + self._direction) % len(self._pixmaps)

            if self._direction > 0:
                cx = (self.width() // 2) + 520 - (eased * 520)
                rotation = 8 - (8 * eased)
            else:
                cx = (self.width() // 2) - 520 + (eased * 520)
                rotation = -8 + (8 * eased)

            scale = 0.92 + (0.08 * eased)
            opacity = eased

            self._draw_product(
                painter, next_index, cx, 205, scale, rotation, opacity
            )

        painter.end()

    def _start_slide(self, direction):
        if self._animating or len(self._pixmaps) < 2:
            return

        self._direction = direction
        self._animating = True
        self._progress = 0.0
        self._timer.stop()

        self._animation = QPropertyAnimation(
            self,
            b"carouselProgress",
            self,
        )
        self._animation.setDuration(1250)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setEasingCurve(QEasingCurve.InOutCubic)
        self._animation.finished.connect(self._finish_slide)
        self._animation.start()

    def next_slide(self):
        self._start_slide(1)

    def previous_slide(self):
        self._start_slide(-1)

    def _finish_slide(self):
        total = len(self._pixmaps)
        self._index = (self._index + self._direction) % total
        self._progress = 0.0
        self._animating = False
        self._animation = None
        self._update_dots()
        self._timer.start()
        self.update()

    def _get_progress(self):
        return self._progress

    def _set_progress(self, value):
        self._progress = float(value)
        self.update()

    carouselProgress = Property(
        float,
        _get_progress,
        _set_progress,
    )


class PortfolioView(QWidget):

    digital_input_clicked = Signal()
    digital_output_clicked = Signal()
    analog_input_clicked = Signal()
    analog_output_clicked = Signal()
    modbus_clicked = Signal()
    logout_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("portfolioView")
        self.setStyleSheet("""
            QWidget#portfolioView { background: #F5FAF6; }
            QFrame#topBar {
                background: rgba(255, 255, 255, 248);
                border-bottom: 1px solid #DCE9E7;
            }
            QLabel#companyName {
                color: #075276;
                font-family: "Segoe UI";
                font-size: 20px;
                font-weight: 700;
            }
            QLabel#suiteName {
                color: #70858E;
                font-family: "Segoe UI";
                font-size: 10px;
                font-weight: 500;
                letter-spacing: 2px;
            }
            QLabel#welcomeLabel {
                color: #6D8993;
                font-family: "Segoe UI";
                font-size: 11px;
                font-weight: 600;
                letter-spacing: 4px;
            }
            QLabel#mainTitle {
                color: #092F49;
                font-family: "Segoe UI";
                font-size: 38px;
                font-weight: 750;
            }
            QLabel#subtitleLabel {
                color: #5F7782;
                font-family: "Segoe UI";
                font-size: 15px;
            }
            QFrame#titleLine {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #18C66A, stop: 0.55 #16A7C7, stop: 1 #1976D2
                );
                border: none;
                border-radius: 2px;
            }
            QLabel#sectionHint {
                color: #718991;
                font-family: "Segoe UI";
                font-size: 10px;
                font-weight: 600;
                letter-spacing: 3px;
            }
            QLabel#tagline {
                color: #6D8993;
                font-family: "Segoe UI";
                font-size: 11px;
                font-weight: 600;
                letter-spacing: 4px;
            }
            QFrame#taglineLine {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #18C66A, stop: 1 #1976D2
                );
                border: none;
            }
            QPushButton#logoutButton {
                color: white;
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #0785AA, stop: 1 #1664A7
                );
                border: none;
                border-radius: 22px;
                font-family: "Segoe UI";
                font-size: 13px;
                font-weight: 700;
            }
            QPushButton#logoutButton:hover { background: #0B7195; }
            QPushButton#logoutButton:pressed { background: #095C7A; }
            QLabel#footerLabel {
                color: #84979E;
                font-family: "Segoe UI";
                font-size: 9px;
                letter-spacing: 2px;
            }
            QPushButton#footerButton {
                color: #176B83;
                background: rgba(255,255,255,235);
                border: 1px solid #C5DFE2;
                border-radius: 9px;
                padding: 7px 13px;
                font-family: "Segoe UI";
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton#footerButton:hover {
                background: #FFFFFF;
                border: 1px solid #5DB7C4;
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.background = PortfolioBackground(self)
        self.background.setGeometry(self.rect())
        self.background.lower()

        # HEADER — same navigation/branding functionality.
        top_bar = QFrame()
        top_bar.setObjectName("topBar")
        top_bar.setFixedHeight(92)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(28, 8, 28, 8)
        top_layout.setSpacing(14)

        logo = QLabel()
        logo.setFixedSize(72, 68)
        logo.setAlignment(Qt.AlignCenter)
        base_dir = os.path.dirname(os.path.dirname(__file__))
        for logo_path in (
            os.path.join(base_dir, "assets", "13.ico"),
            os.path.join(base_dir, "assets", "NelumboLogo.png"),
        ):
            if os.path.exists(logo_path):
                pixmap = QPixmap(logo_path)
                if not pixmap.isNull():
                    logo.setPixmap(pixmap.scaled(64, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    break
        top_layout.addWidget(logo)

        brand_layout = QVBoxLayout()
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(1)
        company = QLabel("Nelumbo Automation Pvt Ltd")
        company.setObjectName("companyName")
        suite = QLabel("CONNECTIVITY UTILITY SUITE")
        suite.setObjectName("suiteName")
        brand_layout.addWidget(company)
        brand_layout.addWidget(suite)
        top_layout.addLayout(brand_layout)
        top_layout.addStretch()

        tagline_top = QVBoxLayout()
        tagline_top.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        tagline = QLabel("ENGINEERING\nCONNECTED\nPOSSIBILITIES")
        tagline.setObjectName("tagline")
        tagline.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        tagline_top.addWidget(tagline)
        top_line = QFrame()
        top_line.setObjectName("taglineLine")
        top_line.setFixedSize(118, 4)
        tagline_top.addWidget(top_line, alignment=Qt.AlignRight)
        top_layout.addLayout(tagline_top)
        root.addWidget(top_bar)

        # HERO — large product image and balanced text, matching the reference.
        hero = QWidget()
        hero.setFixedHeight(430)
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(42, 18, 18, 0)
        hero_layout.setSpacing(8)

        hero_text = QVBoxLayout()
        hero_text.setContentsMargins(0, 12, 0, 8)
        hero_text.setSpacing(6)
        welcome = QLabel("WELCOME TO")
        welcome.setObjectName("welcomeLabel")
        title = QLabel("Nelumbo\nConnectivity Utility Suite")
        title.setObjectName("mainTitle")
        title.setWordWrap(True)
        subtitle = QLabel("Configure and monitor your I/O modules with ease")
        subtitle.setObjectName("subtitleLabel")
        title_line = QFrame()
        title_line.setObjectName("titleLine")
        title_line.setFixedSize(220, 4)
        hero_text.addWidget(welcome)
        hero_text.addSpacing(4)
        hero_text.addWidget(title)
        hero_text.addWidget(subtitle)
        hero_text.addSpacing(12)
        hero_text.addWidget(title_line)
        hero_text.addStretch()
        hero_layout.addLayout(hero_text, 5)

        product_paths = [
            os.path.join(base_dir, "assets", name)
            for name in ("1.png", "2.png", "3.png", "4.png")
        ]
        product_paths = [path for path in product_paths if os.path.exists(path)]
        if product_paths:
            self.product_carousel = ProductCarousel(product_paths)
            hero_layout.addWidget(self.product_carousel, alignment=Qt.AlignCenter)
        else:
            product = QLabel()
            product.setAlignment(Qt.AlignCenter)
            product.setFixedSize(680, 340)
            hero_layout.addWidget(product, alignment=Qt.AlignCenter)
        root.addWidget(hero)

        section_hint = QLabel("SELECT A MODULE TO GET STARTED")
        section_hint.setObjectName("sectionHint")
        section_hint.setAlignment(Qt.AlignCenter)
        section_hint.setFixedHeight(38)
        root.addWidget(section_hint)

        # MODULE CARDS — custom painted to match the reference while remaining clickable.
        cards = QHBoxLayout()
        cards.setContentsMargins(38, 0, 38, 8)
        cards.setSpacing(14)

        self.digital_input_button = ModuleButton(
            "DI", "Digital Input", "Configure and monitor\ndigital input modules", "#1976D2", "digital"
        )
        self.digital_output_button = ModuleButton(
            "DO", "Digital Output", "Configure and control\ndigital output modules", "#20B96A", "digital"
        )
        self.analog_input_button = ModuleButton(
            "AI", "Analog Input", "Configure and monitor\nanalog input modules", "#E88726", "analog"
        )
        self.analog_output_button = ModuleButton(
            "AO", "Analog Output", "Configure and control\nanalog output modules", "#7250D5", "analog"
        )
        self.modbus_button = ModuleButton(
            "TCP", "Modbus to TCP Gateway", "Configure Modbus to\nTCP settings", "#16B8C5", "network"
        )

        for button in (
            self.digital_input_button,
            self.digital_output_button,
            self.analog_input_button,
            self.analog_output_button,
            self.modbus_button,
        ):
            cards.addWidget(button, 1)
        root.addLayout(cards)

        logout_row = QHBoxLayout()
        logout_row.setContentsMargins(0, 4, 0, 5)
        logout_row.addStretch()
        self.logout_button = QPushButton("LOG OUT")
        self.logout_button.setObjectName("logoutButton")
        self.logout_button.setFixedSize(190, 46)
        self.logout_button.setCursor(Qt.PointingHandCursor)
        self.logout_button.clicked.connect(self.handle_logout)
        logout_row.addWidget(self.logout_button)
        logout_row.addStretch()
        root.addLayout(logout_row)

        footer = QHBoxLayout()
        footer.setContentsMargins(28, 4, 28, 12)
        footer.setSpacing(9)
        footer_label = QLabel("NELUMBO  |  CONNECTIVITY UTILITY SUITE")
        footer_label.setObjectName("footerLabel")
        footer.addWidget(footer_label)
        footer.addStretch()
        product_portfolio = QPushButton("▣  Product Portfolio")
        product_portfolio.setObjectName("footerButton")
        product_portfolio.setCursor(Qt.PointingHandCursor)
        product_portfolio.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://nelumbo.in/product-portfolio")))
        contact_us = QPushButton("☎  Contact Us")
        contact_us.setObjectName("footerButton")
        contact_us.setCursor(Qt.PointingHandCursor)
        contact_us.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://nelumbo.in/contact-us")))
        footer.addWidget(product_portfolio)
        footer.addWidget(contact_us)
        root.addLayout(footer)

        # NAVIGATION — unchanged.
        self.digital_input_button.clicked.connect(self.digital_input_clicked.emit)
        self.digital_output_button.clicked.connect(self.digital_output_clicked.emit)
        self.analog_input_button.clicked.connect(self.analog_input_clicked.emit)
        self.analog_output_button.clicked.connect(self.analog_output_clicked.emit)
        self.modbus_button.clicked.connect(self.modbus_clicked.emit)

    def handle_logout(self):
        reply = QMessageBox.question(
            self,
            "Log Out",
            "Are you sure you want to log out?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel
        )
        if reply == QMessageBox.Yes:
            self.logout_clicked.emit()

    def resizeEvent(self, event):
        self.background.setGeometry(self.rect())
        self.background.lower()
        super().resizeEvent(event)
