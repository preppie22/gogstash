import platformdirs
from pathlib import Path
from enum import StrEnum

class ConfigFile(StrEnum):
    SETTINGS = 'settings.json'
    DB_CACHE = 'goglibrary.db'
    TOKEN = 'token.json'
    DOWNLOAD_LOG = 'downloads.log'

def user_download_path() -> Path:
    return platformdirs.user_downloads_path()

def default_download_path() -> Path:
    return user_download_path() / 'GogStash'

def config_path() -> Path:
    return platformdirs.user_config_path(appname='gogstash', appauthor=False)

def config_file_path(config_file: ConfigFile) -> Path:
    return config_path() / config_file.value

def config_file_backup(config_file: ConfigFile) -> Path:
    filename = config_file.value + ".bak"
    return config_path() / filename