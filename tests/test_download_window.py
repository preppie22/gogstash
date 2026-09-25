from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap

from gogstash import library_db
from gogstash.download_queue import DownloadScheduler
from gogstash.download_window import DownloadWindow, UserRole
from gogstash.settings import update_setting

FAKE_PRODUCT = {
    "id": 42,
    "title": "Some Game",
    "slug": "some-game",
    "isMovie": False,
    "url": "/en/game/some_game",
    "image": "//images.example.com/some_game",
    "worksOn": {"Windows": True, "Linux": False, "Mac": True},
}


@pytest.fixture(autouse=True)
def db():
    library_db._create_db(force=True)
    library_db.update_products([FAKE_PRODUCT])


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


@patch.object(DownloadScheduler, "schedule")
@patch("gogstash.download_window.estimate_download_size")
def test_start_downloads_hands_the_queued_rows_and_concurrency_to_the_scheduler(mock_estimate, mock_schedule):
    # The scheduler now lives as long as the window does, and rows get
    # enqueued the moment they're added. Start just sets the concurrency and
    # kicks the thing, no more rebuilding the whole shebang from the table.
    mock_estimate.return_value = 0
    update_setting("download_concurrency", 3)
    window = DownloadWindow()
    window.add_to_queue(_row(title="First Game", product_id=1))
    window.add_to_queue(_row(title="Second Game", product_id=2))

    window.start_downloads()

    queued = [(job["row_idx"], job["product_id"]) for job in window.scheduler.idle_queue]
    assert queued == [(0, 1), (1, 2)]
    assert window.scheduler.max_tokens == 3
    mock_schedule.assert_called_once()
    assert window.current_state == DownloadWindow.DownloadState.RUNNING


@patch.object(DownloadScheduler, "schedule")
@patch("gogstash.download_window.estimate_download_size")
def test_start_turns_the_button_into_pause_and_keeps_the_icon_bookkeeping_on_the_right_button(mock_estimate, mock_schedule):
    # Regression: the pause icon's name got slapped onto the *stop* button,
    # so the next theme change handed Cancel a fucking pause icon.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row())

    window.start_downloads()

    assert window.start_button.text() == "Pause Downloads"
    assert window.start_button.isEnabled() is True
    assert window.start_button.property("iconFile") == "pause.svg"
    assert window.stop_button.property("iconFile") == "stop.svg"


@patch.object(DownloadScheduler, "resume_all")
@patch.object(DownloadScheduler, "pause_all")
@patch.object(DownloadScheduler, "schedule")
@patch("gogstash.download_window.estimate_download_size")
def test_start_button_walks_through_start_pause_resume(mock_estimate, mock_schedule, mock_pause, mock_resume):
    # One button, three jobs, zero raises. The overworked intern of
    # QPushButtons.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row())

    window.start_button.click()
    mock_schedule.assert_called_once()

    window.start_button.click()
    mock_pause.assert_called_once()
    # Still RUNNING until the workers actually stop. The button chills tf
    # out so nobody can spam their way into resuming a pause that
    # hasn't even happened yet.
    assert window.current_state == DownloadWindow.DownloadState.RUNNING
    assert window.start_button.isEnabled() is False

    window._on_paused()
    assert window.current_state == DownloadWindow.DownloadState.PAUSED
    assert window.start_button.text() == "Resume Downloads"
    assert window.start_button.isEnabled() is True

    window.start_button.click()
    mock_resume.assert_called_once()
    assert window.current_state == DownloadWindow.DownloadState.RUNNING
    assert window.start_button.text() == "Pause Downloads"


@patch("gogstash.download_window.DownloadScheduler")
@patch("gogstash.download_window.estimate_download_size")
def test_start_downloads_does_not_require_a_stored_token(mock_estimate, mock_scheduler_cls):
    # Regression: this used to puke ValueError("Invalid
    # access token") the moment nothing was on disk. Not this window's
    # problem anymore, the worker threads sort out their own tokens now.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row())

    window.start_downloads()  # if this blows up, we've regressed

    mock_scheduler_cls.assert_called_once()


def test_stop_downloads_does_not_crash_without_a_scheduler():
    # Regression: stop_downloads() used to call self.scheduler.stop_all() no
    # questions asked, a great way to raise AttributeError if Stop gets
    # clicked before Start ever ran, or after a previous stop already
    # jacked the scheduler back to None.
    window = DownloadWindow()

    window.stop_downloads()  # must not raise


@patch.object(DownloadScheduler, "schedule")
@patch("gogstash.download_window.estimate_download_size")
def test_on_stopped_puts_everything_back_like_start_was_never_clicked(mock_estimate, mock_schedule):
    # Regression: _on_stopped() once forgot to re-enable the start button, and
    # later tried to iterate over rowCount() itself, which is an int, you
    # absolute walnut. Cancel means square one: fresh scheduler, every row
    # queued again.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(title="First Game", product_id=1))
    window.add_to_queue(_row(title="Second Game", product_id=2))
    window.start_downloads()
    old_scheduler = window.scheduler

    window._on_stopped()

    assert window.current_state == DownloadWindow.DownloadState.IDLE
    assert window.start_button.isEnabled() is True
    assert window.start_button.text() == "Start Downloads"
    assert window.start_button.property("iconFile") == "start_download.svg"
    assert window.scheduler is not old_scheduler
    queued = [(job["row_idx"], job["product_id"]) for job in window.scheduler.idle_queue]
    assert queued == [(0, 1), (1, 2)]


@patch.object(DownloadScheduler, "schedule")
@patch("gogstash.download_window.estimate_download_size")
def test_on_finished_resets_the_button_and_requeues_every_row(mock_estimate, mock_schedule):
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(title="First Game", product_id=1))
    window.start_downloads()

    window._on_finished()

    assert window.current_state == DownloadWindow.DownloadState.IDLE
    assert window.start_button.isEnabled() is True
    assert window.start_button.text() == "Start Downloads"
    queued = [(job["row_idx"], job["product_id"]) for job in window.scheduler.idle_queue]
    assert queued == [(0, 1)]


@patch("gogstash.download_window.estimate_download_size")
def test_on_game_stopped_resets_row_progress_and_size_text(mock_estimate):
    mock_estimate.return_value = 2_000_000_000  # 2.0 GB
    window = DownloadWindow()
    window.add_to_queue(_row())
    window.set_progress(0, 55)

    window._on_game_stopped(0)

    assert window.game_queue_table.item(0, 0).data(UserRole.PROGRESS_ROLE.value) == 0
    assert window.game_queue_table.item(0, 1).text() == "0 / 2.0 GB"


@patch("gogstash.download_window.estimate_download_size")
def test_on_game_succeeded_fills_the_row_to_one_hundred_percent(mock_estimate):
    mock_estimate.return_value = 2_000_000_000  # 2.0 GB
    window = DownloadWindow()
    window.add_to_queue(_row())

    window._on_game_succeeded(0)

    assert window.game_queue_table.item(0, 0).data(UserRole.PROGRESS_ROLE.value) == 100
    assert window.game_queue_table.item(0, 1).text() == "2.0 GB / 2.0 GB"
    assert window.game_queue_table.item(0, 1).data(UserRole.FETCHED_SIZE.value) == 2_000_000_000


@patch("gogstash.download_window.estimate_download_size")
def test_on_game_failed_puts_the_reason_in_the_row_tooltip(mock_estimate):
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row())

    window._on_game_failed(0, "connection reset")

    assert window.game_queue_table.item(0, 0).toolTip() == "connection reset"


@patch.object(DownloadScheduler, "pause_all")
@patch.object(DownloadScheduler, "schedule")
@patch("gogstash.download_window.estimate_download_size")
def test_add_to_queue_says_hell_no_while_a_pause_is_landing(mock_estimate, mock_schedule, mock_pause):
    # Workers are mid-pause and the button is disabled. Shoving a new game in
    # right now gets you a -1 and jack shit else: no row, no scheduler entry.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window.start_button.click()
    window.start_button.click()  # pause, still waiting on the workers

    assert window.add_to_queue(_row(product_id=2)) == -1
    assert window.game_queue_table.rowCount() == 1
    assert [j["product_id"] for j in window.scheduler.idle_queue] == [1]


@patch.object(DownloadScheduler, "stop_all")
@patch.object(DownloadScheduler, "schedule")
@patch("gogstash.download_window.estimate_download_size")
def test_add_to_queue_says_hell_no_while_a_stop_is_landing(mock_estimate, mock_schedule, mock_stop):
    # Same deal mid-Cancel. Without this, a game added right then got
    # dispatched and held the whole stop hostage until it finished.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window.start_downloads()
    window.stop_downloads()

    assert window.add_to_queue(_row(product_id=2)) == -1
    assert window.game_queue_table.rowCount() == 1


@patch.object(DownloadScheduler, "schedule")
@patch("gogstash.download_window.estimate_download_size")
def test_add_to_queue_still_works_while_downloads_are_running(mock_estimate, mock_schedule):
    # The -1 bouncer only works the pause/stop door. Mid-run adds are fine.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window.start_downloads()

    assert window.add_to_queue(_row(product_id=2)) == 1
    assert window.game_queue_table.rowCount() == 2
