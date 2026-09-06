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

def get_icon(icon_file: str) -> QIcon:
    color_scheme =  QApplication.instance().styleHints().colorScheme()
    color_folder = 'dark' if color_scheme == Qt.ColorScheme.Dark else 'light'
    icon_path = str(resources.files('gogstash') / 'icons' / color_folder / icon_file)
    return QIcon(icon_path)

def badge_icon(icon: QIcon, count: int) -> QIcon:
    if count == 0: return icon
    base = icon.pixmap(QSize(24,24))
    with QPainter(base) as painter:
        painter.setBrush(QColor(Qt.GlobalColor.red))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(12, 12, 11, 11)
        painter.setPen(QColor(Qt.GlobalColor.white))
        painter.setFont(QFont(painter.font().family(), 7))
        painter.drawText(QRect(13, 13, 10, 10),
                        Qt.AlignmentFlag.AlignCenter,
                        str(count))
    return QIcon(base)