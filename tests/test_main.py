import gc
import sys
import time
from unittest.mock import MagicMock, patch

import humanize
import pytest
from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from gogstash import gog_auth, library_db, manifest
from gogstash.login_window import ExitCode
from gogstash.download_window import DownloadState
from gogstash.main import MainWindow
from gogstash.settings import update_setting
from tests.fakes import gog_product


def _non_null_icon():
    # A plain QIcon() is null, and _color_scheme_refresh's "skip icon-less
    # entries" guard would then treat every recolored button as icon-less too.
    return QIcon(QPixmap(4, 4))


FAKE_GAME = {"product_id": 111, "parent_id": None, "title": "Fake Game", "slug": "fake-game", "download_size": 2048}
FAKE_GAME_2 = {"product_id": 222, "parent_id": None, "title": "Second Fake Game", "slug": "second-fake-game", "download_size": 4096}


def _stock_the_library(games, bonus=False, version=None):
    # Fetched means "every file the settings pick is on disk", so the DB has
    # to list some files. One 5 byte installer per game, plus a 5 byte manual
    # for the ones that came with homework. A game with a parent_id goes in
    # as that game's DLC, so the cache knows whose folder it lives in.
    library_db.update_cache([gog_product(
        game["product_id"], game["title"], game["slug"], osx=False,
        game_type="dlc" if game.get("parent_id") else "game",
        dlcs=[g["product_id"] for g in games if g.get("parent_id") == game["product_id"]],
        downloads={
            "installers": [{
                "id": "installer_windows_en", "name": game["title"], "os": "windows", "language": "en", "total_size": 5,
                "version": version,
                "files": [{"id": "setup", "size": 5, "downlink": f"https://example.com/{game['slug']}/setup"}],
            }],
            "bonus_content": [{
                "id": 1, "name": "manual", "type": "manuals", "total_size": 5,
                "files": [{"id": "manual", "size": 5, "downlink": f"https://example.com/{game['slug']}/manual"}],
            }] if bonus else [],
        },
    ) for game in games])


def _record(download_dir, game, category, folder=None):
    # Writes the file and its manifest entry with the same downlink and listed
    # size the DB has, so this passes for "downlink is in the manifest" and
    # for the stricter check_exist_by_downlink alike. A DLC passes its base
    # game's slug as the folder, and the file name carries the product's own
    # slug so roommates don't overwrite each other's manifest entries.
    game_dir = download_dir / (folder or game["slug"])
    name = "setup" if category == "installers" else "manual"
    path = game_dir / category / f"{game['slug']}-{name}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"hello")
    manifest.add_file(game_dir, path, category=category, downlink=f"https://example.com/{game['slug']}/{name}", db_size=5, checksum="abc", version=None, timestamp=1.0)


def _record_installer(download_dir, game, folder=None):
    _record(download_dir, game, "installers", folder)


def _row(window, row):
    # One tree item per game, all three columns in one object. The table used
    # to hand out a separate object per cell, like a bank teller per coin.
    return window.games_list.topLevelItem(row)


def _row_count(window):
    return window.games_list.topLevelItemCount()


def _is_fetched(window, row):
    # The Fetched cell is all icon and no text now, so ask it what it
    # believes rather than reading what it says.
    return _row(window, row).data(2, Qt.ItemDataRole.UserRole)


def _finish_download(window, game):
    # Same trip a real download takes: the scheduler reports the product ID,
    # the queue paints its row and passes the ID on, the library takes it
    # from there.
    window.download_window.add_to_queue({"product_id": game["product_id"], "title": game["title"], "size": "5 Bytes"})
    window.download_window.scheduler.game_succeeded.emit(game["product_id"])


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


@pytest.fixture
def login_window(monkeypatch):
    # A MainWindow whose login QProcess has had its start() swapped out, so
    # clicking Log in records what would have run instead of popping a real
    # GOG window on whoever is running the tests. The signals are still the
    # real ones, so emitting finished/errorOccurred exercises the actual
    # wiring in __init__.
    window = MainWindow()
    monkeypatch.setattr(window.login_process, "start", MagicMock())
    return window


@pytest.fixture
def paste_dialog():
    with patch("gogstash.main.ExternalLoginDialog") as mock_external_cls:
        mock_external_cls.return_value.exec.return_value = QDialog.DialogCode.Rejected
        yield mock_external_cls


@pytest.fixture
def warning_box():
    # QMessageBox.warning is modal, and a modal box in a headless test is a
    # very patient way to never finish.
    with patch("gogstash.main.QMessageBox.warning") as mock_warning:
        yield mock_warning


def test_open_login_window_runs_helper_module_from_source(login_window, monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)

    login_window.open_login_window()

    login_window.login_process.start.assert_called_once_with(sys.executable, ["-m", "gogstash.login_window"])
    # From source there's no PyInstaller bootloader to reset, so the helper
    # just inherits our environment untouched.
    assert login_window.login_process.processEnvironment().isEmpty()
    assert not login_window.login_internal_action.isEnabled()


def test_open_login_window_frozen_reruns_itself_with_flag_and_fresh_bootloader(login_window, monkeypatch):
    # Regression: the frozen check once defaulted to True with its branches
    # swapped. From source the two mistakes cancelled out; in the AppImage
    # they'd have answered "Log in" with a second copy of the whole app.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("GOGSTASH_TEST_PASSENGER", "still here")

    login_window.open_login_window()

    login_window.login_process.start.assert_called_once_with(sys.executable, ["--login-helper"])
    env = login_window.login_process.processEnvironment()
    # Without this the helper's bootloader thinks setup already happened
    # and never puts the bundled libraries on its path.
    assert env.value("PYINSTALLER_RESET_ENVIRONMENT") == "1"
    # ...and the rest of our environment rides along with it.
    assert env.value("GOGSTASH_TEST_PASSENGER") == "still here"
    assert not login_window.login_internal_action.isEnabled()


def test_helper_success_refreshes_status_and_reenables_login(login_window, paste_dialog):
    # The helper saves the token itself, so all we do is re-read it.
    gog_auth.save_token({"access_token": "abc", "expiry": time.time() + 3600})
    login_window.status_text.setText("stale")  # will be overwritten if the refresh runs
    login_window.open_login_window()

    login_window.login_process.finished.emit(ExitCode.EXIT_OK, QProcess.ExitStatus.NormalExit)

    assert login_window.status_text.text() == "Logged in"
    assert login_window.login_internal_action.isEnabled()
    paste_dialog.assert_not_called()


def test_helper_cancel_changes_nothing_but_reenables_login(login_window, paste_dialog, warning_box):
    login_window.status_text.setText("stale")
    login_window.open_login_window()

    login_window.login_process.finished.emit(ExitCode.EXIT_CANCELLED, QProcess.ExitStatus.NormalExit)

    assert login_window.status_text.text() == "stale"
    assert login_window.login_internal_action.isEnabled()
    paste_dialog.assert_not_called()
    warning_box.assert_not_called()


def test_helper_token_error_warns_instead_of_offering_paste_dialog(login_window, paste_dialog, warning_box):
    # The webview worked fine, GOG just didn't hand over a token. Sending
    # people to the paste dialog would have them log in a second time for
    # the same outcome.
    login_window.open_login_window()

    login_window.login_process.finished.emit(ExitCode.EXIT_TOKEN_ERROR, QProcess.ExitStatus.NormalExit)

    warning_box.assert_called_once()
    paste_dialog.assert_not_called()
    assert login_window.login_internal_action.isEnabled()


@pytest.mark.parametrize("exit_code", [
    ExitCode.EXIT_NO_WEBVIEW,
    1,  # GTK's own exit(1) when it can't open a display, or a plain traceback
])
def test_helper_without_a_working_webview_falls_back_to_paste_dialog(login_window, paste_dialog, warning_box, exit_code):
    login_window.open_login_window()

    login_window.login_process.finished.emit(exit_code, QProcess.ExitStatus.NormalExit)

    paste_dialog.assert_called_once_with(login_window)
    warning_box.assert_not_called()
    assert login_window.login_internal_action.isEnabled()


def test_helper_crash_opens_paste_dialog_once_even_when_signal_looks_like_ours(login_window, paste_dialog, warning_box):
    # On a crash Qt hands over the killing signal's number as the exit code.
    # SIGILL is 4, which happens to be EXIT_TOKEN_ERROR. Regression too: the
    # crash branch once fell through into the match and opened the paste
    # dialog twice.
    login_window.open_login_window()

    login_window.login_process.finished.emit(4, QProcess.ExitStatus.CrashExit)

    paste_dialog.assert_called_once_with(login_window)
    warning_box.assert_not_called()
    assert login_window.login_internal_action.isEnabled()


def test_helper_that_never_starts_falls_back_and_reenables_login(login_window, paste_dialog):
    # FailedToStart is the one failure where finished never fires, so this
    # handler is the only thing standing between the user and a Log in item
    # that stays grey until restart.
    login_window.open_login_window()

    login_window.login_process.errorOccurred.emit(QProcess.ProcessError.FailedToStart)

    paste_dialog.assert_called_once_with(login_window)
    assert login_window.login_internal_action.isEnabled()


def test_other_process_errors_leave_login_disabled_while_helper_runs(login_window, paste_dialog):
    # A read error doesn't mean the helper is gone. Re-enabling here would
    # let a second click try to start a process that's already running.
    login_window.open_login_window()

    login_window.login_process.errorOccurred.emit(QProcess.ProcessError.ReadError)

    paste_dialog.assert_not_called()
    assert not login_window.login_internal_action.isEnabled()


def test_login_button_opens_a_menu_with_both_ways_in():
    # The whole point of the menu: people whose built-in login window breaks
    # need to reach the browser option without going through that window.
    window = MainWindow()
    button = window.main_toolbar.widgetForAction(window.login_button)

    assert window.login_button.menu() is window.login_menu
    assert button.popupMode() == button.ToolButtonPopupMode.InstantPopup
    assert [action.text() for action in window.login_menu.actions()] == [
        "Log in through GogStash",
        "Log in with your browser",
    ]


def test_login_menu_items_start_their_own_logins(login_window, paste_dialog):
    login_window.login_external_action.trigger()
    paste_dialog.assert_called_once_with(login_window)
    login_window.login_process.start.assert_not_called()

    login_window.login_internal_action.trigger()
    login_window.login_process.start.assert_called_once()
    paste_dialog.assert_called_once()  # still just the one from before


@patch("gogstash.main.ExternalLoginDialog")
def test_open_external_login_refreshes_status_when_accepted(mock_external_cls):
    mock_external_cls.return_value.exec.return_value = QDialog.DialogCode.Accepted
    gog_auth.save_token({"access_token": "abc", "expiry": time.time() + 3600})
    window = MainWindow()
    window.status_text.setText("stale")

    window.open_external_login()

    mock_external_cls.assert_called_once_with(window)
    assert window.status_text.text() == "Logged in"


@patch("gogstash.main.ExternalLoginDialog")
def test_open_external_login_leaves_status_untouched_when_rejected(mock_external_cls):
    mock_external_cls.return_value.exec.return_value = QDialog.DialogCode.Rejected
    window = MainWindow()
    window.status_text.setText("stale")

    window.open_external_login()

    assert window.status_text.text() == "stale"


@patch("gogstash.main.SettingsDialog")
def test_open_settings_constructs_and_executes_dialog(mock_settings_dialog_cls):
    window = MainWindow()

    window.open_settings()

    mock_settings_dialog_cls.assert_called_once_with(window)
    mock_settings_dialog_cls.return_value.exec.assert_called_once()


def _answer_about_page(then=None):
    # About is a modal exec(), so whoever closes it has to be waiting in the
    # event loop already. Polls until the box shows up, optionally does
    # something with it, then presses OK. Gives up after a couple of
    # seconds, so a box that never opens doesn't leave a timer lurking
    # around to press OK on some later test's dialog.
    deadline = time.monotonic() + 2

    def poll():
        box = QApplication.activeModalWidget()
        if isinstance(box, QMessageBox) and box.windowTitle() == "About GogStash":
            if then:
                then(box)
            box.accept()
        elif time.monotonic() < deadline:
            QTimer.singleShot(20, poll)

    QTimer.singleShot(0, poll)


def test_about_page_closes_without_taking_the_app_with_it():
    # Regression: the About Qt button's slot once captured the About box
    # itself. On Python 3.14 with PySide6 6.11.2, the garbage collector
    # untangled that cycle while PySide was still using the connection,
    # and closing About took the whole app down (on Windows, a crash in
    # ucrtbase.dll). On 3.14 this fails by aborting the test run, which is
    # loud, if not polite.
    window = MainWindow()

    for _ in range(3):
        _answer_about_page()
        window.open_about_page()
        gc.collect()

    # Getting here at all is most of the test. This is the rest.
    assert QApplication.activeModalWidget() is None


def test_about_qt_opens_over_the_main_window_not_the_about_box():
    # The fix for the crash above, pinned down: the About Qt slot only
    # knows the main window, so there's no cycle back to the About box for
    # the collector to trip over.
    window = MainWindow()

    def press_about_qt(box):
        next(b for b in box.buttons() if b.text() == "About Qt").click()

    with patch.object(QMessageBox, "aboutQt") as mock_about_qt:
        _answer_about_page(then=press_about_qt)
        window.open_about_page()

    mock_about_qt.assert_called_once_with(window)


@patch("gogstash.library_db.LibraryFetchThread")
def test_fetch_games_wires_up_thread_signals_and_starts_it(mock_thread_cls):
    # Login status isn't checked here anymore -- the thread resolves its own
    # token and reports back via auth_failure if there isn't one, so this
    # just has to prove the wiring/start happens regardless.
    window = MainWindow()

    window.fetch_games()

    mock_thread_cls.assert_called_once_with(force=True)
    mock_thread_instance = mock_thread_cls.return_value
    mock_thread_instance.succeeded.connect.assert_called_once_with(window._on_games_loaded)
    mock_thread_instance.failed.connect.assert_called_once_with(window.fetch_failed_handler)
    mock_thread_instance.auth_failure.connect.assert_called_once_with(window.on_auth_failure)
    mock_thread_instance.progress.connect.assert_called_once_with(window.update_fetch_progress)
    # Regression: this was once written as finished(...) without .connect.
    # A mock happily accepts being called like that; the real signal raised
    # and took the Refresh button down with it.
    mock_thread_instance.finished.connect.assert_called_once_with(window._on_fetch_finished)
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


def test_on_games_loaded_populates_the_list_with_games(tmp_path):
    update_setting("download_path", str(tmp_path))  # no manifest under here for "fake-game"
    window = MainWindow()

    window._on_games_loaded([FAKE_GAME])

    assert _row_count(window) == 1
    assert _row(window, 0).text(0) == "Fake Game"
    assert _is_fetched(window, 0) is False
    assert _row(window, 0).toolTip(2) == "Not Fetched"


def test_on_games_loaded_marks_fetched_when_every_selected_file_is_in_the_manifest(tmp_path):
    update_setting("download_path", str(tmp_path))
    _stock_the_library([FAKE_GAME])
    _record_installer(tmp_path, FAKE_GAME)
    window = MainWindow()

    window._on_games_loaded([FAKE_GAME])

    assert _is_fetched(window, 0) is True
    assert _row(window, 0).toolTip(2) == "Fetched"


def test_on_games_loaded_does_not_mark_fetched_for_bonus_content_alone(tmp_path):
    # A manual on disk is not the game on disk. With bonus content switched
    # off the manual isn't even on the shopping list, so it can't vouch for
    # the installer that never showed up.
    update_setting("download_path", str(tmp_path))
    _stock_the_library([FAKE_GAME], bonus=True)
    _record(tmp_path, FAKE_GAME, "bonus_content")
    window = MainWindow()

    window._on_games_loaded([FAKE_GAME])

    assert _is_fetched(window, 0) is False


def test_on_games_loaded_marks_an_extras_only_game_fetched_without_its_installer(tmp_path):
    # #13 flips the test above on its head: with installers unticked, the
    # manual is the whole shopping list, and the installer stays off it.
    update_setting("download_path", str(tmp_path))
    update_setting("installers", False)
    update_setting("bonus_content", True)
    _stock_the_library([FAKE_GAME], bonus=True)
    _record(tmp_path, FAKE_GAME, "bonus_content")
    window = MainWindow()

    window._on_games_loaded([FAKE_GAME])

    assert _is_fetched(window, 0) is True


def test_on_games_loaded_does_not_mark_a_half_finished_game_fetched(tmp_path):
    # Issue #3's other half: the installer made it, the manual didn't. One
    # out of two used to be good enough for a tick.
    update_setting("download_path", str(tmp_path))
    update_setting("bonus_content", True)
    _stock_the_library([FAKE_GAME], bonus=True)
    _record_installer(tmp_path, FAKE_GAME)
    window = MainWindow()

    window._on_games_loaded([FAKE_GAME])

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

    window._on_games_loaded([FAKE_GAME])

    assert _is_fetched(window, 0) is False


def test_on_games_loaded_replaces_previous_rows_not_appends():
    window = MainWindow()
    window._on_games_loaded([FAKE_GAME])

    window._on_games_loaded([FAKE_GAME_2])

    assert _row_count(window) == 1
    assert _row(window, 0).text(0) == "Second Fake Game"


def test_on_games_loaded_with_an_empty_library_selects_nothing_and_survives():
    # topLevelItem(0) on an empty tree is None, and setCurrentItem(None) has
    # to take that in stride. A fresh install's first launch depends on it.
    window = MainWindow()

    window._on_games_loaded([])

    assert _row_count(window) == 0
    assert window.games_list.currentItem() is None


# Size order (Alpha < Gamma < Beta) disagrees with both title order and the
# order they arrive in, so no test here can pass by accident.
SIZED_GAMES = [
    {"product_id": 3, "parent_id": None, "title": "Gamma", "slug": "gamma", "download_size": 900_000_000},
    {"product_id": 1, "parent_id": None, "title": "Alpha", "slug": "alpha", "download_size": 50_000},
    {"product_id": 2, "parent_id": None, "title": "Beta", "slug": "beta", "download_size": 1_200_000_000},
]
SIZE_TEXT = {g["title"]: humanize.naturalsize(g["download_size"]) for g in SIZED_GAMES}


def _rows(window):
    return [(_row(window, row).text(0), _row(window, row).text(1)) for row in range(_row_count(window))]


def test_library_starts_out_sorted_by_title_a_to_z():
    # Qt's out-of-the-box sort is Z to A, and before sortByColumn showed up the
    # header's sort column had wandered off to section 3, which doesn't exist.
    window = MainWindow()

    window._on_games_loaded(SIZED_GAMES)

    assert [title for title, _ in _rows(window)] == ["Alpha", "Beta", "Gamma"]
    header = window.games_list.header()
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
    window._on_games_loaded(SIZED_GAMES)

    window.games_list.sortByColumn(1, order)

    assert _rows(window) == [(title, SIZE_TEXT[title]) for title in expected]


def test_reloading_keeps_the_size_sort_and_every_game_keeps_its_own_size():
    # Regression: filling the table with sorting on moves each row the moment
    # its title lands, so the size and Fetched cells get written into whatever
    # row is now sitting at that index. Games end up wearing each other's sizes,
    # or none at all. A tree row carries all its columns in one object, so it
    # can't lose them in transit anymore, but trust is earned.
    window = MainWindow()
    window._on_games_loaded(SIZED_GAMES)
    window.games_list.sortByColumn(1, Qt.SortOrder.DescendingOrder)

    window._on_games_loaded(SIZED_GAMES)

    assert _rows(window) == [(title, SIZE_TEXT[title]) for title in ["Beta", "Gamma", "Alpha"]]
    assert all(_is_fetched(window, row) is not None for row in range(3))


def test_doubleclick_after_sorting_queues_the_game_on_that_row_now():
    window = MainWindow()
    window._on_games_loaded(SIZED_GAMES)
    window.games_list.sortByColumn(1, Qt.SortOrder.DescendingOrder)
    window.download_window.add_to_queue = MagicMock(return_value=0)

    window.doubleclick_game_list(_row(window, 0), 0)

    window.download_window.add_to_queue.assert_called_once_with(
        {"product_id": 2, "title": "Beta", "size": SIZE_TEXT["Beta"]}
    )


def test_onclick_queue_download_adds_selected_game_title_once():
    # Regression: back when games_list was a table, selectedItems() handed back
    # one item per cell, so 3 for a single selected row. Naively wiring that up
    # queued the same game 3 times. The tree hands back one per row, and this
    # makes sure nobody brings the cell-counting habit back.
    window = MainWindow()
    window._on_games_loaded([FAKE_GAME])  # selects row 0
    captured_calls = []
    # onclick_queue_download reuses the same dict across games, so if we just
    # hang onto the reference we'll catch it after the next game moved in.
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
    window._on_games_loaded([FAKE_GAME])
    window.games_list.clearSelection()
    window.download_window.add_to_queue = MagicMock()

    window.onclick_queue_download()

    window.download_window.add_to_queue.assert_not_called()


@patch("gogstash.main.get_icon")
def test_color_scheme_refresh_reloads_each_toolbar_action_and_button_from_its_own_icon_file(mock_get_icon):
    # The Queue Selection button got an icon too, so it gets a seat on the
    # theme-change bus alongside the toolbar crew. The About button hopped
    # on later, question mark and all. Then the theme picker itself, which
    # would be embarrassing to leave in the wrong colors.
    mock_get_icon.return_value = _non_null_icon()
    window = MainWindow()
    mock_get_icon.reset_mock()

    window._color_scheme_refresh()

    called_files = {call.args[0] for call in mock_get_icon.call_args_list}
    assert called_files == {
        "login.svg", "logout.svg", "fetch.svg", "download_folder.svg", "settings.svg", "theme_mode.svg",
        "question.svg", "enqueue.svg",
    }


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
    window._on_games_loaded([FAKE_GAME])
    window.error_message.showMessage = MagicMock()
    window.download_window.add_to_queue = MagicMock(return_value=-1)

    window.doubleclick_game_list(_row(window, 0), 0)

    window.error_message.showMessage.assert_called_once_with(
        "Please wait for pending operations to complete before queuing downloads"
    )
    assert window.error_message.windowTitle() == "Error Queuing"


def test_doubleclick_that_queues_fine_keeps_its_damn_mouth_shut():
    window = MainWindow()
    window._on_games_loaded([FAKE_GAME])
    window.error_message.showMessage = MagicMock()
    window.download_window.add_to_queue = MagicMock(return_value=0)

    window.doubleclick_game_list(_row(window, 0), 0)

    window.error_message.showMessage.assert_not_called()


def test_toolbar_queue_while_busy_bitches_once_and_quits_trying():
    # Two games selected, queue's in the middle of a pause. One error popup,
    # not one per game, and no pointless retry on the second one.
    window = MainWindow()
    window._on_games_loaded([FAKE_GAME, FAKE_GAME_2])
    window.games_list.selectAll()
    # Without this, a single-selection list turns selectAll() into a no-op,
    # one game gets tried, and the test passes for entirely the wrong reason.
    # Ask the tree that went single-selection behind everyone's back.
    assert len(window.games_list.selectedItems()) == 2
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


def test_settings_locks_while_downloads_are_busy_and_unlocks_once_idle():
    # #26: moving the download folder under a paused game's .part file made
    # it start over from zero, so Settings sits out the whole run, pause
    # included, and says why instead of just going grey and silent.
    from gogstash.download_window import DownloadState
    window = MainWindow()
    assert window.settings_button.isEnabled() is True
    assert window.settings_button.toolTip() == "Settings (Ctrl+,)"

    window.download_window.current_state = DownloadState.RUNNING
    assert window.settings_button.isEnabled() is False
    assert window.settings_button.toolTip() == "Can't change settings while downloads are running or paused"

    window.download_window.current_state = DownloadState.PAUSED
    assert window.settings_button.isEnabled() is False

    window.download_window.current_state = DownloadState.IDLE
    assert window.settings_button.isEnabled() is True
    assert window.settings_button.toolTip() == "Settings (Ctrl+,)"


def _press_ctrl_comma(window):
    # Window shortcuts only fire for the active window, and offscreen there
    # is nobody else to fight over focus with.
    window.show()
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    QTest.keyClick(window, Qt.Key.Key_Comma, Qt.KeyboardModifier.ControlModifier)


@patch("gogstash.main.SettingsDialog")
def test_ctrl_comma_opens_settings(mock_settings_dialog_cls):
    window = MainWindow()

    _press_ctrl_comma(window)

    mock_settings_dialog_cls.return_value.exec.assert_called_once()


@patch("gogstash.main.SettingsDialog")
def test_ctrl_comma_is_locked_out_along_with_the_button(mock_settings_dialog_cls):
    # A greyed-out button with a working back door is just a suggestion.
    from gogstash.download_window import DownloadState
    window = MainWindow()
    window.download_window.current_state = DownloadState.RUNNING

    _press_ctrl_comma(window)

    mock_settings_dialog_cls.assert_not_called()


def _fetched_by_title(window):
    return {_row(window, row).text(0): _is_fetched(window, row) for row in range(_row_count(window))}


def test_finished_download_flips_fetched_to_yes_without_a_reload(tmp_path):
    # Before this, the blank cell stuck around until the next library refresh, which is
    # a strange thing to tell someone whose game just finished downloading.
    update_setting("download_path", str(tmp_path))
    _stock_the_library([FAKE_GAME])
    window = MainWindow()
    window._on_games_loaded([FAKE_GAME])
    _record_installer(tmp_path, FAKE_GAME)

    _finish_download(window, FAKE_GAME)

    assert _fetched_by_title(window) == {"Fake Game": True}
    assert _row(window, 0).toolTip(2) == "Fetched"


def test_finished_download_still_asks_the_manifest_before_saying_yes(tmp_path):
    # Success with nothing recorded (say the disk filled up before the record
    # landed) stays blank. The handler checks the receipts, it doesn't just
    # take the scheduler's word for it.
    update_setting("download_path", str(tmp_path))
    _stock_the_library([FAKE_GAME])
    window = MainWindow()
    window._on_games_loaded([FAKE_GAME])

    _finish_download(window, FAKE_GAME)

    assert _fetched_by_title(window) == {"Fake Game": False}
    assert _row(window, 0).toolTip(2) == "Not Fetched"  # a blank cell still owes an explanation


def test_finished_download_finds_its_game_wherever_the_sort_put_it(tmp_path):
    # Gamma is queue row 0 but library row 1 once sorted biggest first. If the
    # row index ever sneaks across instead of the product ID, Beta gets the
    # credit for a game it never downloaded.
    update_setting("download_path", str(tmp_path))
    _stock_the_library(SIZED_GAMES)
    window = MainWindow()
    window._on_games_loaded(SIZED_GAMES)
    window.games_list.sortByColumn(1, Qt.SortOrder.DescendingOrder)
    gamma = SIZED_GAMES[0]
    _record_installer(tmp_path, gamma)

    _finish_download(window, gamma)

    assert _fetched_by_title(window) == {"Alpha": False, "Beta": False, "Gamma": True}


def test_finished_download_for_a_game_the_library_never_heard_of_changes_nothing(tmp_path):
    update_setting("download_path", str(tmp_path))
    _stock_the_library([FAKE_GAME])
    window = MainWindow()
    window._on_games_loaded([FAKE_GAME])

    window._on_game_succeeded(999)  # should shrug, not raise

    assert _fetched_by_title(window) == {"Fake Game": False}


def test_fetched_still_updates_after_the_queue_swaps_in_a_fresh_scheduler(tmp_path):
    # Stop and Clear Queue hand the queue a brand new scheduler. The library
    # listens to the queue rather than the scheduler, so it shouldn't notice
    # the staff change.
    update_setting("download_path", str(tmp_path))
    _stock_the_library([FAKE_GAME])
    window = MainWindow()
    window._on_games_loaded([FAKE_GAME])
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
    window._on_games_loaded(SIZED_GAMES)

    window.games_list.sortByColumn(2, Qt.SortOrder.DescendingOrder)

    assert _row(window, 0).text(0) == "Gamma"
    assert [_is_fetched(window, row) for row in range(3)] == [True, False, False]


def _tick_pixels(window, row):
    # Green-ish pixels in one Fetched cell, as (x, y) relative to the cell.
    tree = window.games_list
    window.show()
    QApplication.processEvents()
    image = tree.viewport().grab().toImage()
    cell = tree.visualRect(tree.model().index(row, 2))
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
    window._on_games_loaded([FAKE_GAME, FAKE_GAME_2])
    window.games_list.clearSelection()
    fetched_row = 0 if _is_fetched(window, 0) else 1

    tick = _tick_pixels(window, fetched_row)
    blank = _tick_pixels(window, 1 - fetched_row)

    width = window.games_list.columnWidth(2)
    xs = [x for x, _ in tick]
    assert blank == []
    assert abs((min(xs) + max(xs)) / 2 - width / 2) <= 3
    assert max(xs) - min(xs) < 16  # one tick, not a tick and its evil twin


# A base game with two DLCs. Sizes disagree with title order so the
# child sort can't pass by accident.
CULTIST = {"product_id": 10, "parent_id": None, "title": "Cultist Simulator", "slug": "cultist-simulator", "download_size": 400}
DANCER = {"product_id": 11, "parent_id": 10, "title": "Cultist Simulator: The Dancer", "slug": "cultist-simulator-the-dancer", "download_size": 300}
PRIEST = {"product_id": 12, "parent_id": 10, "title": "Cultist Simulator: The Priest", "slug": "cultist-simulator-the-priest", "download_size": 100}


def _children(item):
    return [item.child(i).text(0) for i in range(item.childCount())]


def test_dlcs_sit_under_their_base_game_not_next_to_it():
    window = MainWindow()

    window._on_games_loaded([CULTIST, DANCER, PRIEST, FAKE_GAME])

    assert [_row(window, row).text(0) for row in range(_row_count(window))] == ["Cultist Simulator", "Fake Game"]
    assert _children(_row(window, 0)) == ["Cultist Simulator: The Dancer", "Cultist Simulator: The Priest"]
    assert _row(window, 1).childCount() == 0


def test_a_dlc_listed_before_its_base_game_still_finds_its_way_home():
    # SQLite hands rows back in whatever order it likes. A DLC that shows up
    # first can't be attached to a parent row that doesn't exist yet.
    window = MainWindow()

    window._on_games_loaded([PRIEST, DANCER, CULTIST])

    assert _row_count(window) == 1
    assert _children(_row(window, 0)) == ["Cultist Simulator: The Dancer", "Cultist Simulator: The Priest"]


def test_a_dlc_whose_base_game_is_missing_gets_its_own_row_instead_of_vanishing():
    # Regression: the fallback parent used to be a fresh row that never made
    # it into the tree, so the DLC was adopted by a ghost and never seen again.
    window = MainWindow()

    window._on_games_loaded([DANCER, FAKE_GAME])

    assert sorted(_row(window, row).text(0) for row in range(_row_count(window))) == ["Cultist Simulator: The Dancer", "Fake Game"]


def test_sorting_by_size_shuffles_dlcs_within_their_game_and_leaves_them_there():
    window = MainWindow()
    window._on_games_loaded([CULTIST, DANCER, PRIEST, FAKE_GAME])

    window.games_list.sortByColumn(1, Qt.SortOrder.AscendingOrder)

    assert [_row(window, row).text(0) for row in range(_row_count(window))] == ["Cultist Simulator", "Fake Game"]
    assert _children(_row(window, 0)) == ["Cultist Simulator: The Priest", "Cultist Simulator: The Dancer"]


def test_doubleclick_on_a_dlc_queues_the_dlc_not_its_base_game():
    window = MainWindow()
    window._on_games_loaded([CULTIST, DANCER])
    window.download_window.add_to_queue = MagicMock(return_value=0)

    window.doubleclick_game_list(_row(window, 0).child(0), 0)

    window.download_window.add_to_queue.assert_called_once_with(
        {"product_id": 11, "title": "Cultist Simulator: The Dancer", "size": humanize.naturalsize(300)}
    )


def test_doubleclick_on_a_game_with_dlcs_queues_instead_of_folding_it_up():
    # Double-click means "download this" here. Qt's habit of also toggling
    # the row would turn every queued game into a surprise accordion.
    window = MainWindow()
    window._on_games_loaded([CULTIST, DANCER])
    window.show()
    QApplication.processEvents()
    tree = window.games_list
    rect = tree.visualItemRect(_row(window, 0))
    assert _row(window, 0).isExpanded()  # DLCs start out on display

    # A real double-click opens with a plain click, and the tree only toggles
    # rows it saw pressed first. QTest's double-click alone skips that part.
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    QTest.mouseDClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())

    assert _row(window, 0).isExpanded()


def test_finished_dlc_download_ticks_the_dlc_row_tucked_under_its_game(tmp_path):
    # The old lookup only walked top-level rows, so a DLC's tick would have
    # gone looking for it in all the wrong places. The DLC's file sits in its
    # base game's folder, which is where the tick has to look for it too.
    update_setting("download_path", str(tmp_path))
    _stock_the_library([CULTIST, DANCER])
    window = MainWindow()
    window._on_games_loaded(library_db.get_product_listing())
    _record_installer(tmp_path, DANCER, folder=CULTIST["slug"])

    _finish_download(window, DANCER)

    dancer_row = _row(window, 0).child(0)
    assert dancer_row.data(2, Qt.ItemDataRole.UserRole) is True
    assert dancer_row.toolTip(2) == "Fetched"
    assert _is_fetched(window, 0) is False  # the base game didn't lift a finger


def test_finished_download_for_a_game_dropped_by_the_last_refresh_changes_nothing():
    # Regression: clear() deletes the old rows, but the product ID lookup kept
    # pointing at them. A refunded game finishing its download then poked a
    # dead row and PySide raised "Internal C++ object already deleted".
    window = MainWindow()
    window._on_games_loaded([FAKE_GAME, FAKE_GAME_2])
    window._on_games_loaded([FAKE_GAME_2])

    window._on_game_succeeded(FAKE_GAME["product_id"])  # should shrug, not raise

    assert _row_count(window) == 1


def _queued_titles(window):
    calls = window.download_window.add_to_queue.call_args_list
    return sorted(call.args[0]["title"] for call in calls)


def test_ctrl_a_then_queue_selection_queues_the_whole_library_dlcs_included():
    # Regression: QTreeWidget ships in single-selection mode where the table
    # was extended, so Ctrl+A did nothing and bulk queuing, the entire point
    # of the app, quietly left the building. Ctrl+A also only grabs rows you
    # can see, so the DLCs have to start out unfolded to come along.
    window = MainWindow()
    window._on_games_loaded([CULTIST, DANCER, PRIEST, FAKE_GAME])
    window.download_window.add_to_queue = MagicMock(return_value=0)
    window.show()
    QApplication.processEvents()
    window.games_list.setFocus()

    QTest.keyClick(window.games_list, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    window.onclick_queue_download()

    assert _queued_titles(window) == [
        "Cultist Simulator", "Cultist Simulator: The Dancer", "Cultist Simulator: The Priest", "Fake Game",
    ]


def test_ctrl_click_adds_a_second_game_instead_of_swapping_the_first_one_out():
    window = MainWindow()
    window._on_games_loaded(SIZED_GAMES)  # Alpha, Beta, Gamma, with Alpha selected
    window.download_window.add_to_queue = MagicMock(return_value=0)
    window.show()
    QApplication.processEvents()
    tree = window.games_list
    gamma = tree.visualItemRect(_row(window, 2)).center()

    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, gamma)
    window.onclick_queue_download()

    assert _queued_titles(window) == ["Alpha", "Gamma"]


def test_a_new_installer_version_takes_the_check_mark_away_even_at_the_same_size(tmp_path):
    # #24: GOG's listed sizes are rounded, so a small patch can look identical
    # on paper. The version is the one detail that can't keep a straight face.
    update_setting("download_path", str(tmp_path))
    _stock_the_library([FAKE_GAME])
    _record_installer(tmp_path, FAKE_GAME)  # recorded on version None, matching the cache
    _stock_the_library([FAKE_GAME], version="1.1")
    window = MainWindow()

    window._on_games_loaded([FAKE_GAME])

    assert _is_fetched(window, 0) is False


def _theme_action(window, label):
    return next(a for a in window.theme_toggle_group.actions() if a.text() == label)


def test_picking_a_theme_saves_it_before_applying_it():
    # set_color_theme reads the theme back from disk, so the order matters.
    # Apply first and you get last time's theme, a very confident one-click lag.
    from gogstash import settings
    window = MainWindow()
    applied_with = []

    with patch("gogstash.main.SettingsDialog.set_color_theme",
               side_effect=lambda: applied_with.append(settings.read_setting("theme"))):
        _theme_action(window, "Light").trigger()

    assert applied_with == ["Light"]
    assert _theme_action(window, "Light").isChecked() is True
    assert _theme_action(window, "Dark").isChecked() is False


@pytest.mark.parametrize("saved", ["Dark", "Light", "System"])
def test_theme_menu_starts_with_the_saved_theme_ticked(saved):
    update_setting("theme", saved)

    window = MainWindow()

    assert [a.text() for a in window.theme_toggle_group.actions() if a.isChecked()] == [saved]


def test_theme_button_opens_its_menu_on_a_plain_click():
    # A toolbar button with a menu defaults to a split button, where the big
    # part does nothing and the menu hides behind a sliver of an arrow.
    from PySide6.QtWidgets import QToolButton
    window = MainWindow()

    button = window.main_toolbar.widgetForAction(window.theme_set_button)

    assert button.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup
    assert window.theme_set_button.menu() is window.theme_toggle_menu


def test_theme_stays_changeable_while_settings_is_locked():
    # The whole reason it moved out of Settings. Changing colors never
    # stranded a .part file.
    from gogstash import settings
    from gogstash.download_window import DownloadState
    update_setting("theme", "Dark")
    window = MainWindow()
    window.download_window.current_state = DownloadState.RUNNING

    with patch("gogstash.main.SettingsDialog.set_color_theme"):
        _theme_action(window, "Light").trigger()

    assert window.settings_button.isEnabled() is False
    assert window.theme_set_button.isEnabled() is True
    assert settings.read_setting("theme") == "Light"


@patch("gogstash.main.QDesktopServices.openUrl", return_value=True)
def test_open_downloads_folder_hands_the_download_path_to_the_file_manager(mock_open_url, tmp_path):
    # A space in the path, like the real NAS share. QUrl has to escape it,
    # not the file manager squinting at "Game%20Setups" and giving up.
    download_dir = tmp_path / "Game Setups" / "gogstash"
    download_dir.mkdir(parents=True)
    update_setting("download_path", str(download_dir))
    window = MainWindow()

    window.open_downloads_button.trigger()

    [url] = mock_open_url.call_args.args
    assert url.isLocalFile()
    assert url.toLocalFile() == str(download_dir)


@patch("gogstash.main.QDesktopServices.openUrl", return_value=True)
def test_open_downloads_folder_makes_the_folder_on_a_fresh_install(mock_open_url, tmp_path):
    # Nothing downloaded yet means no folder yet. Opening a folder that
    # doesn't exist gets you an error dialog or a shrug, depending on the
    # file manager's mood.
    download_dir = tmp_path / "not" / "yet"
    update_setting("download_path", str(download_dir))
    window = MainWindow()

    window.open_downloads_folder()

    assert download_dir.is_dir()
    mock_open_url.assert_called_once()


@patch("gogstash.main.QMessageBox.warning")
@patch("gogstash.main.QDesktopServices.openUrl")
def test_open_downloads_folder_says_so_when_the_folder_cant_be_made(mock_open_url, mock_warning, tmp_path):
    # A file squatting where a folder should go stands in for an unmounted
    # share or a read-only drive. The user hears about it, the file
    # manager is spared.
    squatter = tmp_path / "squatter"
    squatter.write_text("I live here now")
    update_setting("download_path", str(squatter / "gogstash"))
    window = MainWindow()

    window.open_downloads_folder()

    mock_open_url.assert_not_called()
    mock_warning.assert_called_once()
    assert str(squatter / "gogstash") in mock_warning.call_args.args[2]


@patch("gogstash.main.QMessageBox.critical")
@patch("gogstash.main.QDesktopServices.openUrl", return_value=False)
def test_open_downloads_folder_speaks_up_when_nothing_can_open_folders(mock_open_url, mock_critical, tmp_path):
    # A desktop with no file manager. Rare, but a button that silently
    # does nothing is how bug reports titled "button broken" are born.
    update_setting("download_path", str(tmp_path))
    window = MainWindow()

    window.open_downloads_folder()

    mock_critical.assert_called_once()
    _parent, title, text = mock_critical.call_args.args
    assert title == "No Folder Handler"
    assert "open folders" in text


# --- Quitting while threads run (#30) ---

@pytest.fixture
def busy_window(monkeypatch):
    # A MainWindow whose download queue claims to be RUNNING, with
    # stop_downloads swapped for a mock so nothing has to actually stop.
    window = MainWindow()
    monkeypatch.setattr(window.download_window, "stop_downloads", MagicMock())
    window.download_window.current_state = DownloadState.RUNNING
    yield window
    # Back to IDLE, or the fixture's own teardown close would ask us to quit
    window.download_window.current_state = DownloadState.IDLE
    window.quit_pending = False


def _refreshing_thread():
    thread = MagicMock()
    thread.isRunning.return_value = True
    return thread


def test_close_while_idle_just_closes():
    window = MainWindow()

    with patch("gogstash.main.QMessageBox.exec") as mock_exec:
        assert window.close() is True

    mock_exec.assert_not_called()
    assert window.quit_pending is False


def test_close_mid_download_answering_no_keeps_everything_running(busy_window):
    with patch("gogstash.main.QMessageBox.exec", return_value=QMessageBox.StandardButton.No):
        assert busy_window.close() is False

    busy_window.download_window.stop_downloads.assert_not_called()
    assert busy_window.quit_pending is False


def test_close_mid_download_answering_yes_stops_and_keeps_the_window_open(busy_window):
    # Accepting here would destroy the workers mid-chunk, which is how #30
    # started. The window waits for the queue to go idle instead.
    with patch("gogstash.main.QMessageBox.exec", return_value=QMessageBox.StandardButton.Yes):
        assert busy_window.close() is False

    busy_window.download_window.stop_downloads.assert_called_once()
    assert busy_window.quit_pending is True


def test_close_mid_download_yes_also_interrupts_a_running_refresh(busy_window):
    busy_window.fetch_thread = _refreshing_thread()

    with patch("gogstash.main.QMessageBox.exec", return_value=QMessageBox.StandardButton.Yes):
        assert busy_window.close() is False

    busy_window.fetch_thread.requestInterruption.assert_called_once()


def test_close_mid_download_no_leaves_a_running_refresh_alone(busy_window):
    # Regression: the refresh was once interrupted before the question was
    # even asked, so "No, keep going" still cost you your refresh.
    busy_window.fetch_thread = _refreshing_thread()

    with patch("gogstash.main.QMessageBox.exec", return_value=QMessageBox.StandardButton.No):
        busy_window.close()

    busy_window.fetch_thread.requestInterruption.assert_not_called()


def test_close_mid_download_without_ever_refreshing_does_not_trip_over_no_fetch_thread(busy_window):
    # Regression: fetch_thread is None until the first Refresh, and calling
    # requestInterruption on None made closeEvent raise. Qt then went ahead
    # and closed anyway, workers and all.
    assert busy_window.fetch_thread is None

    with patch("gogstash.main.QMessageBox.exec", return_value=QMessageBox.StandardButton.Yes):
        assert busy_window.close() is False

    busy_window.download_window.stop_downloads.assert_called_once()


def test_yes_after_the_queue_went_idle_during_the_question_quits_right_away(busy_window):
    # The downloads finished while the user was still reading the box. No
    # busy_changed(False) is coming after this, so waiting would mean
    # waiting forever.
    def finish_while_asking():
        busy_window.download_window.current_state = DownloadState.IDLE
        return QMessageBox.StandardButton.Yes

    with patch("gogstash.main.QMessageBox.exec", side_effect=finish_while_asking):
        assert busy_window.close() is True


def test_close_again_while_still_stopping_does_not_ask_twice(busy_window):
    busy_window.quit_pending = True

    with patch("gogstash.main.QMessageBox.exec") as mock_exec:
        assert busy_window.close() is False

    mock_exec.assert_not_called()
    busy_window.download_window.stop_downloads.assert_not_called()


def test_close_during_a_refresh_alone_interrupts_it_without_asking():
    # A half-done refresh never touches the cache, so there's nothing to
    # lose and nothing worth a dialog.
    window = MainWindow()
    window.fetch_thread = _refreshing_thread()

    with patch("gogstash.main.QMessageBox.exec") as mock_exec:
        assert window.close() is False

    mock_exec.assert_not_called()
    window.fetch_thread.requestInterruption.assert_called_once()
    assert window.quit_pending is True
    window.fetch_thread.isRunning.return_value = False
    window.quit_pending = False


def test_threads_busy_covers_both_the_queue_and_the_refresh():
    # Regression: this once returned the "everything is idle" condition,
    # which made every quit a coin toss with the wrong coin.
    window = MainWindow()
    assert window._threads_busy() is False

    window.fetch_thread = _refreshing_thread()
    assert window._threads_busy() is True

    window.fetch_thread.isRunning.return_value = False
    window.download_window.current_state = DownloadState.PAUSED
    assert window._threads_busy() is True

    window.download_window.current_state = DownloadState.IDLE
    assert window._threads_busy() is False


@patch("gogstash.main.QTimer")
def test_queue_going_idle_closes_the_window_only_if_a_quit_is_pending(mock_timer):
    window = MainWindow()

    # Downloads finishing on their own is not a request to quit
    window._on_quit_pending(False)
    mock_timer.singleShot.assert_not_called()

    window.quit_pending = True
    window._on_quit_pending(True)
    mock_timer.singleShot.assert_not_called()

    window._on_quit_pending(False)
    mock_timer.singleShot.assert_called_once_with(0, window.close)
    window.quit_pending = False


@patch("gogstash.main.QTimer")
def test_refresh_finishing_waits_for_the_thread_then_closes_if_a_quit_is_pending(mock_timer):
    window = MainWindow()
    window.fetch_thread = MagicMock()

    window._on_fetch_finished()
    mock_timer.singleShot.assert_not_called()
    window.fetch_thread.wait.assert_not_called()

    window.quit_pending = True
    window._on_fetch_finished()
    # finished fires just before the thread really exits; without the wait,
    # _threads_busy could still see it running and refuse the close
    window.fetch_thread.wait.assert_called_once()
    mock_timer.singleShot.assert_called_once_with(0, window.close)
    window.quit_pending = False
