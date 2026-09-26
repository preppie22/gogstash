"""User settings stored as JSON in the config directory.

Attributes:
    DEFAULT_SETTINGS (dict): Every valid setting key and its default
        value. Keys missing from the settings file fall back to these.
"""

import json
from typing import Any

from gogstash import paths

DEFAULT_SETTINGS = {
    'download_path': str(paths.default_download_path()),
    'download_concurrency': 2,
    'platform_filter': ['Linux','Windows','MacOS'],
    'verify_downloads': True,
    'installers': True,
    'bonus_content': False,
    'patches': True,
    'theme': 'System'
}

def _create_settings(force: bool = False) -> None:
    """Write the default settings file.

    Args:
        force (bool): Overwrite the settings file if it already exists.
    """
    settings_file = paths.config_file_path(paths.ConfigFile.SETTINGS)
    if settings_file.exists() and not force:
        return
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_file, 'w') as sfw:
        json.dump(obj=DEFAULT_SETTINGS, fp=sfw, indent=2)

def _write_settings(settings: dict) -> None:
    """Write settings to disk, creating the file first if needed.

    Args:
        settings (dict): The complete settings to save.
    """
    settings_file = paths.config_file_path(paths.ConfigFile.SETTINGS)
    if not settings_file.exists():
        _create_settings()
    with open(settings_file, 'w') as sfw:
        json.dump(obj=settings, fp=sfw, indent=2)

def _read_settings() -> dict:
    """Read settings from disk, creating the file first if needed.

    Returns:
        dict: Saved settings merged over ``DEFAULT_SETTINGS``.
    """
    settings_file = paths.config_file_path(paths.ConfigFile.SETTINGS)
    if not settings_file.exists():
        _create_settings()
    with open(settings_file, 'r') as sfr:
        settings: dict = {**DEFAULT_SETTINGS, **json.load(fp=sfr)}
    return settings

def update_setting(key: str, value: Any) -> None:
    """Update and save a single setting.

    Args:
        key (str): The setting to update.
        value (Any): The new value.

    Raises:
        KeyError: If ``key`` is not a known setting.
    """
    settings = _read_settings()
    if key not in DEFAULT_SETTINGS.keys():
        raise KeyError(key)
    settings[key] = value
    _write_settings(settings)

def update_settings(settings: dict) -> None:
    """Update and save several settings at once.

    Nothing is written if any key is invalid.

    Args:
        settings (dict): Setting keys mapped to their new values.

    Raises:
        KeyError: If any key is not a known setting.
    """
    current_settings = _read_settings()
    for item in settings.items():
        if item[0] not in DEFAULT_SETTINGS:
            raise KeyError(item[0])
        current_settings[item[0]] = item[1] 
    _write_settings(current_settings)

def read_setting(key: str) -> Any:
    """Return the value of a single setting.

    Args:
        key (str): The setting to read.

    Returns:
        Any: The setting's value, or None if the key is unknown.
    """
    settings = _read_settings()
    return settings.get(key)

def read_settings() -> dict:
    """Return all settings.

    Returns:
        dict: Saved settings merged over ``DEFAULT_SETTINGS``.
    """
    return _read_settings()

def set_default(key: str) -> None:
    """Reset a single setting to its default value.

    Args:
        key (str): The setting to reset.

    Raises:
        KeyError: If ``key`` is not a known setting.
    """
    settings = _read_settings()
    if key not in DEFAULT_SETTINGS.keys():
        raise KeyError(key)
    settings[key] = DEFAULT_SETTINGS.get(key)
    _write_settings(settings)

def restore_defaults() -> None:
    """Overwrite the settings file with ``DEFAULT_SETTINGS``."""
    _create_settings(force=True)