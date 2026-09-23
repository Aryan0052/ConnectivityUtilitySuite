import os
import sys

# 150% is the reference application size.
os.environ["QT_SCALE_FACTOR"] = str(1.0 / 1.5)

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QStackedWidget,
)

from views.login_view import LoginView


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle(
            "Nelumbo Connectivity Utility Suite"
        )

        # Application / window icon
        if getattr(sys, "frozen", False):
            icon_base_path = sys._MEIPASS
        else:
            icon_base_path = os.path.dirname(
                os.path.abspath(__file__)
            )

        self.app_icon = QIcon(
            os.path.join(
                icon_base_path,
                "assets",
                "13.ico"
            )
        )

        self.setWindowIcon(
            self.app_icon
        )

        # Default application size.
        # The window remains resizable so Windows display scaling and
        # maximize/restore can be handled normally.
        self.resize(
            1100,
            870
        )

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

        self.stack = QStackedWidget()

        self.stack.setObjectName(
            "mainStack"
        )

        self.setCentralWidget(
            self.stack
        )

        # -------------------------------------------------
        # VIEWS
        # -------------------------------------------------

        # Login is the only view created during startup.
        # Other views are created only when the user opens them.
        self.login_view = LoginView()

        self.stack.addWidget(
            self.login_view
        )

        # -------------------------------------------------
        # LOGIN -> PORTFOLIO
        # -------------------------------------------------

        if hasattr(
            self.login_view,
            "login_successful"
        ):
            self.login_view.login_successful.connect(
                self.show_portfolio
            )

        # -------------------------------------------------
        # START WITH LOGIN
        # -------------------------------------------------

        self.stack.setCurrentWidget(
            self.login_view
        )

    # -----------------------------------------------------
    # NAVIGATION
    # -----------------------------------------------------

    def show_portfolio(self):

        if not hasattr(self, "portfolio_view"):
            from views.portfolio_view import PortfolioView

            self.portfolio_view = PortfolioView()
            self.stack.addWidget(
                self.portfolio_view
            )

            if hasattr(
                self.portfolio_view,
                "digital_input_clicked"
            ):
                self.portfolio_view.digital_input_clicked.connect(
                    self.show_digital_input
                )

            if hasattr(
                self.portfolio_view,
                "digital_output_clicked"
            ):
                self.portfolio_view.digital_output_clicked.connect(
                    self.show_digital_output
                )

            if hasattr(
                self.portfolio_view,
                "analog_input_clicked"
            ):
                self.portfolio_view.analog_input_clicked.connect(
                    self.show_analog_input
                )

            if hasattr(
                self.portfolio_view,
                "analog_output_clicked"
            ):
                self.portfolio_view.analog_output_clicked.connect(
                    self.show_analog_output
                )

            if hasattr(
                self.portfolio_view,
                "modbus_clicked"
            ):
                self.portfolio_view.modbus_clicked.connect(
                    self.show_modbus
                )

            if hasattr(
                self.portfolio_view,
                "logout_clicked"
            ):
                self.portfolio_view.logout_clicked.connect(
                    self.show_login
                )

        self.stack.setCurrentWidget(
            self.portfolio_view
        )

    def show_login(self):

        self.login_view.username_input.clear()
        self.login_view.password_input.clear()

        self.stack.setCurrentWidget(
            self.login_view
        )

    def show_digital_input(self):

        if not hasattr(self, "digital_input_view"):
            from views.digital_input_view import DigitalInputView

            self.digital_input_view = DigitalInputView()
            self.stack.addWidget(
                self.digital_input_view
            )

            if hasattr(
                self.digital_input_view,
                "back_clicked"
            ):
                self.digital_input_view.back_clicked.connect(
                    self.show_portfolio
                )

        self.stack.setCurrentWidget(
            self.digital_input_view
        )

    def show_digital_output(self):

        if not hasattr(self, "digital_output_view"):
            from views.digital_output_view import DigitalOutputView

            self.digital_output_view = DigitalOutputView()
            self.stack.addWidget(
                self.digital_output_view
            )

            if hasattr(
                self.digital_output_view,
                "back_clicked"
            ):
                self.digital_output_view.back_clicked.connect(
                    self.show_portfolio
                )

        self.stack.setCurrentWidget(
            self.digital_output_view
        )

    def show_analog_input(self):

        if not hasattr(self, "analog_input_view"):
            from views.analog_input_view import AnalogInputView

            self.analog_input_view = AnalogInputView()
            self.stack.addWidget(
                self.analog_input_view
            )

            if hasattr(
                self.analog_input_view,
                "back_clicked"
            ):
                self.analog_input_view.back_clicked.connect(
                    self.show_portfolio
                )

            if hasattr(
                self.analog_input_view,
                "_test_mode_button"
            ):
                self.analog_input_view._test_mode_button.clicked.connect(
                    self.show_analog_input_test_mode
                )

        self.stack.setCurrentWidget(
            self.analog_input_view
        )

    def show_analog_input_test_mode(self):

        if not hasattr(self, "analog_input_test_mode_view"):
            from views.analog_input_test_mode_view import AnalogInputTestModeView

            self.analog_input_test_mode_view = AnalogInputTestModeView()
            self.stack.addWidget(
                self.analog_input_test_mode_view
            )

            self.analog_input_test_mode_view.set_connection_context(
                lambda: self.analog_input_view._serial_connection,
                lambda: self.analog_input_view._slave_id.text(),
            )

            if hasattr(
                self.analog_input_test_mode_view,
                "back_clicked"
            ):
                self.analog_input_test_mode_view.back_clicked.connect(
                    self.show_analog_input
                )

        self.stack.setCurrentWidget(
            self.analog_input_test_mode_view
        )

    def show_analog_output(self):

        if not hasattr(self, "analog_output_view"):
            from views.analog_output_view import AnalogOutputView

            self.analog_output_view = AnalogOutputView()
            self.stack.addWidget(
                self.analog_output_view
            )

            if hasattr(
                self.analog_output_view,
                "back_clicked"
            ):
                self.analog_output_view.back_clicked.connect(
                    self.show_portfolio
                )

        self.stack.setCurrentWidget(
            self.analog_output_view
        )

    def show_modbus(self):

        if not hasattr(self, "modbus_view"):
            from views.modbus_view import ModbusView

            self.modbus_view = ModbusView()
            self.stack.addWidget(
                self.modbus_view
            )

            if hasattr(
                self.modbus_view,
                "back_clicked"
            ):
                self.modbus_view.back_clicked.connect(
                    self.show_portfolio
                )

        self.stack.setCurrentWidget(
            self.modbus_view
        )


def main():

    # Windows taskbar/application identity.
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Nelumbo.Automation.ConnectivityUtilitySuite"
        )

    app = QApplication(
        sys.argv
    )

    # -------------------------------------------------
    # APPLICATION ICON
    # -------------------------------------------------

    if getattr(sys, "frozen", False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(
            os.path.abspath(__file__)
        )

    icon_path = os.path.join(
        base_path,
        "assets",
        "13.ico"
    )

    app_icon = QIcon(
        icon_path
    )

    app.setWindowIcon(
        app_icon
    )

    app.setStyle(
        "Fusion"
    )

    window = MainWindow()

    # Explicitly apply the same icon to the main window.
    window.setWindowIcon(
        app_icon
    )

    # Keep the existing default size. The window is intentionally
    # resizable/maximizable instead of fixed-size.
    screen = (
        app.primaryScreen().availableGeometry()
    )

    base_width = 1100
    base_height = 870

    width = min(
        base_width,
        screen.width()
    )

    height = min(
        base_height,
        screen.height()
    )

    window.resize(
        width,
        height
    )

    window.move(
        screen.x() + (screen.width() - window.width()) // 2,
        screen.y() + (screen.height() - window.height()) // 2
    )

    window.show()

    sys.exit(
        app.exec()
    )


if __name__ == "__main__":

    main()