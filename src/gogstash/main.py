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
    QPushButton,
    QProgressBar
)
from PySide6.QtGui import (
    QAction,
)
from PySide6.QtCore import Qt, QSize

from gogstash import gog_auth
from gogstash.gog_api import LibraryFetchThread, load_library
from gogstash.login_window import LoginWindow
from gogstash.settings_dialog import SettingsDialog
from gogstash.download_window import DownloadWindow, UserRole
from gogstash.icon_utils import get_icon, badge_icon


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
        self.status_progress = QProgressBar()
        self.status_progress.setVisible(False)
        self.statusBar()
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().addWidget(self.logged_in_indicator)
        self.statusBar().addWidget(self.status_text)
        self.statusBar().addWidget(self.status_progress)
        self.main_toolbar = self.addToolBar("Main")
        self.main_toolbar.setMovable(False)
        
        self.error_message = QErrorMessage()

        self.login_button = QAction("Login", self, icon=get_icon('login.svg'))
        self.login_button.setProperty('iconFile', 'login.svg')
        self.login_button.triggered.connect(self.open_login_window)
        self.main_toolbar.addAction(self.login_button)

        self.logout_button = QAction("Logout", self, icon=get_icon('logout.svg'))
        self.logout_button.setProperty('iconFile', 'logout.svg')
        self.logout_button.triggered.connect(self.logout)
        self.main_toolbar.addAction(self.logout_button)
        self.main_toolbar.addSeparator()

        self.fetch_games_button = QAction("Refresh Games List", self, icon=get_icon('fetch.svg'))
        self.fetch_games_button.setProperty('iconFile', 'fetch.svg')
        self.fetch_games_button.triggered.connect(self.fetch_games)
        self.main_toolbar.addAction(self.fetch_games_button)
        # self.main_toolbar.addSeparator()

        self.downloads_window_button = QAction("Show Download Queue", self, icon=get_icon('download.svg'))
        self.downloads_window_button.setProperty('iconFile', 'download.svg')
        self.downloads_window_button.triggered.connect(self.open_downloads)
        self.main_toolbar.addAction(self.downloads_window_button)

        self.spacer = QWidget()
        self.spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.main_toolbar.addWidget(self.spacer)

        self.settings_button = QAction("Settings", self, icon=get_icon('settings.svg'))
        self.settings_button.setProperty('iconFile', 'settings.svg')
        self.settings_button.triggered.connect(self.open_settings)
        self.main_toolbar.addAction(self.settings_button)
        QApplication.instance().styleHints().colorSchemeChanged.connect(self._color_scheme_refresh)
        SettingsDialog.set_color_theme()

        self.central_widget = QWidget()
        self.central_layout = QHBoxLayout()
        self.central_widget.setLayout(self.central_layout)

        self.games_list = QTableWidget()
        self.games_list.cellDoubleClicked.connect(self.doubleclick_game_list)
        self.games_list.setColumnCount(3)
        self.games_list.setHorizontalHeaderLabels(['Title', 'Total Size', 'Fetched'])
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

        self.open_download_queue_button = QPushButton("Show Download Queue")
        self.open_download_queue_button.clicked.connect(self.open_downloads)
        self.button_layout.addWidget(self.open_download_queue_button)

        self.central_layout.addWidget(self.games_list)
        self.central_layout.addLayout(self.button_layout)

        self.setCentralWidget(self.central_widget)
        self._update_login_status()
        self._color_scheme_refresh()
        self.on_games_loaded(load_library())

    def _color_scheme_refresh(self) -> None:
        self.set_download_badge(self._queue_count)
        for button in self.main_toolbar.actions():
            if button is self.downloads_window_button: continue
            if not button.icon(): continue
            button.setIcon(get_icon(button.property('iconFile')))
    
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
        base_icon = get_icon('download.svg')
        badged_icon = badge_icon(base_icon, count)
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
        self.on_games_loaded(load_library())

    def open_downloads(self):
        self.download_window.show()

    def fetch_games(self):
        token = gog_auth.get_valid_token()
        if not token:
            self.error_message.showMessage("You are not logged in to GOG!")
            return
        self.fetch_thread = LibraryFetchThread(token["access_token"], force=True)
        self.fetch_thread.succeeded.connect(self.on_games_loaded)
        self.fetch_thread.failed.connect(self.fetch_failed_handler)
        self.fetch_thread.progress.connect(self.update_fetch_progress)
        self.fetch_games_button.setDisabled(True)
        self.status_text.setText("Fetching games list...")
        self.fetch_thread.start()

    def onclick_queue_download(self):
        selection_data = self.games_list.selectedItems()
        row_data = {}
        for item in selection_data:
            if item.column() == 0:
                row_data['product_id'] = item.data(UserRole.PRODUCT_ID_ROLE.value)
                row_data['title'] = item.text()
            elif item.column() == 1:
                row_data['size'] = item.text()
            elif item.column() == 2:
                self.download_window.add_to_queue(row_data.copy())
                row_data.clear()

    def doubleclick_game_list(self, row, _):
        row_data = {}
        row_data['product_id'] = self.games_list.item(row, 0).data(UserRole.PRODUCT_ID_ROLE.value)
        row_data['title'] = self.games_list.item(row, 0).text()
        row_data['size'] = self.games_list.item(row, 1).text()
        self.download_window.add_to_queue(row_data.copy())

    def update_fetch_progress(self, progress: int):
        if not self.status_progress.isVisible():
            self.status_progress.setVisible(True)
        self.status_text.setText(f"Fetching metadata ")
        self.status_progress.setValue(int(progress))
        return

    def fetch_failed_handler(self, error_message: str):
        self.error_message.showMessage(error_message)
        self._update_login_status()
        self.status_progress.setVisible(False)
        self.fetch_games_button.setDisabled(False)

    def on_games_loaded(self, result):
        self._update_login_status()
        self.status_progress.setVisible(False)
        self.fetch_games_button.setDisabled(False)
        self.games_list.setRowCount(0)
        result = sorted(result, key=(lambda n: n['title']))
        for game in result:
            row_idx = self.games_list.rowCount()
            first_column = QTableWidgetItem(game['title'])
            first_column.setData(UserRole.PRODUCT_ID_ROLE.value, game['product_id'])
            self.games_list.insertRow(row_idx)
            self.games_list.setItem(row_idx, 0, first_column)
            self.games_list.setItem(row_idx, 1, QTableWidgetItem(humanize.naturalsize(game['download_size'])))
            self.games_list.setItem(row_idx, 2, QTableWidgetItem(str(game['fetched'])))
        self.games_list.selectRow(0)
        self.games_list.setFocus()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())