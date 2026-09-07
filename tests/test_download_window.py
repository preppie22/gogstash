from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap

from gogstash.download_window import DownloadWindow, UserRole


def _non_null_icon():
    # A plain QIcon() is null, and _color_scheme_refresh's "skip icon-less
    # entries" guard would then treat every recolored button as icon-less too.
    return QIcon(QPixmap(4, 4))


def _row(title="Some Game", size="2 GB", product_id=42):
    return {"title": title, "size": size, "product_id": product_id}


@patch("gogstash.download_window.estimate_download_size")
def test_add_to_queue_inserts_row_with_title_and_size(mock_estimate):
    mock_estimate.return_value = 2_000_000_000  # 2.0 GB
    window = DownloadWindow()

    window.add_to_queue(_row(title="Some Game"))

    assert window.game_queue_table.rowCount() == 1
    assert window.game_queue_table.item(0, 0).text() == "Some Game"
    assert window.game_queue_table.item(0, 1).text() == "0 / 2.0 GB"


def test_add_to_queue_stores_the_product_id_on_the_title_item():
    window = DownloadWindow()

    window.add_to_queue(_row(product_id=99))

    item = window.game_queue_table.item(0, 0)
    assert item.data(UserRole.PRODUCT_ID_ROLE.value) == 99


def test_add_to_queue_sets_initial_progress_to_zero():
    window = DownloadWindow()

    window.add_to_queue(_row())

    assert window.game_queue_table.item(0, 0).data(UserRole.PROGRESS_ROLE.value) == 0


def test_add_to_queue_selects_the_new_row():
    window = DownloadWindow()
    window.add_to_queue(_row(title="First Game"))

    window.add_to_queue(_row(title="Second Game"))

    assert window.game_queue_table.currentRow() == 1


def test_add_to_queue_returns_incrementing_row_index():
    window = DownloadWindow()

    first_idx = window.add_to_queue(_row(title="First Game"))
    second_idx = window.add_to_queue(_row(title="Second Game"))

    assert first_idx == 0
    assert second_idx == 1


def test_add_to_queue_emits_queue_changed_with_new_count():
    window = DownloadWindow()
    received = []
    window.queue_changed.connect(lambda count: received.append(count))

    window.add_to_queue(_row(title="First Game"))
    window.add_to_queue(_row(title="Second Game"))

    assert received == [1, 2]


def test_set_progress_updates_progress_role_data():
    window = DownloadWindow()
    window.add_to_queue(_row())

    window.set_progress(0, 42)

    assert window.game_queue_table.item(0, 0).data(UserRole.PROGRESS_ROLE.value) == 42


@patch("gogstash.download_window.get_icon")
def test_color_scheme_refresh_reloads_each_button_from_its_own_icon_file(mock_get_icon):
    mock_get_icon.return_value = _non_null_icon()
    window = DownloadWindow()
    mock_get_icon.reset_mock()

    window._color_scheme_refresh()

    called_files = {call.args[0] for call in mock_get_icon.call_args_list}
    assert called_files == {"trash.svg", "start_download.svg", "stop.svg"}


@patch("gogstash.download_window.get_icon")
def test_color_scheme_refresh_sets_the_reloaded_icon_on_each_button(mock_get_icon):
    mock_get_icon.return_value = _non_null_icon()
    window = DownloadWindow()
    mock_get_icon.reset_mock()
    mock_get_icon.return_value = _non_null_icon()  # a fresh, distinct icon to detect the swap

    window._color_scheme_refresh()

    for button in window.dialog_buttons.buttons():
        assert button.icon().cacheKey() == mock_get_icon.return_value.cacheKey()
