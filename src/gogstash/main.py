"""Application entry point and main window."""

import sys
import humanize
from pathlib import Path
import importlib.metadata
from enum import IntEnum
import logging

from PySide6.QtWidgets import (
    QWidget,
    QApplication,
    QMainWindow,
    QDialog,
    QDockWidget,
    QErrorMessage,
    QTreeWidget,
    QTreeWidgetItem,
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QPushButton,
    QProgressBar,
    QDialogButtonBox,
    QMessageBox,
    QStyledItemDelegate,
    QMenu,
    QToolButton
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QKeySequence,
    QDesktopServices,
    QCloseEvent
)
from PySide6.QtCore import (
    Qt,
    QSize,
    QUrl,
    QProcess,
    QProcessEnvironment,
    QTimer
)

from gogstash import gog_auth
from gogstash.login_window import ExitCode
from gogstash.external_login import ExternalLoginDialog
from gogstash import library_db
from gogstash.settings_dialog import SettingsDialog
from gogstash.settings import read_setting, update_setting
from gogstash.manifest import read_manifest, check_exist_by_downlink
from gogstash.download_window import DownloadWindow, UserRole, DownloadState
from gogstash.icon_utils import get_icon, get_logo, status_indicator
from gogstash import paths

class Column(IntEnum):
    """Column indices of the library tree."""
    TITLE = 0
    SIZE = 1
    FETCHED = 2

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

class GameListItem(QTreeWidgetItem):
    """Library row that sorts the Size and Fetched columns by stored values.

    One item holds all three columns of a game. The Title column sorts by
    its text. The Size column shows a readable size such as "900.0 MB",
    which would sort before "1.2 GB" as text, so it stores the byte count.
    The Fetched column has no text at all, so it stores whether the game
    is fetched. Both values are stored under ``Qt.ItemDataRole.UserRole``
    in their own column and compared instead of the text.
    """
    def __lt__(self, other):
        """Compare two rows by the column the tree is sorted on.

        The tree compares whole rows, so the column comes from
        ``treeWidget().sortColumn()``.

        Args:
            other (GameListItem): The row to compare against.

        Returns:
            bool: True if this row sorts before ``other``. Not fetched
            sorts before fetched.
        """
        col_idx = self.treeWidget().sortColumn()
        match col_idx:
            case Column.TITLE:
                return self.text(Column.TITLE) < other.text(Column.TITLE)
            case Column.SIZE:
                return self.data(Column.SIZE, Qt.ItemDataRole.UserRole) < other.data(Column.SIZE, Qt.ItemDataRole.UserRole)
            case Column.FETCHED:
                return self.data(Column.FETCHED, Qt.ItemDataRole.UserRole) < other.data(Column.FETCHED, Qt.ItemDataRole.UserRole)

class MainWindow(QMainWindow):
    """Main application window.

    Holds the toolbar, the library list in the left dock, the download
    queue in the right dock and a status bar showing the login state and
    fetch progress.
    """
    def __init__(self):
        """Build the window and load the cached library."""
        super().__init__()

        # Variables
        self._games_list_map = {}
        self.log = logging.getLogger(__name__)
        self.quit_pending = False
        self.fetch_thread = None

        # Login Helper Process
        self.login_process = QProcess(self)
        self.login_process.finished.connect(self.on_login_finished)
        self.login_process.errorOccurred.connect(self.on_webview_error)

        # Main Window Setup
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

        # Login
        self.login_menu = QMenu(self)
        self.login_internal_action = QAction("Log in through GogStash", self.login_menu)
        self.login_internal_action.triggered.connect(self.open_login_window)
        self.login_menu.addAction(self.login_internal_action)

        self.login_external_action = QAction("Log in with your browser", self.login_menu)
        self.login_external_action.triggered.connect(self.open_external_login)
        self.login_menu.addAction(self.login_external_action)

        self.login_button = QAction("Login", self, icon=get_icon('login.svg'))
        self.login_button.setProperty('iconFile', 'login.svg')
        self.login_button.setMenu(self.login_menu)

        self.main_toolbar.addAction(self.login_button)
        self.main_toolbar.widgetForAction(self.login_button).setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        # Logout
        self.logout_button = QAction("Logout", self, icon=get_icon('logout.svg'))
        self.logout_button.setProperty('iconFile', 'logout.svg')
        self.logout_button.triggered.connect(self.logout)
        self.main_toolbar.addAction(self.logout_button)
        self.main_toolbar.addSeparator()

        # Fetch Games
        self.fetch_games_button = QAction("Refresh Games List", self, icon=get_icon('fetch.svg'))
        self.fetch_games_button.setProperty('iconFile', 'fetch.svg')
        self.fetch_games_button.triggered.connect(self.fetch_games)
        self.main_toolbar.addAction(self.fetch_games_button)

        # Open Downloads Folder
        self.open_downloads_button = QAction("Open Downloads Folder", self, icon=get_icon('download_folder.svg'))
        self.open_downloads_button.setProperty('iconFile', 'download_folder.svg')
        self.open_downloads_button.triggered.connect(self.open_downloads_folder)
        self.main_toolbar.addAction(self.open_downloads_button)

        # Spacer
        self.spacer = QWidget()
        self.spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.main_toolbar.addWidget(self.spacer)

        # Settings
        self.settings_button = QAction("Settings", self, icon=get_icon('settings.svg'))
        self.settings_button.setProperty('iconFile', 'settings.svg')
        self.settings_button.triggered.connect(self.open_settings)
        self.settings_button.setShortcut(QKeySequence("Ctrl+,"))
        self.settings_button.setToolTip(f"Settings ({self.settings_button.shortcut().toString(QKeySequence.SequenceFormat.NativeText)})")
        self.main_toolbar.addAction(self.settings_button)

        self.download_window.busy_changed.connect(self._on_busy_changed)
        self.download_window.busy_changed.connect(self._on_quit_pending)

        # Theme
        self.theme_toggle_group = QActionGroup(self)
        self.theme_toggle_group.addAction(QAction("Dark", self.theme_toggle_group, checkable=True))
        self.theme_toggle_group.addAction(QAction("Light", self.theme_toggle_group, checkable=True))
        self.theme_toggle_group.addAction(QAction("System", self.theme_toggle_group, checkable=True))
        self.theme_toggle_menu = QMenu(self)
        self.theme_toggle_menu.addActions(self.theme_toggle_group.actions())
        self.theme_set_button = QAction("Theme", self, icon=get_icon('theme_mode.svg'))
        self.theme_set_button.setMenu(self.theme_toggle_menu)
        self.theme_set_button.setProperty('iconFile', 'theme_mode.svg')
        self.main_toolbar.addAction(self.theme_set_button)
        self.main_toolbar.widgetForAction(self.theme_set_button).setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.theme_toggle_group.triggered.connect(self._on_theme_changed)

        # Set Theme Buttons
        current_theme = read_setting('theme')
        for theme_setting in self.theme_toggle_group.actions():
            if current_theme == theme_setting.text():
                theme_setting.setChecked(True)
                break

        # About
        self.about_button = QAction("About", self, icon=get_icon('question.svg'))
        self.about_button.setProperty('iconFile', 'question.svg')
        self.about_button.triggered.connect(self.open_about_page)
        self.main_toolbar.addAction(self.about_button)

        # Left Dock
        self.left_dock = QDockWidget()
        self.library_widget = QWidget()
        self.library_layout = QVBoxLayout()
        self.library_widget.setLayout(self.library_layout)
        self.left_dock.setWidget(self.library_widget)
        self.left_dock.setWindowTitle("Library")
        self.left_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)

        # Main Games List
        self.games_list = QTreeWidget()
        self.games_list.setUniformRowHeights(True)
        self.games_list.itemDoubleClicked.connect(self.doubleclick_game_list)
        self.games_list.setExpandsOnDoubleClick(False)
        self.games_list.setColumnCount(len(Column))
        self.games_list.setHeaderLabels(['Title', 'Size', 'Fetched'])
        self.games_list.setAlternatingRowColors(True)
        self.games_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.games_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.games_list.header().setMinimumSectionSize(16)
        self.games_list.setColumnWidth(Column.FETCHED, 60)
        self.games_list.header().setSectionResizeMode(Column.TITLE, QHeaderView.ResizeMode.Stretch)
        self.games_list.header().setSectionResizeMode(Column.SIZE, QHeaderView.ResizeMode.ResizeToContents)
        self.games_list.header().setSectionResizeMode(Column.FETCHED, QHeaderView.ResizeMode.Fixed)
        self.games_list.header().setStretchLastSection(False)
        self.games_list.setItemDelegateForColumn(Column.FETCHED, FetchedDelegate(self.games_list))
        self.games_list.setSortingEnabled(True)
        self.games_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.games_list.sortByColumn(Column.TITLE, Qt.SortOrder.AscendingOrder)

        # Enqueue Selection
        self.queue_download_button = QPushButton("Queue Selection")
        self.queue_download_button.setIcon(get_icon('enqueue.svg'))
        self.queue_download_button.setProperty('iconFile', 'enqueue.svg')
        self.queue_download_button.clicked.connect(self.onclick_queue_download)
        self.button_layout = QDialogButtonBox()
        self.button_layout.addButton(self.queue_download_button, QDialogButtonBox.ButtonRole.ActionRole)

        # Main Window Layout
        self.library_layout.addWidget(self.games_list)
        self.library_layout.addWidget(self.button_layout)

        # Verify Cache
        if not library_db.verify_schema_version():
            QMessageBox.information(
                self,
                "Cache Outdated",
                "Your library cache was built by an older version of GogStash and has been updated. "
                "Click Refresh to reload your library and rebuild the cache.",
                QMessageBox.StandardButton.Ok
            )

        # Add Download Window
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,self.left_dock)
        
        # Init Stuff
        self._update_login_status()
        QApplication.instance().styleHints().colorSchemeChanged.connect(self._color_scheme_refresh)
        SettingsDialog.set_color_theme()
        self._color_scheme_refresh()
        self._on_games_loaded(library_db.get_product_listing())

    def _threads_busy(self) -> bool:
        """Check whether a background thread would stop the app quitting.

        Returns:
            bool: True while the download queue is not idle or a library
            refresh is running.
        """
        return not (self.download_window.current_state == DownloadState.IDLE and
            (self.fetch_thread is None or not self.fetch_thread.isRunning()))

    def closeEvent(self, event: QCloseEvent):
        """Ask before quitting while downloads are running.

        Worker threads must exit before the app does, so a Yes stops the
        downloads, interrupts a library refresh and keeps the window open.
        ``_on_quit_pending`` and ``_on_fetch_finished`` close it again, and
        the close goes through once neither is busy. Closing again while
        they are still stopping does nothing. If everything went idle on its
        own while the question was open, a Yes quits right away.

        A library refresh on its own is interrupted without asking, since
        the cache is only replaced once a refresh completes. Closing while
        idle or paused needs no question, since no worker is running then.

        Args:
            event (QCloseEvent): The close request. Ignoring it keeps the
                window open.
        """
        if self.quit_pending and self._threads_busy():
            event.ignore()
            return
        exit_confirmed = False
        if self.download_window.current_state == DownloadState.RUNNING:
            confirmation = QMessageBox(
                QMessageBox.Icon.Warning,
                "Quit GogStash",
                "Are you sure you want to cancel downloads and quit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                self,
                informativeText="Clicking yes will cancel all downloads and quit the program."
            )
            confirmation.setDefaultButton(QMessageBox.StandardButton.No)
            if confirmation.exec() == QMessageBox.StandardButton.Yes:
                exit_confirmed = True
            else:
                event.ignore()
                return
        elif self.fetch_thread is not None and self.fetch_thread.isRunning():
            exit_confirmed = True

        if exit_confirmed:
            self.quit_pending = True
            self.download_window.stop_downloads()
            if self.fetch_thread is not None and self.fetch_thread.isRunning():
                self.fetch_thread.requestInterruption()
            if not self._threads_busy():
                return super().closeEvent(event)
            event.ignore()
        else:
            super().closeEvent(event)

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
        """Start the login helper in its own process.

        "Log in through GogStash" stays disabled until the helper exits, and
        ``on_login_finished`` handles the result. The frozen build runs
        itself again with ``--login-helper``, with
        ``PYINSTALLER_RESET_ENVIRONMENT`` set so the helper's bootloader
        sets up the bundled libraries again. From source it runs
        ``gogstash.login_window`` as a module.
        """
        self.login_internal_action.setEnabled(False)
        if getattr(sys, "frozen", False):
            env = QProcessEnvironment.systemEnvironment()
            env.insert("PYINSTALLER_RESET_ENVIRONMENT", "1")
            self.login_process.setProcessEnvironment(env)
            self.login_process.start(sys.executable, ["--login-helper"])
        else:
            self.login_process.start(sys.executable, ["-m","gogstash.login_window"])

    def open_external_login(self):
        """Show the browser login dialog and update the login indicator on success."""
        external_login = ExternalLoginDialog(self)
        if external_login.exec() == QDialog.DialogCode.Accepted:
            self._update_login_status()

    def open_settings(self):
        """Show the settings dialog, then reload the library list."""
        settings_dialog = SettingsDialog(self)
        settings_dialog.exec()
        self._on_games_loaded(library_db.get_product_listing())
        settings_dialog.deleteLater()

    def open_downloads_folder(self):
        """Open the download folder in the system file manager.

        The folder is created first if it doesn't exist yet. If it can't
        be created, for example on an unmounted network share, a warning
        shows the path and the error instead. If the system has nothing
        that can open folders, an error says so.
        """
        folder_path = Path(read_setting('download_path'))
        try:
            folder_path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(
                self,
                "Path Error",
                f"Error opening {str(folder_path)}\n\n{str(e)}"
            )
            return
        check = QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder_path)))
        if not check:
            QMessageBox.critical(
                self,
                "No Folder Handler",
                "Your system does not have a way to open folders!"
            )

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
        about_qt_button.clicked.connect(lambda: QMessageBox.aboutQt(self))
        about_page.addButton(QMessageBox.StandardButton.Ok)
        about_page.exec()

    def fetch_games(self):
        """Refresh the library from GOG in a background thread."""
        self.fetch_thread = library_db.LibraryFetchThread(force=True)
        self.fetch_thread.auth_failure.connect(self.on_auth_failure)
        self.fetch_thread.succeeded.connect(self._on_games_loaded)
        self.fetch_thread.failed.connect(self.fetch_failed_handler)
        self.fetch_thread.progress.connect(self.update_fetch_progress)
        self.fetch_thread.finished.connect(self._on_fetch_finished)
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

    def on_login_finished(self, exit_code: int, exit_status: QProcess.ExitStatus):
        """Act on how the login helper ended and re-enable its menu item.

        Logged in refreshes the login indicator, cancelled does nothing, and
        a failed token exchange shows a warning. A crash or a missing web
        view opens the browser login instead.

        Args:
            exit_code (int): The helper's exit code, an ``ExitCode`` value.
            exit_status (QProcess.ExitStatus): Whether the helper exited
                normally or crashed.
        """
        self.login_internal_action.setDisabled(False)
        if exit_status == QProcess.ExitStatus.CrashExit:
            self.open_external_login()
            return
        match exit_code:
            case ExitCode.EXIT_OK:
                self._update_login_status()
            case ExitCode.EXIT_CANCELLED:
                pass
            case ExitCode.EXIT_TOKEN_ERROR:
                QMessageBox.warning(
                    self,
                    "Login Error",
                    "You signed into GOG, but GogStash could not finish "
                    "connecting to your account. Check your internet connection "
                    "and try again."
                )
            case _:
                self.open_external_login()

    def on_webview_error(self, error: QProcess.ProcessError):
        """Open the browser login if the login helper couldn't start.

        Other errors, like a crash, also end with ``finished``, so
        ``on_login_finished`` handles those and the browser login opens
        only once.

        Args:
            error (QProcess.ProcessError): What went wrong with the helper.
        """
        if error == QProcess.ProcessError.FailedToStart:
            self.login_internal_action.setDisabled(False)
            self.open_external_login()

    def onclick_queue_download(self):
        """Add the selected games to the download queue.

        Shows an error if the queue is not accepting games while downloads
        are pausing or stopping.
        """
        selection_data = self.games_list.selectedItems()
        row_data = {}
        for item in selection_data:
            row_data['product_id'] = item.data(Column.TITLE, UserRole.PRODUCT_ID_ROLE)
            row_data['title'] = item.text(Column.TITLE)
            row_data['size'] = item.text(Column.SIZE)
            idx = self.download_window.add_to_queue(row_data.copy())
            if idx == -1:
                self.error_message.setWindowTitle("Error Queuing")
                self.error_message.showMessage("Please wait for pending operations to complete before queuing downloads")
                break

    def doubleclick_game_list(self, item, _):
        """Add the double-clicked game to the download queue.

        Args:
            item (GameListItem): The double-clicked row.
            _ (int): Column index of the clicked cell, unused.
        """
        row_data = {}
        row_data['product_id'] = item.data(Column.TITLE, UserRole.PRODUCT_ID_ROLE)
        row_data['title'] = item.text(Column.TITLE)
        row_data['size'] = item.text(Column.SIZE)
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

    def _on_fetch_finished(self):
        """Close the window if a quit was waiting for the library refresh.

        ``finished`` is emitted just before the thread exits, so ``wait()``
        makes sure it has, otherwise ``_threads_busy`` could still see it
        running and refuse the close.
        """
        if self.quit_pending:
            self.fetch_thread.wait()
            QTimer.singleShot(0, self.close)

    def _on_games_loaded(self, result):
        """Fill the library list, keeping the column sort the user picked.

        Games are top-level rows and each DLC is a child of its base game.
        Games are added first, since ``result`` can list a DLC before its
        game. A DLC whose game is not in ``result`` gets a top-level row of
        its own. The list starts out sorted by title, A to Z, and DLCs are
        sorted within their game. The Fetched column shows whether every
        file the current settings select for the product is already
        downloaded, see ``_check_fetched``.

        Args:
            result (list[dict]): Products from
                ``library_db.get_product_listing``.
        """
        self._update_login_status()
        self.status_progress.setVisible(False)
        self.fetch_games_button.setDisabled(False)
        self.games_list.clear()
        self._games_list_map.clear()
        self.games_list.setSortingEnabled(False)

        fetched_games = self._check_fetched(result)
        for game in result:
            if game['parent_id'] is None:
                row_item = self._make_games_list_item(game, fetched_games)
                self._games_list_map[game['product_id']] = row_item
                self.games_list.addTopLevelItem(row_item)
        for game in result:
            if game['parent_id'] is not None:
                row_item = self._make_games_list_item(game, fetched_games)
                parent_item: GameListItem = self._games_list_map.get(game['parent_id'])
                self._games_list_map[game['product_id']] = row_item
                if parent_item is None:
                    self.games_list.addTopLevelItem(row_item)
                else:
                    parent_item.addChild(row_item)

        self.games_list.setSortingEnabled(True)
        self.games_list.setCurrentItem(self.games_list.topLevelItem(0))
        self.games_list.setFocus()
        self.games_list.expandAll()

    def _make_games_list_item(self, game: dict, fetched_games: dict) -> GameListItem:
        """Build a library row for a game or DLC, not yet added to the list.

        Args:
            game (dict): A product from ``library_db.get_product_listing``.
            fetched_games (dict[int, bool]): Whether each product is
                fetched, keyed by product ID, from ``_check_fetched``.

        Returns:
            GameListItem: The row, with the title, size and Fetched columns
            filled in.
        """
        row_item = GameListItem()
        row_item.setText(Column.TITLE, game['title'])
        row_item.setData(Column.TITLE, UserRole.PRODUCT_ID_ROLE, game['product_id'])

        row_item.setText(Column.SIZE, humanize.naturalsize(game['download_size']))
        row_item.setData(Column.SIZE, Qt.ItemDataRole.UserRole, game['download_size'])

        fetched = fetched_games[game['product_id']]
        row_item.setData(Column.FETCHED, Qt.ItemDataRole.UserRole, True if fetched else False)
        row_item.setToolTip(Column.FETCHED, "Fetched" if fetched else "Not Fetched")
        return row_item

    def _on_game_succeeded(self, product_id: int):
        """Refresh a game's Fetched column after its download succeeds.

        The game's files are checked again instead of assuming "Yes", so a
        file that never made it into the manifest still shows "No". Does
        nothing if the game is not in the library list.

        Args:
            product_id (int): GOG product ID of the game.
        """
        row_item = self._games_list_map.get(product_id)
        if row_item is None: 
            return
        if self._check_fetched(library_db.get_product_listing((product_id,))).get(product_id, False):
            row_item.setData(Column.FETCHED, Qt.ItemDataRole.UserRole, True)
            row_item.setToolTip(Column.FETCHED, "Fetched")
        else:
            row_item.setData(Column.FETCHED, Qt.ItemDataRole.UserRole, False)
            row_item.setToolTip(Column.FETCHED, "Not Fetched")

    def _on_quit_pending(self, is_busy: bool):
        """Close the window once a stop requested by quitting has finished.

        The close is queued instead of called directly, since the signal
        arrives in the middle of ``DownloadWindow._reset_all``, which still
        has to finish setting up the new scheduler.

        Args:
            is_busy (bool): True while the download queue is not idle.
        """
        if not is_busy and self.quit_pending:
            QTimer.singleShot(0, self.close)

    def _on_busy_changed(self, is_busy: bool):
        """Lock Settings while downloads are running or paused.

        Changing the download folder or the file selection mid-run would
        strand paused ``.part`` files and mix old and new settings in the
        queue. Disabling the action also disables its shortcut.

        Args:
            is_busy (bool): True while the download queue is not idle.
        """
        self.settings_button.setDisabled(is_busy)
        self.settings_button.setToolTip("Can't change settings while downloads are running or paused" if is_busy else
                                         f"Settings ({self.settings_button.shortcut().toString(QKeySequence.SequenceFormat.NativeText)})")

    def _on_theme_changed(self, action: QAction):
        """Save and apply the theme picked from the toolbar menu.

        The theme is saved first, since ``SettingsDialog.set_color_theme``
        reads it back from the settings file.

        Args:
            action (QAction): The checked menu entry. Its text is the theme
                name stored in the settings.
        """
        update_setting('theme', action.text())
        SettingsDialog.set_color_theme()

    def _check_fetched(self, product_listing: list[dict]) -> dict:
        """Check which games have every selected file downloaded.

        A game is fetched when each file the current settings select for
        it passes ``check_exist_by_downlink``: recorded in the manifest,
        still on disk at its recorded size, and with the same listed size
        and version GOG has now. A changed listed size or version means
        GOG updated the file.
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
                if not check_exist_by_downlink(game_dir, d['downlink'], d['file_size'], d['version'], manifest):
                    break
            else:
                fetched[game['product_id']] = True
        return fetched

def main():
    """Start the application and show the main window."""
    app = QApplication(sys.argv)
    log_file = paths.config_file_path(paths.ConfigFile.APP_LOG)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(log_file),
        format='[%(asctime)s | %(module)s] - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    app.setStyle('Fusion')
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
