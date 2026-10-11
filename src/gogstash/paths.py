"""Filesystem locations for GogStash configuration and downloads."""

import platformdirs
from pathlib import Path
from enum import StrEnum
import logging
import logging.handlers

class ConfigFile(StrEnum):
    """Names of the files kept in the GogStash config directory."""
    SETTINGS = 'settings.json'
    DB_CACHE = 'goglibrary.db'
    TOKEN = 'token.json'

class LogFile(StrEnum):
    """Names of the files kept in the ``logs`` folder of the config directory."""
    DOWNLOAD_LOG = 'downloads.log'
    APP_LOG = 'gogstash.log'
    AUTH_LOG = 'login.log'

def user_download_path() -> Path:
    """Return the user's downloads directory.

    Returns:
        Path: The platform-specific downloads directory.
    """
    return platformdirs.user_downloads_path()

def default_download_path() -> Path:
    """Return the default download directory for games.

    Returns:
        Path: A ``GogStash`` folder inside the user's downloads directory.
    """
    return user_download_path() / 'GogStash'

def config_path() -> Path:
    """Return the GogStash configuration directory.

    Returns:
        Path: The platform-specific config directory for GogStash.
    """
    return platformdirs.user_config_path(appname='gogstash', appauthor=False)

def config_file_path(config_file: ConfigFile) -> Path:
    """Return the full path of a config file.

    Args:
        config_file (ConfigFile): The config file to locate.

    Returns:
        Path: Path to the file inside the config directory.
    """
    return config_path() / config_file.value

def log_file_path(log_file: LogFile) -> Path:
    """Return the full path of a log file.

    Args:
        log_file (LogFile): The log file to locate.

    Returns:
        Path: Path to the file inside the ``logs`` folder of the config
        directory.
    """
    return config_path() / "logs" / log_file.value

def config_file_backup(config_file: ConfigFile) -> Path:
    """Return the backup path of a config file.

    Args:
        config_file (ConfigFile): The config file to back up.

    Returns:
        Path: Path next to the original file with a ``.bak`` suffix.
    """
    filename = config_file.value + ".bak"
    return config_path() / filename

def setup_logging(log_file: LogFile):
    """Send every log record of this process to a log file.

    Sets up the root logger with ``logging.basicConfig``, so the logger of
    every module writes to the file. The ``logs`` folder is created if
    needed, and the file rolls over at 2 MB and keeps three old files.
    Each process gets its own file, the main window ``APP_LOG`` and the
    login helper ``AUTH_LOG``, since two processes can't safely share one
    that rotates. ``DOWNLOAD_LOG`` sets up nothing, since the download
    queue writes that file itself.

    Args:
        log_file (LogFile): The log file to write to.
    """
    if log_file == LogFile.DOWNLOAD_LOG:
        return
    file_path = log_file_path(log_file)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    log_handler = logging.handlers.RotatingFileHandler(
        str(file_path),
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding='utf-8'
    )
    logging.basicConfig(
        handlers=[log_handler],
        format='[%(asctime)s | %(module)s] - %(levelname)s - %(message)s',
        level=logging.INFO
    )