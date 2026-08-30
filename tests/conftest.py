import platformdirs
import pytest
from PySide6.QtCore import QCoreApplication


@pytest.fixture(autouse=True)
def isolated_config_dir(tmp_path, monkeypatch):
    """Redirect every platformdirs lookup used by the app to a throwaway tmp_path
    for every test, so tests never read/write the real ~/.config/gogstash/ or
    ~/.local/share/gogstash/ files."""
    monkeypatch.setattr(platformdirs, "user_config_dir", lambda **kwargs: str(tmp_path))
    monkeypatch.setattr(platformdirs, "user_config_path", lambda **kwargs: tmp_path)
    monkeypatch.setattr(platformdirs, "user_data_dir", lambda **kwargs: str(tmp_path))
    monkeypatch.setattr(platformdirs, "user_data_path", lambda **kwargs: tmp_path)


@pytest.fixture(scope="session", autouse=True)
def qapp():
    """Some code under test (QThread subclasses) needs a Qt application instance
    to exist, even when we never start a real event loop."""
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app
