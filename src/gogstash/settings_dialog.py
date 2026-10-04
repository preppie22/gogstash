"""Modal dialog for editing user settings."""

import sys
import humanize

from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QDialog,
    QHBoxLayout,
    QVBoxLayout,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QSpinBox,
    QCheckBox,
    QGroupBox,
    QLabel,
    QDialogButtonBox,
    QMessageBox,
    QSpacerItem,
    QSizePolicy,
    QStyle,
    QListWidget,
    QListWidgetItem,
)
from PySide6.QtCore import (
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QPalette,
    QColor,
    QAction,
    QIcon
)
from gogstash import settings
from gogstash import library_db
from gogstash import gog_auth

class SettingsDialog(QDialog):
    """Dialog for editing user settings and clearing the library cache.

    Attributes:
        cache_cleared (Signal): Emitted after the library cache is cleared.
    """
    cache_cleared = Signal()

    def __init__(self, parent=None):
        """Build the form and fill it with the saved settings.

        Args:
            parent (QWidget): Optional parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("Settings")

        self.window_layout = QFormLayout()
        self.window_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.setLayout(self.window_layout)

        # Download Path
        self.download_edit_path = QLineEdit()
        browse_action = QAction(QIcon.fromTheme('folder-open'), "Browse", self.download_edit_path)
        browse_action.triggered.connect(self.onclick_browse_download_path)
        self.download_edit_path.addAction(browse_action, QLineEdit.ActionPosition.TrailingPosition)
        self.window_layout.addRow("Download Directory", self.download_edit_path)

        # Download Concurrency
        self.download_concurrency_edit = QSpinBox()
        self.download_concurrency_edit.setMinimum(1)
        self.download_concurrency_edit.setMaximum(999)
        self.download_concurrency_edit.valueChanged.connect(self.on_concurrency_changed)
        self.window_layout.addRow("Download Concurrency", self.download_concurrency_edit)

        # Platform Filter
        self.platform_filter_layout = QHBoxLayout()
        self.platform_filter_check = {
            "Linux": QCheckBox("Linux"),
            "Windows": QCheckBox("Windows"),
            "MacOS": QCheckBox("MacOS")
        }
        for checkbox in self.platform_filter_check.items():
            self.platform_filter_layout.addWidget(checkbox[1])
        self.window_layout.addRow("Platforms", self.platform_filter_layout)

        # Verify Downloads
        self.verify_downloads_check = QCheckBox()
        self.verify_downloads_check.setToolTip("Do not redownload files that exist on disk")
        self.window_layout.addRow("Prevent Redownload", self.verify_downloads_check)

        # Download Filters
        self.download_categories_layout = QHBoxLayout()
        self.download_categories_check = {
            "installers": QCheckBox("Installers"),
            "bonus_content": QCheckBox("Bonus Content"),
            "patches": QCheckBox("Patches")
        }
        for checkbox in self.download_categories_check.items():
            self.download_categories_layout.addWidget(checkbox[1])
        self.window_layout.addRow("Download Categories", self.download_categories_layout)

        # Download Languages
        self.language_picker = QListWidget()
        for code, description in settings.GOG_LANGUAGES.items():
            entry = QListWidgetItem(description, self.language_picker)
            entry.setCheckState(Qt.CheckState.Unchecked)
            entry.setData(Qt.ItemDataRole.UserRole, code)
        self.language_picker.setMaximumHeight(
            self.language_picker.sizeHintForRow(0) * 6 + self.language_picker.frameWidth() * 2
        )
        self.language_picker.setAlternatingRowColors(True)
        self.language_picker.itemChanged.connect(self.on_language_changed)
        self.window_layout.addRow("Download Languages", self.language_picker)

        # Spacer
        self.window_layout.addItem(QSpacerItem(0, 16, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed))

        # Cache
        self.cache_groupbox = QGroupBox("Library Cache")
        self.cache_groupbox_layout = QVBoxLayout()
        self.cache_groupbox.setLayout(self.cache_groupbox_layout)
        self.current_cache_label = QLabel(f"Size: {humanize.naturalsize(library_db.get_cache_size())}")
        self.clear_cache_button = QPushButton("Clear Cache")
        self.clear_cache_button.clicked.connect(self.onclick_clear_cache)
        self.cache_groupbox_layout.addWidget(self.current_cache_label)
        self.cache_groupbox_layout.addWidget(self.clear_cache_button)
        self.window_layout.addRow(self.cache_groupbox)

        # Settings Buttons
        self.settings_form_buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save|
            QDialogButtonBox.StandardButton.RestoreDefaults|
            QDialogButtonBox.StandardButton.Close
        )
        discard_button = self.settings_form_buttons.addButton("Discard Changes", QDialogButtonBox.ButtonRole.DestructiveRole)
        discard_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogDiscardButton))
        self.settings_form_buttons.clicked.connect(self.settings_buttons_handler)
        self.window_layout.addWidget(self.settings_form_buttons)

        self.adjustSize()
        self.on_concurrency_changed(self.download_concurrency_edit.value())
        self.load_settings()

    @staticmethod
    def set_color_theme() -> None:
        """Apply the saved theme setting to the application.

        The ``'System'`` theme follows the operating system's color scheme.
        """
        theme = settings.read_setting('theme')
        if theme == 'System': QApplication.instance().styleHints().setColorScheme(Qt.ColorScheme.Unknown)
        elif theme == 'Light': QApplication.instance().styleHints().setColorScheme(Qt.ColorScheme.Light)
        elif theme == 'Dark': QApplication.instance().styleHints().setColorScheme(Qt.ColorScheme.Dark)

    def load_settings(self, values: dict = None):
        """Fill the form fields.

        Args:
            values (dict): Settings to show. The saved settings are used if
                omitted.
        """
        if values:
            form_settings = values
        else:
            form_settings = settings.read_settings()
        self.download_edit_path.setText(form_settings.get('download_path'))
        self.download_concurrency_edit.setValue(form_settings.get('download_concurrency'))
        platform_filters = form_settings.get('platform_filter') or settings.DEFAULT_SETTINGS['platform_filter']
        for checkbox in self.platform_filter_check.items():
            if checkbox[0] in platform_filters:
                checkbox[1].setChecked(True)
            else:
                checkbox[1].setChecked(False)
        self.verify_downloads_check.setChecked(form_settings.get('verify_downloads'))
        for checkbox in self.download_categories_check.items():
            if form_settings.get(checkbox[0]):
                checkbox[1].setChecked(True)
            else:
                checkbox[1].setChecked(False)
        languages = form_settings.get('languages') or settings.DEFAULT_SETTINGS['languages']
        for row_idx in range(self.language_picker.count()):
            entry = self.language_picker.item(row_idx)
            if entry.data(Qt.ItemDataRole.UserRole) in languages:
                entry.setCheckState(Qt.CheckState.Checked)
            else:
                entry.setCheckState(Qt.CheckState.Unchecked)

    def settings_buttons_handler(self, button):
        """Handle clicks on the dialog buttons.

        Save writes the form to disk and closes the dialog, unless no
        platform or no download category is ticked: then it shows one
        warning listing both problems and saves nothing.
        Discard Changes reloads the saved settings. Restore Defaults fills the
        form with default values without saving. Close closes the dialog
        without saving.

        Args:
            button (QAbstractButton): The clicked button.
        """
        role = self.settings_form_buttons.buttonRole(button)
        if role == QDialogButtonBox.ButtonRole.AcceptRole:
            form_settings = {
                'download_path': self.download_edit_path.text(),
                'download_concurrency': self.download_concurrency_edit.value(),
                'platform_filter': [checkbox[0] for checkbox in self.platform_filter_check.items() if checkbox[1].isChecked()],
                'verify_downloads': self.verify_downloads_check.isChecked(),
                'installers': self.download_categories_check['installers'].isChecked(),
                'bonus_content': self.download_categories_check['bonus_content'].isChecked(),
                'patches': self.download_categories_check['patches'].isChecked(),
            }
            languages = []
            for row_idx in range(self.language_picker.count()):
                entry = self.language_picker.item(row_idx)
                if entry.checkState() == Qt.CheckState.Checked:
                    languages.append(entry.data(Qt.ItemDataRole.UserRole))
            form_settings['languages'] = languages or settings.DEFAULT_SETTINGS['languages']
            error_lines = []
            if not form_settings['platform_filter']:
                error_lines.append("Pick at least one platform")
            if not (form_settings['installers'] or form_settings['bonus_content'] or form_settings['patches']):
                error_lines.append("Pick at least one download category")
            if error_lines:
                error_messages = '\n'.join(error_lines)
                QMessageBox.warning(
                    self,
                    "Invalid Settings",
                    f"Before saving:\n\n{error_messages}"
                )
                return
            settings.update_settings(form_settings)
            self.accept()
        if role == QDialogButtonBox.ButtonRole.DestructiveRole:
            self.load_settings()
        if role == QDialogButtonBox.ButtonRole.ResetRole:
            self.load_settings(settings.DEFAULT_SETTINGS)
        if role == QDialogButtonBox.ButtonRole.RejectRole:
            self.reject()

    def onclick_browse_download_path(self):
        """Pick a folder and put its path in the download directory field."""
        current_directory = settings.read_setting('download_path')
        folder_selection = QFileDialog.getExistingDirectory(dir=current_directory)
        if folder_selection:
            self.download_edit_path.setText(folder_selection)

    def onclick_clear_cache(self):
        """Clear the library cache after asking for confirmation.

        Emits ``cache_cleared`` if the cache was cleared, then refreshes the
        displayed cache size.
        """
        confirmation = QMessageBox()
        confirmation.setIcon(QMessageBox.Icon.Question)
        confirmation.setWindowTitle("Clear Cache")
        confirmation.setInformativeText("Cache rebuild can take a long time for large libraries.")
        confirmation.setText("Are you sure you want to clear cache?")
        confirmation.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        confirmation.setDefaultButton(QMessageBox.StandardButton.No)
        confirmation.setEscapeButton(QMessageBox.StandardButton.No)
        response = confirmation.exec()
        if response == QMessageBox.StandardButton.Yes:
            library_db.clear_cache()
            self.cache_cleared.emit()
        self.current_cache_label.setText(f"Size: {humanize.naturalsize(library_db.get_cache_size())}")

    def on_concurrency_changed(self, value: int):
        """Warn about high download concurrency.

        Values of 5 or more tint the field red and add a warning tooltip.

        Args:
            value (int): The new concurrency value.
        """
        color_palette = QPalette(self.download_concurrency_edit.parentWidget().palette())
        if value >= 5:
            color_palette.setColor(QPalette.ColorRole.Base, QColor(255, 0, 0, 60))
            color_palette.setColor(QPalette.ColorRole.Button, QColor(255, 0, 0, 60))
            self.download_concurrency_edit.setPalette(color_palette)
            self.download_concurrency_edit.setToolTip("WARNING: High concurrency may increase risk of throttling or GOG flagging your account")
        else:
            self.download_concurrency_edit.setPalette(color_palette)
            self.download_concurrency_edit.setStyleSheet("")
            self.download_concurrency_edit.setToolTip("")

    def on_language_changed(self, item: QListWidgetItem):
        checked_count = 0
        for row_idx in range(self.language_picker.count()):
            if self.language_picker.item(row_idx).checkState() == Qt.CheckState.Checked:
                checked_count += 1
        color_palette = QPalette(self.language_picker.parentWidget().palette())
        if checked_count == 0:
            color_palette.setColor(QPalette.ColorRole.Base, QColor(255, 0, 0, 60))
            color_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(255, 0, 0, 60))
            self.language_picker.setPalette(color_palette)
            self.language_picker.setToolTip("At least one language must be picked")
            self.settings_form_buttons.button(QDialogButtonBox.StandardButton.Save).setDisabled(True)
        else:
            self.language_picker.setPalette(color_palette)
            self.language_picker.setStyleSheet("")
            self.language_picker.setToolTip("")
            self.settings_form_buttons.button(QDialogButtonBox.StandardButton.Save).setDisabled(False)


        
if __name__ == "__main__":
    app = QApplication(sys.argv)
    dialog = SettingsDialog()
    dialog.exec()

