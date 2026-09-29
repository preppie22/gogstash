from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtCore import QSize, Qt

from gogstash.icon_utils import get_icon, material_dark, material_light, status_indicator


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


# --- status_indicator ---

STATES = ["base", "blue", "green", "red", "yellow"]


def draw_indicator(mock_app_cls, scheme, state):
    mock_app_cls.instance.return_value.styleHints.return_value.colorScheme.return_value = scheme
    return status_indicator(state).pixmap(QSize(16, 16)).toImage()


def shape_of(image):
    # Only where paint landed, never what color it is. This is what a
    # colour-blind user (or a greyscale screenshot) gets to work with.
    return {(x, y) for x in range(image.width()) for y in range(image.height()) if image.pixelColor(x, y).alpha() > 128}


@pytest.mark.parametrize("scheme", [Qt.ColorScheme.Light, Qt.ColorScheme.Dark])
@pytest.mark.parametrize("state", STATES + ["mystery"])
@patch("gogstash.icon_utils.QApplication")
def test_status_indicator_paints_something_for_every_state(mock_app_cls, state, scheme):
    # A shape that throws halfway through painting takes the whole app down
    # with it (a QPainter that never ends is a segfault waiting to happen),
    # so every state has to make it to the finish line in both schemes.
    image = draw_indicator(mock_app_cls, scheme, state)

    assert image.size() == QSize(16, 16)
    assert len(shape_of(image)) > 10


@patch("gogstash.icon_utils.QApplication")
def test_every_state_has_its_own_shape_regardless_of_color(mock_app_cls):
    shapes = {state: shape_of(draw_indicator(mock_app_cls, Qt.ColorScheme.Dark, state)) for state in STATES}

    for i, first in enumerate(STATES):
        for second in STATES[i + 1:]:
            assert shapes[first] != shapes[second], f"{first} and {second} are the same shape"


@patch("gogstash.icon_utils.QApplication")
def test_unknown_state_falls_back_to_the_queued_ring(mock_app_cls):
    ring = draw_indicator(mock_app_cls, Qt.ColorScheme.Dark, "base")

    assert draw_indicator(mock_app_cls, Qt.ColorScheme.Dark, "mystery") == ring
    assert draw_indicator(mock_app_cls, Qt.ColorScheme.Dark, "") == ring


@pytest.mark.parametrize("state", STATES)
@patch("gogstash.icon_utils.QApplication")
def test_status_indicator_uses_the_palette_of_the_active_scheme(mock_app_cls, state):
    for scheme, palette in [(Qt.ColorScheme.Dark, material_dark), (Qt.ColorScheme.Light, material_light)]:
        image = draw_indicator(mock_app_cls, scheme, state)
        drawn = {image.pixelColor(x, y).rgb() for x, y in shape_of(image) if image.pixelColor(x, y).alpha() == 255}

        # The middle of a stroke is fully opaque and exactly the palette color.
        assert palette[state].rgb() in drawn


@patch("gogstash.icon_utils.QApplication")
def test_status_indicator_looks_different_in_dark_and_light(mock_app_cls):
    # Blue on purpose: green and red happen to be the same in both schemes,
    # which makes for a very boring comparison.
    dark = draw_indicator(mock_app_cls, Qt.ColorScheme.Dark, "blue")
    light = draw_indicator(mock_app_cls, Qt.ColorScheme.Light, "blue")

    assert dark != light
