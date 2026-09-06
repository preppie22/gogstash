from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap

from gogstash.icon_utils import get_icon, color_icon, badge_icon


def _solid_icon(color, size=24):
    pixmap = QPixmap(size, size)
    pixmap.fill(color)
    return QIcon(pixmap)


def _transparent_icon(size=24):
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    return QIcon(QPixmap.fromImage(image))


def test_get_icon_returns_a_path_that_exists():
    path = get_icon("download.svg")

    assert path.endswith("download.svg")
    assert Path(path).is_file()


def test_color_icon_recolors_opaque_pixels_to_the_target_color():
    icon = _solid_icon(QColor("blue"))

    recolored = color_icon(icon, QColor("red"))

    pixel = recolored.pixmap(QSize(24, 24)).toImage().pixelColor(12, 12)
    assert pixel == QColor("red")


def test_color_icon_preserves_transparency():
    icon = _transparent_icon()

    recolored = color_icon(icon, QColor("red"))

    pixel = recolored.pixmap(QSize(24, 24)).toImage().pixelColor(12, 12)
    assert pixel.alpha() == 0


def test_badge_icon_returns_the_same_icon_unchanged_when_count_is_zero():
    # Regression: badge_icon used to take an unused `color` argument and always
    # draw a badge even for an empty queue; count == 0 should be a no-op.
    icon = _solid_icon(QColor("blue"))

    result = badge_icon(icon, 0)

    assert result is icon


def test_badge_icon_draws_something_in_the_corner_when_count_is_positive():
    icon = _transparent_icon()
    before = icon.pixmap(QSize(24, 24)).toImage().pixelColor(17, 17)

    badged = badge_icon(icon, 3)

    after = badged.pixmap(QSize(24, 24)).toImage().pixelColor(17, 17)
    assert before.alpha() == 0
    assert after.alpha() > 0
