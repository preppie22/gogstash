from importlib import resources

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import (
    QIcon,
    QPainter,
    QColor,
    QFont
)
from PySide6.QtCore import (
    Qt,
    QSize,
    QRect,
)

def get_logo() -> QIcon:
    return QIcon(str(resources.files('gogstash') / 'icons' / 'gogstash.svg'))

def get_icon(icon_file: str) -> QIcon:
    color_scheme =  QApplication.instance().styleHints().colorScheme()
    color_folder = 'dark' if color_scheme == Qt.ColorScheme.Dark else 'light'
    icon_path = str(resources.files('gogstash') / 'icons' / color_folder / icon_file)
    return QIcon(icon_path)