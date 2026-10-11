import logging
import logging.handlers
import re
from pathlib import Path

import pytest

from gogstash import log_setup, paths


@pytest.fixture
def basic_config(monkeypatch):
    """Catches what setup_logging hands basicConfig, instead of letting it
    loose on the test run's own root logger. Closes the handlers after, so
    no log file is left open behind the test."""
    calls = []
    monkeypatch.setattr(log_setup.logging, "basicConfig", lambda **kwargs: calls.append(kwargs))
    yield calls
    for call in calls:
        for handler in call["handlers"]:
            handler.close()


@pytest.mark.parametrize("log_file", [paths.LogFile.APP_LOG, paths.LogFile.AUTH_LOG])
def test_setup_logging_writes_a_rotating_utf8_file_in_the_logs_folder(basic_config, tmp_path, log_file):
    paths_given = paths.log_file_path(log_file)

    log_setup.setup_logging(paths_given)

    [call] = basic_config
    [handler] = call["handlers"]
    assert isinstance(handler, logging.handlers.RotatingFileHandler)
    assert Path(handler.baseFilename) == tmp_path / "logs" / log_file.value
    assert (tmp_path / "logs").is_dir()  # first run on a fresh machine, nobody made it yet
    assert handler.maxBytes == 2 * 1024 * 1024
    assert handler.backupCount == 3  # 0 would look like rotation and quietly grow forever
    assert handler.encoding == "utf-8"  # Windows' code page meets a Polish game title, loses
    assert call["level"] == logging.INFO
    assert "filename" not in call  # basicConfig refuses filename and handlers together


def test_rotating_handler_takes_its_own_sizes(tmp_path):
    # The download history will want to keep more than the debug chatter.
    handler = log_setup._rotating_handler(tmp_path / "logs" / "x.log", max_bytes=10, backup_count=7)
    try:
        assert handler.maxBytes == 10
        assert handler.backupCount == 7
    finally:
        handler.close()


def test_rotating_handler_actually_rotates(tmp_path):
    # The settings above are only promises. Write past the limit and count files.
    log_file = tmp_path / "logs" / "x.log"
    handler = log_setup._rotating_handler(log_file, max_bytes=100, backup_count=2)
    logger = logging.getLogger("test_log_setup.rotation")
    logger.propagate = False
    logger.addHandler(handler)
    try:
        for i in range(20):
            logger.warning("line %02d, padded out to take up some room", i)
    finally:
        logger.removeHandler(handler)
        handler.close()

    assert sorted(p.name for p in log_file.parent.iterdir()) == ["x.log", "x.log.1", "x.log.2"]  # and no .3


@pytest.fixture
def download_logger():
    """The download logger lives for the whole test run, so whatever a test
    bolts onto it comes back off afterwards."""
    logger = logging.getLogger(log_setup.DOWNLOAD_LOGGER)
    yield logger
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(logging.NOTSET)
    logger.propagate = True


def test_download_log_writes_time_then_message_and_nothing_else(download_logger, tmp_path):
    log_file = tmp_path / "logs" / "downloads.log"
    log_setup.setup_download_log(log_file)

    download_logger.info(": Downloads paused")
    download_logger.handlers[0].flush()

    # Same shape as the history has always had, so a user's eyes (or grep)
    # don't need retraining. No milliseconds, no level, no module.
    assert re.fullmatch(r"\[\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\] : Downloads paused\n", log_file.read_text(encoding="utf-8"))


def test_download_log_keeps_more_history_than_the_app_log(download_logger, tmp_path):
    log_setup.setup_download_log(tmp_path / "logs" / "downloads.log")

    [handler] = download_logger.handlers
    assert isinstance(handler, logging.handlers.RotatingFileHandler)
    assert handler.maxBytes == 5 * 1024 * 1024
    assert handler.backupCount == 5
    assert handler.encoding == "utf-8"


class _Collector(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def test_download_log_stays_out_of_the_app_log(download_logger, tmp_path):
    log_setup.setup_download_log(tmp_path / "logs" / "downloads.log")
    # Stands in for gogstash.log's handler on the root logger. Not caplog:
    # pytest 9 also clips its capture handlers straight onto loggers that
    # don't propagate, so caplog would hear the line either way.
    root, app_log = logging.getLogger(), _Collector()
    root.addHandler(app_log)
    try:
        download_logger.info("| Witcher3.exe : Fetched 1.2 GB")
    finally:
        root.removeHandler(app_log)

    # Every fetched file in gogstash.log too would bury the one traceback
    # someone actually came looking for.
    assert app_log.records == []


def test_urllib3_keeps_its_request_lines_to_itself_even_at_debug(basic_config, request):
    # urllib3 logs every request's full path and query at DEBUG: refresh
    # tokens, login codes, signed CDN links, the lot. Turning gogstash.log
    # down to DEBUG one day must not turn it into a keyring.
    root, urllib3_logger = logging.getLogger(), logging.getLogger("urllib3")
    old_levels = root.level, urllib3_logger.level
    # setLevel, not a monkeypatched attribute, so logging's level cache is cleared on the way back too
    request.addfinalizer(lambda: (root.setLevel(old_levels[0]), urllib3_logger.setLevel(old_levels[1])))

    log_setup.setup_logging(paths.log_file_path(paths.LogFile.APP_LOG))
    root.setLevel(logging.DEBUG)  # what "turning it down" looks like

    assert not logging.getLogger("urllib3.connectionpool").isEnabledFor(logging.DEBUG)
    assert logging.getLogger("urllib3.connectionpool").isEnabledFor(logging.WARNING)
