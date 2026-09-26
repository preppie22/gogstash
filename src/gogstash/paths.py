"""Filesystem locations for GogStash configuration and downloads."""

import platformdirs
from pathlib import Path
from enum import StrEnum

class ConfigFile(StrEnum):
    """Names of the files kept in the GogStash config directory."""
    SETTINGS = 'settings.json'
    DB_CACHE = 'goglibrary.db'
    TOKEN = 'token.json'
    DOWNLOAD_LOG = 'downloads.log'

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

def config_file_backup(config_file: ConfigFile) -> Path:
    """Return the backup path of a config file.

    Args:
        config_file (ConfigFile): The config file to back up.

    Returns:
        Path: Path next to the original file with a ``.bak`` suffix.
    """
    filename = config_file.value + ".bak"
    return config_path() / filename