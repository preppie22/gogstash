import time
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QDialog

from gogstash import gog_auth
from gogstash.main import MainWindow


FAKE_GAME = {"title": "Fake Game", "download_size": 2048, "fetched": 1}
FAKE_GAME_2 = {"title": "Second Fake Game", "download_size": 4096, "fetched": 0}


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


def test_fetch_games_shows_error_and_does_not_start_thread_when_logged_out():
    window = MainWindow()
    window.error_message.showMessage = MagicMock()

    window.fetch_games()

    window.error_message.showMessage.assert_called_once_with("You are not logged in to GOG!")
    assert not hasattr(window, "fetch_thread")


@patch("gogstash.main.LibraryFetchThread")
def test_fetch_games_starts_thread_with_access_token_when_logged_in(mock_thread_cls):
    gog_auth.save_token({"access_token": "mytoken", "expiry": time.time() + 3600})
    window = MainWindow()

    window.fetch_games()

    mock_thread_cls.assert_called_once_with("mytoken")
    mock_thread_instance = mock_thread_cls.return_value
    mock_thread_instance.succeeded.connect.assert_called_once_with(window.on_games_loaded)
    mock_thread_instance.start.assert_called_once()


def test_on_games_loaded_populates_table_with_games():
    window = MainWindow()

    window.on_games_loaded([FAKE_GAME])

    assert window.games_list.rowCount() == 1
    assert window.games_list.item(0, 0).text() == "Fake Game"
    assert window.games_list.item(0, 2).text() == "1"


def test_on_games_loaded_replaces_previous_rows_not_appends():
    window = MainWindow()
    window.on_games_loaded([FAKE_GAME])

    window.on_games_loaded([FAKE_GAME_2])

    assert window.games_list.rowCount() == 1
    assert window.games_list.item(0, 0).text() == "Second Fake Game"
