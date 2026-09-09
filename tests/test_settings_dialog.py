from unittest.mock import patch

from PySide6.QtWidgets import QDialogButtonBox, QMessageBox

from gogstash import library_db, paths, settings
from gogstash.settings_dialog import SettingsDialog


SAVED_SETTINGS = {
    "download_path": "/saved/path",
    "download_concurrency": 3,
    "platform_filter": ["Linux"],
    "verify_downloads": False,
    "bonus_content": True,
    "patches": False,
    "theme": "Dark",
}


def click(dialog, standard_button):
    dialog.settings_form_buttons.button(standard_button).click()


def test_dialog_loads_saved_settings_on_construction():
    settings.update_settings(SAVED_SETTINGS)

    dialog = SettingsDialog()

    assert dialog.download_edit_path.text() == "/saved/path"
    assert dialog.download_concurrency_edit.value() == 3
    assert dialog.platform_filter_check["Linux"].isChecked() is True
    assert dialog.platform_filter_check["Windows"].isChecked() is False
    assert dialog.platform_filter_check["MacOS"].isChecked() is False
    assert dialog.theme_select.currentText() == "Dark"
    assert dialog.verify_downloads_check.isChecked() is False
    assert dialog.download_categories_check["bonus_content"].isChecked() is True
    assert dialog.download_categories_check["patches"].isChecked() is False


def test_installers_checkbox_is_always_checked_and_disabled():
    # Regression: load_settings() has no "installers" key to read from settings.json
    # (installers are never optional), so it must never let that checkbox be unchecked.
    settings.update_settings(SAVED_SETTINGS)
    dialog = SettingsDialog()

    installers = dialog.download_categories_check["installers"]
    assert installers.isChecked() is True
    assert installers.isEnabled() is False


def test_save_persists_edited_values():
    dialog = SettingsDialog()
    dialog.download_edit_path.setText("/new/path")
    dialog.download_concurrency_edit.setValue(7)
    dialog.theme_select.setCurrentText("Light")
    dialog.verify_downloads_check.setChecked(False)
    dialog.platform_filter_check["Windows"].setChecked(True)
    dialog.platform_filter_check["Linux"].setChecked(False)
    dialog.platform_filter_check["MacOS"].setChecked(False)
    dialog.download_categories_check["bonus_content"].setChecked(True)
    dialog.download_categories_check["patches"].setChecked(False)

    click(dialog, QDialogButtonBox.StandardButton.Save)

    saved = settings._read_settings()
    assert saved["download_path"] == "/new/path"
    assert saved["download_concurrency"] == 7
    assert saved["theme"] == "Light"
    assert saved["verify_downloads"] is False
    assert saved["platform_filter"] == ["Windows"]
    assert saved["bonus_content"] is True
    assert saved["patches"] is False


def test_save_closes_the_dialog():
    dialog = SettingsDialog()
    click(dialog, QDialogButtonBox.StandardButton.Save)
    assert dialog.result() == dialog.DialogCode.Accepted  # accept() was called


def test_discard_reverts_unsaved_edits_without_touching_disk():
    settings.update_settings(SAVED_SETTINGS)
    dialog = SettingsDialog()
    dialog.download_edit_path.setText("/unsaved/edit")
    dialog.theme_select.setCurrentText("Light")

    click(dialog, QDialogButtonBox.StandardButton.Discard)

    assert dialog.download_edit_path.text() == "/saved/path"
    assert dialog.theme_select.currentText() == "Dark"
    assert settings._read_settings()["download_path"] == "/saved/path"


def test_discard_unchecks_boxes_not_in_saved_platform_filter():
    # Regression: load_settings() used to only ever check boxes, never uncheck
    # them, so Discard/RestoreDefaults couldn't turn an already-checked box off.
    settings.update_settings(SAVED_SETTINGS)  # platform_filter: ["Linux"] only
    dialog = SettingsDialog()
    dialog.platform_filter_check["Windows"].setChecked(True)
    dialog.platform_filter_check["MacOS"].setChecked(True)

    click(dialog, QDialogButtonBox.StandardButton.Discard)

    assert dialog.platform_filter_check["Linux"].isChecked() is True
    assert dialog.platform_filter_check["Windows"].isChecked() is False
    assert dialog.platform_filter_check["MacOS"].isChecked() is False


def test_restore_defaults_populates_widgets_without_saving_to_disk():
    settings.update_settings(SAVED_SETTINGS)
    dialog = SettingsDialog()

    click(dialog, QDialogButtonBox.StandardButton.RestoreDefaults)

    assert dialog.theme_select.currentText() == settings.DEFAULT_SETTINGS["theme"]
    assert dialog.download_concurrency_edit.value() == settings.DEFAULT_SETTINGS["download_concurrency"]
    assert settings._read_settings()["theme"] == "Dark"  # disk still holds the saved value


def test_restore_defaults_unchecks_bonus_content_when_default_is_false():
    settings.update_settings(SAVED_SETTINGS)  # bonus_content: True
    dialog = SettingsDialog()
    assert dialog.download_categories_check["bonus_content"].isChecked() is True  # sanity check

    click(dialog, QDialogButtonBox.StandardButton.RestoreDefaults)

    assert dialog.download_categories_check["bonus_content"].isChecked() == settings.DEFAULT_SETTINGS["bonus_content"]


@patch("gogstash.settings_dialog.QFileDialog.getExistingDirectory")
def test_browse_updates_download_path_when_a_folder_is_chosen(mock_get_dir):
    mock_get_dir.return_value = "/chosen/folder"
    dialog = SettingsDialog()

    dialog.onclick_browse_download_path()

    assert dialog.download_edit_path.text() == "/chosen/folder"


@patch("gogstash.settings_dialog.QFileDialog.getExistingDirectory")
def test_browse_does_not_clear_path_when_dialog_is_cancelled(mock_get_dir):
    mock_get_dir.return_value = ""  # Qt returns "" when the user cancels the picker
    dialog = SettingsDialog()
    dialog.download_edit_path.setText("/existing/path")

    dialog.onclick_browse_download_path()

    assert dialog.download_edit_path.text() == "/existing/path"


@patch("gogstash.settings_dialog.QMessageBox.exec")
def test_clear_cache_button_removes_the_active_db_file_when_confirmed(mock_exec):
    mock_exec.return_value = QMessageBox.StandardButton.Yes
    library_db.update_products([])  # creates an (empty) db file
    db_path = paths.config_file_path(paths.ConfigFile.DB_CACHE)
    assert db_path.exists()
    dialog = SettingsDialog()

    dialog.clear_cache_button.click()

    assert not db_path.exists()


@patch("gogstash.settings_dialog.QMessageBox.exec")
def test_clear_cache_button_keeps_db_file_when_cancelled(mock_exec):
    mock_exec.return_value = QMessageBox.StandardButton.No
    library_db.update_products([])  # creates an (empty) db file
    db_path = paths.config_file_path(paths.ConfigFile.DB_CACHE)
    assert db_path.exists()
    dialog = SettingsDialog()

    dialog.clear_cache_button.click()

    assert db_path.exists()
