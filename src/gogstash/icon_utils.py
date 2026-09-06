from importlib import resources
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


def get_icon(icon_file: str) -> str:
    resources.files('gogstash')
    return str(resources.files('gogstash') / 'icons' / icon_file)

def color_icon(icon: QIcon, color: QColor) -> QIcon:
    base = icon.pixmap(QSize(24, 24))
    with QPainter(base) as painter:
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(base.rect(), color)
    return QIcon(base)

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