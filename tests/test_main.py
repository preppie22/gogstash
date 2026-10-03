import time
from unittest.mock import MagicMock, patch

import humanize
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QDialog

from gogstash import gog_auth, library_db, manifest
from gogstash.main import MainWindow
from gogstash.settings import update_setting
from tests.fakes import gog_product


def _non_null_icon():
    # A plain QIcon() is null, and _color_scheme_refresh's "skip icon-less
    # entries" guard would then treat every recolored button as icon-less too.
    return QIcon(QPixmap(4, 4))


FAKE_GAME = {"product_id": 111, "title": "Fake Game", "slug": "fake-game", "download_size": 2048}
FAKE_GAME_2 = {"product_id": 222, "title": "Second Fake Game", "slug": "second-fake-game", "download_size": 4096}


def _stock_the_library(games, bonus=False):
    # Fetched means "every file the settings pick is on disk", so the DB has
    # to list some files. One 5 byte installer per game, plus a 5 byte manual
    # for the ones that came with homework.
    library_db.update_cache([gog_product(
        game["product_id"], game["title"], game["slug"], osx=False,
        downloads={
            "installers": [{
                "id": "installer_windows_en", "name": game["title"], "os": "windows", "language": "en", "total_size": 5,
                "files": [{"id": "setup", "size": 5, "downlink": f"https://example.com/{game['slug']}/setup"}],
            }],
            "bonus_content": [{
                "id": 1, "name": "manual", "type": "manuals", "total_size": 5,
                "files": [{"id": "manual", "size": 5, "downlink": f"https://example.com/{game['slug']}/manual"}],
            }] if bonus else [],
        },
    ) for game in games])


def _record(download_dir, game, category):
    # Writes the file and its manifest entry with the same downlink and listed
    # size the DB has, so this passes for "downlink is in the manifest" and
    # for the stricter check_exist_by_downlink alike.
    game_dir = download_dir / game["slug"]
    name = "setup" if category == "installers" else "manual"
    path = game_dir / category / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"hello")
    manifest.add_file(game_dir, path, category=category, downlink=f"https://example.com/{game['slug']}/{name}", db_size=5, checksum="abc", timestamp=1.0)


def _record_installer(download_dir, game):
    _record(download_dir, game, "installers")


def _is_fetched(window, row):
    # The Fetched cell is all icon and no text now, so ask it what it
    # believes rather than reading what it says.
    return window.games_list.item(row, 2).data(Qt.ItemDataRole.UserRole)


def _finish_download(window, game):
    # Same trip a real download takes: the scheduler reports the queue row,
    # the queue turns it into a product ID, the library takes it from there.
    row_idx = window.download_window.add_to_queue({"product_id": game["product_id"], "title": game["title"], "size": "5 Bytes"})
    window.download_window.scheduler.game_succeeded.emit(row_idx)


def test_not_logged_in_shows_red_indicator_and_status_text():
    window = MainWindow()
    assert window.status_text.text() == "Not logged in"
    assert "red" in window.logged_in_indicator.styleSheet()


def test_logged_in_shows_green_indicator_and_status_text():
    gog_auth.save_token({"access_token": "abc", "expiry": time.time() + 3600})
    window = MainWindow()
    assert window.status_text.text() == "Logged in"
    assert "green" in window.logged_in_indicator.styleSheet()


def test_logout_clears_token_and_reverts_status_to_logged_out():
    gog_auth.save_token({"access_token": "abc", "expiry": time.time() + 3600})
    window = MainWindow()

    window.logout()

    assert gog_auth.get_valid_token() is None
    assert window.status_text.text() == "Not logged in"
    assert "red" in window.logged_in_indicator.styleSheet()


def test_logout_is_safe_when_already_logged_out():
    window = MainWindow()

    window.logout()  # should not raise even though there was no token to clear

    assert window.status_text.text() == "Not logged in"


@patch("gogstash.main.LoginWindow")
def test_open_login_window_refreshes_status_when_accepted(mock_login_window_cls):
    mock_login_window_cls.return_value.exec.return_value = QDialog.DialogCode.Accepted
    gog_auth.save_token({"access_token": "abc", "expiry": time.time() + 3600})
    window = MainWindow()
    window.status_text.setText("stale")  # will be overwritten if the refresh runs

    window.open_login_window()

    mock_login_window_cls.assert_called_once_with(window)
    assert window.status_text.text() == "Logged in"


@patch("gogstash.main.LoginWindow")
def test_open_login_window_leaves_status_untouched_when_rejected(mock_login_window_cls):
    mock_login_window_cls.return_value.exec.return_value = QDialog.DialogCode.Rejected
    window = MainWindow()
    window.status_text.setText("stale")

    window.open_login_window()

    assert window.status_text.text() == "stale"


@patch("gogstash.main.SettingsDialog")
def test_open_settings_constructs_and_executes_dialog(mock_settings_dialog_cls):
    window = MainWindow()

    window.open_settings()

    mock_settings_dialog_cls.assert_called_once_with(window)
    mock_settings_dialog_cls.return_value.exec.assert_called_once()


@patch("gogstash.library_db.LibraryFetchThread")
def test_fetch_games_wires_up_thread_signals_and_starts_it(mock_thread_cls):
    # Login status isn't checked here anymore -- the thread resolves its own
    # token and reports back via auth_failure if there isn't one, so this
    # just has to prove the wiring/start happens regardless.
    window = MainWindow()

    window.fetch_games()

    mock_thread_cls.assert_called_once_with(force=True)
    mock_thread_instance = mock_thread_cls.return_value
    mock_thread_instance.succeeded.connect.assert_called_once_with(window.on_games_loaded)
    mock_thread_instance.failed.connect.assert_called_once_with(window.fetch_failed_handler)
    mock_thread_instance.auth_failure.connect.assert_called_once_with(window.on_auth_failure)
    mock_thread_instance.progress.connect.assert_called_once_with(window.update_fetch_progress)
    mock_thread_instance.start.assert_called_once()


def test_on_auth_failure_shows_error_and_resets_ui_state():
    # Regression: on_auth_failure used to only show the error message, so a
    # click on "Refresh Games List" while logged out left the button
    # disabled and the status text stuck on "Fetching games list..." forever.
    window = MainWindow()
    window.error_message.showMessage = MagicMock()
    window.fetch_games_button.setDisabled(True)
    window.status_progress.setVisible(True)

    window.on_auth_failure()

    window.error_message.showMessage.assert_called_once_with("You are not logged in to GOG!")
    assert window.fetch_games_button.isEnabled()
    assert not window.status_progress.isVisible()


def test_on_games_loaded_populates_table_with_games(tmp_path):
    update_setting("download_path", str(tmp_path))  # no manifest under here for "fake-game"
    window = MainWindow()

    window.on_games_loaded([FAKE_GAME])

    assert window.games_list.rowCount() == 1
    assert window.games_list.item(0, 0).text() == "Fake Game"
    assert _is_fetched(window, 0) is False
    assert window.games_list.item(0, 2).toolTip() == "Not Fetched"


def test_on_games_loaded_marks_fetched_when_every_selected_file_is_in_the_manifest(tmp_path):
    update_setting("download_path", str(tmp_path))
    _stock_the_library([FAKE_GAME])
    _record_installer(tmp_path, FAKE_GAME)
    window = MainWindow()

    window.on_games_loaded([FAKE_GAME])

    assert _is_fetched(window, 0) is True
    assert window.games_list.item(0, 2).toolTip() == "Fetched"


def test_on_games_loaded_does_not_mark_fetched_for_bonus_content_alone(tmp_path):
    # A manual on disk is not the game on disk. With bonus content switched
    # off the manual isn't even on the shopping list, so it can't vouch for
    # the installer that never showed up.
    update_setting("download_path", str(tmp_path))
    _stock_the_library([FAKE_GAME], bonus=True)
    _record(tmp_path, FAKE_GAME, "bonus_content")
    window = MainWindow()

    window.on_games_loaded([FAKE_GAME])

    assert _is_fetched(window, 0) is False


def test_on_games_loaded_does_not_mark_a_half_finished_game_fetched(tmp_path):
    # Issue #3's other half: the installer made it, the manual didn't. One
    # out of two used to be good enough for a tick.
    update_setting("download_path", str(tmp_path))
    update_setting("bonus_content", True)
    _stock_the_library([FAKE_GAME], bonus=True)
    _record_installer(tmp_path, FAKE_GAME)
    window = MainWindow()

    window.on_games_loaded([FAKE_GAME])

    assert _is_fetched(window, 0) is False


def test_on_games_loaded_does_not_call_a_game_with_nothing_to_download_fetched(tmp_path):
    # The settings pick zero files for this one, yet there's a manifest from
    # some earlier life. "Every one of no files is here" is technically true,
    # and technically true is the worst kind of true for a status column.
    update_setting("download_path", str(tmp_path))
    _stock_the_library([FAKE_GAME])
    update_setting("platform_filter", ["Linux"])  # its only installer is for Windows
    _record_installer(tmp_path, FAKE_GAME)
    window = MainWindow()

    window.on_games_loaded([FAKE_GAME])

    assert _is_fetched(window, 0) is False


def test_on_games_loaded_replaces_previous_rows_not_appends():
    window = MainWindow()
    window.on_games_loaded([FAKE_GAME])

    window.on_games_loaded([FAKE_GAME_2])

    assert window.games_list.rowCount() == 1
    assert window.games_list.item(0, 0).text() == "Second Fake Game"


# Size order (Alpha < Gamma < Beta) disagrees with both title order and the
# order they arrive in, so no test here can pass by accident.
SIZED_GAMES = [
    {"product_id": 3, "title": "Gamma", "slug": "gamma", "download_size": 900_000_000},
    {"product_id": 1, "title": "Alpha", "slug": "alpha", "download_size": 50_000},
    {"product_id": 2, "title": "Beta", "slug": "beta", "download_size": 1_200_000_000},
]
SIZE_TEXT = {g["title"]: humanize.naturalsize(g["download_size"]) for g in SIZED_GAMES}


def _rows(window):
    table = window.games_list
    return [(table.item(row, 0).text(), table.item(row, 1).text()) for row in range(table.rowCount())]


def test_library_starts_out_sorted_by_title_a_to_z():
    # Qt's out-of-the-box sort is Z to A, and before sortByColumn showed up the
    # header's sort column had wandered off to section 3, which doesn't exist.
    window = MainWindow()

    window.on_games_loaded(SIZED_GAMES)

    assert [title for title, _ in _rows(window)] == ["Alpha", "Beta", "Gamma"]
    header = window.games_list.horizontalHeader()
    assert (header.sortIndicatorSection(), header.sortIndicatorOrder()) == (0, Qt.SortOrder.AscendingOrder)


@pytest.mark.parametrize("order, expected", [
    (Qt.SortOrder.AscendingOrder, ["Alpha", "Gamma", "Beta"]),
    (Qt.SortOrder.DescendingOrder, ["Beta", "Gamma", "Alpha"]),
])
def test_sorting_by_size_counts_bytes_instead_of_reading_the_label(order, expected):
    # As text, "900.0 MB" outranks "1.2 GB" because 9 > 1. GOG's biggest games
    # would sink to the bottom of the "biggest first" list, which is a bold
    # take on "biggest".
    window = MainWindow()
    window.on_games_loaded(SIZED_GAMES)

    window.games_list.sortByColumn(1, order)

    assert _rows(window) == [(title, SIZE_TEXT[title]) for title in expected]


def test_reloading_keeps_the_size_sort_and_every_game_keeps_its_own_size():
    # Regression: filling the table with sorting on moves each row the moment
    # its title lands, so the size and Fetched cells get written into whatever
    # row is now sitting at that index. Games end up wearing each other's sizes,
    # or none at all.
    window = MainWindow()
    window.on_games_loaded(SIZED_GAMES)
    window.games_list.sortByColumn(1, Qt.SortOrder.DescendingOrder)

    window.on_games_loaded(SIZED_GAMES)

    assert _rows(window) == [(title, SIZE_TEXT[title]) for title in ["Beta", "Gamma", "Alpha"]]
    assert all(window.games_list.item(row, 2) is not None for row in range(3))


def test_doubleclick_after_sorting_queues_the_game_on_that_row_now():
    window = MainWindow()
    window.on_games_loaded(SIZED_GAMES)
    window.games_list.sortByColumn(1, Qt.SortOrder.DescendingOrder)
    window.download_window.add_to_queue = MagicMock(return_value=0)

    window.doubleclick_game_list(0, 0)

    window.download_window.add_to_queue.assert_called_once_with(
        {"product_id": 2, "title": "Beta", "size": SIZE_TEXT["Beta"]}
    )


def test_onclick_queue_download_adds_selected_game_title_once():
    # Regression: games_list has 3 columns per row under SelectRows, so
    # selectedItems() hands back 3 items for a single selected row. Naively
    # wiring that up would queue the same game 3 times instead of once.
    window = MainWindow()
    window.on_games_loaded([FAKE_GAME])  # selects row 0
    captured_calls = []
    # onclick_queue_download reuses and clears the same dict every call, so if
    # we just hang onto the reference we'll catch it after it's been wiped.
    # Snapshot a copy at call time instead, or this test lies to you.
    window.download_window.add_to_queue = MagicMock(
        side_effect=lambda row_data: captured_calls.append(dict(row_data))
    )

    window.onclick_queue_download()

    assert captured_calls == [{
        "product_id": FAKE_GAME["product_id"],
        "title": "Fake Game",
        "size": humanize.naturalsize(FAKE_GAME["download_size"]),
    }]


def test_onclick_queue_download_does_nothing_without_a_selection():
    window = MainWindow()
    window.on_games_loaded([FAKE_GAME])
    window.games_list.clearSelection()
    window.download_window.add_to_queue = MagicMock()

    window.onclick_queue_download()

    window.download_window.add_to_queue.assert_not_called()


@patch("gogstash.main.get_icon")
def test_color_scheme_refresh_reloads_each_toolbar_action_and_button_from_its_own_icon_file(mock_get_icon):
    # The Queue Selection button got an icon too, so it gets a seat on the
    # theme-change bus alongside the toolbar crew. The About button hopped
    # on later, question mark and all.
    mock_get_icon.return_value = _non_null_icon()
    window = MainWindow()
    mock_get_icon.reset_mock()

    window._color_scheme_refresh()

    called_files = {call.args[0] for call in mock_get_icon.call_args_list}
    assert called_files == {"login.svg", "logout.svg", "fetch.svg", "settings.svg", "question.svg", "enqueue.svg"}


def test_theme_change_mid_construction_doesnt_trip_over_half_built_widgets(monkeypatch):
    # Regression: on Windows, setColorScheme() fires colorSchemeChanged on the
    # spot, and the refresh used to be wired up before button_layout was even
    # born. Linux never emitted there, so it took Windows to notice. Here we
    # play the part of Windows. Qt swallows slot exceptions and hands them to
    # sys.excepthook, so that's where the evidence ends up.
    slot_errors = []
    monkeypatch.setattr("sys.excepthook", lambda _type, value, _tb: slot_errors.append(value))

    def set_color_theme_like_windows():
        hints = QApplication.instance().styleHints()
        hints.colorSchemeChanged.emit(Qt.ColorScheme.Dark)

    with patch("gogstash.main.SettingsDialog.set_color_theme", side_effect=set_color_theme_like_windows):
        MainWindow()

    assert slot_errors == []


def test_doubleclick_while_queue_is_busy_tells_the_user_to_hold_their_horses():
    window = MainWindow()
    window.on_games_loaded([FAKE_GAME])
    window.error_message.showMessage = MagicMock()
    window.download_window.add_to_queue = MagicMock(return_value=-1)

    window.doubleclick_game_list(0, 0)

    window.error_message.showMessage.assert_called_once_with(
        "Please wait for pending operations to complete before queuing downloads"
    )
    assert window.error_message.windowTitle() == "Error Queuing"


def test_doubleclick_that_queues_fine_keeps_its_damn_mouth_shut():
    window = MainWindow()
    window.on_games_loaded([FAKE_GAME])
    window.error_message.showMessage = MagicMock()
    window.download_window.add_to_queue = MagicMock(return_value=0)

    window.doubleclick_game_list(0, 0)

    window.error_message.showMessage.assert_not_called()


def test_toolbar_queue_while_busy_bitches_once_and_quits_trying():
    # Two games selected, queue's in the middle of a pause. One error popup,
    # not one per game, and no pointless retry on the second one.
    window = MainWindow()
    window.on_games_loaded([FAKE_GAME, FAKE_GAME_2])
    window.games_list.selectAll()
    window.error_message.showMessage = MagicMock()
    window.download_window.add_to_queue = MagicMock(return_value=-1)

    window.onclick_queue_download()

    window.download_window.add_to_queue.assert_called_once()
    window.error_message.showMessage.assert_called_once_with(
        "Please wait for pending operations to complete before queuing downloads"
    )
    assert window.error_message.windowTitle() == "Error Queuing"


def test_opening_settings_over_and_over_doesnt_hoard_dead_dialogs():
    # Regression: the main window parents each SettingsDialog, so dropping
    # the Python name did nothing and every open left one more behind.
    from PySide6.QtCore import QCoreApplication, QEvent
    from gogstash.main import SettingsDialog
    window = MainWindow()

    with patch.object(SettingsDialog, "exec", return_value=0):
        for _ in range(3):
            window.open_settings()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    assert window.findChildren(SettingsDialog) == []


def _fetched_by_title(window):
    table = window.games_list
    return {table.item(row, 0).text(): _is_fetched(window, row) for row in range(table.rowCount())}


def test_finished_download_flips_fetched_to_yes_without_a_reload(tmp_path):
    # Before this, the blank cell stuck around until the next library refresh, which is
    # a strange thing to tell someone whose game just finished downloading.
    update_setting("download_path", str(tmp_path))
    _stock_the_library([FAKE_GAME])
    window = MainWindow()
    window.on_games_loaded([FAKE_GAME])
    _record_installer(tmp_path, FAKE_GAME)

    _finish_download(window, FAKE_GAME)

    assert _fetched_by_title(window) == {"Fake Game": True}
    assert window.games_list.item(0, 2).toolTip() == "Fetched"


def test_finished_download_still_asks_the_manifest_before_saying_yes(tmp_path):
    # Success with nothing recorded (say the disk filled up before the record
    # landed) stays blank. The handler checks the receipts, it doesn't just
    # take the scheduler's word for it.
    update_setting("download_path", str(tmp_path))
    _stock_the_library([FAKE_GAME])
    window = MainWindow()
    window.on_games_loaded([FAKE_GAME])

    _finish_download(window, FAKE_GAME)

    assert _fetched_by_title(window) == {"Fake Game": False}
    assert window.games_list.item(0, 2).toolTip() == "Not Fetched"  # a blank cell still owes an explanation


def test_finished_download_finds_its_game_wherever_the_sort_put_it(tmp_path):
    # Gamma is queue row 0 but library row 1 once sorted biggest first. If the
    # row index ever sneaks across instead of the product ID, Beta gets the
    # credit for a game it never downloaded.
    update_setting("download_path", str(tmp_path))
    _stock_the_library(SIZED_GAMES)
    window = MainWindow()
    window.on_games_loaded(SIZED_GAMES)
    window.games_list.sortByColumn(1, Qt.SortOrder.DescendingOrder)
    gamma = SIZED_GAMES[0]
    _record_installer(tmp_path, gamma)

    _finish_download(window, gamma)

    assert _fetched_by_title(window) == {"Alpha": False, "Beta": False, "Gamma": True}


def test_finished_download_for_a_game_the_library_never_heard_of_changes_nothing(tmp_path):
    update_setting("download_path", str(tmp_path))
    _stock_the_library([FAKE_GAME])
    window = MainWindow()
    window.on_games_loaded([FAKE_GAME])

    window._on_game_succeeded(999)  # should shrug, not raise

    assert _fetched_by_title(window) == {"Fake Game": False}


def test_fetched_still_updates_after_the_queue_swaps_in_a_fresh_scheduler(tmp_path):
    # Stop and Clear Queue hand the queue a brand new scheduler. The library
    # listens to the queue rather than the scheduler, so it shouldn't notice
    # the staff change.
    update_setting("download_path", str(tmp_path))
    _stock_the_library([FAKE_GAME])
    window = MainWindow()
    window.on_games_loaded([FAKE_GAME])
    window.download_window._reset_scheduler()
    _record_installer(tmp_path, FAKE_GAME)

    _finish_download(window, FAKE_GAME)

    assert _fetched_by_title(window) == {"Fake Game": True}


def test_sorting_by_fetched_groups_the_downloaded_games_together(tmp_path):
    # Blank cells all have the same text, so without the stored flag every
    # row ties and the sort shrugs. Gamma is the one that's actually home.
    update_setting("download_path", str(tmp_path))
    _stock_the_library(SIZED_GAMES)
    _record_installer(tmp_path, SIZED_GAMES[0])
    window = MainWindow()
    window.on_games_loaded(SIZED_GAMES)

    window.games_list.sortByColumn(2, Qt.SortOrder.DescendingOrder)

    assert window.games_list.item(0, 0).text() == "Gamma"
    assert [_is_fetched(window, row) for row in range(3)] == [True, False, False]


def _tick_pixels(window, row):
    # Green-ish pixels in one Fetched cell, as (x, y) relative to the cell.
    table = window.games_list
    window.show()
    QApplication.processEvents()
    image = table.viewport().grab().toImage()
    cell = table.visualRect(table.model().index(row, 2))
    return [(x - cell.left(), y - cell.top())
            for x in range(cell.left(), cell.right() + 1)
            for y in range(cell.top(), cell.bottom() + 1)
            if (c := QColor(image.pixel(x, y))).green() > 100 and c.green() > c.red() + 30 and c.green() > c.blue()]


def test_fetched_tick_sits_in_the_middle_of_its_cell_and_nowhere_else(tmp_path):
    # Qt parks icons on the left edge unless told otherwise. A stray setIcon
    # would also sneak a second tick in over there, which is one tick too
    # many for a yes/no question.
    update_setting("download_path", str(tmp_path))
    _stock_the_library([FAKE_GAME, FAKE_GAME_2])
    _record_installer(tmp_path, FAKE_GAME)
    window = MainWindow()
    window.on_games_loaded([FAKE_GAME, FAKE_GAME_2])
    window.games_list.clearSelection()
    fetched_row = 0 if _is_fetched(window, 0) else 1

    tick = _tick_pixels(window, fetched_row)
    blank = _tick_pixels(window, 1 - fetched_row)

    width = window.games_list.columnWidth(2)
    xs = [x for x, _ in tick]
    assert blank == []
    assert abs((min(xs) + max(xs)) / 2 - width / 2) <= 3
    assert max(xs) - min(xs) < 16  # one tick, not a tick and its evil twin
