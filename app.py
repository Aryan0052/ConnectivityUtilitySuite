import importlib
import os
import sys

# 150% is the reference application size.
os.environ["QT_SCALE_FACTOR"] = str(1.0 / 1.5)

import time

from PySide6.QtCore import Qt, QTimer, QObject, QEvent
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QScrollArea,
    QFrame,
    QStackedWidget,
    QWidget,
    QPushButton,
)

from views.login_view import LoginView, preload_assets as preload_login_assets

# The pages are loaded later with importlib (see _ensure_view). PyInstaller cannot see such imports, so they are
# listed here in a block that never runs: the exe then contains every page.
if sys.argv is None:  # never true
    import views.portfolio_view, views.digital_input_view, views.digital_output_view  # noqa: F401,E401
    import views.analog_input_view, views.analog_output_view, views.modbus_view  # noqa: F401,E401
    import views.communication_view, views.multi_device_view, views.mft_view  # noqa: F401,E401
    import views.mft_analog_view, views.analog_input_test_mode_view  # noqa: F401,E401
    import views.analog_input_data_analysis_view, views.port_list  # noqa: F401,E401

# Pre-building the pages while the user is on the login / portfolio screen.
WARMUP_FIRST_MS = 150      # wait after the window is shown
WARMUP_GAP_MS = 40         # pause between two warm-up steps
WARMUP_IDLE_MS = 400       # a warm-up step starts only after the user has not typed / clicked for this long


class InputClock(QObject):
    """Remembers when the user last pressed a key / clicked the mouse / turned the wheel, so background
    work can wait. It sees every event of the application, so it is removed as soon as the warm-up is done."""
    # (mouse MOVES are not counted: just hovering over the Portfolio would stop the pages from being built)
    _TYPES = frozenset(int(t.value) for t in (QEvent.KeyPress, QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
                                             QEvent.Wheel))

    def __init__(self):
        super().__init__()
        self.last = 0.0

    def eventFilter(self, obj, event):
        if event.type().value in self._TYPES:
            self.last = time.monotonic()
        return False

    def idle_ms(self):
        return (time.monotonic() - self.last) * 1000.0


class AdaptiveStack(QStackedWidget):
    """Page stack that adapts to any display size / Windows scaling (100 - 200 %).

    Every page except the login screen is shown inside a scroll area that follows the window: when the window
    is at least as large as the page needs, the page simply fills it (nothing changes); when the display is
    smaller (e.g. 175 / 200 % scaling) the window can still be fitted to the screen and the page scrolls
    instead of being cut off. The code outside only ever sees the pages themselves (addWidget /
    setCurrentWidget / currentWidget take and return the page)."""

    def __init__(self):
        super().__init__()
        self._holder_of = {}          # page -> scroll area that shows it

    def addWidget(self, widget):
        if isinstance(widget, LoginView):
            return super().addWidget(widget)       # the login artwork scales to the window by itself
        holder = QScrollArea()
        holder.setWidgetResizable(True)
        holder.setFrameShape(QFrame.NoFrame)
        holder.viewport().setAutoFillBackground(False)
        holder.setWidget(widget)
        self._holder_of[widget] = holder
        return super().addWidget(holder)

    def setCurrentWidget(self, widget):
        super().setCurrentWidget(self._holder_of.get(widget, widget))

    def currentWidget(self):
        current = super().currentWidget()
        if isinstance(current, QScrollArea):
            return current.widget() or current
        return current


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Nelumbo Connectivity Utility Suite")

        # Application / window icon
        if getattr(sys, "frozen", False):
            icon_base_path = sys._MEIPASS
        else:
            icon_base_path = os.path.dirname(os.path.abspath(__file__))

        self.app_icon = _square_icon(_icon_file(icon_base_path))
        self.setWindowIcon(self.app_icon)

        # Default application size.
        # The window remains resizable so Windows display scaling and
        # maximize/restore can be handled normally.
        self.resize(1100, 870)

        self.setStyleSheet("""
            QMainWindow {
                background: #F5FAEF;
            }
            QStackedWidget {
                background: #F5FAEF;
            }
        """)

        # -------------------------------------------------
        # STACK
        # -------------------------------------------------
        self.stack = AdaptiveStack()
        self.stack.setObjectName("mainStack")
        self.setCentralWidget(self.stack)

        # -------------------------------------------------
        # VIEWS
        # -------------------------------------------------
        # Login is the only view created during startup.
        # Other views are created only when the user opens them.
        self.login_view = LoginView()
        self.stack.addWidget(self.login_view)

        # -------------------------------------------------
        # LOGIN -> PORTFOLIO
        # -------------------------------------------------
        if hasattr(self.login_view, "login_successful"):
            self.login_view.login_successful.connect(self.show_portfolio)

        # -------------------------------------------------
        # START WITH LOGIN
        # -------------------------------------------------
        self.stack.setCurrentWidget(self.login_view)

    # -----------------------------------------------------
    # NAVIGATION
    # -----------------------------------------------------
    def _ensure_portfolio(self):
        if not hasattr(self, "portfolio_view"):
            from views.portfolio_view import PortfolioView

            self.portfolio_view = PortfolioView()
            self.stack.addWidget(self.portfolio_view)

            routes = (
                ("digital_input_clicked", self.show_digital_input),
                ("digital_output_clicked", self.show_digital_output),
                ("analog_input_clicked", self.show_analog_input),
                ("analog_output_clicked", self.show_analog_output),
                ("modbus_clicked", self.show_modbus),
                ("communication_clicked", self.show_communication),
                ("multi_device_clicked", self.show_multi_device),
                ("mft_clicked", self.show_mft),
                ("mft_analog_clicked", self.show_mft_analog),
                ("logout_clicked", self.show_login),
            )
            for signal_name, handler in routes:
                if hasattr(self.portfolio_view, signal_name):
                    getattr(self.portfolio_view, signal_name).connect(handler)
        return self.portfolio_view

    def show_portfolio(self):
        self.stack.setCurrentWidget(self._ensure_portfolio())

    # -----------------------------------------------------
    # VIEW CREATION / WARM-UP
    # -----------------------------------------------------
    # key -> (module, class). The view is stored as self.<key>_view.
    _VIEW_SPECS = {
        "digital_input": ("digital_input_view", "DigitalInputView"),
        "digital_output": ("digital_output_view", "DigitalOutputView"),
        "analog_input": ("analog_input_view", "AnalogInputView"),
        "analog_output": ("analog_output_view", "AnalogOutputView"),
        "modbus": ("modbus_view", "ModbusView"),
        "communication": ("communication_view", "CommunicationView"),
        "multi_device": ("multi_device_view", "MultiDeviceView"),
        "mft": ("mft_view", "MFTView"),
        "mft_analog": ("mft_analog_view", "MFTAnalogView"),
    }

    def _ensure_view(self, key, build_later=False):
        """Create a view the first time it is needed (or when the warm-up reaches it). A page that can be
        built in pieces (build_step / finish_build, e.g. Multi Device) is started with build_later=True by the
        warm-up; any other call completes it first."""
        attr = key + "_view"
        view = getattr(self, attr, None)
        if view is not None:
            if not build_later and callable(getattr(view, "finish_build", None)):
                view.finish_build()
            return view
        module_name, class_name = self._VIEW_SPECS[key]
        module = importlib.import_module("views." + module_name)
        cls = getattr(module, class_name)
        view = cls(build_later=True) if build_later and hasattr(cls, "build_step") else cls()
        setattr(self, attr, view)
        self.stack.addWidget(view)
        if hasattr(view, "back_clicked"):
            view.back_clicked.connect(self.show_portfolio)
        if key == "analog_input" and hasattr(view, "_test_mode_button"):
            view._test_mode_button.clicked.connect(self.show_analog_input_test_mode)
        return view

    def _prepare_view(self, view):
        """Do the first-show work (style-sheet polish and layout) while the view is still hidden."""
        view.resize(self.stack.size())
        for child in view.findChildren(QWidget):
            child.ensurePolished()
        view.ensurePolished()
        layout = view.layout()
        if layout is not None:
            layout.activate()
        auto_scale = getattr(view, "_auto_scale", None)      # e.g. Multi Device: DPI / window-size styling
        if callable(auto_scale):
            auto_scale()
        if getattr(view, "_pg_sync", None) is not None:        # single-device pages: theme / window-size styling
            from views import ui_theme
            ui_theme.prepare(view)

    def _show_view(self, key):
        try:
            view = self._ensure_view(key)
        except Exception:
            # without this a failing page just does nothing when clicked (no console in the exe)
            import traceback
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Could not open page",
                                 f"The page '{key}' could not be opened:\n\n{traceback.format_exc()[-1500:]}")
            return
        self.stack.setCurrentWidget(view)

    def _start_warmup(self):
        """Build the pages in the background of the login / portfolio screen, one small step at a
        time, so that a click on a module only has to switch pages. Steps wait while a module is open
        (never compete with live polling) and stop doing anything once everything is ready."""
        self._input_clock = InputClock()
        QApplication.instance().installEventFilter(self._input_clock)
        steps = [self._ensure_portfolio, lambda: self._prepare_view(self._ensure_portfolio())]
        steps += [lambda mod=module_name: importlib.import_module("views." + mod) for module_name, _c in self._VIEW_SPECS.values()]
        # Multi Device is the biggest page (built in pieces): it is built first, so it is ready soonest
        order = ["multi_device"] + [k for k in self._VIEW_SPECS if k != "multi_device"]
        for key in order:
            steps.append(lambda k=key: self._build_piece(k))
            steps.append(lambda k=key: self._prepare_view(self._ensure_view(k)))
        self._warmup_steps = steps
        QTimer.singleShot(WARMUP_FIRST_MS, self._warmup_step)

    def _build_piece(self, key):
        """Warm-up: build one piece of a page that can be built in pieces (the whole page otherwise); the
        step stays first in the list until the page is complete, so the screen never stands still for long."""
        view = self._ensure_view(key, build_later=True)
        step = getattr(view, "build_step", None)
        if callable(step) and not step():
            self._warmup_steps.insert(0, lambda: self._build_piece(key))

    def preload_all_pages(self):
        """Build every page while the window is still hidden, so the application opens only when everything
        is ready and every page opens at once. Returns False if a page could not be built (that page is then
        built when it is first opened, as before)."""
        ok = True
        try:
            self._prepare_view(self._ensure_portfolio())
        except Exception:
            ok = False
        order = ["multi_device"] + [k for k in self._VIEW_SPECS if k != "multi_device"]
        for key in order:
            try:
                view = self._ensure_view(key)            # complete build (Multi Device: all its pieces)
                self._prepare_view(view)
            except Exception:
                ok = False
        return ok

    def _hold_slideshow(self, hold):
        # the Portfolio slide show stands still while pages are being built (a build can take a moment)
        carousel = getattr(getattr(self, "portfolio_view", None), "product_carousel", None)
        if carousel is not None:
            carousel.set_paused(hold)

    def _warmup_done(self):
        self._hold_slideshow(False)
        clock = getattr(self, "_input_clock", None)
        if clock is not None:                        # no more event filter on every event of the application
            QApplication.instance().removeEventFilter(clock)
            self._input_clock = None

    def _warmup_step(self):
        if not self._warmup_steps:
            self._warmup_done()
            return
        current = self.stack.currentWidget()
        idle = current is self.login_view or current is getattr(self, "portfolio_view", None)
        if idle and self._input_clock.idle_ms() < WARMUP_IDLE_MS:
            QTimer.singleShot(150, self._warmup_step)         # the user is typing / clicking: wait
            return
        if idle:
            if self._warmup_steps and len(self._warmup_steps) > 0:
                self._hold_slideshow(True)
            step = self._warmup_steps.pop(0)
            try:
                step()
            except Exception:
                pass                         # a failing pre-build is retried by the normal click path
            if not self._warmup_steps:
                self._warmup_done()
                return
        QTimer.singleShot(WARMUP_GAP_MS if idle else 1000, self._warmup_step)

    def show_login(self):
        self.login_view.username_input.clear()
        self.login_view.password_input.clear()
        self.stack.setCurrentWidget(self.login_view)

    def show_digital_input(self):
        self._show_view("digital_input")

    def show_digital_output(self):
        self._show_view("digital_output")

    def show_analog_input(self):
        self._show_view("analog_input")

    def show_analog_input_test_mode(self):
        if not hasattr(self, "analog_input_test_mode_view"):
            from views.analog_input_test_mode_view import AnalogInputTestModeView

            self.analog_input_test_mode_view = AnalogInputTestModeView()
            self.stack.addWidget(self.analog_input_test_mode_view)

            # Show the Test Mode page first, then let Qt finish the
            # remaining heavy UI work without blocking the navigation click.
            self.stack.setCurrentWidget(self.analog_input_test_mode_view)

            self.analog_input_test_mode_view.set_connection_context(
                lambda: self.analog_input_view._serial_connection,
                lambda: self.analog_input_view._slave_id.text(),
            )

            if hasattr(self.analog_input_test_mode_view, "back_clicked"):
                self.analog_input_test_mode_view.back_clicked.connect(
                    self.show_analog_input
                )

        self.stack.setCurrentWidget(self.analog_input_test_mode_view)

        # Connect only the existing DATA ANALYSIS button.
        for button in self.analog_input_test_mode_view.findChildren(QPushButton):
            if button.text().strip().upper() == "DATA ANALYSIS":
                button.clicked.connect(self.show_analog_input_data_analysis)
                self.analog_input_test_mode_view._data_analysis_button = button
                break

    def show_analog_input_data_analysis(self):
        if not hasattr(self, "analog_input_data_analysis_view"):
            from views.analog_input_data_analysis_view import AnalogInputDataAnalysisView

            self.analog_input_data_analysis_view = AnalogInputDataAnalysisView()
            self.stack.addWidget(self.analog_input_data_analysis_view)

            if hasattr(self.analog_input_data_analysis_view, "back_clicked"):
                self.analog_input_data_analysis_view.back_clicked.connect(
                    self.show_analog_input_test_mode
                )

        self.stack.setCurrentWidget(self.analog_input_data_analysis_view)

    def show_analog_output(self):
        self._show_view("analog_output")

    def show_modbus(self):
        self._show_view("modbus")

    def show_communication(self):
        self._show_view("communication")

    def show_multi_device(self):
        self._show_view("multi_device")

    def show_mft(self):
        self._show_view("mft")

    def show_mft_analog(self):
        self._show_view("mft_analog")


def _icon_file(base_path):
    """Window / taskbar icon: assets/app_icon.ico (a real multi-size Windows icon - Windows needs that for the
    taskbar) when present, else assets/13.ico (the logo picture, also used inside the pages)."""
    real = os.path.join(base_path, "assets", "app_icon.ico")
    return real if os.path.exists(real) else os.path.join(base_path, "assets", "13.ico")


def _square_icon(path):
    """The logo picture as a window / taskbar icon. 13.ico is a 969 x 733 picture: Windows shows a
    non-square icon in the title bar but not in the taskbar, so the SAME picture is placed in the middle of a
    square with transparent bands above and below (nothing else is changed), in the sizes Windows asks for."""
    from PySide6.QtGui import QImage, QPixmap, QPainter
    image = QImage(path)
    if image.isNull():
        return QIcon(path)
    icon = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64, 96, 128, 256):
        picture = image.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        square = QPixmap(size, size)
        square.fill(Qt.transparent)
        painter = QPainter(square)
        painter.drawImage((size - picture.width()) // 2, (size - picture.height()) // 2, picture)
        painter.end()
        icon.addPixmap(square)
    return icon


def _preload_portfolio():
    from views.portfolio_view import preload_assets
    preload_assets()           # Portfolio pictures are decoded in a thread while the login page is shown


def main():
    # Windows taskbar/application identity.
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Nelumbo.Automation.ConnectivityUtilitySuite"
        )

    app = QApplication(sys.argv)
    try:
        from views import port_list
        port_list.install()         # COM port list read in the background (no freeze when a page is opened)
    except ImportError:
        pass                        # views/port_list.py missing: the pages read the list directly (slower)

    # -------------------------------------------------
    # APPLICATION ICON
    # -------------------------------------------------
    if getattr(sys, "frozen", False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))

    icon_path = _icon_file(base_path)
    app_icon = _square_icon(icon_path)
    app.setWindowIcon(app_icon)

    app.setStyle("Fusion")

    preload_login_assets()          # decode the 4K login artwork in a thread while the window is built
    _preload_portfolio()            # Portfolio pictures too
    window = MainWindow()

    # Explicitly apply the same icon to the main window.
    window.setWindowIcon(app_icon)

    # Keep the existing default size. The window is intentionally
    # resizable/maximizable instead of fixed-size.
    screen = app.primaryScreen().availableGeometry()

    base_width = 1100
    base_height = 870

    width = min(base_width, screen.width())
    height = min(base_height, screen.height())

    window.resize(width, height)

    window.move(
        screen.x() + (screen.width() - window.width()) // 2,
        screen.y() + (screen.height() - window.height()) // 2,
    )

    # Every page is built BEFORE the window appears (nothing is shown meanwhile, only the busy mouse
    # cursor), at the full-screen size because the text size follows the window size. When the window opens,
    # every page opens at once.
    app.setOverrideCursor(Qt.WaitCursor)
    window.resize(screen.width(), screen.height())
    window.layout().activate()
    all_built = window.preload_all_pages()
    app.restoreOverrideCursor()

    window.showMaximized()          # the application opens full screen
    if not all_built:
        window._start_warmup()      # a page that failed is tried again in the background

    sys.exit(app.exec())


if __name__ == "__main__":
    main()