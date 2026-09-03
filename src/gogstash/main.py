import sys
import humanize
from importlib import resources

from PySide6.QtWidgets import (
    QWidget,
    QApplication,
    QMainWindow,
    QDialog,
    QErrorMessage,
    QTableWidget,
    QTableWidgetItem,
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QSizePolicy
)
from PySide6.QtGui import (
    QAction,
    QIcon,
    QColor,
    QPainter,
)
from PySide6.QtCore import Qt, QSize

from gogstash import gog_auth
from gogstash.gog_api import LibraryFetchThread, load_library
from gogstash.login_window import LoginWindow
from gogstash.settings_dialog import SettingsDialog

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GogStash")
        self.resize(800, 600)

        self.logged_in_indicator = QLabel()
        self.logged_in_indicator.setFixedSize(QSize(10,10))
        self.logged_in_indicator.setStyleSheet("background-color: red; border-radius: 5")
        self.status_text = QLabel()
        self.statusBar()
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().addWidget(self.logged_in_indicator)
        self.statusBar().addWidget(self.status_text)
        self.main_toolbar = self.addToolBar("Main")
        # self.main_toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.main_toolbar.setMovable(False)
        
        self.error_message = QErrorMessage()

        self.login_button = QAction("Login", self, icon=QIcon(self._get_icon('login.svg')))
        self.login_button.triggered.connect(self.open_login_window)
        self.main_toolbar.addAction(self.login_button)

        self.logout_button = QAction("Logout", self, icon=QIcon(self._get_icon('logout.svg')))
        self.logout_button.triggered.connect(self.logout)
        self.main_toolbar.addAction(self.logout_button)
        self.main_toolbar.addSeparator()

        self.fetch_games_button = QAction("Refresh Games List", self, icon=QIcon(self._get_icon('fetch.svg')))
        self.fetch_games_button.triggered.connect(self.fetch_games)
        self.main_toolbar.addAction(self.fetch_games_button)
        # self.main_toolbar.addSeparator()

        self.spacer = QWidget()
        self.spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.main_toolbar.addWidget(self.spacer)

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
        self._color_scheme_refresh(QApplication.instance().styleHints().colorScheme())
        self.on_games_loaded(load_library())

    @staticmethod
    def _get_icon(icon_file: str) -> str:
        resources.files('gogstash')
        return str(resources.files('gogstash') / 'icons' / icon_file)

    @staticmethod
    def _color_icon(icon: QIcon, color: QColor) -> QIcon:
        base = icon.pixmap(QSize(24, 24))
        with QPainter(base) as painter:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(base.rect(), color)
        return QIcon(base)

    def _color_scheme_refresh(self, scheme: Qt.ColorScheme) -> None:
        for button in self.main_toolbar.actions():
            current_icon = button.icon()
            if scheme == Qt.ColorScheme.Light:
                button.setIcon(self._color_icon(current_icon, QColor(Qt.GlobalColor.black)))
            else:
                button.setIcon(self._color_icon(current_icon, QColor(Qt.GlobalColor.white)))
    
    def _update_login_status(self):
        token = gog_auth.get_valid_token()
        if token:
            self.status_text.setText("Logged in")
            self.logged_in_indicator.setStyleSheet("background-color: green; border-radius: 5")
        else:
            self.status_text.setText("Not logged in")
            self.logged_in_indicator.setStyleSheet("background-color: red; border-radius: 5")

    def logout(self):
        gog_auth.clear_token()
        self._update_login_status()

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
        self.games_list.selectRow(0)
        self.games_list.setFocus()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())