import logging
import logging.handlers
from pathlib import Path

import pytest

from gogstash import paths


@pytest.fixture
def basic_config(monkeypatch):
    """Catches what setup_logging hands basicConfig, instead of letting it
    loose on the test run's own root logger. Closes the handlers after, so
    no log file is left open behind the test."""
    calls = []
    monkeypatch.setattr(paths.logging, "basicConfig", lambda **kwargs: calls.append(kwargs))
    yield calls
    for call in calls:
        for handler in call["handlers"]:
            handler.close()


def test_log_files_live_in_their_own_folder(tmp_path):
    # The config folder holds settings, the token and the cache. The logs
    # get a room of their own instead of sprawling across the living room.
    for log_file in paths.LogFile:
        assert paths.log_file_path(log_file) == tmp_path / "logs" / log_file.value


@pytest.mark.parametrize("log_file, name", [
    (paths.LogFile.APP_LOG, "gogstash.log"),
    (paths.LogFile.AUTH_LOG, "login.log"),
])
def test_setup_logging_writes_a_rotating_utf8_file_in_the_logs_folder(basic_config, tmp_path, log_file, name):
    paths.setup_logging(log_file)

    [call] = basic_config
    [handler] = call["handlers"]
    assert isinstance(handler, logging.handlers.RotatingFileHandler)
    assert Path(handler.baseFilename) == tmp_path / "logs" / name
    assert (tmp_path / "logs").is_dir()  # first run on a fresh machine, nobody made it yet
    assert handler.maxBytes == 2 * 1024 * 1024
    assert handler.backupCount == 3  # 0 would look like rotation and quietly grow forever
    assert handler.encoding == "utf-8"
    assert call["level"] == logging.INFO
    assert "filename" not in call  # basicConfig refuses filename and handlers together


def test_setup_logging_leaves_the_download_history_alone(basic_config, tmp_path):
    # downloads.log has its own writer. A rotating handler on top of it
    # would be two pens on one page.
    paths.setup_logging(paths.LogFile.DOWNLOAD_LOG)

    assert basic_config == []
    assert not (tmp_path / "logs").exists()
