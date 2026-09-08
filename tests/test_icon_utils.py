from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap

from gogstash.icon_utils import get_icon, badge_icon


def _solid_icon(color, size=24):
    pixmap = QPixmap(size, size)
    pixmap.fill(color)
    return QIcon(pixmap)


def _transparent_icon(size=24):
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    return QIcon(QPixmap.fromImage(image))


@patch("gogstash.icon_utils.QApplication")
def test_get_icon_returns_a_non_null_icon_for_light_scheme(mock_app_cls):
    mock_app_cls.instance.return_value.styleHints.return_value.colorScheme.return_value = Qt.ColorScheme.Light

    icon = get_icon("download.svg")

    assert not icon.isNull()


@patch("gogstash.icon_utils.QApplication")
def test_get_icon_returns_a_non_null_icon_for_dark_scheme(mock_app_cls):
    mock_app_cls.instance.return_value.styleHints.return_value.colorScheme.return_value = Qt.ColorScheme.Dark

    icon = get_icon("download.svg")

    assert not icon.isNull()


@patch("gogstash.icon_utils.QIcon")
@patch("gogstash.icon_utils.QApplication")
def test_get_icon_loads_from_the_dark_folder_for_dark_scheme(mock_app_cls, mock_qicon_cls):
    mock_app_cls.instance.return_value.styleHints.return_value.colorScheme.return_value = Qt.ColorScheme.Dark

    get_icon("download.svg")

    used_path = Path(mock_qicon_cls.call_args.args[0])
    assert "dark" in used_path.parts
    assert "light" not in used_path.parts


@patch("gogstash.icon_utils.QIcon")
@patch("gogstash.icon_utils.QApplication")
def test_get_icon_loads_from_the_light_folder_for_light_scheme(mock_app_cls, mock_qicon_cls):
    mock_app_cls.instance.return_value.styleHints.return_value.colorScheme.return_value = Qt.ColorScheme.Light

    get_icon("download.svg")

    used_path = Path(mock_qicon_cls.call_args.args[0])
    assert "light" in used_path.parts
    assert "dark" not in used_path.parts


def test_badge_icon_returns_the_same_icon_unchanged_when_count_is_zero():
    # Regression: badge_icon used to take an unused `color` argument and
    # would draw a badge even for an empty queue. count == 0 should be a no-op.
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
