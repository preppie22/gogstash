import logging
import sys
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from gogstash import gog_auth
from gogstash import login_window
from gogstash.login_window import BASE_PAGE, ExitCode, LoginWindow


SUCCESS_URL = "https://embed.gog.com/on_login_success?origin=client&code=thecode"
TOKEN = {"access_token": "abc", "refresh_token": "def", "expires_in": 3600, "expiry": 9999999999}


class FakeEvent:
    """Just enough of pywebview's Event: a flag you can wait on, plus a
    list of handlers that += appends to and set() calls."""

    def __init__(self):
        self._flag = threading.Event()
        self._handlers = []

    def __iadd__(self, handler):
        self._handlers.append(handler)
        return self

    def set(self):
        self._flag.set()
        for handler in self._handlers:
            handler()

    def clear(self):
        self._flag.clear()

    def is_set(self):
        return self._flag.is_set()

    def wait(self, timeout=None):
        return self._flag.wait(timeout)


class FakeWindow:
    def __init__(self, html, landing_url):
        self.html = html
        self.landing_url = landing_url
        self.url = None
        self.load_error = None
        self.requested_urls = []
        self.page_requested = threading.Event()
        self.gone = threading.Event()
        self.events = SimpleNamespace(loaded=FakeEvent(), closed=FakeEvent())

    def load_url(self, url):
        self.page_requested.set()
        if self.load_error:
            raise self.load_error
        # Real load_url clears the flag before navigating, then GOG's page
        # loads, the user does their thing, and the browser ends up wherever
        # the test says they ended up.
        self.events.loaded.clear()
        self.requested_urls.append(url)
        self.url = self.landing_url or url
        self.events.loaded.set()

    def get_current_url(self):
        return self.url

    def destroy(self):
        self.close()

    def close(self):
        if not self.gone.is_set():
            self.gone.set()
            self.events.closed.set()


class FakeWebview:
    """Stands in for the webview module. start() plays the part of the GTK
    loop: it "finishes loading" the spinner page, acts out the scenario,
    then blocks until the window is gone and the poll thread has wrapped up,
    so every test sees the helper's final answer and not a race."""

    def __init__(self, threads, landing_url=None, scenario="wait", start_error=None):
        self.threads = threads
        self.landing_url = landing_url
        self.scenario = scenario
        self.start_error = start_error
        self.window = None
        self.start_kwargs = None

    def create_window(self, title, url=None, html=None, width=None, height=None):
        assert url is None, "GOG's page should wait until the spinner is up"
        self.window = FakeWindow(html, self.landing_url)
        return self.window

    def start(self, **kwargs):
        self.start_kwargs = kwargs
        if self.start_error:
            raise self.start_error
        window = self.window
        if self.scenario == "close_during_spinner":
            # Gone before load_url gets a look in, so load_url finds
            # nothing to load into.
            window.close()
            window.load_error = RuntimeError("window is gone")
        elif self.scenario == "load_fails":
            window.load_error = RuntimeError("WebKit had a bad day")
        window.events.loaded.set()
        if self.scenario == "close_after_page_loads":
            assert window.page_requested.wait(5)
            window.close()
        assert window.gone.wait(5), "the helper never closed its window"
        for thread in self.threads:
            thread.join(5)
            assert not thread.is_alive(), "the poll thread outlived its window"


@pytest.fixture
def poll_threads(monkeypatch):
    # Hand the fake every thread the helper starts, so start() can wait for
    # the poll to finish like a well-mannered GTK loop would not.
    threads = []

    class RecordedThread(threading.Thread):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            threads.append(self)

    monkeypatch.setattr(login_window.threading, "Thread", RecordedThread)
    return threads


@pytest.fixture
def install_webview(monkeypatch, poll_threads):
    def install(**kwargs):
        fake = FakeWebview(poll_threads, **kwargs)
        monkeypatch.setitem(sys.modules, "webview", fake)
        return fake
    return install


@pytest.fixture
def not_frozen(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)


@patch("gogstash.gog_auth.fetch_token", return_value=TOKEN)
def test_successful_login_saves_token_and_exits_ok(mock_fetch, install_webview, not_frozen):
    webview = install_webview(landing_url=SUCCESS_URL)

    result = LoginWindow().start_helper()

    assert result == ExitCode.EXIT_OK
    mock_fetch.assert_called_once_with("thecode")
    assert gog_auth._load_token() == TOKEN
    # Spinner first, GOG second, in a window the user can't lose cookies to.
    assert webview.window.html == BASE_PAGE
    assert webview.window.requested_urls == [gog_auth.build_auth_uri()]
    assert webview.start_kwargs["private_mode"] is True


@patch("gogstash.gog_auth.fetch_token")
def test_closing_window_without_logging_in_is_a_cancel(mock_fetch, install_webview, not_frozen):
    install_webview(scenario="close_after_page_loads")

    result = LoginWindow().start_helper()

    assert result == ExitCode.EXIT_CANCELLED
    mock_fetch.assert_not_called()
    assert gog_auth._load_token() is None


def test_closing_window_during_spinner_is_a_cancel_not_a_broken_webview(install_webview, not_frozen, caplog):
    # Regression: load_url failing because the user had already closed the
    # window got blamed on the webview, and a plain "never mind" earned a
    # trip to the paste dialog.
    caplog.set_level(logging.INFO)
    install_webview(scenario="close_during_spinner")

    result = LoginWindow().start_helper()

    assert result == ExitCode.EXIT_CANCELLED
    assert "unable to load login page" not in caplog.text


def test_login_page_that_fails_to_load_means_no_webview(install_webview, not_frozen, caplog):
    caplog.set_level(logging.INFO)
    webview = install_webview(scenario="load_fails")

    result = LoginWindow().start_helper()

    assert result == ExitCode.EXIT_NO_WEBVIEW
    # The helper closes the window itself rather than leaving the user to
    # admire a spinner for the rest of their life.
    assert webview.window.gone.is_set()
    # Regression: this warning once lived after webview.start(), reading an
    # `e` that Python had already tidied away, and crashed the helper
    # instead of logging anything.
    assert "WebKit had a bad day" in caplog.text


def test_webview_that_wont_start_means_no_webview(install_webview, not_frozen):
    install_webview(start_error=RuntimeError("no display"))

    assert LoginWindow().start_helper() == ExitCode.EXIT_NO_WEBVIEW


def test_missing_pywebview_means_no_webview(monkeypatch, not_frozen):
    monkeypatch.setitem(sys.modules, "webview", None)  # makes `import webview` raise

    assert LoginWindow().start_helper() == ExitCode.EXIT_NO_WEBVIEW


@pytest.mark.parametrize("failure", [
    requests.ConnectionError("GOG is having a lie down"),
    KeyError("expires_in"),  # GOG's error reply for a used or expired code
])
def test_token_exchange_failure_is_its_own_exit_code(install_webview, not_frozen, caplog, failure):
    caplog.set_level(logging.INFO)
    install_webview(landing_url=SUCCESS_URL)

    with patch("gogstash.gog_auth.fetch_token", side_effect=failure):
        result = LoginWindow().start_helper()

    # Not EXIT_NO_WEBVIEW: the webview did its job, and the paste dialog
    # would only walk the user into the same wall.
    assert result == ExitCode.EXIT_TOKEN_ERROR
    assert gog_auth._load_token() is None
    assert repr(failure) in caplog.text


@pytest.mark.parametrize("platform, gui", [("linux", "gtk"), ("win32", "edgechromium")])
def test_picks_the_platform_webview(install_webview, not_frozen, monkeypatch, platform, gui):
    monkeypatch.setattr(sys, "platform", platform)
    webview = install_webview(scenario="close_after_page_loads")

    LoginWindow().start_helper()

    assert webview.start_kwargs["gui"] == gui


def test_frozen_linux_points_gi_at_only_the_typelib_dirs_that_exist(monkeypatch, tmp_path):
    present_a, missing, present_b = tmp_path / "debian", tmp_path / "fedora", tmp_path / "arch"
    present_a.mkdir()
    present_b.mkdir()
    monkeypatch.setattr(login_window, "TYPELIB_DIRS", (str(present_a), str(missing), str(present_b)))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("GI_TYPELIB_PATH", raising=False)
    monkeypatch.setitem(sys.modules, "webview", None)  # bail right after the setup we care about

    LoginWindow().start_helper()

    assert login_window.os.environ["GI_TYPELIB_PATH"] == f"{present_a}:{present_b}"


def test_from_source_leaves_gi_typelib_path_alone(monkeypatch, not_frozen):
    monkeypatch.setenv("GI_TYPELIB_PATH", "/whatever/the/user/had")
    monkeypatch.setitem(sys.modules, "webview", None)

    LoginWindow().start_helper()

    assert login_window.os.environ["GI_TYPELIB_PATH"] == "/whatever/the/user/had"
