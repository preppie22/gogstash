from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QItemSelectionModel, QObject, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QTreeWidget

from gogstash import library_db
from gogstash.download_queue import DownloadScheduler
from gogstash.download_window import Column, DownloadState, DownloadWindow, StatusDelegate, UserRole
from gogstash.settings import update_setting
from tests.fakes import gog_product

FAKE_PRODUCT = gog_product(42, "Some Game", "some-game")


@pytest.fixture(autouse=True)
def db():
    library_db._create_db(force=True)
    library_db.update_cache([FAKE_PRODUCT])


class SizedDownloadList:
    """Stands in for generate_download_list, since the queue's sizes now come
    from enqueue() adding up the game's file list. Every game is one file of
    `return_value` bytes, so tests can keep saying how big a game is the same
    way they used to."""

    def __init__(self):
        self.return_value = 0

    def __call__(self, product_ids):
        return [{
            "directory": "installer_windows_en", "category": "installers", "file": f"file_{pid}",
            "os": "windows", "size": self.return_value, "downlink": f"https://example.com/{pid}",
        } for pid in product_ids]


def sized_downloads():
    return patch("gogstash.download_queue.generate_download_list", new_callable=SizedDownloadList)


@pytest.fixture(autouse=True)
def default_download_sizes():
    # Tests that don't care how big anything is still shouldn't go digging
    # through the DB and manifests for games that only exist as product ids.
    with sized_downloads():
        yield


def _non_null_icon():
    # A plain QIcon() is null, and _color_scheme_refresh's "skip icon-less
    # entries" guard would then treat every recolored button as icon-less too.
    return QIcon(QPixmap(4, 4))


def _row(title="Some Game", size="2 GB", product_id=42):
    return {"title": title, "size": size, "product_id": product_id}


@sized_downloads()
def test_add_to_queue_inserts_row_with_title_and_size(mock_estimate):
    mock_estimate.return_value = 2_000_000_000  # 2.0 GB
    window = DownloadWindow()

    window.add_to_queue(_row(title="Some Game"))

    assert window.game_queue_table.rowCount() == 1
    assert window.game_queue_table.item(0, Column.TITLE).text() == "Some Game"
    assert window.game_queue_table.item(0, Column.PROGRESS).text() == "0 Bytes / 2.0 GB"


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
    window.add_to_queue(_row(product_id=7))

    window.set_progress(7, 42)

    assert window.game_queue_table.item(0, Column.TITLE).data(UserRole.PROGRESS_ROLE) == 42


@patch("gogstash.download_window.get_icon")
def test_color_scheme_refresh_reloads_each_button_from_its_own_icon_file(mock_get_icon):
    mock_get_icon.return_value = _non_null_icon()
    window = DownloadWindow()
    mock_get_icon.reset_mock()

    window._color_scheme_refresh()

    called_files = {call.args[0] for call in mock_get_icon.call_args_list}
    assert called_files == {"trash.svg", "start_download.svg", "stop.svg", "dequeue.svg"}


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
@sized_downloads()
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

    queued = [(job["priority"], job["product_id"]) for job in window.scheduler.idle_queue]
    assert queued == [(0, 1), (1, 2)]
    assert window.scheduler.max_tokens == 3
    mock_schedule.assert_called_once()
    assert window.current_state == DownloadState.RUNNING


@patch.object(DownloadScheduler, "schedule")
@sized_downloads()
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
@sized_downloads()
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


@patch.object(DownloadScheduler, "schedule")
@sized_downloads()
def test_busy_changed_stays_busy_through_a_pause_and_only_relaxes_once_idle(mock_estimate, mock_schedule):
    # #26: the main window locks Settings off this signal. Paused counts as
    # busy, since the paused game's .part file is still sitting in the old
    # download folder, waiting for someone to move it out from under it.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    heard = []
    window.busy_changed.connect(heard.append)

    window.start_downloads()
    window._on_paused()
    window.stop_downloads()
    window._on_stopped()

    assert heard == [True, True, False]


@patch("gogstash.download_window.DownloadScheduler")
@sized_downloads()
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
@sized_downloads()
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
    queued = [(job["priority"], job["product_id"]) for job in window.scheduler.idle_queue]
    assert queued == [(0, 1), (1, 2)]


@patch.object(DownloadScheduler, "schedule")
@sized_downloads()
def test_on_finished_resets_the_button_and_requeues_every_row(mock_estimate, mock_schedule):
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(title="First Game", product_id=1))
    window.start_downloads()

    window._on_finished()

    assert window.current_state == DownloadState.IDLE
    assert window.start_button.isEnabled() is True
    assert window.start_button.text() == "Start Downloads"
    queued = [(job["priority"], job["product_id"]) for job in window.scheduler.idle_queue]
    assert queued == [(0, 1)]


@sized_downloads()
def test_on_game_stopped_resets_row_progress_and_size_text(mock_estimate):
    mock_estimate.return_value = 2_000_000_000  # 2.0 GB
    window = DownloadWindow()
    window.add_to_queue(_row())
    window.set_progress(42, 55)

    window._on_game_stopped(42)

    assert window.game_queue_table.item(0, Column.TITLE).data(UserRole.PROGRESS_ROLE) == 0
    assert window.game_queue_table.item(0, Column.PROGRESS).text() == "0 Bytes / 2.0 GB"


@sized_downloads()
def test_on_game_succeeded_fills_the_row_to_one_hundred_percent(mock_estimate):
    mock_estimate.return_value = 2_000_000_000  # 2.0 GB
    window = DownloadWindow()
    window.add_to_queue(_row())

    window._on_game_succeeded(42)

    assert window.game_queue_table.item(0, Column.TITLE).data(UserRole.PROGRESS_ROLE) == 100
    assert window.game_queue_table.item(0, Column.PROGRESS).text() == "2.0 GB / 2.0 GB"
    assert window.game_queue_table.item(0, Column.PROGRESS).data(UserRole.FETCHED_SIZE) == 2_000_000_000


def test_on_game_succeeded_tells_the_library_which_game_not_which_row():
    # Queue rows and library rows have nothing in common, so the row index
    # would be useless (and confidently wrong) outside this table.
    window = DownloadWindow()
    window.add_to_queue(_row(title="Some Game", product_id=42))
    window.add_to_queue(_row(title="Other Game", product_id=77))
    announced = []
    window.game_succeeded.connect(announced.append)

    window._on_game_succeeded(77)

    assert announced == [77]


def test_on_game_succeeded_announces_product_ids_too_big_for_32_bits():
    # A Signal(int) is a C++ int under the hood. The biggest ID in a real
    # library today is 2147483137, a mere 510 short of the edge. One GOG
    # release later, an ID one past the edge comes out the other side as
    # -2147483648 and no library row will ever answer to it.
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=2_147_483_648))
    announced = []
    window.game_succeeded.connect(announced.append)

    window._on_game_succeeded(2_147_483_648)

    assert announced == [2_147_483_648]


@sized_downloads()
def test_on_game_failed_puts_the_reason_on_the_red_dot(mock_estimate):
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row())

    window._on_game_failed(42, "connection reset")

    assert window.game_queue_table.item(0, Column.STATUS).toolTip() == "Failed: connection reset"
    assert window.game_queue_table.item(0, Column.STATUS).data(UserRole.STATUS_ROLE) == "red"


@patch.object(DownloadScheduler, "pause_all")
@patch.object(DownloadScheduler, "schedule")
@sized_downloads()
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
@sized_downloads()
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
@sized_downloads()
def test_add_to_queue_still_works_while_downloads_are_running(mock_estimate, mock_schedule):
    # The -1 bouncer only works the pause/stop door. Mid-run adds are fine.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window.start_downloads()

    assert window.add_to_queue(_row(product_id=2)) == 1
    assert window.game_queue_table.rowCount() == 2


@sized_downloads()
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
@sized_downloads()
def test_double_clicking_a_game_thats_already_downloading_doesnt_start_a_second_copy(mock_estimate, mock_schedule):
    # The mid-run version, a.k.a. the impatient double-clicker.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window.start_downloads()

    window.add_to_queue(_row(product_id=1))

    assert window.game_queue_table.rowCount() == 1
    assert [j["product_id"] for j in window.scheduler.idle_queue] == [1]


@sized_downloads()
def test_add_to_queue_still_takes_a_different_game_after_bouncing_a_duplicate(mock_estimate):
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window.add_to_queue(_row(product_id=1))

    assert window.add_to_queue(_row(product_id=2)) == 1
    assert window.game_queue_table.rowCount() == 2


@sized_downloads()
def test_queuing_a_game_with_nothing_to_download_doesnt_divide_by_fucking_zero(mock_estimate):
    # A Mac-only game with the filter set to Linux/Windows estimates to 0
    # bytes. As the first row in the queue, that made the overall bar divide
    # by zero and took add_to_queue down with it.
    mock_estimate.return_value = 0
    window = DownloadWindow()

    assert window.add_to_queue(_row(product_id=1)) == 0  # if this blows up, we've regressed
    assert window.progress_bar.value() == 0  # nothing to measure means nothing done, not "whatever it said before"


@sized_downloads()
def test_adding_a_game_after_a_finish_drags_the_overall_bar_back_to_reality(mock_estimate):
    # _on_finished pins the bar at 100%. Queue another game afterwards and the
    # bar used to keep bragging about 100% until someone hit Start.
    mock_estimate.return_value = 1000
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window._on_game_succeeded(1)
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


@sized_downloads()
def test_a_freshly_queued_game_gets_a_base_dot_and_a_queued_tooltip(mock_estimate):
    mock_estimate.return_value = 0
    window = DownloadWindow()

    window.add_to_queue(_row())

    assert _status(window, 0) == "base"
    assert window.game_queue_table.item(0, Column.STATUS).toolTip() == "Queued"
    assert isinstance(window.game_queue_table.itemDelegateForColumn(Column.STATUS), StatusDelegate)


@sized_downloads()
def test_each_scheduler_signal_paints_the_dot_its_own_color(mock_estimate):
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row())

    for handler, args, color, tip in [
        (window._on_game_started, (42,), "blue", "Downloading"),
        (window._on_game_paused, (42,), "yellow", "Paused"),
        (window._on_game_stopped, (42,), "base", "Queued"),  # stopped games go right back in line
        (window._on_game_failed, (42, "nope"), "red", "Failed: nope"),
        (window._on_game_succeeded, (42,), "green", "Finished"),
    ]:
        handler(*args)
        assert _status(window, 0) == color, handler.__name__
        assert window.game_queue_table.item(0, Column.STATUS).toolTip() == tip


@sized_downloads()
def test_a_theme_change_repaints_the_dot_without_forgetting_its_color(mock_estimate):
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row())
    window._on_game_failed(42, "nope")

    window._color_scheme_refresh()

    assert _status(window, 0) == "red"


@sized_downloads()
def test_clearing_an_idle_queue_empties_it_but_keeps_the_headers(mock_estimate):
    # Regression: QTableWidget.clear() nuked the items AND the headers but left
    # every row standing, a table full of ghosts that crashed the next loop.
    mock_estimate.return_value = 1000
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window._on_game_succeeded(1)
    window._on_finished()

    window.clear_queue_button.click()

    assert window.game_queue_table.rowCount() == 0
    assert window.game_queue_table.horizontalHeaderItem(Column.TITLE).text() == "Title"
    assert window.scheduler.idle_queue == []
    assert window.progress_bar.value() == 0  # no more bragging about a 100% of nothing
    assert window.clear_queue_button.isEnabled() is True


@patch.object(DownloadScheduler, "stop_all")
@patch.object(DownloadScheduler, "schedule")
@sized_downloads()
def test_clearing_mid_run_waits_for_the_stop_before_wiping_the_table(mock_estimate, mock_schedule, mock_stop):
    # The workers are still out there sending product IDs. Yank the rows
    # before they're done and every late signal goes looking for a game
    # that's no longer in the map.
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
@sized_downloads()
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
@sized_downloads()
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
@sized_downloads()
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
@sized_downloads()
def test_restarting_can_drop_the_finished_games_and_the_scheduler_keeps_up(mock_estimate, mock_schedule):
    # Two regressions for the price of one: removing rows front to back
    # skipped every other one, and the scheduler kept jobs for rows that no
    # longer existed, pointing its signals at the wrong games.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    for i in range(5):
        window.add_to_queue(_row(title=f"G{i}", product_id=100 + i))
    for pid in (100, 102, 104):
        window._on_game_succeeded(pid)
    window._on_finished()

    with _answer_dialog(YES):
        window.start_downloads()

    assert _titles(window) == ["G1", "G3"]
    queued = [(job["priority"], job["product_id"]) for job in window.scheduler.idle_queue]
    assert queued == [(0, 101), (1, 103)]
    mock_schedule.assert_called_once()
    assert window.current_state == DownloadState.RUNNING


@patch.object(DownloadScheduler, "schedule")
@sized_downloads()
def test_dropping_every_finished_game_doesnt_start_a_download_of_nothing(mock_estimate, mock_schedule):
    # Otherwise the scheduler finishes an empty queue on the spot and
    # proudly announces "Downloads complete". Complete what, exactly?
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window._on_game_succeeded(1)
    window._on_finished()

    with _answer_dialog(YES):
        window.start_downloads()

    assert window.game_queue_table.rowCount() == 0
    mock_schedule.assert_not_called()
    assert window.current_state == DownloadState.IDLE


@patch.object(DownloadScheduler, "schedule")
@sized_downloads()
def test_keeping_finished_games_resets_the_whole_row_and_the_overall_bar_before_the_redownload(mock_estimate, mock_schedule):
    mock_estimate.return_value = 1000
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window._on_game_succeeded(1)
    window._on_finished()

    with _answer_dialog(NO):
        window.start_downloads()

    assert window.game_queue_table.rowCount() == 1
    assert _status(window, 0) == "base"
    assert window.game_queue_table.item(0, Column.TITLE).data(UserRole.PROGRESS_ROLE) == 0
    assert window.game_queue_table.item(0, Column.PROGRESS).text() == "0 Bytes / 1.0 kB"
    assert window.game_queue_table.item(0, Column.PROGRESS).data(UserRole.FETCHED_SIZE) == 0
    assert window.progress_bar.value() == 0  # not a head start of 100% on a download that hasn't happened
    assert [j["product_id"] for j in window.scheduler.idle_queue] == [1]


@patch.object(DownloadScheduler, "resume_all")
@patch.object(DownloadScheduler, "pause_all")
@patch.object(DownloadScheduler, "schedule")
@sized_downloads()
def test_resuming_never_offers_to_remove_rows_out_from_under_the_scheduler(mock_estimate, mock_schedule, mock_pause, mock_resume):
    # A game can finish right before the pause lands. Resume means "carry
    # on", not "tidy up": the finished row stays until the next fresh Start.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(title="A", product_id=1))
    window.add_to_queue(_row(title="B", product_id=2))
    window.start_downloads()
    window.pause_downloads()
    window._on_game_succeeded(1)
    window._on_paused()

    with _answer_dialog(YES) as mock_exec:
        window.start_downloads()

    mock_exec.assert_not_called()
    assert _titles(window) == ["A", "B"]
    mock_resume.assert_called_once()


@sized_downloads()
def test_a_failed_game_drops_its_half_download_from_the_overall_bar(mock_estimate):
    # The partial file is gone or useless, so counting it as progress is
    # just lying to the user with extra steps.
    mock_estimate.return_value = 1000
    window = DownloadWindow()
    window.add_to_queue(_row())
    window._on_progress(42, 600, 1000)

    window._on_game_failed(42, "nope")

    assert window.game_queue_table.item(0, Column.PROGRESS).data(UserRole.FETCHED_SIZE) == 0
    assert window.game_queue_table.item(0, Column.PROGRESS).text() == "0 Bytes / 1.0 kB"


@patch.object(DownloadScheduler, "schedule")
@sized_downloads()
def test_restarting_puts_failed_games_back_in_line_without_asking(mock_estimate, mock_schedule):
    # Red rows aren't "completed", so no prompt. They just get their dot
    # scrubbed and try again.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window._on_game_failed(1, "nope")
    window._on_finished()

    with _answer_dialog(YES) as mock_exec:
        window.start_downloads()

    mock_exec.assert_not_called()
    assert _status(window, 0) == "base"
    assert window.game_queue_table.item(0, Column.STATUS).toolTip() == "Queued"


@sized_downloads()
def test_finishing_with_failures_owns_up_to_them(mock_estimate):
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window.add_to_queue(_row(product_id=2))
    window._on_game_succeeded(1)
    window._on_game_failed(2, "nope")

    window._on_finished()

    assert window.downloads_status.text() == "Finished with 1 failure"


@sized_downloads()
def test_finishing_with_several_failures_gets_the_plural_it_deserves(mock_estimate):
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window.add_to_queue(_row(product_id=2))
    window._on_game_failed(1, "nope")
    window._on_game_failed(2, "also nope")

    window._on_finished()

    assert window.downloads_status.text() == "Finished with 2 failures"


@sized_downloads()
def test_a_clean_finish_still_says_complete(mock_estimate):
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window._on_game_succeeded(1)

    window._on_finished()

    assert window.downloads_status.text() == "Downloads complete"


@patch.object(DownloadScheduler, "schedule")
@sized_downloads()
def test_the_leftover_ready_timer_doesnt_stomp_on_a_new_run(mock_estimate, mock_schedule):
    # Regression: finish, hit Start within five seconds, and the old timer
    # cheerfully announced "Ready!" over an active download.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window.start_downloads()

    window._reset_status()  # the timer firing late

    assert window.downloads_status.text() == "Downloading..."


# --- low disk space ---

class _IdleWorker(QObject):
    """A worker that never works. Enough for the window's scheduler to dispatch
    to without a real QThread wandering off to download from GOG."""

    succeeded = Signal()
    failed = Signal(str)
    progress = Signal(float, float)
    stopped = Signal()
    paused = Signal(dict)
    fetched = Signal(dict)
    disk_full = Signal(dict)

    def __init__(self, product_id, file_queue=None, resume_link=None):
        super().__init__()
        self.total_size = sum(f["size"] for f in file_queue or [])
        self.fetched_size = 0

    def start(self):
        pass

    def wait(self):
        return True

    def stop_worker(self):
        self.stopped.emit()

    def pause_worker(self):
        self.paused.emit({})


def _full_disk():
    return patch("gogstash.download_queue.shutil.disk_usage", return_value=MagicMock(free=0))


def _roomy_disk():
    return patch("gogstash.download_queue.shutil.disk_usage", return_value=MagicMock(free=10**12))


def _status_of(window, row):
    return window.game_queue_table.item(row, Column.STATUS).data(UserRole.STATUS_ROLE)


def _deliver_queued_signals():
    # low_disk_space is a queued connection, so its slot only runs once the
    # event loop gets a turn. In a test, we are the event loop.
    QApplication.processEvents()


@patch("gogstash.download_queue.DownloadWorkerThread", _IdleWorker)
@sized_downloads()
def test_low_disk_space_waits_for_start_to_finish_before_asking(mock_estimate):
    # Regression: as a direct connection, the dialog popped up from inside
    # start_downloads(), saw the window still IDLE, and "No" did nothing
    # because stop_downloads() ignores an idle window. Then start carried on
    # and left a window claiming to download with every button greyed out.
    mock_estimate.return_value = 1000
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    seen_states = []

    def answer(*_):
        seen_states.append(window.current_state)
        return NO

    with _full_disk(), patch("gogstash.download_window.QMessageBox.exec", side_effect=answer):
        window.start_downloads()
        assert seen_states == []  # not from inside start, thanks
        _deliver_queued_signals()

    assert seen_states == [DownloadState.RUNNING]


@patch("gogstash.download_queue.DownloadWorkerThread", _IdleWorker)
@sized_downloads()
def test_pausing_on_a_full_disk_before_anything_started_still_lands_on_paused(mock_estimate):
    # Regression: with no active worker around to report back, nobody ever
    # announced "paused" and the window sat on "Pausing. Please wait..." with
    # Start and Clear greyed out, waiting for a phone call that never came.
    mock_estimate.return_value = 1000
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))

    with _full_disk(), _answer_dialog(NO):
        window.start_downloads()
        _deliver_queued_signals()

    assert window.current_state == DownloadState.PAUSED
    assert window.downloads_status.text() == "Downloads paused"
    assert window.start_button.text() == "Resume Downloads"
    assert window.start_button.isEnabled() is True
    assert window.clear_queue_button.isEnabled() is True
    assert window.game_queue_table.rowCount() == 1  # pausing isn't clearing


@patch("gogstash.download_queue.DownloadWorkerThread", _IdleWorker)
@sized_downloads()
def test_pausing_on_a_full_disk_mid_run_pauses_the_active_game_and_keeps_the_rest_queued(mock_estimate):
    # The download that was happily running gets to keep its .part file
    # instead of being thrown out because a newcomer was too big.
    mock_estimate.return_value = 1000
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    with _roomy_disk():
        window.start_downloads()
    assert [j["priority"] for j in window.scheduler.active_queue] == [0]

    with _full_disk(), _answer_dialog(NO):
        window.add_to_queue(_row(title="Huge Game", product_id=2))
        _deliver_queued_signals()

    assert window.current_state == DownloadState.PAUSED
    assert _status_of(window, 0) == "yellow"
    assert _status_of(window, 1) == "base"
    assert [j["priority"] for j in window.scheduler.paused_queue] == [0]


@patch("gogstash.download_queue.DownloadWorkerThread", _IdleWorker)
@sized_downloads()
def test_resuming_onto_a_disk_that_is_still_full_asks_again(mock_estimate):
    # Regression: the one-dialog-per-run guard outlived the pause, so Resume
    # on a still-full disk got its warning swallowed, started nothing, and
    # cheerfully claimed "Downloading..." forever.
    mock_estimate.return_value = 1000
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    with _full_disk(), _answer_dialog(NO):
        window.start_downloads()
        _deliver_queued_signals()
    assert window.current_state == DownloadState.PAUSED

    with _full_disk(), _answer_dialog(NO) as mock_exec:
        window.start_downloads()  # Resume, without actually freeing anything
        _deliver_queued_signals()

    assert mock_exec.call_count == 1
    assert window.current_state == DownloadState.PAUSED


@patch("gogstash.download_queue.DownloadWorkerThread", _IdleWorker)
@sized_downloads()
def test_saying_yes_to_a_full_disk_downloads_anyway_with_the_buttons_still_working(mock_estimate):
    mock_estimate.return_value = 1000
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))

    with _full_disk(), _answer_dialog(YES):
        window.start_downloads()
        _deliver_queued_signals()

    assert window.scheduler.free_space_check is False
    assert [j["priority"] for j in window.scheduler.active_queue] == [0]
    assert window.current_state == DownloadState.RUNNING
    assert window.start_button.isEnabled() is True  # Pause still works
    assert window.clear_queue_button.isEnabled() is True


@patch("gogstash.download_queue.DownloadWorkerThread", _IdleWorker)
@sized_downloads()
def test_a_full_disk_only_asks_once_no_matter_how_often_the_scheduler_complains(mock_estimate):
    # The scheduler re-checks after every finished game, and dialog.exec()
    # keeps delivering queued signals while it waits for an answer. Without
    # the guard, the user would be stacking dialogs like dinner plates.
    mock_estimate.return_value = 1000
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))

    def answer_while_the_scheduler_keeps_yelling(*_):
        window.scheduler.low_disk_space.emit(1000, 0)
        window.scheduler.low_disk_space.emit(1000, 0)
        _deliver_queued_signals()
        return YES

    with _full_disk(), patch("gogstash.download_window.QMessageBox.exec",
                             side_effect=answer_while_the_scheduler_keeps_yelling) as mock_exec:
        window.start_downloads()
        _deliver_queued_signals()

    assert mock_exec.call_count == 1


@patch("gogstash.download_queue.DownloadWorkerThread", _IdleWorker)
@sized_downloads()
def test_the_next_run_gets_its_own_free_space_check(mock_estimate):
    # "Download anyway" is a one-run pass, not a lifetime membership.
    mock_estimate.return_value = 1000
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    with _full_disk(), _answer_dialog(YES):
        window.start_downloads()
        _deliver_queued_signals()
    window.scheduler.active_queue[0]["worker"].succeeded.emit()  # run finishes, window resets

    with _full_disk(), _answer_dialog(NO) as mock_exec:
        window.start_downloads()
        _deliver_queued_signals()

    # Two dialogs: "remove completed downloads?" for the finished row, then
    # the disk one again. A leftover pass would have skipped the second.
    assert mock_exec.call_count == 2


@patch("gogstash.download_queue.DownloadWorkerThread", _IdleWorker)
@sized_downloads()
def test_stopping_while_paused_gives_the_start_button_back(mock_estimate):
    # Regression: with nothing active, the stop lands synchronously inside
    # stop_all(), and _on_stopped re-enables Start before stop_downloads()
    # gets to its next line, which then greys it right back out. Idle window,
    # dead Start button, restart the app to download anything ever again.
    mock_estimate.return_value = 1000
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window.start_downloads()
    window.pause_downloads()
    assert window.current_state == DownloadState.PAUSED

    window.stop_downloads()

    assert window.current_state == DownloadState.IDLE
    assert window.start_button.isEnabled() is True


# --- the disk fills up mid-download ---

def _fill_the_disk(window, pid=1):
    job = next(j for j in window.scheduler.active_queue if j["product_id"] == pid)
    job["worker"].disk_full.emit({"partpath": None, "downlink": "x"})


OK = QMessageBox.StandardButton.Ok


@patch("gogstash.download_queue.DownloadWorkerThread", _IdleWorker)
@sized_downloads()
def test_a_full_disk_mid_download_pauses_and_says_why(mock_estimate):
    # Regression: the game just went red with "[Errno 28]" and the next one
    # marched off into the same full disk. Now: pause, explain, wait.
    mock_estimate.return_value = 1000
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    with _roomy_disk():
        window.start_downloads()

    with _answer_dialog(OK) as mock_exec:
        _fill_the_disk(window)
        _deliver_queued_signals()

    assert mock_exec.call_count == 1
    assert window.current_state == DownloadState.PAUSED
    assert window.downloads_status.text() == "Downloads paused"  # not stuck on "Pausing..."
    assert window.start_button.text() == "Resume Downloads"
    assert window.start_button.isEnabled() is True
    assert _status_of(window, 0) == "yellow"


@patch("gogstash.download_queue.DownloadWorkerThread", _IdleWorker)
@sized_downloads()
def test_a_full_disk_after_download_anyway_still_explains_and_rechecks_on_resume(mock_estimate):
    # "Download anyway" is how you usually end up here, so it's exactly the
    # case that can't go quiet. And the user's "I know better" pass expires
    # the moment the disk proves otherwise.
    mock_estimate.return_value = 1000
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    with _full_disk(), _answer_dialog(YES):
        window.start_downloads()
        _deliver_queued_signals()
    assert window.scheduler.free_space_check is False

    with _answer_dialog(OK) as mock_exec:
        _fill_the_disk(window)
        _deliver_queued_signals()

    assert mock_exec.call_count == 1
    assert window.scheduler.free_space_check is True

    with _full_disk(), _answer_dialog(NO) as mock_exec:
        window.start_downloads()  # Resume, without freeing anything
        _deliver_queued_signals()

    assert mock_exec.call_count == 1  # the low-disk dialog, instead of diving back in
    assert window.scheduler.active_queue == []
    assert window.current_state == DownloadState.PAUSED


@patch("gogstash.download_queue.DownloadWorkerThread", _IdleWorker)
@sized_downloads()
def test_a_full_disk_waits_for_the_other_downloads_before_saying_paused(mock_estimate):
    # Two downloads, one hits the wall. The other takes a moment to put its
    # pen down, and the window shouldn't claim "paused" before it has.
    update_setting("download_concurrency", 2)
    mock_estimate.return_value = 1000
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window.add_to_queue(_row(title="Other Game", product_id=2))
    with _roomy_disk():
        window.start_downloads()
    slow_job = next(j for j in window.scheduler.active_queue if j["product_id"] == 2)
    slow_job["worker"].pause_worker = lambda: None  # still finishing its chunk

    with _answer_dialog(OK):
        _fill_the_disk(window, pid=1)
        _deliver_queued_signals()

    assert window.downloads_status.text() == "Download folder is full. Pausing..."
    assert window.start_button.isEnabled() is False

    slow_job["worker"].paused.emit({})

    assert window.current_state == DownloadState.PAUSED
    assert window.downloads_status.text() == "Downloads paused"
    assert window.start_button.isEnabled() is True


# --- rows are found by product ID, not by where they happen to sit ---

@patch("gogstash.download_queue.DownloadWorkerThread", _IdleWorker)
def test_queuing_an_already_downloaded_game_mid_run_goes_green_on_the_spot():
    # Regression: with a slot free, enqueue() scheduled on its own and the
    # game was declared finished before add_to_queue had written its size
    # down. naturalsize(None) blew up, PySide shrugged, and the row sat on
    # "Queued" for a job the scheduler had already forgotten about.
    update_setting("download_concurrency", 2)
    window = DownloadWindow()
    window.add_to_queue(_row(title="Big Game", product_id=1))
    with _roomy_disk():
        window.start_downloads()
    announced = []
    window.game_succeeded.connect(announced.append)

    with _roomy_disk(), patch("gogstash.download_queue.generate_download_list", lambda ids: []):
        window.add_to_queue(_row(title="Already Here", product_id=2))

    assert _status_of(window, 1) == "green"
    assert window.game_queue_table.item(1, Column.STATUS).toolTip() == "Finished"
    assert window.game_queue_table.item(1, Column.PROGRESS).text() == "0 Bytes / 0 Bytes"
    assert announced == [2]


@patch("gogstash.download_queue.DownloadWorkerThread", _IdleWorker)
@sized_downloads()
def test_a_game_queued_mid_run_still_grabs_a_free_slot(mock_estimate):
    # enqueue() doesn't schedule anymore, so the window has to kick it.
    # Forget that and a mid-run add waits for someone else to finish first.
    update_setting("download_concurrency", 2)
    mock_estimate.return_value = 1000
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    with _roomy_disk():
        window.start_downloads()

    with _roomy_disk():
        window.add_to_queue(_row(title="Latecomer", product_id=2))

    assert [j["product_id"] for j in window.scheduler.active_queue] == [1, 2]
    assert _status_of(window, 1) == "blue"


@patch("gogstash.download_queue.DownloadWorkerThread", _IdleWorker)
@sized_downloads()
def test_a_game_queued_while_paused_waits_for_resume(mock_estimate):
    mock_estimate.return_value = 1000
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    with _roomy_disk():
        window.start_downloads()
        window.pause_downloads()

        window.add_to_queue(_row(title="Patient Game", product_id=2))

    assert window.scheduler.active_queue == []
    assert [j["product_id"] for j in window.scheduler.idle_queue] == [2]
    assert _status_of(window, 1) == "base"


@patch.object(DownloadScheduler, "schedule")
@sized_downloads()
def test_signals_still_find_their_row_after_the_rows_above_it_are_gone(mock_estimate, mock_schedule):
    # The whole point of #11's groundwork: drop the finished rows, and a
    # signal for G3 lands on G3, wherever G3 ended up.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    for i in range(4):
        window.add_to_queue(_row(title=f"G{i}", product_id=100 + i))
    for pid in (100, 101):
        window._on_game_succeeded(pid)
    window._on_finished()
    with _answer_dialog(YES):
        window.start_downloads()
    assert _titles(window) == ["G2", "G3"]

    window._on_game_started(103)

    assert _status_of(window, 1) == "blue"
    assert _status_of(window, 0) == "base"


@sized_downloads()
def test_a_cleared_game_can_be_queued_again(mock_estimate):
    # Regression: clearing an idle queue emptied the table but not the map.
    # _reset_all then poked items Qt had already deleted, and re-adding the
    # game "found" it in the map and selected a row that wasn't there.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row(product_id=1))
    window.clear_queue_button.click()

    assert window.add_to_queue(_row(product_id=1)) == 0
    assert window.game_queue_table.rowCount() == 1
    assert [j["product_id"] for j in window.scheduler.idle_queue] == [1]


# --- removing games from the queue ---

def _queue(window, count):
    for i in range(count):
        window.add_to_queue(_row(title=f"G{i}", product_id=100 + i))


def _select_rows(window, *rows):
    table = window.game_queue_table
    table.clearSelection()
    for row in rows:
        table.selectionModel().select(
            table.model().index(row, Column.TITLE),
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
        )


def _remove_rows(window, *rows):
    _select_rows(window, *rows)
    window.remove_button.click()


@sized_downloads()
def test_removing_a_waiting_game_takes_its_row_and_its_place_in_line(mock_estimate):
    window = DownloadWindow()
    _queue(window, 3)

    _remove_rows(window, 1)

    assert _titles(window) == ["G0", "G2"]
    assert [j["product_id"] for j in window.scheduler.idle_queue] == [100, 102]


@sized_downloads()
def test_removing_several_games_at_once_gets_every_one_of_them(mock_estimate):
    window = DownloadWindow()
    _queue(window, 3)

    _remove_rows(window, 0, 2)

    assert _titles(window) == ["G1"]
    assert [j["product_id"] for j in window.scheduler.idle_queue] == [101]


@sized_downloads()
def test_a_removed_game_can_be_queued_again(mock_estimate):
    window = DownloadWindow()
    _queue(window, 2)
    _remove_rows(window, 0)

    assert window.add_to_queue(_row(title="G0 again", product_id=100)) == 1

    assert _titles(window) == ["G1", "G0 again"]
    assert sorted(j["product_id"] for j in window.scheduler.idle_queue) == [100, 101]


@patch("gogstash.download_queue.DownloadWorkerThread", _IdleWorker)
@sized_downloads()
def test_a_game_added_after_a_removal_gets_its_own_row_and_the_back_of_the_line(mock_estimate):
    # Regression x2. The new row's items went to row "priority counter",
    # which is past the end of the table once anything's been removed, so
    # Qt binned them and the window choked on an empty row. And with
    # rowCount() as the priority, three removals let the newcomer start
    # ahead of the two games that were already waiting. Rude.
    update_setting("download_concurrency", 1)
    mock_estimate.return_value = 1000
    window = DownloadWindow()
    _queue(window, 5)
    _remove_rows(window, 0, 1, 2)

    window.add_to_queue(_row(title="Latecomer", product_id=105))
    assert _titles(window) == ["G3", "G4", "Latecomer"]

    with _roomy_disk():
        window.start_downloads()
        assert [j["product_id"] for j in window.scheduler.active_queue] == [103]
        window.scheduler.active_queue[0]["worker"].succeeded.emit()

    assert [j["product_id"] for j in window.scheduler.active_queue] == [104]


@patch("gogstash.download_queue.DownloadWorkerThread", _IdleWorker)
@sized_downloads()
def test_the_remove_button_sits_out_the_downloading_and_comes_back_for_the_pause(mock_estimate):
    mock_estimate.return_value = 1000
    window = DownloadWindow()
    _queue(window, 1)
    assert window.remove_button.isEnabled() is True

    with _roomy_disk():
        window.start_downloads()
    assert window.remove_button.isEnabled() is False
    assert window.remove_button.toolTip() == "Pause or Cancel Downloads before removing"

    window.pause_downloads()
    assert window.remove_button.isEnabled() is True
    assert window.remove_button.toolTip() == "Remove selected items from queue (Del)"


@patch("gogstash.download_queue.DownloadWorkerThread", _IdleWorker)
@sized_downloads()
def test_removing_mid_download_does_nothing_even_if_someone_gets_past_the_button(mock_estimate):
    # The button is greyed out, but a keyboard shortcut or context menu
    # someday won't be. The handler has to say no on its own, even to the
    # games still waiting, which the scheduler alone would happily let go.
    update_setting("download_concurrency", 1)
    mock_estimate.return_value = 1000
    window = DownloadWindow()
    _queue(window, 3)
    with _roomy_disk():
        window.start_downloads()
    _select_rows(window, 0, 1, 2)

    window._onclick_remove_button()

    assert _titles(window) == ["G0", "G1", "G2"]
    assert [j["product_id"] for j in window.scheduler.active_queue] == [100]
    assert [j["product_id"] for j in window.scheduler.idle_queue] == [101, 102]


@patch("gogstash.download_queue.DownloadWorkerThread", _IdleWorker)
@sized_downloads()
def test_a_paused_game_can_be_removed_and_the_rest_resume_without_it(mock_estimate):
    update_setting("download_concurrency", 1)
    mock_estimate.return_value = 1000
    window = DownloadWindow()
    _queue(window, 2)
    with _roomy_disk():
        window.start_downloads()
    window.pause_downloads()
    assert _status_of(window, 0) == "yellow"

    _remove_rows(window, 0)

    assert _titles(window) == ["G1"]
    assert window.scheduler.paused_queue == []
    with _roomy_disk():
        window.start_downloads()
    assert [j["product_id"] for j in window.scheduler.active_queue] == [101]


@patch("gogstash.download_queue.DownloadWorkerThread", _IdleWorker)
@sized_downloads()
def test_finished_and_failed_games_can_be_removed_while_paused(mock_estimate):
    # Mid-run, these two already said their goodbyes to the scheduler, so
    # dequeue() has never heard of them. Their rows still have to go.
    update_setting("download_concurrency", 3)
    mock_estimate.return_value = 1000
    window = DownloadWindow()
    _queue(window, 3)
    with _roomy_disk():
        window.start_downloads()
    done, broken, _ = [j["worker"] for j in window.scheduler.active_queue]
    done.succeeded.emit()
    broken.failed.emit("the CDN ate it")
    window.pause_downloads()
    assert [_status_of(window, r) for r in range(3)] == ["green", "red", "yellow"]

    _remove_rows(window, 0, 1)

    assert _titles(window) == ["G2"]
    assert window.current_state == DownloadState.PAUSED


@patch("gogstash.download_queue.DownloadWorkerThread", _IdleWorker)
@sized_downloads()
def test_removing_the_last_game_while_paused_lands_back_on_idle_instead_of_a_dead_resume_button(mock_estimate):
    # Regression: an empty table while PAUSED left Resume clicking into
    # start_downloads(), which bails on an empty table. Forever paused,
    # pausing nothing.
    mock_estimate.return_value = 1000
    window = DownloadWindow()
    _queue(window, 1)
    with _roomy_disk():
        window.start_downloads()
    window.pause_downloads()

    _remove_rows(window, 0)

    assert window.game_queue_table.rowCount() == 0
    assert window.current_state == DownloadState.IDLE
    assert window.start_button.text() == "Start Downloads"
    assert window.downloads_status.text() == "Ready!"  # not still "Downloads paused"


@sized_downloads()
def test_removing_a_game_takes_its_bytes_off_the_overall_bar(mock_estimate):
    mock_estimate.return_value = 100
    window = DownloadWindow()
    _queue(window, 2)
    window._on_progress(100, 50, 100)
    assert window.progress_bar.value() == 25

    _remove_rows(window, 1)

    assert window.progress_bar.value() == 50


# --- the Del key ---

@pytest.fixture
def docked():
    # Shortcuts only fire in a shown, active window with focus where the
    # shortcut's context says it should be. So: a tiny main window with a
    # QTreeWidget standing in for the library list, like the real thing.
    # Not a QLineEdit: that hogs Del for itself, so the queue's shortcut
    # would never fire there no matter how badly it was scoped.
    main = QMainWindow()
    window = DownloadWindow(main)
    main.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, window)
    elsewhere = QTreeWidget()
    main.setCentralWidget(elsewhere)
    main.show()
    main.activateWindow()
    QApplication.processEvents()
    yield window, elsewhere
    main.close()


def _press_del(widget):
    widget.setFocus()
    QApplication.processEvents()
    QTest.keyClick(widget, Qt.Key.Key_Delete)


@sized_downloads()
def test_del_on_the_queue_removes_the_selected_games(mock_estimate, docked):
    window, _ = docked
    _queue(window, 3)
    _select_rows(window, 0, 2)

    _press_del(window.game_queue_table)

    assert _titles(window) == ["G1"]
    assert [j["product_id"] for j in window.scheduler.idle_queue] == [101]


@sized_downloads()
def test_del_somewhere_else_in_the_window_leaves_the_queue_alone(mock_estimate, docked):
    # Del while browsing the library shouldn't quietly bin whatever
    # happens to be selected over in the queue.
    window, elsewhere = docked
    _queue(window, 2)
    _select_rows(window, 0)

    _press_del(elsewhere)

    assert _titles(window) == ["G0", "G1"]


@patch("gogstash.download_queue.DownloadWorkerThread", _IdleWorker)
@sized_downloads()
def test_del_mid_download_does_nothing_even_though_the_button_cant_stop_it(mock_estimate, docked):
    # Disabling the button does nothing for the keyboard. The handler's own
    # RUNNING check is the only thing standing between Del and the queue.
    update_setting("download_concurrency", 1)
    mock_estimate.return_value = 1000
    window, _ = docked
    _queue(window, 2)
    with _roomy_disk():
        window.start_downloads()
    _select_rows(window, 0, 1)

    _press_del(window.game_queue_table)

    assert _titles(window) == ["G0", "G1"]
    assert [j["product_id"] for j in window.scheduler.idle_queue] == [101]
