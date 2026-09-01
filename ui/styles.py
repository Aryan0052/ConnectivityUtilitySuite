from __future__ import annotations

from PySide6.QtGui import QColor, QLinearGradient
from PySide6.QtWidgets import QWidget


PANEL_BORDER = "#12C92A"
INPUT_BACKGROUND = "#D9E2DF"
INPUT_BORDER = "#E8EEEE"
LOGIN_GREEN = "#16D322"
TEXT_COLOR = "#111111"


def apply_login_panel_gradient(widget: QWidget) -> None:
    gradient = QLinearGradient(0, 0, 1, 1)
    gradient.setCoordinateMode(QLinearGradient.ObjectBoundingMode)
    gradient.setColorAt(0.0, QColor("#10A9B8"))
    gradient.setColorAt(0.45, QColor("#087EA9"))
    gradient.setColorAt(1.0, QColor("#15558F"))

    widget.setStyleSheet(
        f"""
        QWidget#loginPanel {{
            background: qlineargradient(
                x1: 0, y1: 0,
                x2: 1, y2: 1,
                stop: 0 #10A9B8,
                stop: 0.45 #087EA9,
                stop: 1 #15558F
            );
            border: 2px solid {PANEL_BORDER};
            border-radius: 26px;
        }}
        """
    )


LOGIN_INPUT_STYLE = f"""
QLineEdit {{
    background: {INPUT_BACKGROUND};
    color: {TEXT_COLOR};
    border: 2px solid {INPUT_BORDER};
    border-radius: 16px;
    padding-left: 58px;
    padding-right: 18px;
    font-family: Georgia, "Times New Roman", serif;
    font-size: 25px;
}}

QLineEdit:focus {{
    border: 2px solid #FFFFFF;
}}
"""


LOGIN_BUTTON_STYLE = f"""
QPushButton {{
    background: {LOGIN_GREEN};
    color: white;
    border: 2px solid #A8F2A8;
    border-radius: 15px;
    font-family: Georgia, "Times New Roman", serif;
    font-size: 25px;
    font-weight: bold;
}}

QPushButton:hover {{
    background: #18D927;
}}

QPushButton:pressed {{
    background: #12BC20;
}}
"""
