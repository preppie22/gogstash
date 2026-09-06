import sys
import humanize

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
    QSizePolicy,
    QHBoxLayout,
    QVBoxLayout,
    QPushButton
)
from PySide6.QtGui import (
    QAction,
    QIcon,
    QColor,
)
from PySide6.QtCore import Qt, QSize

from gogstash import gog_auth
from gogstash.gog_api import LibraryFetchThread, load_library
from gogstash.login_window import LoginWindow
from gogstash.settings_dialog import SettingsDialog
from gogstash.download_window import DownloadWindow
from gogstash.icon_utils import get_icon, color_icon, badge_icon

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GogStash")
        self.resize(800, 600)
        self.download_window = DownloadWindow(self)
        self.download_window.queue_changed.connect(self.set_download_badge)
        self._queue_count = 0

        self.logged_in_indicator = QLabel()
        self.logged_in_indicator.setFixedSize(QSize(10,10))
        self.logged_in_indicator.setStyleSheet("background-color: red; border-radius: 5")
        self.status_text = QLabel()
        self.statusBar()
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().addWidget(self.logged_in_indicator)
        self.statusBar().addWidget(self.status_text)
        self.main_toolbar = self.addToolBar("Main")
        self.main_toolbar.setMovable(False)
        
        self.error_message = QErrorMessage()

        self.login_button = QAction("Login", self, icon=QIcon(get_icon('login.svg')))
        self.login_button.triggered.connect(self.open_login_window)
        self.main_toolbar.addAction(self.login_button)

        self.logout_button = QAction("Logout", self, icon=QIcon(get_icon('logout.svg')))
        self.logout_button.triggered.connect(self.logout)
        self.main_toolbar.addAction(self.logout_button)
        self.main_toolbar.addSeparator()

        self.fetch_games_button = QAction("Refresh Games List", self, icon=QIcon(get_icon('fetch.svg')))
        self.fetch_games_button.triggered.connect(self.fetch_games)
        self.main_toolbar.addAction(self.fetch_games_button)
        # self.main_toolbar.addSeparator()

        self.downloads_window_button = QAction("Show Download Queue", self, icon=QIcon(get_icon('download.svg')))
        self.downloads_window_button.triggered.connect(self.open_downloads)
        self.main_toolbar.addAction(self.downloads_window_button)

        self.spacer = QWidget()
        self.spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.main_toolbar.addWidget(self.spacer)

        self.settings_button = QAction("Settings", self, icon=QIcon(get_icon('settings.svg')))
        self.settings_button.triggered.connect(self.open_settings)
        self.main_toolbar.addAction(self.settings_button)
        QApplication.instance().styleHints().colorSchemeChanged.connect(self._color_scheme_refresh)
        SettingsDialog.set_color_theme()

        self.central_widget = QWidget()
        self.central_layout = QHBoxLayout()
        self.central_widget.setLayout(self.central_layout)

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

        self.button_layout = QVBoxLayout()
        self.button_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.queue_download_button = QPushButton("Add to Download Queue")
        self.queue_download_button.clicked.connect(self.onclick_queue_download)
        self.button_layout.addWidget(self.queue_download_button)

        self.central_layout.addWidget(self.games_list)
        self.central_layout.addLayout(self.button_layout)

        self.setCentralWidget(self.central_widget)
        self._update_login_status()
        self._color_scheme_refresh(QApplication.instance().styleHints().colorScheme())
        self.on_games_loaded(load_library())

    def _color_scheme_refresh(self, scheme: Qt.ColorScheme) -> None:
        self.set_download_badge(self._queue_count)
        for button in self.main_toolbar.actions():
            if button is self.downloads_window_button: continue
            current_icon = button.icon()
            if not current_icon: continue
            if scheme == Qt.ColorScheme.Light:
                button.setIcon(color_icon(current_icon, QColor(Qt.GlobalColor.black)))
            else:
                button.setIcon(color_icon(current_icon, QColor(Qt.GlobalColor.white)))
    
    def _update_login_status(self):
        token = gog_auth.get_valid_token()
        if token:
            self.status_text.setText("Logged in")
            self.logged_in_indicator.setStyleSheet("background-color: green; border-radius: 5")
        else:
            self.status_text.setText("Not logged in")
            self.logged_in_indicator.setStyleSheet("background-color: red; border-radius: 5")

    def set_download_badge(self, count: int):
        self._queue_count = count
        base_icon = QIcon(get_icon('download.svg'))
        color_scheme = QApplication.instance().styleHints().colorScheme()
        scheme_color = None
        if color_scheme == Qt.ColorScheme.Light:
            scheme_color = QColor(Qt.GlobalColor.black)
        else:
            scheme_color = QColor(Qt.GlobalColor.white)
        colored_icon = color_icon(base_icon, scheme_color)
        badged_icon = badge_icon(colored_icon, count)
        self.downloads_window_button.setIcon(badged_icon)

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

    def open_downloads(self):
        self.download_window.show()

    def fetch_games(self):
        token = gog_auth.get_valid_token()
        if not token:
            self.error_message.showMessage("You are not logged in to GOG!")
            return
        self.fetch_thread = LibraryFetchThread(token["access_token"])
        self.fetch_thread.succeeded.connect(self.on_games_loaded)
        self.fetch_thread.failed.connect(lambda msg: self.error_message.showMessage(msg))
        self.fetch_thread.start()

    def onclick_queue_download(self):
        selection = self.games_list.selectedItems()
        for item in selection:
            if item.column() == 0:
                self.download_window.add_to_queue(item.text())

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