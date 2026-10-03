"""Application entry point and main window."""

import sys
import humanize
from pathlib import Path
import importlib.metadata
from enum import IntEnum

from PySide6.QtWidgets import (
    QWidget,
    QApplication,
    QMainWindow,
    QDialog,
    QDockWidget,
    QErrorMessage,
    QTableWidget,
    QTableWidgetItem,
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QPushButton,
    QProgressBar,
    QDialogButtonBox,
    QMessageBox,
    QStyledItemDelegate
)
from PySide6.QtGui import (
    QAction,
)
from PySide6.QtCore import Qt, QSize

from gogstash import gog_auth
from gogstash.login_window import LoginWindow
from gogstash import library_db
from gogstash.settings_dialog import SettingsDialog
from gogstash.settings import read_setting
from gogstash.manifest import read_manifest, check_exist_by_downlink
from gogstash.download_window import DownloadWindow, UserRole
from gogstash.icon_utils import get_icon, get_logo, status_indicator

class FetchedDelegate(QStyledItemDelegate):
    """Draws a centered check mark in the Fetched cell of fetched games.

    The cell has no icon of its own, since Qt would draw that on the left
    edge. The fetched flag is read from ``Qt.ItemDataRole.UserRole``, and
    the check mark is drawn on every paint, so it follows a change of
    color scheme without being reset.
    """
    def paint(self, painter, option, index):
        """Paint the cell background, then the check mark if fetched.

        Args:
            painter (QPainter): The painter to draw with.
            option (QStyleOptionViewItem): Style options for the cell.
            index (QModelIndex): The cell being painted.
        """
        super().paint(painter, option, index)
        if index.data(Qt.ItemDataRole.UserRole):
            icon = status_indicator('green')
            icon.paint(painter, option.rect, Qt.AlignmentFlag.AlignCenter)

class GameListItem(QTableWidgetItem):
    """Library cell that sorts by a stored value instead of by its text.

    Used for the Size and Fetched columns. A size cell shows a readable
    size such as "900.0 MB", which would sort before "1.2 GB" as text, so
    it stores the byte count. A Fetched cell has no text at all, so it
    stores whether the game is fetched. The value is stored under
    ``Qt.ItemDataRole.UserRole`` and compared instead of the text.
    """
    def __lt__(self, other):
        """Compare two cells of the same column by their stored values.

        Args:
            other (GameListItem): The cell to compare against.

        Returns:
            bool: True if this cell's stored value is less than ``other``'s.
            Not fetched sorts before fetched.
        """
        return self.data(Qt.ItemDataRole.UserRole) < other.data(Qt.ItemDataRole.UserRole)

class Column(IntEnum):
    """Column indices of the library table."""
    TITLE = 0
    SIZE = 1
    FETCHED = 2

class MainWindow(QMainWindow):
    """Main application window.

    Holds the toolbar, the library list in the left dock, the download
    queue in the right dock and a status bar showing the login state and
    fetch progress.
    """
    def __init__(self):
        """Build the window and load the cached library."""
        super().__init__()
        self.setWindowTitle("GogStash")
        self.setWindowIcon(get_logo())
        self.resize(1024, 768)
        self.download_window = DownloadWindow(self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.download_window)
        self.download_window.game_succeeded.connect(self._on_game_succeeded)

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

        self.spacer = QWidget()
        self.spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.main_toolbar.addWidget(self.spacer)

        self.settings_button = QAction("Settings", self, icon=get_icon('settings.svg'))
        self.settings_button.setProperty('iconFile', 'settings.svg')
        self.settings_button.triggered.connect(self.open_settings)
        self.main_toolbar.addAction(self.settings_button)

        self.about_button = QAction("About", self, icon=get_icon('question.svg'))
        self.about_button.setProperty('iconFile', 'question.svg')
        self.about_button.triggered.connect(self.open_about_page)
        self.main_toolbar.addAction(self.about_button)

        self.left_dock = QDockWidget()
        self.library_widget = QWidget()
        self.library_layout = QVBoxLayout()
        self.library_widget.setLayout(self.library_layout)
        self.left_dock.setWidget(self.library_widget)
        self.left_dock.setWindowTitle("Library")
        self.left_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)

        self.games_list = QTableWidget()
        self.games_list.cellDoubleClicked.connect(self.doubleclick_game_list)
        self.games_list.setColumnCount(len(Column))
        self.games_list.setHorizontalHeaderLabels(['Title', 'Size', 'Fetched'])
        self.games_list.setAlternatingRowColors(True)
        self.games_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.games_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.games_list.verticalHeader().setVisible(False)
        self.games_list.horizontalHeader().setMinimumSectionSize(16)
        self.games_list.setColumnWidth(Column.FETCHED, 60)
        self.games_list.horizontalHeader().setSectionResizeMode(Column.TITLE, QHeaderView.ResizeMode.Stretch)
        self.games_list.horizontalHeader().setSectionResizeMode(Column.SIZE, QHeaderView.ResizeMode.ResizeToContents)
        self.games_list.horizontalHeader().setSectionResizeMode(Column.FETCHED, QHeaderView.ResizeMode.Fixed)
        self.games_list.setItemDelegateForColumn(Column.FETCHED, FetchedDelegate(self.games_list))
        self.games_list.setSortingEnabled(True)
        self.games_list.sortByColumn(Column.TITLE, Qt.SortOrder.AscendingOrder)

        self.queue_download_button = QPushButton("Queue Selection")
        self.queue_download_button.setIcon(get_icon('enqueue.svg'))
        self.queue_download_button.setProperty('iconFile', 'enqueue.svg')
        self.queue_download_button.clicked.connect(self.onclick_queue_download)

        self.button_layout = QDialogButtonBox()
        self.button_layout.addButton(self.queue_download_button, QDialogButtonBox.ButtonRole.ActionRole)

        self.library_layout.addWidget(self.games_list)
        self.library_layout.addWidget(self.button_layout)

        if not library_db.verify_schema_version():
            QMessageBox.information(
                self,
                "Cache Outdated",
                "Your library cache was built by an older version of GogStash and has been updated. "
                "Click Refresh to reload your library and rebuild the cache.",
                QMessageBox.StandardButton.Ok
            )

        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,self.left_dock)
        self._update_login_status()
        QApplication.instance().styleHints().colorSchemeChanged.connect(self._color_scheme_refresh)
        SettingsDialog.set_color_theme()
        self._color_scheme_refresh()
        self.on_games_loaded(library_db.get_product_listing())

    def _color_scheme_refresh(self) -> None:
        """Reload toolbar and button icons for the current color scheme."""
        for button in self.main_toolbar.actions():
            icon_file = button.property('iconFile')
            if icon_file:
                button.setIcon(get_icon(icon_file))
        for button in self.button_layout.buttons():
            icon_file = button.property('iconFile')
            if icon_file:
                button.setIcon(get_icon(icon_file))
    
    def _update_login_status(self):
        """Update the login indicator in the status bar.

        Refreshes the saved token if it has expired.
        """
        token = gog_auth.get_valid_token()
        if token:
            self.status_text.setText("Logged in")
            self.logged_in_indicator.setStyleSheet("background-color: green; border-radius: 5")
        else:
            self.status_text.setText("Not logged in")
            self.logged_in_indicator.setStyleSheet("background-color: red; border-radius: 5")

    def logout(self):
        """Delete the saved token and update the login indicator."""
        gog_auth.clear_token()
        self._update_login_status()

    def open_login_window(self):
        """Show the GOG login dialog and update the login indicator on success."""
        login_window = LoginWindow(self)
        if login_window.exec() == QDialog.DialogCode.Accepted:
            self._update_login_status()

    def open_settings(self):
        """Show the settings dialog, then reload the library list."""
        settings_dialog = SettingsDialog(self)
        settings_dialog.exec()
        self.on_games_loaded(library_db.get_product_listing())
        settings_dialog.deleteLater()

    def open_about_page(self):
        """Show the about page."""
        version = importlib.metadata.version("gogstash")
        about_page = QMessageBox(self)
        about_page.setWindowTitle("About GogStash")
        about_page.setIconPixmap(get_logo().pixmap(64, 64))
        about_page.setText(f"""
        <h3>GogStash</h3>
        <p>Version {version}</p>
        <p>A desktop GUI for downloading and backing up your GOG.com game library.</p>
        <p>
        <a href="https://github.com/preppie22/gogstash">Project page</a> &middot;
        <a href="https://github.com/preppie22/gogstash/issues">Report a bug</a>
        </p>
        <p>Copyright &copy; 2026 Piyush Puranik<br>
        Released under the <a href="https://github.com/preppie22/gogstash/blob/main/LICENSE">MIT License</a>.</p>
        <p><small>GogStash is not affiliated with or endorsed by GOG.com or CD PROJEKT.
        Built with Qt via PySide6, licensed under the LGPL (see About Qt).</small></p>
        """)
        about_page.setTextFormat(Qt.TextFormat.RichText)
        about_page.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        about_qt_button = QPushButton("About Qt")
        about_page.addButton(about_qt_button, QMessageBox.ButtonRole.ActionRole)
        about_qt_button.clicked.disconnect()
        about_qt_button.clicked.connect(lambda: QMessageBox.aboutQt(about_page))
        about_page.addButton(QMessageBox.StandardButton.Ok)
        about_page.exec()

    def fetch_games(self):
        """Refresh the library from GOG in a background thread."""
        self.fetch_thread = library_db.LibraryFetchThread(force=True)
        self.fetch_thread.auth_failure.connect(self.on_auth_failure)
        self.fetch_thread.succeeded.connect(self.on_games_loaded)
        self.fetch_thread.failed.connect(self.fetch_failed_handler)
        self.fetch_thread.progress.connect(self.update_fetch_progress)
        self.fetch_games_button.setDisabled(True)
        self.status_text.setText("Fetching games list...")
        self.fetch_thread.start()

    def on_auth_failure(self):
        """Show a login error and re-enable the refresh button."""
        self.error_message.setWindowTitle("Login Error")
        self.error_message.showMessage("You are not logged in to GOG!")
        self._update_login_status()
        self.status_progress.setVisible(False)
        self.fetch_games_button.setDisabled(False)

    def onclick_queue_download(self):
        """Add the selected games to the download queue.

        Shows an error if the queue is not accepting games while downloads
        are pausing or stopping.
        """
        selection_data = self.games_list.selectedItems()
        row_data = {}
        for item in selection_data:
            if item.column() == Column.TITLE:
                row_data['product_id'] = item.data(UserRole.PRODUCT_ID_ROLE)
                row_data['title'] = item.text()
            elif item.column() == Column.SIZE:
                row_data['size'] = item.text()
            elif item.column() == Column.FETCHED:
                idx = self.download_window.add_to_queue(row_data.copy())
                if idx == -1:
                    self.error_message.setWindowTitle("Error Queuing")
                    self.error_message.showMessage("Please wait for pending operations to complete before queuing downloads")
                    break
                row_data.clear()


    def doubleclick_game_list(self, row, _):
        """Add the double-clicked game to the download queue.

        Args:
            row (int): Row index of the clicked cell.
            _ (int): Column index of the clicked cell, unused.
        """
        row_data = {}
        row_data['product_id'] = self.games_list.item(row, Column.TITLE).data(UserRole.PRODUCT_ID_ROLE)
        row_data['title'] = self.games_list.item(row, Column.TITLE).text()
        row_data['size'] = self.games_list.item(row, Column.SIZE).text()
        idx = self.download_window.add_to_queue(row_data.copy())
        if idx == -1:
            self.error_message.setWindowTitle("Error Queuing")
            self.error_message.showMessage("Please wait for pending operations to complete before queuing downloads")

    def update_fetch_progress(self, progress: int):
        """Show metadata fetch progress in the status bar.

        Args:
            progress (int): Percent of products fetched.
        """
        if not self.status_progress.isVisible():
            self.status_progress.setVisible(True)
        self.status_text.setText(f"Fetching metadata ")
        self.status_progress.setValue(int(progress))
        return

    def fetch_failed_handler(self, error_message: str):
        """Show a library fetch error and re-enable the refresh button.

        Args:
            error_message (str): The error to show.
        """
        self.error_message.setWindowTitle("Library Error")
        self.error_message.showMessage(error_message)
        self._update_login_status()
        self.status_progress.setVisible(False)
        self.fetch_games_button.setDisabled(False)

    def on_games_loaded(self, result):
        """Fill the library list, keeping the column sort the user picked.

        The list starts out sorted by title, A to Z. The Fetched column
        shows whether every file the current settings select for the game
        is already downloaded, see ``_check_fetched``.

        Args:
            result (list[dict]): Products from
                ``library_db.get_product_listing``.
        """
        self._update_login_status()
        self.status_progress.setVisible(False)
        self.fetch_games_button.setDisabled(False)
        self.games_list.setRowCount(0)
        self.games_list.setSortingEnabled(False)
        fetched_games = self._check_fetched(result)
        for game in result:
            fetched = fetched_games[game['product_id']]
            row_idx = self.games_list.rowCount()
            title_item = QTableWidgetItem(game['title'])
            title_item.setData(UserRole.PRODUCT_ID_ROLE, game['product_id'])
            self.games_list.insertRow(row_idx)
            self.games_list.setItem(row_idx, Column.TITLE, title_item)
            size_item = GameListItem(humanize.naturalsize(game['download_size']))
            size_item.setData(Qt.ItemDataRole.UserRole, game['download_size'])
            self.games_list.setItem(row_idx, Column.SIZE, size_item)
            fetched_item = GameListItem("")
            fetched_item.setData(Qt.ItemDataRole.UserRole, True if fetched else False)
            fetched_item.setToolTip("Fetched" if fetched else "Not Fetched")
            self.games_list.setItem(row_idx, Column.FETCHED, fetched_item)
        self.games_list.setSortingEnabled(True)
        self.games_list.selectRow(0)
        self.games_list.setFocus()

    def _on_game_succeeded(self, product_id: int):
        """Refresh a game's Fetched cell after its download succeeds.

        The game's files are checked again instead of assuming "Yes", so a
        file that never made it into the manifest still shows "No". Does
        nothing if the game is not in the library list.

        Args:
            product_id (int): GOG product ID of the game.
        """
        for row_idx in range(self.games_list.rowCount()):
            if self.games_list.item(row_idx, Column.TITLE).data(UserRole.PRODUCT_ID_ROLE) == product_id:
                if self._check_fetched(library_db.get_product_listing((product_id,))).get(product_id, False):
                    self.games_list.item(row_idx, Column.FETCHED).setData(Qt.ItemDataRole.UserRole, True)
                    self.games_list.item(row_idx, Column.FETCHED).setToolTip("Fetched")
                else:
                    self.games_list.item(row_idx, Column.FETCHED).setData(Qt.ItemDataRole.UserRole, False)
                    self.games_list.item(row_idx, Column.FETCHED).setToolTip("Not Fetched")
                break

    def _check_fetched(self, product_listing: list[dict]) -> dict:
        """Check which games have every selected file downloaded.

        A game is fetched when each file the current settings select for
        it passes ``check_exist_by_downlink``: recorded in the manifest,
        still on disk at its recorded size, and with the same listed size
        GOG has now. A changed listed size means GOG updated the file.
        A game with no manifest, or no files selected, is not fetched.
        Changing the download settings can change the result.

        Args:
            product_listing (list[dict]): Products with ``product_id`` and
                ``slug``, such as from ``library_db.get_product_listing``.

        Returns:
            dict[int, bool]: Whether each product in ``product_listing``
            is fetched, keyed by product ID. Empty if the listing is empty.
        """
        if len(product_listing) == 0:
            return {}
        games = product_listing
        product_ids = [g['product_id'] for g in product_listing]
        downloadables = library_db.get_downloadables(tuple(product_ids), filtered=True)
        game_files = {}
        for d in downloadables:
            game_files.setdefault(d['product_id'], []).append(d)
        fetched = {k: False for k in product_ids}
        download_path = Path(read_setting('download_path'))
        for game in games:
            game_dir = download_path / game['slug']
            manifest = read_manifest(game_dir)
            if 'error' in manifest or not manifest.values():
                continue
            game_data = game_files.get(game['product_id'], [])
            if not game_data:
                continue
            for d in game_data:
                if not check_exist_by_downlink(game_dir, d['downlink'], d['file_size'], manifest):
                    break
            else:
                fetched[game['product_id']] = True
        return fetched

def main():
    """Start the application and show the main window."""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
