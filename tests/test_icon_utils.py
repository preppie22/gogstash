from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt

from gogstash.icon_utils import get_icon


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
