from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QMessageBox

from gogstash import library_db
from gogstash.download_queue import DownloadScheduler
from gogstash.download_window import Column, DownloadState, DownloadWindow, UserRole
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
    assert window.game_queue_table.item(0, Column.TITLE).text() == "Some Game"
    assert window.game_queue_table.item(0, Column.PROGRESS).text() == "0 / 2.0 GB"


def test_add_to_queue_stores_the_product_id_on_the_title_item():
    window = DownloadWindow()

    window.add_to_queue(_row(product_id=99))

    item = window.game_queue_table.item(0, Column.TITLE)
    assert item.data(UserRole.PRODUCT_ID_ROLE) == 99


def test_add_to_queue_sets_initial_progress_to_zero():
    window = DownloadWindow()

    window.add_to_queue(_row())

    assert window.game_queue_table.item(0, Column.TITLE).data(UserRole.PROGRESS_ROLE) == 0


def test_add_to_queue_selects_the_new_row():
    window = DownloadWindow()
    window.add_to_queue(_row(title="First Game", product_id=1))

    window.add_to_queue(_row(title="Second Game", product_id=2))

    assert window.game_queue_table.currentRow() == 1


def test_add_to_queue_returns_incrementing_row_index():
    window = DownloadWindow()

    first_idx = window.add_to_queue(_row(title="First Game", product_id=1))
    second_idx = window.add_to_queue(_row(title="Second Game", product_id=2))

    assert first_idx == 0
    assert second_idx == 1


def test_set_progress_updates_progress_role_data():
    window = DownloadWindow()
    window.add_to_queue(_row())

    window.set_progress(0, 42)

    assert window.game_queue_table.item(0, Column.TITLE).data(UserRole.PROGRESS_ROLE) == 42


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
    assert window.current_state == DownloadState.RUNNING


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
    assert window.current_state == DownloadState.RUNNING
    assert window.start_button.isEnabled() is False

    window._on_paused()
    assert window.current_state == DownloadState.PAUSED
    assert window.start_button.text() == "Resume Downloads"
    assert window.start_button.isEnabled() is True

    window.start_button.click()
    mock_resume.assert_called_once()
    assert window.current_state == DownloadState.RUNNING
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

    assert window.current_state == DownloadState.IDLE
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

    assert window.current_state == DownloadState.IDLE
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

    assert window.game_queue_table.item(0, Column.TITLE).data(UserRole.PROGRESS_ROLE) == 0
    assert window.game_queue_table.item(0, Column.PROGRESS).text() == "0 / 2.0 GB"


@patch("gogstash.download_window.estimate_download_size")
def test_on_game_succeeded_fills_the_row_to_one_hundred_percent(mock_estimate):
    mock_estimate.return_value = 2_000_000_000  # 2.0 GB
    window = DownloadWindow()
    window.add_to_queue(_row())

    window._on_game_succeeded(0)

    assert window.game_queue_table.item(0, Column.TITLE).data(UserRole.PROGRESS_ROLE) == 100
    assert window.game_queue_table.item(0, Column.PROGRESS).text() == "2.0 GB / 2.0 GB"
    assert window.game_queue_table.item(0, Column.PROGRESS).data(UserRole.FETCHED_SIZE) == 2_000_000_000


@patch("gogstash.download_window.estimate_download_size")
def test_on_game_failed_puts_the_reason_on_the_red_dot(mock_estimate):
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row())

    window._on_game_failed(0, "connection reset")

    assert window.game_queue_table.item(0, Column.STATUS).toolTip() == "Failed: connection reset"
    assert window.game_queue_table.item(0, Column.STATUS).data(UserRole.STATUS_ROLE) == "red"


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


@patch("gogstash.download_window.estimate_download_size")
def test_add_to_queue_wont_queue_the_same_damn_game_twice(mock_estimate):
    # Regression: nothing stopped a game from being queued twice, and with
    # concurrency 2 both copies downloaded into the same .part files at once.
    # Best case one fails its MD5, worst case both do. Now the second add just
    # points you at the row that's already there.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(title="First Game", product_id=1))
    window.add_to_queue(_row(title="Second Game", product_id=2))

    window.add_to_queue(_row(title="First Game", product_id=1))

    assert window.game_queue_table.rowCount() == 2
    assert window.game_queue_table.currentRow() == 0
    assert [j["product_id"] for j in window.scheduler.idle_queue] == [1, 2]


@patch.object(DownloadScheduler, "schedule")
@patch("gogstash.download_window.estimate_download_size")
def test_double_clicking_a_game_thats_already_downloading_doesnt_start_a_second_copy(mock_estimate, mock_schedule):
    # The mid-run version, a.k.a. the impatient double-clicker.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window.start_downloads()

    window.add_to_queue(_row(product_id=1))

    assert window.game_queue_table.rowCount() == 1
    assert [j["product_id"] for j in window.scheduler.idle_queue] == [1]


@patch("gogstash.download_window.estimate_download_size")
def test_add_to_queue_still_takes_a_different_game_after_bouncing_a_duplicate(mock_estimate):
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window.add_to_queue(_row(product_id=1))

    assert window.add_to_queue(_row(product_id=2)) == 1
    assert window.game_queue_table.rowCount() == 2


@patch("gogstash.download_window.estimate_download_size")
def test_queuing_a_game_with_nothing_to_download_doesnt_divide_by_fucking_zero(mock_estimate):
    # A Mac-only game with the filter set to Linux/Windows estimates to 0
    # bytes. As the first row in the queue, that made the overall bar divide
    # by zero and took add_to_queue down with it.
    mock_estimate.return_value = 0
    window = DownloadWindow()

    assert window.add_to_queue(_row(product_id=1)) == 0  # if this blows up, we've regressed
    assert window.progress_bar.value() == 0  # nothing to measure means nothing done, not "whatever it said before"


@patch("gogstash.download_window.estimate_download_size")
def test_adding_a_game_after_a_finish_drags_the_overall_bar_back_to_reality(mock_estimate):
    # _on_finished pins the bar at 100%. Queue another game afterwards and the
    # bar used to keep bragging about 100% until someone hit Start.
    mock_estimate.return_value = 1000
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window._on_game_succeeded(0)
    window._on_finished()
    assert window.progress_bar.value() == 100

    window.add_to_queue(_row(product_id=2))

    assert window.progress_bar.value() == 50


def _answer_dialog(button):
    # QMessageBox.exec blocks forever in a headless test run, so we answer
    # for the user. Politely.
    return patch("gogstash.download_window.QMessageBox.exec", return_value=button)


YES = QMessageBox.StandardButton.Yes
NO = QMessageBox.StandardButton.No


def _titles(window):
    return [window.game_queue_table.item(r, Column.TITLE).text() for r in range(window.game_queue_table.rowCount())]


def _status(window, row):
    return window.game_queue_table.item(row, Column.STATUS).data(UserRole.STATUS_ROLE)


@patch("gogstash.download_window.estimate_download_size")
def test_a_freshly_queued_game_gets_a_base_dot_and_a_queued_tooltip(mock_estimate):
    mock_estimate.return_value = 0
    window = DownloadWindow()

    window.add_to_queue(_row())

    assert _status(window, 0) == "base"
    assert window.game_queue_table.item(0, Column.STATUS).toolTip() == "Queued"
    assert not window.game_queue_table.item(0, Column.STATUS).icon().isNull()


@patch("gogstash.download_window.estimate_download_size")
def test_each_scheduler_signal_paints_the_dot_its_own_color(mock_estimate):
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row())

    for handler, args, color, tip in [
        (window._on_game_started, (0,), "blue", "Downloading"),
        (window._on_game_paused, (0,), "yellow", "Paused"),
        (window._on_game_stopped, (0,), "base", "Queued"),  # stopped games go right back in line
        (window._on_game_failed, (0, "nope"), "red", "Failed: nope"),
        (window._on_game_succeeded, (0,), "green", "Finished"),
    ]:
        handler(*args)
        assert _status(window, 0) == color, handler.__name__
        assert window.game_queue_table.item(0, Column.STATUS).toolTip() == tip


@patch("gogstash.download_window.estimate_download_size")
def test_a_theme_change_repaints_the_dot_without_forgetting_its_color(mock_estimate):
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row())
    window._on_game_failed(0, "nope")

    window._color_scheme_refresh()

    assert _status(window, 0) == "red"


@patch("gogstash.download_window.estimate_download_size")
def test_clearing_an_idle_queue_empties_it_but_keeps_the_headers(mock_estimate):
    # Regression: QTableWidget.clear() nuked the items AND the headers but left
    # every row standing, a table full of ghosts that crashed the next loop.
    mock_estimate.return_value = 1000
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window._on_game_succeeded(0)
    window._on_finished()

    window.clear_queue_button.click()

    assert window.game_queue_table.rowCount() == 0
    assert window.game_queue_table.horizontalHeaderItem(Column.TITLE).text() == "Title"
    assert window.scheduler.idle_queue == []
    assert window.progress_bar.value() == 0  # no more bragging about a 100% of nothing
    assert window.clear_queue_button.isEnabled() is True


@patch.object(DownloadScheduler, "stop_all")
@patch.object(DownloadScheduler, "schedule")
@patch("gogstash.download_window.estimate_download_size")
def test_clearing_mid_run_waits_for_the_stop_before_wiping_the_table(mock_estimate, mock_schedule, mock_stop):
    # The workers are still out there sending row indexes. Yank the rows
    # before they're done and every late signal lands on a None.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window.start_downloads()

    with _answer_dialog(YES):
        window.clear_queue_button.click()

    mock_stop.assert_called_once()
    assert window.game_queue_table.rowCount() == 1  # still here, stop hasn't landed
    assert window.clear_queue_button.isEnabled() is False

    window._on_stopped()

    assert window.game_queue_table.rowCount() == 0
    assert window.scheduler.idle_queue == []
    assert window.clear_queue_button.isEnabled() is True
    assert window.current_state == DownloadState.IDLE


@patch.object(DownloadScheduler, "stop_all")
@patch.object(DownloadScheduler, "schedule")
@patch("gogstash.download_window.estimate_download_size")
def test_chickening_out_of_a_mid_run_clear_changes_nothing(mock_estimate, mock_schedule, mock_stop):
    # Regression: saying No left the Clear button greyed out for eternity.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window.start_downloads()

    with _answer_dialog(NO):
        window.clear_queue_button.click()

    mock_stop.assert_not_called()
    assert window.game_queue_table.rowCount() == 1
    assert window.clear_queue_button.isEnabled() is True


@patch.object(DownloadScheduler, "stop_all")
@patch.object(DownloadScheduler, "pause_all")
@patch.object(DownloadScheduler, "schedule")
@patch("gogstash.download_window.estimate_download_size")
def test_cancelling_while_a_pause_is_landing_gives_the_clear_button_back(mock_estimate, mock_schedule, mock_pause, mock_stop):
    # Regression: pause disabled Clear and waited for _on_paused to undo it,
    # but a Cancel mid-pause means paused never fires. Clear stayed dead.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window.start_downloads()
    window.pause_downloads()
    assert window.clear_queue_button.isEnabled() is False

    window.stop_downloads()
    window._on_stopped()

    assert window.clear_queue_button.isEnabled() is True


@patch.object(DownloadScheduler, "schedule")
@patch("gogstash.download_window.estimate_download_size")
def test_a_fresh_start_doesnt_nag_about_completed_downloads_that_dont_exist(mock_estimate, mock_schedule):
    # Regression: the check was upside down, so every first Start asked to
    # remove "completed" downloads and then deleted the ones you wanted.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(title="A", product_id=1))
    window.add_to_queue(_row(title="B", product_id=2))

    with _answer_dialog(YES) as mock_exec:
        window.start_downloads()

    mock_exec.assert_not_called()
    assert _titles(window) == ["A", "B"]


@patch.object(DownloadScheduler, "schedule")
@patch("gogstash.download_window.estimate_download_size")
def test_restarting_can_drop_the_finished_games_and_the_scheduler_keeps_up(mock_estimate, mock_schedule):
    # Two regressions for the price of one: removing rows front to back
    # skipped every other one, and the scheduler kept jobs for rows that no
    # longer existed, pointing its signals at the wrong games.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    for i in range(5):
        window.add_to_queue(_row(title=f"G{i}", product_id=100 + i))
    for row in (0, 2, 4):
        window._on_game_succeeded(row)
    window._on_finished()

    with _answer_dialog(YES):
        window.start_downloads()

    assert _titles(window) == ["G1", "G3"]
    queued = [(job["row_idx"], job["product_id"]) for job in window.scheduler.idle_queue]
    assert queued == [(0, 101), (1, 103)]
    mock_schedule.assert_called_once()
    assert window.current_state == DownloadState.RUNNING


@patch.object(DownloadScheduler, "schedule")
@patch("gogstash.download_window.estimate_download_size")
def test_dropping_every_finished_game_doesnt_start_a_download_of_nothing(mock_estimate, mock_schedule):
    # Otherwise the scheduler finishes an empty queue on the spot and
    # proudly announces "Downloads complete". Complete what, exactly?
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window._on_game_succeeded(0)
    window._on_finished()

    with _answer_dialog(YES):
        window.start_downloads()

    assert window.game_queue_table.rowCount() == 0
    mock_schedule.assert_not_called()
    assert window.current_state == DownloadState.IDLE


@patch.object(DownloadScheduler, "schedule")
@patch("gogstash.download_window.estimate_download_size")
def test_keeping_finished_games_resets_the_whole_row_and_the_overall_bar_before_the_redownload(mock_estimate, mock_schedule):
    mock_estimate.return_value = 1000
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window._on_game_succeeded(0)
    window._on_finished()

    with _answer_dialog(NO):
        window.start_downloads()

    assert window.game_queue_table.rowCount() == 1
    assert _status(window, 0) == "base"
    assert window.game_queue_table.item(0, Column.TITLE).data(UserRole.PROGRESS_ROLE) == 0
    assert window.game_queue_table.item(0, Column.PROGRESS).text() == "0 / 1.0 kB"
    assert window.game_queue_table.item(0, Column.PROGRESS).data(UserRole.FETCHED_SIZE) == 0
    assert window.progress_bar.value() == 0  # not a head start of 100% on a download that hasn't happened
    assert [j["product_id"] for j in window.scheduler.idle_queue] == [1]


@patch.object(DownloadScheduler, "resume_all")
@patch.object(DownloadScheduler, "pause_all")
@patch.object(DownloadScheduler, "schedule")
@patch("gogstash.download_window.estimate_download_size")
def test_resuming_never_offers_to_remove_rows_out_from_under_the_scheduler(mock_estimate, mock_schedule, mock_pause, mock_resume):
    # A game can finish right before the pause lands. Removing its row on
    # resume would shift the row indexes the paused jobs are still holding.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(title="A", product_id=1))
    window.add_to_queue(_row(title="B", product_id=2))
    window.start_downloads()
    window.pause_downloads()
    window._on_game_succeeded(0)
    window._on_paused()

    with _answer_dialog(YES) as mock_exec:
        window.start_downloads()

    mock_exec.assert_not_called()
    assert _titles(window) == ["A", "B"]
    mock_resume.assert_called_once()


@patch("gogstash.download_window.estimate_download_size")
def test_a_failed_game_drops_its_half_download_from_the_overall_bar(mock_estimate):
    # The partial file is gone or useless, so counting it as progress is
    # just lying to the user with extra steps.
    mock_estimate.return_value = 1000
    window = DownloadWindow()
    window.add_to_queue(_row())
    window._on_progress(0, 600, 1000)

    window._on_game_failed(0, "nope")

    assert window.game_queue_table.item(0, Column.PROGRESS).data(UserRole.FETCHED_SIZE) == 0
    assert window.game_queue_table.item(0, Column.PROGRESS).text() == "0 / 1.0 kB"


@patch.object(DownloadScheduler, "schedule")
@patch("gogstash.download_window.estimate_download_size")
def test_restarting_puts_failed_games_back_in_line_without_asking(mock_estimate, mock_schedule):
    # Red rows aren't "completed", so no prompt. They just get their dot
    # scrubbed and try again.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window._on_game_failed(0, "nope")
    window._on_finished()

    with _answer_dialog(YES) as mock_exec:
        window.start_downloads()

    mock_exec.assert_not_called()
    assert _status(window, 0) == "base"
    assert window.game_queue_table.item(0, Column.STATUS).toolTip() == "Queued"


@patch("gogstash.download_window.estimate_download_size")
def test_finishing_with_failures_owns_up_to_them(mock_estimate):
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window.add_to_queue(_row(product_id=2))
    window._on_game_succeeded(0)
    window._on_game_failed(1, "nope")

    window._on_finished()

    assert window.downloads_status.text() == "Finished with 1 failure"


@patch("gogstash.download_window.estimate_download_size")
def test_finishing_with_several_failures_gets_the_plural_it_deserves(mock_estimate):
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window.add_to_queue(_row(product_id=2))
    window._on_game_failed(0, "nope")
    window._on_game_failed(1, "also nope")

    window._on_finished()

    assert window.downloads_status.text() == "Finished with 2 failures"


@patch("gogstash.download_window.estimate_download_size")
def test_a_clean_finish_still_says_complete(mock_estimate):
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window._on_game_succeeded(0)

    window._on_finished()

    assert window.downloads_status.text() == "Downloads complete"


@patch.object(DownloadScheduler, "schedule")
@patch("gogstash.download_window.estimate_download_size")
def test_the_leftover_ready_timer_doesnt_stomp_on_a_new_run(mock_estimate, mock_schedule):
    # Regression: finish, hit Start within five seconds, and the old timer
    # cheerfully announced "Ready!" over an active download.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window.start_downloads()

    window._reset_status()  # the timer firing late

    assert window.downloads_status.text() == "Downloading..."
