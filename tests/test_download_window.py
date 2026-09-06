from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap

from gogstash.download_window import DownloadWindow, PROGRESS_ROLE


def _non_null_icon():
    # A plain QIcon() is null, and _color_scheme_refresh's "skip icon-less
    # entries" guard would then treat every recolored button as icon-less too.
    return QIcon(QPixmap(4, 4))


def test_add_to_queue_inserts_row_with_title_and_placeholder_size():
    window = DownloadWindow()

    window.add_to_queue("Some Game")

    assert window.game_queue_table.rowCount() == 1
    assert window.game_queue_table.item(0, 0).text() == "Some Game"
    assert window.game_queue_table.item(0, 1).text() == "N/A"


def test_add_to_queue_sets_initial_progress_to_zero():
    window = DownloadWindow()

    window.add_to_queue("Some Game")

    assert window.game_queue_table.item(0, 0).data(PROGRESS_ROLE) == 0


def test_add_to_queue_selects_the_new_row():
    window = DownloadWindow()
    window.add_to_queue("First Game")

    window.add_to_queue("Second Game")

    assert window.game_queue_table.currentRow() == 1


def test_add_to_queue_returns_incrementing_row_index():
    window = DownloadWindow()

    first_idx = window.add_to_queue("First Game")
    second_idx = window.add_to_queue("Second Game")

    assert first_idx == 0
    assert second_idx == 1


def test_add_to_queue_emits_queue_changed_with_new_count():
    window = DownloadWindow()
    received = []
    window.queue_changed.connect(lambda count: received.append(count))

    window.add_to_queue("First Game")
    window.add_to_queue("Second Game")

    assert received == [1, 2]


def test_set_progress_updates_progress_role_data():
    window = DownloadWindow()
    window.add_to_queue("Some Game")

    window.set_progress(0, 42)

    assert window.game_queue_table.item(0, 0).data(PROGRESS_ROLE) == 42


@patch("gogstash.download_window.color_icon")
def test_color_scheme_refresh_recolors_buttons_black_for_light_scheme(mock_color_icon):
    mock_color_icon.return_value = _non_null_icon()
    window = DownloadWindow()
    mock_color_icon.reset_mock()

    window._color_scheme_refresh(Qt.ColorScheme.Light)

    assert mock_color_icon.call_count == 3  # clear_queue, start_pause, stop buttons
    for call in mock_color_icon.call_args_list:
        assert call.args[1] == QColor(Qt.GlobalColor.black)


@patch("gogstash.download_window.color_icon")
def test_color_scheme_refresh_recolors_buttons_white_for_dark_scheme(mock_color_icon):
    mock_color_icon.return_value = _non_null_icon()
    window = DownloadWindow()
    mock_color_icon.reset_mock()

    window._color_scheme_refresh(Qt.ColorScheme.Dark)

    assert mock_color_icon.call_count == 3
    for call in mock_color_icon.call_args_list:
        assert call.args[1] == QColor(Qt.GlobalColor.white)
