from unittest.mock import patch

from PySide6.QtCore import Qt
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
    "languages": ["de", "fr"],
}


def click(dialog, standard_button):
    button = dialog.settings_form_buttons.button(standard_button)
    if button is None and standard_button == QDialogButtonBox.StandardButton.Discard:
        # Discard is a custom-added button here, not Qt's standard one, since
        # 3660ecb deliberately dodged inconsistent per-platform wording
        # ("Discard" vs "Don't Save"). .button() only finds actual standard
        # buttons, so track it down by its role instead.
        button = next(
            b for b in dialog.settings_form_buttons.buttons()
            if dialog.settings_form_buttons.buttonRole(b) == QDialogButtonBox.ButtonRole.DestructiveRole
        )
    button.click()


def language_items(dialog):
    picker = dialog.language_picker
    return {picker.item(i).data(Qt.ItemDataRole.UserRole): picker.item(i) for i in range(picker.count())}


def ticked_languages(dialog):
    return {code for code, item in language_items(dialog).items() if item.checkState() == Qt.CheckState.Checked}


def set_language(dialog, code, checked):
    language_items(dialog)[code].setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)


def save_button(dialog):
    return dialog.settings_form_buttons.button(QDialogButtonBox.StandardButton.Save)


def test_dialog_loads_saved_settings_on_construction():
    settings.update_settings(SAVED_SETTINGS)

    dialog = SettingsDialog()

    assert dialog.download_edit_path.text() == "/saved/path"
    assert dialog.download_concurrency_edit.value() == 3
    assert dialog.platform_filter_check["Linux"].isChecked() is True
    assert dialog.platform_filter_check["Windows"].isChecked() is False
    assert dialog.platform_filter_check["MacOS"].isChecked() is False
    assert dialog.verify_downloads_check.isChecked() is False
    assert dialog.download_categories_check["bonus_content"].isChecked() is True
    assert dialog.download_categories_check["patches"].isChecked() is False


def test_installers_checkbox_is_a_real_choice_now():
    # #13: it spent its whole life ticked, greyed out and powerless, like a
    # decorative light switch. Now it shows what's saved, and saves what's shown.
    settings.update_settings({**SAVED_SETTINGS, "installers": False})
    dialog = SettingsDialog()
    installers = dialog.download_categories_check["installers"]
    assert installers.isEnabled() is True
    assert installers.isChecked() is False

    installers.setChecked(True)
    click(dialog, QDialogButtonBox.StandardButton.Save)

    assert settings._read_settings()["installers"] is True


def untick_every_category(dialog):
    for checkbox in dialog.download_categories_check.values():
        checkbox.setChecked(False)


@patch("gogstash.settings_dialog.QMessageBox.warning")
def test_save_refuses_when_no_download_category_is_ticked(mock_warning):
    # Nothing ticked means every game is a 0 byte download that "finishes"
    # instantly. Very fast, very useless.
    settings.update_settings(SAVED_SETTINGS)
    dialog = SettingsDialog()
    untick_every_category(dialog)

    click(dialog, QDialogButtonBox.StandardButton.Save)

    mock_warning.assert_called_once()
    assert "category" in mock_warning.call_args.args[2]
    assert "platform" not in mock_warning.call_args.args[2]
    assert settings._read_settings()["bonus_content"] is True  # nothing written
    assert dialog.result() != dialog.DialogCode.Accepted


@patch("gogstash.settings_dialog.QMessageBox.warning")
def test_save_lists_every_problem_in_one_warning(mock_warning):
    # One dialog with both complaints, not a game of whack-a-mole where
    # fixing the platforms reveals the categories were empty too.
    settings.update_settings(SAVED_SETTINGS)
    dialog = SettingsDialog()
    untick_every_category(dialog)
    for checkbox in dialog.platform_filter_check.values():
        checkbox.setChecked(False)

    click(dialog, QDialogButtonBox.StandardButton.Save)

    mock_warning.assert_called_once()
    message = mock_warning.call_args.args[2]
    assert "platform" in message and "category" in message
    assert settings._read_settings()["platform_filter"] == ["Linux"]


def test_save_persists_edited_values():
    dialog = SettingsDialog()
    dialog.download_edit_path.setText("/new/path")
    dialog.download_concurrency_edit.setValue(7)
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
    assert saved["verify_downloads"] is False
    assert saved["platform_filter"] == ["Windows"]
    assert saved["bonus_content"] is True
    assert saved["patches"] is False


def test_saving_settings_leaves_the_theme_picked_in_the_toolbar_alone():
    # The theme moved out to the toolbar so it can change mid-download. The
    # form no longer has a say in it, and must not quietly reset it to
    # whatever it thinks the default is on the way out.
    settings.update_settings(SAVED_SETTINGS)
    dialog = SettingsDialog()

    click(dialog, QDialogButtonBox.StandardButton.Save)

    assert settings._read_settings()["theme"] == "Dark"


def test_save_closes_the_dialog():
    dialog = SettingsDialog()
    click(dialog, QDialogButtonBox.StandardButton.Save)
    assert dialog.result() == dialog.DialogCode.Accepted  # accept() was called


def test_discard_reverts_unsaved_edits_without_touching_disk():
    settings.update_settings(SAVED_SETTINGS)
    dialog = SettingsDialog()
    dialog.download_edit_path.setText("/unsaved/edit")

    click(dialog, QDialogButtonBox.StandardButton.Discard)

    assert dialog.download_edit_path.text() == "/saved/path"
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

    assert dialog.download_concurrency_edit.value() == settings.DEFAULT_SETTINGS["download_concurrency"]
    assert settings._read_settings()["download_concurrency"] == 3  # disk still holds the saved value


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
    library_db.update_cache([])  # creates an (empty) db file
    db_path = paths.config_file_path(paths.ConfigFile.DB_CACHE)
    assert db_path.exists()
    dialog = SettingsDialog()

    dialog.clear_cache_button.click()

    assert not db_path.exists()


@patch("gogstash.settings_dialog.QMessageBox.exec")
def test_clear_cache_button_keeps_db_file_when_cancelled(mock_exec):
    mock_exec.return_value = QMessageBox.StandardButton.No
    library_db.update_cache([])  # creates an (empty) db file
    db_path = paths.config_file_path(paths.ConfigFile.DB_CACHE)
    assert db_path.exists()
    dialog = SettingsDialog()

    dialog.clear_cache_button.click()

    assert db_path.exists()


# --- Download languages ---

def test_language_picker_lists_every_gog_language_with_english_on_top():
    dialog = SettingsDialog()

    assert list(language_items(dialog)) == list(settings.GOG_LANGUAGES)
    assert dialog.language_picker.item(0).text() == "English"


def test_dialog_ticks_the_saved_languages():
    settings.update_settings(SAVED_SETTINGS)

    dialog = SettingsDialog()

    assert ticked_languages(dialog) == {"de", "fr"}


def test_save_persists_the_ticked_language_codes():
    # The picker shows "Deutsch" but settings.json wants "de". Saving the
    # label instead of the code would filter for a language GOG has never
    # heard of and quietly fall back to English every time.
    dialog = SettingsDialog()
    set_language(dialog, "en", False)
    set_language(dialog, "de", True)
    set_language(dialog, "jp", True)

    click(dialog, QDialogButtonBox.StandardButton.Save)

    assert sorted(settings._read_settings()["languages"]) == ["de", "jp"]


def test_restore_defaults_unticks_languages_that_are_not_default():
    settings.update_settings(SAVED_SETTINGS)
    dialog = SettingsDialog()

    click(dialog, QDialogButtonBox.StandardButton.RestoreDefaults)

    assert ticked_languages(dialog) == set(settings.DEFAULT_SETTINGS["languages"])


def test_discard_restores_the_saved_languages():
    settings.update_settings(SAVED_SETTINGS)
    dialog = SettingsDialog()
    set_language(dialog, "de", False)
    set_language(dialog, "pl", True)

    click(dialog, QDialogButtonBox.StandardButton.Discard)

    assert ticked_languages(dialog) == {"de", "fr"}


def test_unticking_every_language_disables_save_until_one_comes_back():
    # Zero languages would be a very efficient downloader. It would also
    # never download anything, so Save sits this one out.
    dialog = SettingsDialog()
    assert ticked_languages(dialog) == {"en"}

    set_language(dialog, "en", False)

    assert save_button(dialog).isEnabled() is False
    assert dialog.language_picker.toolTip() != ""

    set_language(dialog, "de", True)

    assert save_button(dialog).isEnabled() is True
    assert dialog.language_picker.toolTip() == ""


def test_a_mangled_language_setting_opens_with_the_default_ticked():
    # Hand-edited settings.json with languages set to [] or null. The
    # dialog should show what the downloader will actually use, not a
    # blank list, and definitely not a TypeError.
    for mangled in ([], None):
        settings.update_setting("languages", mangled)

        dialog = SettingsDialog()

        assert ticked_languages(dialog) == set(settings.DEFAULT_SETTINGS["languages"])


def test_a_mangled_platform_setting_opens_with_the_defaults_ticked():
    settings.update_setting("platform_filter", None)

    dialog = SettingsDialog()

    ticked = [name for name, box in dialog.platform_filter_check.items() if box.isChecked()]
    assert ticked == settings.DEFAULT_SETTINGS["platform_filter"]


@patch("gogstash.settings_dialog.QMessageBox.warning")
def test_save_refuses_when_no_platform_is_ticked(mock_warning):
    # Every game at 0 bytes is technically a very fast library. Not saved.
    settings.update_settings(SAVED_SETTINGS)  # platform_filter: ["Linux"]
    dialog = SettingsDialog()
    dialog.platform_filter_check["Linux"].setChecked(False)

    click(dialog, QDialogButtonBox.StandardButton.Save)

    mock_warning.assert_called_once()
    assert settings._read_settings()["platform_filter"] == ["Linux"]
    assert dialog.result() != dialog.DialogCode.Accepted
