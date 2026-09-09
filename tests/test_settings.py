import json

import pytest

from gogstash import paths, settings


def test_create_settings_writes_default_settings_file():
    settings._create_settings()
    settings_file = paths.config_file_path(paths.ConfigFile.SETTINGS)
    assert settings_file.exists()
    with open(settings_file) as f:
        assert json.load(f) == settings.DEFAULT_SETTINGS


def test_create_settings_is_idempotent_without_force():
    settings._create_settings()
    settings.update_setting("theme", "Dark")

    settings._create_settings()  # force=False: should not overwrite

    assert settings.read_setting("theme") == "Dark"


def test_create_settings_force_overwrites():
    settings._create_settings()
    settings.update_setting("theme", "Dark")

    settings._create_settings(force=True)

    assert settings.read_setting("theme") == settings.DEFAULT_SETTINGS["theme"]


def test_read_setting_creates_file_if_missing():
    settings_file = paths.config_file_path(paths.ConfigFile.SETTINGS)
    assert not settings_file.exists()

    result = settings.read_setting("theme")

    assert settings_file.exists()
    assert result == settings.DEFAULT_SETTINGS["theme"]


def test_read_settings_merges_missing_keys_from_defaults():
    settings._create_settings()
    settings_file = paths.config_file_path(paths.ConfigFile.SETTINGS)
    with open(settings_file, "w") as f:
        json.dump({"theme": "Dark"}, f)  # simulates a settings file from an older version

    result = settings._read_settings()

    assert result["theme"] == "Dark"
    assert result["download_concurrency"] == settings.DEFAULT_SETTINGS["download_concurrency"]


def test_update_setting_persists_new_value():
    settings.update_setting("download_concurrency", 5)
    assert settings.read_setting("download_concurrency") == 5


def test_update_setting_persists_falsy_values():
    # Regression: an earlier version treated any falsy new value as "no update".
    settings.update_setting("verify_downloads", False)
    assert settings.read_setting("verify_downloads") is False

    settings.update_setting("download_concurrency", 0)
    assert settings.read_setting("download_concurrency") == 0


def test_update_setting_raises_for_unknown_key():
    with pytest.raises(KeyError):
        settings.update_setting("not_a_real_setting", "value")


def test_read_setting_returns_none_for_unknown_key():
    assert settings.read_setting("not_a_real_setting") is None


def test_set_default_resets_single_key():
    settings.update_setting("theme", "Dark")
    settings.update_setting("download_concurrency", 10)

    settings.set_default("theme")

    assert settings.read_setting("theme") == settings.DEFAULT_SETTINGS["theme"]
    assert settings.read_setting("download_concurrency") == 10  # untouched


def test_set_default_resets_key_currently_set_to_falsy_value():
    # Regression: an earlier version skipped the reset whenever the current value was falsy.
    settings.update_setting("verify_downloads", False)

    settings.set_default("verify_downloads")

    assert settings.read_setting("verify_downloads") == settings.DEFAULT_SETTINGS["verify_downloads"]


def test_set_default_raises_for_unknown_key():
    with pytest.raises(KeyError):
        settings.set_default("not_a_real_setting")


def test_restore_defaults_resets_everything():
    settings.update_setting("theme", "Dark")
    settings.update_setting("download_concurrency", 10)

    settings.restore_defaults()

    assert settings._read_settings() == settings.DEFAULT_SETTINGS
