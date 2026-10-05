import os

import platformdirs
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication


@pytest.fixture(autouse=True)
def isolated_config_dir(tmp_path, monkeypatch):
    """Redirect every platformdirs lookup used by the app to a throwaway tmp_path
    for every test, so tests never read/write the real ~/.config/gogstash/ or
    ~/.local/share/gogstash/ files."""
    monkeypatch.setattr(platformdirs, "user_config_dir", lambda **kwargs: str(tmp_path))
    monkeypatch.setattr(platformdirs, "user_config_path", lambda **kwargs: tmp_path)
    monkeypatch.setattr(platformdirs, "user_data_dir", lambda **kwargs: str(tmp_path))
    monkeypatch.setattr(platformdirs, "user_data_path", lambda **kwargs: tmp_path)


@pytest.fixture(autouse=True)
def isolated_download_dir(tmp_path, monkeypatch):
    """The default download_path is the user's real ~/Downloads/GogStash, baked in
    at import time. The scheduler's free-space check will happily mkdir it, so
    keep every test that never sets its own path out of the real Downloads folder."""
    from gogstash import settings
    monkeypatch.setitem(settings.DEFAULT_SETTINGS, "download_path", str(tmp_path / "downloads"))


@pytest.fixture(scope="session", autouse=True)
def qapp():
    """Some code under test (QThread subclasses, QDialog subclasses) needs a real
    QApplication instance to exist, even when we never start a real event loop.
    QT_QPA_PLATFORM=offscreen lets this run without a real display (CI, sandboxes)."""
    app = QApplication.instance() or QApplication([])
    yield app
    # Tests build windows and walk away. Left to Python's last garbage
    # collection, they get torn down in whatever order the collector likes,
    # and once the Login menu joined the toolbar that order had PySide delete
    # a toolbar button out from under its toolbar: a segfault after every
    # test had already passed. Hand the leftovers to Qt instead, which knows
    # to take a window apart from the top down.
    for widget in QApplication.topLevelWidgets():
        widget.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
