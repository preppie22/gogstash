from importlib import resources

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import (
    QIcon,
    QPainter,
    QColor,
    QPixmap
)
from PySide6.QtCore import (
    Qt,
    QSize,
)
material_dark = {
    'blue': QColor('#64B5F6'),
    'green': QColor('#81C784'),
    'red': QColor('#EF5350'),
    'yellow': QColor('#FFD54F'),
    'base': QColor('#FDFDFD')
}
material_light = {
    'blue': QColor('#1E88E5'),
    'green': QColor('#43A047'),
    'red': QColor('#E53935'),
    'yellow': QColor('#F9A825'),
    'base': QColor('#020202')
}

def get_logo() -> QIcon:
    return QIcon(str(resources.files('gogstash') / 'icons' / 'gogstash.svg'))

def get_icon(icon_file: str) -> QIcon:
    color_scheme =  QApplication.instance().styleHints().colorScheme()
    color_folder = 'dark' if color_scheme == Qt.ColorScheme.Dark else 'light'
    icon_path = str(resources.files('gogstash') / 'icons' / color_folder / icon_file)
    return QIcon(icon_path)

def status_indicator(color: str = "") -> QIcon:
    color_scheme = QApplication.instance().styleHints().colorScheme()
    if color_scheme == Qt.ColorScheme.Dark:
        icon_color = material_dark.get(color, material_dark['base'])
    else:
        icon_color = material_light.get(color, material_light['base'])
    indicator = QPixmap(QSize(12,12))
    indicator.fill(Qt.GlobalColor.transparent)
    painter = QPainter(indicator)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(icon_color)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(indicator.rect())
    painter.end()
    return QIcon(indicator)
    
