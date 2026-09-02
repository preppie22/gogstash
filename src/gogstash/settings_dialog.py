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
    QComboBox,
    QCheckBox,
    QGroupBox,
    QLabel,
    QDialogButtonBox,
    QStatusBar
)
from PySide6.QtCore import (
    Qt
)
from PySide6.QtGui import QStyleHints
from gogstash import settings
from gogstash import library_db

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")

        self.parent_layout = QVBoxLayout()
        self.window_layout = QFormLayout()

        self.setLayout(self.parent_layout)
        self.parent_layout.addLayout(self.window_layout)
        self.parent_layout.addStretch()
        self.status_bar = QStatusBar()
        self.parent_layout.addWidget(self.status_bar)

        # Download Path
        self.download_edit = QHBoxLayout()
        self.download_edit_path = QLineEdit()
        self.download_edit_browse = QPushButton("Browse")
        self.download_edit_browse.clicked.connect(self.onclick_browse_download_path)
        self.download_edit.addWidget(self.download_edit_path)
        self.download_edit.addWidget(self.download_edit_browse)
        self.window_layout.addRow("Download Directory", self.download_edit)

        # Download Concurrency
        self.download_concurrency_edit = QSpinBox()
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

        # Theme
        self.theme_select = QComboBox()
        self.theme_select.addItems(['Dark','Light','System'])
        self.window_layout.addRow("Theme", self.theme_select)

        # Verify Downloads
        self.verify_downloads_check = QCheckBox()
        self.window_layout.addRow("Verify Downloads", self.verify_downloads_check)

        # Download Filters
        self.download_categories_layout = QHBoxLayout()
        self.download_categories_check = {
            "installers": QCheckBox("Installers"),
            "bonus_content": QCheckBox("Bonus Content"),
            "patches": QCheckBox("Patches")
        }
        self.download_categories_check['installers'].setChecked(True)
        self.download_categories_check['installers'].setEnabled(False)
        self.download_categories_check['installers'].setToolTip("Installers will always be downloaded")
        for checkbox in self.download_categories_check.items():
            self.download_categories_layout.addWidget(checkbox[1])
        self.window_layout.addRow("Download Categories", self.download_categories_layout)

        # Cache
        self.cache_groupbox = QGroupBox("Library Cache")
        self.cache_groupbox_layout = QVBoxLayout()
        self.cache_groupbox.setLayout(self.cache_groupbox_layout)
        self.current_cache_label = QLabel(f"Size: {humanize.naturalsize(library_db.get_cache_size())}")
        self.clear_cache_button = QPushButton("Clear Cache")
        self.clear_cache_button.clicked.connect(self.onclick_clear_cache)
        self.cache_groupbox_layout.addWidget(self.current_cache_label)
        self.cache_groupbox_layout.addWidget(self.clear_cache_button)
        self.window_layout.addWidget(self.cache_groupbox)

        # Settings Buttons
        self.settings_form_buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save|
            QDialogButtonBox.StandardButton.Discard|
            QDialogButtonBox.StandardButton.RestoreDefaults
        )
        self.settings_form_buttons.clicked.connect(self.settings_buttons_handler)
        self.window_layout.addWidget(self.settings_form_buttons)

        self.adjustSize()
        self.load_settings()

    @staticmethod
    def set_color_theme() -> None:
        theme = settings.read_setting('theme')
        if theme == 'System': QApplication.instance().styleHints().setColorScheme(Qt.ColorScheme.Unknown)
        elif theme == 'Light': QApplication.instance().styleHints().setColorScheme(Qt.ColorScheme.Light)
        elif theme == 'Dark': QApplication.instance().styleHints().setColorScheme(Qt.ColorScheme.Dark)

    def load_settings(self, values: dict = None):
        if values:
            form_settings = values
        else:
            form_settings = settings.read_settings()
        self.download_edit_path.setText(form_settings.get('download_path'))
        self.download_concurrency_edit.setValue(form_settings.get('download_concurrency'))
        platform_filters = form_settings.get('platform_filter')
        for checkbox in self.platform_filter_check.items():
            if checkbox[0] in platform_filters:
                checkbox[1].setChecked(True)
            else:
                checkbox[1].setChecked(False)
        self.theme_select.setCurrentText(form_settings.get('theme'))
        self.verify_downloads_check.setChecked(form_settings.get('verify_downloads'))
        for checkbox in self.download_categories_check.items():
            if form_settings.get(checkbox[0]):
                checkbox[1].setChecked(True)
            else:
                checkbox[1].setChecked(False)

    def settings_buttons_handler(self, button):
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
                'theme': self.theme_select.currentText()
            }
            settings.update_settings(form_settings)
            self.set_color_theme()
            self.status_bar.showMessage("Settings Saved!", 2000)
        if role == QDialogButtonBox.ButtonRole.DestructiveRole:
            self.load_settings()
        if role == QDialogButtonBox.ButtonRole.ResetRole:
            self.load_settings(settings.DEFAULT_SETTINGS)

    def onclick_browse_download_path(self):
        current_directory = settings.read_setting('download_path')
        folder_selection = QFileDialog.getExistingDirectory(dir=current_directory)
        if folder_selection:
            self.download_edit_path.setText(folder_selection)

    def onclick_clear_cache(self):
        library_db.clear_cache()
        
if __name__ == "__main__":
    app = QApplication(sys.argv)
    dialog = SettingsDialog()
    dialog.exec()

