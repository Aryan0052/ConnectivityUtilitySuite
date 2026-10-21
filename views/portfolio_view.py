import os
import re
import time
from PySide6.QtCore import Qt, Signal, QUrl, QTimer, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup, Property, QSize, QRect
from PySide6.QtGui import QPainter, QPixmap, QDesktopServices, QColor, QPen, QBrush, QFont, QPainterPath, QFontMetrics
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QMessageBox,
    QSizePolicy,
    QGridLayout,
)

try:
    from . import image_cache
except ImportError:          # started as a plain script
    import image_cache

# The pictures are decoded in a background thread (image_cache) and kept at this maximum size.
PRODUCT_MAX = (1600, 1100)
BACKGROUND_MAX = (1920, 1080)
MIN_CARD_WIDTH = 232         # the module cards flow into as many columns as fit (5 at most)
_PX = re.compile(r"(\d+(?:\.\d+)?)px")


def page_scale(window):
    """UI size factor for the window size (1.0 at the design size, up to 1.8): at 100 % / 125 % Windows
    scaling the window is big in pixels, so the whole page grows with it instead of looking tiny."""
    width, height = window.width(), window.height()
    if width <= 0 or height <= 0:
        return 1.0
    return max(1.0, min(1.8, round(min(width / 1250.0, height / 940.0) * 10) / 10.0))


def asset(name):
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", name)


def preload_assets():
    """Start decoding the Portfolio pictures in the background (called while the login page is shown)."""
    image_cache.preload(asset("portfolio_BG.png"), *BACKGROUND_MAX)
    for name in ("1.png", "2.png", "3.png", "4.png"):
        if os.path.exists(asset(name)):
            image_cache.preload(asset(name), *PRODUCT_MAX)


class PortfolioBackground(QWidget):
    """Full-window picture. It is scaled once per window size - not at every repaint (the carousel
    animation repaints this widget many times per second)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.pixmap = image_cache.pixmap(asset("portfolio_BG.png"), *BACKGROUND_MAX)
        self._scaled = QPixmap()
        self._scaled_size = QSize()
        self._scaled_smooth = True
        self._dragging = False
        self._last_resize = 0.0
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(120)
        self._settle.timeout.connect(self._settled)
        self.lower()
    def resizeEvent(self, event):
        # resize events in quick succession = the window is being dragged: quick scaling meanwhile,
        # the smooth version follows 120 ms after the last event
        now = time.monotonic()
        self._dragging = (now - self._last_resize) < 0.15
        self._last_resize = now
        self._settle.start()
        super().resizeEvent(event)
    def _settled(self):
        self._dragging = False
        if not self._scaled_smooth:
            self.update()
    def paintEvent(self, event):
        if self.pixmap.isNull():
            return
        size = self.size()
        if self._scaled_size != size or (not self._scaled_smooth and not self._dragging):
            self._scaled = self.pixmap.scaled(
                size, Qt.IgnoreAspectRatio,
                Qt.FastTransformation if self._dragging else Qt.SmoothTransformation
            )
            self._scaled_size = size
            self._scaled_smooth = not self._dragging
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._scaled)
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
        self.setMinimumWidth(MIN_CARD_WIDTH)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setFlat(True)
        self._title_font_for = (None, None)            # (width, font) - the title font that fits the card
        self._s = 1.0                                  # UI size factor (PortfolioView._auto_scale)
    def set_scale(self, factor):
        if factor != self._s:
            self._s = factor
            self._title_font_for = (None, None)
            self.setMinimumHeight(round(185 * factor))
            self.setMinimumWidth(round(MIN_CARD_WIDTH * factor))
            self.update()
    _FONTS = {}
    @classmethod
    def _font(cls, size, weight):
        key = (round(size, 2), weight)
        if key not in cls._FONTS:
            font = QFont("Segoe UI")
            font.setPointSizeF(key[0])
            font.setWeight(weight)
            cls._FONTS[key] = font
        return cls._FONTS[key]
    def _fit_title(self, width):
        """Largest title font (12 .. 9 pt) that shows the whole title in at most two lines."""
        if self._title_font_for[0] == width:
            return self._title_font_for[1]
        chosen = self._font(9 * self._s, QFont.DemiBold)
        for size in (12, 11, 10, 9):
            font = self._font(size * self._s, QFont.DemiBold)
            metrics = QFontMetrics(font)
            box = metrics.boundingRect(QRect(0, 0, width, 1000), Qt.TextWordWrap, self.title)
            if box.height() <= metrics.lineSpacing() * 2 + 1 and box.width() <= width:
                chosen = font
                break
        self._title_font_for = (width, chosen)
        return chosen
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)
        s = self._s

        def k(value):
            return round(value * s)
        radius = k(16)
        # Card
        painter.setPen(QPen(QColor("#D7E6EA"), 1))
        painter.setBrush(QBrush(QColor(255, 255, 255, 244)))
        painter.drawRoundedRect(rect, radius, radius)
        # Accent bottom bar
        bottom = rect.adjusted(0, rect.height() - k(5), 0, 0)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(self.accent))
        painter.drawRoundedRect(bottom, 3, 3)
        # Icon square
        icon_rect = rect.adjusted(k(28), k(28), 0, 0)
        icon_rect.setWidth(k(62))
        icon_rect.setHeight(k(62))
        painter.setBrush(QBrush(self.accent))
        painter.drawRoundedRect(icon_rect, k(11), k(11))
        painter.save()                                 # the icon is drawn at the design size, then scaled
        painter.translate(icon_rect.x(), icon_rect.y())
        painter.scale(s, s)
        self._draw_icon(painter, QRect(0, 0, 62, 62))
        painter.restore()
        # Text
        left = icon_rect.right() + k(18)
        title_y = rect.top() + k(30)
        painter.setPen(QColor("#092F49"))
        painter.setFont(self._font(15 * s, QFont.Bold))
        painter.drawText(left, title_y + k(4), self.code)
        title_width = max(k(40), rect.right() - k(12) - left)
        painter.setFont(self._fit_title(title_width))
        painter.drawText(QRect(left, title_y + k(12), title_width, k(40)), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, self.title)
        painter.setPen(QColor("#607986"))
        painter.setFont(self._font(10 * s, QFont.Normal))
        desc_rect = rect.adjusted(k(28), k(103), -k(18), -k(35))
        painter.drawText(
            desc_rect,
            Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
            self.description
        )
        painter.setPen(self.accent)
        painter.setFont(self._font(10 * s, QFont.Bold))
        painter.drawText(
            rect.adjusted(k(28), rect.height() - k(38), -k(18), -k(10)),
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
        elif self.icon_type == "meter":
            # Multi-function meter: gauge arc with a needle.
            arc_rect = rect.adjusted(11, 13, -11, -9)
            painter.drawArc(arc_rect, 20 * 16, 140 * 16)
            cx, cy = x + w // 2, y + h // 2 + 8
            painter.drawLine(cx, cy, cx + 10, cy - 14)
            painter.setBrush(Qt.white)
            painter.drawEllipse(cx - 3, cy - 3, 6, 6)
            painter.setBrush(Qt.NoBrush)
            painter.drawLine(x + 16, y + h - 12, x + w - 16, y + h - 12)
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
        self.setMinimumSize(300, 260)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)   # width: the hero layout's 5 : 6 split decides
        self._paths = image_paths
        self._pixmaps = [image_cache.pixmap(path, *PRODUCT_MAX) for path in image_paths]
        self._shown = {}                       # (index, w, h) -> picture already scaled for the current size
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
    def sizeHint(self):
        return QSize(1160, 470)
    def set_paused(self, paused):
        """Hold the slide show (used while the other pages are being pre-built in the background)."""
        self._paused = bool(paused)
        if self._paused:
            self._timer.stop()
        elif not self._animating and self.isVisible() and len(self._pixmaps) > 1:
            self._timer.start()
    def _box(self):
        """Space of the large product picture (the former 780 x 410 of a 1160 x 470 carousel)."""
        return max(60, int(self.width() * 0.90)), max(60, int(self.height() * 0.872))
    def _scaled_product(self, index):
        width, height = self._box()
        key = (index, width, height)
        pixmap = self._shown.get(key)
        if pixmap is None:
            if len(self._shown) > len(self._pixmaps) + 1:
                self._shown.clear()
            pixmap = self._pixmaps[index].scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._shown[key] = pixmap
        return pixmap
    def resizeEvent(self, event):
        self._shown.clear()
        self._update_dots()
        super().resizeEvent(event)
    def showEvent(self, event):
        super().showEvent(event)
        if not self._animating and len(self._pixmaps) > 1 and not getattr(self, "_paused", False):
            self._timer.start()
    def hideEvent(self, event):
        super().hideEvent(event)
        if not self._animating:
            self._timer.stop()            # nothing moves while another page is open
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
            dot.move(start_x + i * 24, self.height() - 32)
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
    def _cy(self):
        return int(self.height() * 0.436)        # 205 of 470
    def _travel(self):
        return self.width() * 0.448              # 520 of 1160
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
        scaled = self._scaled_product(index)
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
                self._cy(),
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
                cx = (self.width() // 2) - (eased * self._travel())
                rotation = -8 * eased
            else:
                cx = (self.width() // 2) + (eased * self._travel())
                rotation = 8 * eased
            scale = 1.0 - (0.08 * eased)
            opacity = 1.0 - eased
            self._draw_product(
                painter, self._index, cx, self._cy(), scale, rotation, opacity
            )
        elif progress < 0.55:
            # Intentional short gap: no product is shown.
            pass
        else:
            local = (progress - 0.55) / 0.45
            eased = self._ease(local)
            next_index = (self._index + self._direction) % len(self._pixmaps)
            if self._direction > 0:
                cx = (self.width() // 2) + self._travel() - (eased * self._travel())
                rotation = 8 - (8 * eased)
            else:
                cx = (self.width() // 2) - self._travel() + (eased * self._travel())
                rotation = -8 + (8 * eased)
            scale = 0.92 + (0.08 * eased)
            opacity = eased
            self._draw_product(
                painter, next_index, cx, self._cy(), scale, rotation, opacity
            )
        painter.end()
    def _start_slide(self, direction):
        if self._animating or len(self._pixmaps) < 2:
            return
        self._direction = direction
        self._animating = True
        self._progress = 0.0
        self._timer.stop()
        self._scaled_product((self._index + direction) % len(self._pixmaps))      # ready before the first frame
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
        if self.isVisible() and not getattr(self, "_paused", False):
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
    multi_device_clicked = Signal()
    mft_clicked = Signal()
    mft_analog_clicked = Signal()
    communication_clicked = Signal()
    logout_clicked = Signal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("portfolioView")
        self._scale = 1.0
        self._sized = []          # (object, method, design-size args): re-applied with the UI size factor
        self._qss = ("""
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
        self.setStyleSheet(self._qss)
        size = self._size
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.background = PortfolioBackground(self)
        self.background.setGeometry(self.rect())
        self.background.lower()
        # HEADER — same navigation/branding functionality.
        top_bar = QFrame()
        top_bar.setObjectName("topBar")
        size(top_bar, "setFixedHeight", 92)
        top_layout = QHBoxLayout(top_bar)
        size(top_layout, "setContentsMargins", 28, 8, 28, 8)
        size(top_layout, "setSpacing", 14)
        logo = QLabel()
        self._logo, self._logo_pixmap = logo, None
        size(logo, "setFixedSize", 72, 68)
        logo.setAlignment(Qt.AlignCenter)
        base_dir = os.path.dirname(os.path.dirname(__file__))
        for logo_path in (
            os.path.join(base_dir, "assets", "13.ico"),
            os.path.join(base_dir, "assets", "NelumboLogo.png"),
        ):
            if os.path.exists(logo_path):
                pixmap = QPixmap(logo_path)
                if not pixmap.isNull():
                    self._logo_pixmap = pixmap
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
        size(top_line, "setFixedSize", 118, 4)
        tagline_top.addWidget(top_line, alignment=Qt.AlignRight)
        top_layout.addLayout(tagline_top)
        root.addWidget(top_bar)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollArea > QWidget > QWidget {
                background: transparent;
            }
        """)
        scroll_area.viewport().setAttribute(Qt.WA_TranslucentBackground, True)
        content_widget = QWidget()
        content_widget.setAttribute(Qt.WA_TranslucentBackground, True)
        content_widget.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        scroll_area.setWidget(content_widget)
        root.addWidget(scroll_area, 1)
        # HERO — large product image and balanced text, matching the reference.
        hero = QWidget()
        hero.setFixedHeight(430)                 # bigger UI: _fit_hero gives the cards the room they need
        self._hero, self._content, self._scroll = hero, content_widget, scroll_area
        hero_layout = QHBoxLayout(hero)
        size(hero_layout, "setContentsMargins", 42, 18, 18, 0)
        size(hero_layout, "setSpacing", 8)
        text_box = QWidget()
        text_box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)   # 5 : 6 split with the carousel
        size(text_box, "setMinimumWidth", 260)
        hero_text = QVBoxLayout(text_box)
        size(hero_text, "setContentsMargins", 0, 12, 0, 8)
        size(hero_text, "setSpacing", 6)
        welcome = QLabel("WELCOME TO")
        welcome.setObjectName("welcomeLabel")
        title = QLabel("Nelumbo\nConnectivity Utility Suite")
        title.setObjectName("mainTitle")
        title.setWordWrap(True)
        subtitle = QLabel("Configure and monitor your I/O modules with ease")
        subtitle.setObjectName("subtitleLabel")
        subtitle.setWordWrap(True)
        title_line = QFrame()
        title_line.setObjectName("titleLine")
        size(title_line, "setFixedSize", 220, 4)
        hero_text.addWidget(welcome)
        hero_text.addSpacing(4)
        hero_text.addWidget(title)
        hero_text.addWidget(subtitle)
        hero_text.addSpacing(12)
        hero_text.addWidget(title_line)
        hero_text.addStretch()
        hero_layout.addWidget(text_box, 5)
        product_paths = [
            os.path.join(base_dir, "assets", name)
            for name in ("1.png", "2.png", "3.png", "4.png")
        ]
        product_paths = [path for path in product_paths if os.path.exists(path)]
        if product_paths:
            self.product_carousel = ProductCarousel(product_paths)
            hero_layout.addWidget(self.product_carousel, 6)
        else:
            product = QLabel()
            product.setAlignment(Qt.AlignCenter)
            product.setMinimumSize(300, 260)
            hero_layout.addWidget(product, 6)
        content_layout.addWidget(hero)
        section_hint = QLabel("SELECT A MODULE TO GET STARTED")
        section_hint.setObjectName("sectionHint")
        section_hint.setAlignment(Qt.AlignCenter)
        size(section_hint, "setFixedHeight", 38)
        content_layout.addWidget(section_hint)
        # MODULE CARDS — custom painted to match the reference while remaining clickable.
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
        self.communication_button = ModuleButton(
            "COM", "Communication", "Manage RTU, TCP and\nGateway communication", "#159FC0", "network"
        )
        self.multi_device_button = ModuleButton(
            "MD", "Multi Device Management", "Manage multiple\nI/O devices together", "#159FC0", "network"
        )
        self.mft_button = ModuleButton(
            "MFT", "MFT Transducer", "Configure RTU settings,\nCT and PT ratio", "#D9467B", "meter"
        )
        self.mft_analog_button = ModuleButton(
            "MFT-A", "MFT Analog", "Configure 4-20mA outputs,\nCT and PT ratio", "#E5A100", "meter"
        )
        # Nine cards in a grid: as many columns as fit the window (5 -> 4 on a smaller window ...), so no card is
        # ever cut off. With 5 columns this is the same two-row layout as before.
        self._card_buttons = [
            self.digital_input_button, self.digital_output_button, self.analog_input_button,
            self.analog_output_button, self.modbus_button, self.communication_button,
            self.multi_device_button, self.mft_button, self.mft_analog_button,
        ]
        self._cards_grid = QGridLayout()
        size(self._cards_grid, "setContentsMargins", 38, 0, 38, 8)
        size(self._cards_grid, "setHorizontalSpacing", 14)
        size(self._cards_grid, "setVerticalSpacing", 8)
        self._columns = 0
        self._reflow_cards(5)
        content_layout.addLayout(self._cards_grid)
        logout_row = QHBoxLayout()
        size(logout_row, "setContentsMargins", 0, 4, 0, 5)
        logout_row.addStretch()
        self.logout_button = QPushButton("LOG OUT")
        self.logout_button.setObjectName("logoutButton")
        size(self.logout_button, "setFixedSize", 190, 46)
        self.logout_button.setCursor(Qt.PointingHandCursor)
        self.logout_button.clicked.connect(self.handle_logout)
        logout_row.addWidget(self.logout_button)
        logout_row.addStretch()
        root.addLayout(logout_row)
        footer = QHBoxLayout()
        size(footer, "setContentsMargins", 28, 4, 28, 12)
        size(footer, "setSpacing", 9)
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
        content_layout.addLayout(footer)
        # NAVIGATION — unchanged.
        self.digital_input_button.clicked.connect(self.digital_input_clicked.emit)
        self.digital_output_button.clicked.connect(self.digital_output_clicked.emit)
        self.analog_input_button.clicked.connect(self.analog_input_clicked.emit)
        self.analog_output_button.clicked.connect(self.analog_output_clicked.emit)
        self.modbus_button.clicked.connect(self.modbus_clicked.emit)
        self.communication_button.clicked.connect(self.communication_clicked.emit)
        self.multi_device_button.clicked.connect(self.multi_device_clicked.emit)
        self.mft_button.clicked.connect(self.mft_clicked.emit)
        self.mft_analog_button.clicked.connect(self.mft_analog_clicked.emit)
        self._scale_timer = QTimer(self)
        self._scale_timer.setSingleShot(True)
        self._scale_timer.setInterval(100)          # window resize: re-size once it has settled
        self._scale_timer.timeout.connect(self._resized)
    def _size(self, obj, method, *args):
        self._sized.append((obj, method, args))
        getattr(obj, method)(*args)
    def _auto_scale(self):
        """Whole page follows the window size (text, header, hero, cards, buttons) - see page_scale."""
        factor = page_scale(self.window())
        if factor == self._scale:
            return
        self._scale = factor

        def k(value):
            return max(1, round(value * factor)) if value else 0
        self.setUpdatesEnabled(False)
        try:
            self.setStyleSheet(_PX.sub(lambda m: f"{k(float(m.group(1)))}px", self._qss))
            for obj, method, args in self._sized:
                getattr(obj, method)(*[k(a) for a in args])
            if self._logo_pixmap is not None:
                self._logo.setPixmap(self._logo_pixmap.scaled(k(64), k(60), Qt.KeepAspectRatio,
                                                              Qt.SmoothTransformation))
            for button in self._card_buttons:
                button.set_scale(factor)
            self._reflow_for(self.width())
        finally:
            self.setUpdatesEnabled(True)
    def _fit_hero(self):
        """Design size (factor 1.0): the hero keeps its 430 px. Bigger UI: the hero gives up height (430 -> 300
        at most, scaled) so the module cards stay on screen."""
        k = self._scale
        height = 430
        if k > 1.0:
            rest = self._content.sizeHint().height() - self._hero.height()
            height = max(round(300 * k), min(round(430 * k), self._scroll.viewport().height() - rest))
        if height != self._hero.height():
            self._hero.setFixedHeight(height)
    def _resized(self):
        self._auto_scale()
        self._fit_hero()
    def showEvent(self, event):
        self._resized()
        super().showEvent(event)
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
    def _reflow_cards(self, columns):
        if columns == self._columns:
            return
        for column in range(max(self._columns, columns)):
            self._cards_grid.setColumnStretch(column, 1 if column < columns else 0)
        for button in self._card_buttons:
            self._cards_grid.removeWidget(button)
        for number, button in enumerate(self._card_buttons):
            self._cards_grid.addWidget(button, number // columns, number % columns)
        self._columns = columns
    def resizeEvent(self, event):
        self.background.setGeometry(self.rect())
        self.background.lower()
        self._reflow_for(event.size().width())
        if self.isVisible():
            self._scale_timer.start()
        super().resizeEvent(event)
    def _reflow_for(self, width):
        k = self._scale
        usable = width - round(76 * k) - 18                   # card margins and the scroll bar
        gap = round(14 * k)
        self._reflow_cards(max(2, min(5, (usable + gap) // (round(MIN_CARD_WIDTH * k) + gap))))