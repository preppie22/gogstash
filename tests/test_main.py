import time
from unittest.mock import MagicMock, patch

import humanize
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QDialog

from gogstash import gog_auth, manifest
from gogstash.main import MainWindow
from gogstash.settings import update_setting


def _non_null_icon():
    # A plain QIcon() is null, and _color_scheme_refresh's "skip icon-less
    # entries" guard would then treat every recolored button as icon-less too.
    return QIcon(QPixmap(4, 4))


FAKE_GAME = {"product_id": 111, "title": "Fake Game", "slug": "fake-game", "download_size": 2048}
FAKE_GAME_2 = {"product_id": 222, "title": "Second Fake Game", "slug": "second-fake-game", "download_size": 4096}


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
    assert window.games_list.item(0, 2).text() == "No"


def test_on_games_loaded_marks_fetched_when_an_installer_is_in_the_manifest(tmp_path):
    update_setting("download_path", str(tmp_path))
    game_dir = tmp_path / "fake-game"
    installer = game_dir / "installer_windows_en" / "setup.exe"
    installer.parent.mkdir(parents=True)
    installer.write_bytes(b"hello")
    manifest.add_file(game_dir, installer, category="installers", checksum="abc", timestamp=1.0)
    window = MainWindow()

    window.on_games_loaded([FAKE_GAME])

    assert window.games_list.item(0, 2).text() == "Yes"


def test_on_games_loaded_does_not_mark_fetched_for_bonus_content_alone(tmp_path):
    # A game with only its manual/soundtrack downloaded shouldn't read as
    # "fetched" -- that's the whole reason this checks category, not just
    # "is the manifest non-empty".
    update_setting("download_path", str(tmp_path))
    game_dir = tmp_path / "fake-game"
    manual = game_dir / "bonus_content" / "manual.pdf"
    manual.parent.mkdir(parents=True)
    manual.write_bytes(b"doc")
    manifest.add_file(game_dir, manual, category="bonus_content", checksum="xyz", timestamp=1.0)
    window = MainWindow()

    window.on_games_loaded([FAKE_GAME])

    assert window.games_list.item(0, 2).text() == "No"


def test_on_games_loaded_replaces_previous_rows_not_appends():
    window = MainWindow()
    window.on_games_loaded([FAKE_GAME])

    window.on_games_loaded([FAKE_GAME_2])

    assert window.games_list.rowCount() == 1
    assert window.games_list.item(0, 0).text() == "Second Fake Game"


def test_open_downloads_shows_the_persistent_download_window():
    window = MainWindow()
    window.download_window.show = MagicMock()

    window.open_downloads()

    window.download_window.show.assert_called_once()


def test_open_downloads_does_not_create_a_new_window_each_time():
    # Regression: open_downloads() used to construct a fresh DownloadWindow on
    # every call, silently discarding whatever was already queued.
    window = MainWindow()
    first_instance = window.download_window

    window.open_downloads()
    window.open_downloads()

    assert window.download_window is first_instance


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


def test_set_download_badge_stores_the_new_count():
    window = MainWindow()

    window.set_download_badge(7)

    assert window._queue_count == 7


@patch("gogstash.main.badge_icon")
@patch("gogstash.main.get_icon")
def test_set_download_badge_composes_the_download_icon_then_badges_it(mock_get_icon, mock_badge_icon):
    mock_get_icon.return_value = _non_null_icon()  # needed to survive construction below
    mock_badge_icon.return_value = _non_null_icon()
    window = MainWindow()
    mock_get_icon.reset_mock()
    mock_badge_icon.reset_mock()
    mock_get_icon.return_value = "DOWNLOAD_ICON_SENTINEL"
    mock_badge_icon.return_value = QIcon()

    window.set_download_badge(3)

    mock_get_icon.assert_called_once_with("download.svg")
    mock_badge_icon.assert_called_once_with("DOWNLOAD_ICON_SENTINEL", 3)
    assert window.downloads_window_button.icon().cacheKey() == mock_badge_icon.return_value.cacheKey()


def test_color_scheme_refresh_always_recomputes_the_download_badge():
    window = MainWindow()
    window.set_download_badge = MagicMock()

    window._color_scheme_refresh()

    window.set_download_badge.assert_called_once_with(window._queue_count)


@patch("gogstash.main.get_icon")
def test_color_scheme_refresh_skips_the_downloads_toolbar_action(mock_get_icon):
    # Regression: reloading the download-queue icon plain via get_icon here
    # would wipe out the badge that set_download_badge drew on it.
    mock_get_icon.side_effect = lambda *args, **kwargs: _non_null_icon()  # distinct icon per call
    window = MainWindow()
    window.set_download_badge = MagicMock()
    downloads_icon = window.downloads_window_button.icon()
    mock_get_icon.reset_mock()

    window._color_scheme_refresh()

    called_icons = [call.args[0] for call in mock_get_icon.call_args_list]
    assert "download.svg" not in called_icons
    assert len(called_icons) == 4  # login, logout, fetch_games, settings


@patch("gogstash.main.get_icon")
def test_color_scheme_refresh_reloads_each_toolbar_action_from_its_own_icon_file(mock_get_icon):
    mock_get_icon.return_value = _non_null_icon()
    window = MainWindow()
    window.set_download_badge = MagicMock()
    mock_get_icon.reset_mock()

    window._color_scheme_refresh()

    called_files = {call.args[0] for call in mock_get_icon.call_args_list}
    assert called_files == {"login.svg", "logout.svg", "fetch.svg", "settings.svg"}
