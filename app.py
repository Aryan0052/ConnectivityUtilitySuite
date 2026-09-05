import os
import sys

# Keep the existing UI scaling exactly as it is.
os.environ["QT_SCALE_FACTOR"] = "0.72"

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QStackedWidget,
)

from views.login_view import LoginView
from views.portfolio_view import PortfolioView
from views.digital_input_view import DigitalInputView
from views.digital_output_view import DigitalOutputView
from views.analog_input_view import AnalogInputView
from views.analog_output_view import AnalogOutputView
from views.modbus_view import ModbusView


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle(
            "Connectivity Utility Suite"
        )

        # Fixed application size.
        self.setFixedSize(
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

        self.login_view = LoginView()

        self.portfolio_view = PortfolioView()

        self.digital_input_view = DigitalInputView()

        self.digital_output_view = DigitalOutputView()

        self.analog_input_view = AnalogInputView()

        self.analog_output_view = AnalogOutputView()

        self.modbus_view = ModbusView()

        # -------------------------------------------------
        # ADD VIEWS TO STACK
        # -------------------------------------------------

        self.stack.addWidget(
            self.login_view
        )

        self.stack.addWidget(
            self.portfolio_view
        )

        self.stack.addWidget(
            self.digital_input_view
        )

        self.stack.addWidget(
            self.digital_output_view
        )

        self.stack.addWidget(
            self.analog_input_view
        )

        self.stack.addWidget(
            self.analog_output_view
        )

        self.stack.addWidget(
            self.modbus_view
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
        # PORTFOLIO -> DIGITAL INPUT
        # -------------------------------------------------

        if hasattr(
            self.portfolio_view,
            "digital_input_clicked"
        ):
            self.portfolio_view.digital_input_clicked.connect(
                self.show_digital_input
            )

        # -------------------------------------------------
        # PORTFOLIO -> DIGITAL OUTPUT
        # -------------------------------------------------

        if hasattr(
            self.portfolio_view,
            "digital_output_clicked"
        ):
            self.portfolio_view.digital_output_clicked.connect(
                self.show_digital_output
            )

        # -------------------------------------------------
        # PORTFOLIO -> ANALOG INPUT
        # -------------------------------------------------

        if hasattr(
            self.portfolio_view,
            "analog_input_clicked"
        ):
            self.portfolio_view.analog_input_clicked.connect(
                self.show_analog_input
            )

        # -------------------------------------------------
        # PORTFOLIO -> ANALOG OUTPUT
        # -------------------------------------------------

        if hasattr(
            self.portfolio_view,
            "analog_output_clicked"
        ):
            self.portfolio_view.analog_output_clicked.connect(
                self.show_analog_output
            )

        # -------------------------------------------------
        # PORTFOLIO -> MODBUS RTU & TCP/IP
        # -------------------------------------------------

        if hasattr(
            self.portfolio_view,
            "modbus_clicked"
        ):
            self.portfolio_view.modbus_clicked.connect(
                self.show_modbus
            )

        # -------------------------------------------------
        # DIGITAL INPUT -> PORTFOLIO
        # -------------------------------------------------

        if hasattr(
            self.digital_input_view,
            "back_clicked"
        ):
            self.digital_input_view.back_clicked.connect(
                self.show_portfolio
            )

        # -------------------------------------------------
        # DIGITAL OUTPUT -> PORTFOLIO
        # -------------------------------------------------

        if hasattr(
            self.digital_output_view,
            "back_clicked"
        ):
            self.digital_output_view.back_clicked.connect(
                self.show_portfolio
            )

        # -------------------------------------------------
        # ANALOG INPUT -> PORTFOLIO
        # -------------------------------------------------

        if hasattr(
            self.analog_input_view,
            "back_clicked"
        ):
            self.analog_input_view.back_clicked.connect(
                self.show_portfolio
            )

        # -------------------------------------------------
        # ANALOG OUTPUT -> PORTFOLIO
        # -------------------------------------------------

        if hasattr(
            self.analog_output_view,
            "back_clicked"
        ):
            self.analog_output_view.back_clicked.connect(
                self.show_portfolio
            )

        # -------------------------------------------------
        # MODBUS -> PORTFOLIO
        # -------------------------------------------------

        if hasattr(
            self.modbus_view,
            "back_clicked"
        ):
            self.modbus_view.back_clicked.connect(
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

        self.stack.setCurrentWidget(
            self.portfolio_view
        )

    def show_digital_input(self):

        self.stack.setCurrentWidget(
            self.digital_input_view
        )

    def show_digital_output(self):

        self.stack.setCurrentWidget(
            self.digital_output_view
        )

    def show_analog_input(self):

        self.stack.setCurrentWidget(
            self.analog_input_view
        )

    def show_analog_output(self):

        self.stack.setCurrentWidget(
            self.analog_output_view
        )

    def show_modbus(self):

        self.stack.setCurrentWidget(
            self.modbus_view
        )


def main():

    app = QApplication(
        sys.argv
    )

    app.setStyle(
        "Fusion"
    )

    window = MainWindow()

    # -------------------------------------------------
    # CENTER APPLICATION
    # -------------------------------------------------

    screen = (
        app.primaryScreen()
        .availableGeometry()
    )

    x = (
        screen.x()
        + (
            screen.width()
            - window.width() * 0.72
        ) // 2
    )

    y = (
        screen.y()
        + (
            screen.height()
            - window.height() * 0.72
        ) // 2
    )

    window.move(
        int(x),
        int(y)
    )

    window.show()

    sys.exit(
        app.exec()
    )


if __name__ == "__main__":

    main()