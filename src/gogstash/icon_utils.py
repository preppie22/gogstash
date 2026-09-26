"""Icon helpers that follow the application's light or dark color scheme.

Attributes:
    material_dark (dict[str, QColor]): Status dot colors for dark mode.
    material_light (dict[str, QColor]): Status dot colors for light mode.
"""

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
    """Return the GogStash application icon.

    Returns:
        QIcon: The application logo.
    """
    return QIcon(str(resources.files('gogstash') / 'icons' / 'gogstash.svg'))

def get_icon(icon_file: str) -> QIcon:
    """Load an icon matching the current color scheme.

    Args:
        icon_file (str): File name of the icon inside ``icons/dark`` or
            ``icons/light``.

    Returns:
        QIcon: The icon for the active color scheme.
    """
    color_scheme =  QApplication.instance().styleHints().colorScheme()
    color_folder = 'dark' if color_scheme == Qt.ColorScheme.Dark else 'light'
    icon_path = str(resources.files('gogstash') / 'icons' / color_folder / icon_file)
    return QIcon(icon_path)

def status_indicator(color: str = "") -> QIcon:
    """Draw a filled circle used as a status dot.

    Args:
        color (str): One of ``'blue'``, ``'green'``, ``'red'`` or
            ``'yellow'``. Any other value uses the neutral ``'base'``
            color.

    Returns:
        QIcon: A 12x12 dot in the palette of the current color scheme.
    """
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
    
