import sys
import humanize
import pathlib
from importlib import resources

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QDialog,
    QErrorMessage,
    QTableWidget,
    QTableWidgetItem,
    QAbstractItemView,
    QHeaderView
)
from PySide6.QtGui import QAction, QIcon
from PySide6.QtCore import Qt

from gogstash import gog_auth
from gogstash.gog_api import LibraryFetchThread
from gogstash.login_window import LoginWindow
from gogstash.settings_dialog import SettingsDialog

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GogStash")
        self.resize(800, 600)

        self.statusBar()
        self.main_toolbar = self.addToolBar("Main")
        # self.main_toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        
        self.error_message = QErrorMessage()

        self.login_button = QAction("Login", self, icon=QIcon(self._get_icon('login.svg')))
        self.login_button.triggered.connect(self.open_login_window)
        self.main_toolbar.addAction(self.login_button)

        self.fetch_games_button = QAction("Load Games List", self, icon=QIcon(self._get_icon('fetch.svg')))
        self.fetch_games_button.triggered.connect(self.fetch_games)
        self.main_toolbar.addAction(self.fetch_games_button)

        self.settings_button = QAction("Settings", self, icon=QIcon(self._get_icon('settings.svg')))
        self.settings_button.triggered.connect(self.open_settings)
        self.main_toolbar.addAction(self.settings_button)
        QApplication.instance().styleHints().colorSchemeChanged.connect(self._color_scheme_refresh)
        SettingsDialog.set_color_theme()


        self.games_list = QTableWidget()
        self.games_list.setColumnCount(3)
        self.games_list.setHorizontalHeaderLabels(['Title', 'Download Size', 'Fetched'])
        self.games_list.setAlternatingRowColors(True)
        self.games_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.games_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.games_list.verticalHeader().setVisible(False)
        self.games_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.games_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.games_list.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        self.setCentralWidget(self.games_list)
        self._update_login_status()

    @staticmethod
    def _get_icon(icon_file: str) -> str:
        resources.files('gogstash')
        return str(resources.files('gogstash') / 'res/icons' / icon_file)

    def _color_scheme_refresh(self, scheme: Qt.ColorScheme) -> None:
        toolbar_buttons = self.main_toolbar.children()
        for button in toolbar_buttons:
            current_icon = button.icon()
    
    def _update_login_status(self):
        token = gog_auth.get_valid_token()
        if token:
            self.statusBar().showMessage("Logged in")
        else:
            self.statusBar().showMessage("Not logged in")

    def open_login_window(self):
        login_window = LoginWindow(self)
        if login_window.exec() == QDialog.DialogCode.Accepted:
            self._update_login_status()

    def open_settings(self):
        settings_dialog = SettingsDialog(self)
        settings_dialog.exec()

    def fetch_games(self):
        token = gog_auth.get_valid_token()
        if not token:
            self.error_message.showMessage("You are not logged in to GOG!")
            return
        self.fetch_thread = LibraryFetchThread(token["access_token"])
        self.fetch_thread.succeeded.connect(self.on_games_loaded)
        self.fetch_thread.failed.connect(lambda msg: self.error_message.showMessage(msg))
        self.fetch_thread.start()

    def on_games_loaded(self, result):
        self.games_list.setRowCount(0)
        for game in result:
            row_idx = self.games_list.rowCount()
            self.games_list.insertRow(row_idx)
            self.games_list.setItem(row_idx, 0, QTableWidgetItem(game['title']))
            self.games_list.setItem(row_idx, 1, QTableWidgetItem(humanize.naturalsize(game['download_size'])))
            self.games_list.setItem(row_idx, 2, QTableWidgetItem(str(game['fetched'])))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())