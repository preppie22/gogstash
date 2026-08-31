from pathlib import Path
import platformdirs
import json
from typing import Any

def _user_data_helper() -> str:
    data_dir = platformdirs.user_data_dir(appname='gogstash')
    return data_dir

DEFAULT_SETTINGS = {
    'download_path': _user_data_helper(),
    'download_concurrency': 2,
    'platform_filter': ['Linux','Windows','MacOS'],
    'verify_downloads': True,
    'installers': True,
    'bonus_content': False,
    'patches': True,
    'theme': 'System'
}

def _settings_path_helper(filename: str = "settings.json") -> Path:
    config_dir = platformdirs.user_config_path(appname='gogstash')
    return config_dir / filename

def _create_settings(force: bool = False) -> None:
    settings_file = _settings_path_helper()
    if settings_file.exists() and not force:
        return
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_file, 'w') as sfw:
        json.dump(obj=DEFAULT_SETTINGS, fp=sfw, indent=2)

def _write_settings(settings: dict) -> None:
    settings_file = _settings_path_helper()
    if not settings_file.exists():
        _create_settings()
    with open(settings_file, 'w') as sfw:
        json.dump(obj=settings, fp=sfw, indent=2)

def _read_settings() -> dict:
    settings_file = _settings_path_helper()
    if not settings_file.exists():
        _create_settings()
    with open(settings_file, 'r') as sfr:
        settings: dict = {**DEFAULT_SETTINGS, **json.load(fp=sfr)}
    return settings

def update_setting(key: str, value: Any) -> None:
    settings = _read_settings()
    if key not in DEFAULT_SETTINGS.keys():
        raise KeyError(key)
    settings[key] = value
    _write_settings(settings)

def update_settings(settings: dict) -> None:
    current_settings = _read_settings()
    for item in settings.items():
        if item[0] not in DEFAULT_SETTINGS:
            raise KeyError(item[0])
        current_settings[item[0]] = item[1] 
    _write_settings(current_settings)

def read_setting(key: str) -> Any:
    settings = _read_settings()
    return settings.get(key)

def read_settings() -> dict:
    return _read_settings()

def set_default(key: str) -> None:
    settings = _read_settings()
    if key not in DEFAULT_SETTINGS.keys():
        raise KeyError(key)
    settings[key] = DEFAULT_SETTINGS.get(key)
    _write_settings(settings)

def restore_defaults() -> None:
    _create_settings(force=True)