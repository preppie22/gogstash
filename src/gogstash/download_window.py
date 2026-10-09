"""Download queue dock widget.

Attributes:
    LIGHT_FILL_COLOR (QColor): Progress fill color in light mode.
    DARK_FILL_COLOR (QColor): Progress fill color in dark mode.
"""

from enum import Enum, IntEnum
import humanize

from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QTableWidget,
    QTableWidgetItem,
    QAbstractItemView,
    QHeaderView,
    QVBoxLayout,
    QPushButton,
    QDialogButtonBox,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QProgressBar,
    QLabel,
    QWidget,
    QStyle,
    QMessageBox
)
from PySide6.QtCore import ( 
    Qt,
    Signal,
    QModelIndex,
    QRect,
    QTimer,
)
from PySide6.QtGui import (
    QPainter,
    QColor,
    QShortcut,
    QKeySequence
)
from gogstash.icon_utils import get_icon, status_indicator
from gogstash.download_queue import DownloadScheduler
from gogstash.settings import read_setting


LIGHT_FILL_COLOR = QColor("#4CAF50")
DARK_FILL_COLOR = QColor("#1B5E20")

class UserRole(IntEnum):
    """Custom item data roles used by the queue table.

    Attributes:
        STATUS_ROLE: Status dot color, stored on the status column.
        PROGRESS_ROLE: Download percentage, stored on the title column.
        PRODUCT_ID_ROLE: GOG product ID, stored on the title column.
        TOTAL_SIZE: Total bytes to download, stored on the progress column.
        FETCHED_SIZE: Bytes downloaded so far, stored on the progress
            column.
    """
    STATUS_ROLE = Qt.ItemDataRole.UserRole + 0
    PROGRESS_ROLE = Qt.ItemDataRole.UserRole + 1
    PRODUCT_ID_ROLE = Qt.ItemDataRole.UserRole + 2
    TOTAL_SIZE = Qt.ItemDataRole.UserRole + 3
    FETCHED_SIZE = Qt.ItemDataRole.UserRole + 4

class Column(IntEnum):
    """Column indices of the queue table."""
    STATUS = 0
    TITLE = 1
    PROGRESS = 2

class DownloadState(Enum):
    """State of the download queue.

    Attributes:
        IDLE: No downloads are running.
        RUNNING: Downloads are in progress.
        PAUSED: Downloads are paused and can be resumed.
    """
    IDLE = 0
    RUNNING = 1
    PAUSED = 2

class TitleDelegate(QStyledItemDelegate):
    """Draws the title cell with a progress fill behind the text."""
    def __init__(self):
        """Create the delegate."""
        super().__init__()

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        """Paint the progress fill and the title text.

        Args:
            painter (QPainter): The painter to draw with.
            option (QStyleOptionViewItem): Style options for the cell.
            index (QModelIndex): The cell being painted.
        """
        progress = index.sibling(index.row(), Column.TITLE).data(UserRole.PROGRESS_ROLE) or 0
        fill_width = int(option.rect.width() * progress / 100)
        scheme = QApplication.instance().styleHints().colorScheme()
        fill_color = LIGHT_FILL_COLOR if scheme == Qt.ColorScheme.Light else DARK_FILL_COLOR
        painter.fillRect(
            QRect(option.rect.x(), option.rect.y() + 4 , fill_width, option.rect.height() - 8),
            fill_color
        )
        current_style = option.widget.style()
        margin_h = current_style.pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, option, option.widget) + 1
        painter.drawText(
            option.rect.adjusted(margin_h, 0, -margin_h, 0),
            Qt.AlignmentFlag.AlignVCenter,
            index.data(Qt.ItemDataRole.DisplayRole)
        )

class StatusDelegate(QStyledItemDelegate):
    """Draws the status indicator centered in the status cell.

    The color is read from ``UserRole.STATUS_ROLE`` and the indicator is
    drawn on every paint, so it follows a change of color scheme without
    being reset.
    """
    def paint(self, painter, option, index):
        """Paint the cell background, then the status indicator.

        Args:
            painter (QPainter): The painter to draw with.
            option (QStyleOptionViewItem): Style options for the cell.
            index (QModelIndex): The cell being painted.
        """
        super().paint(painter, option, index)
        icon = status_indicator(index.data(UserRole.STATUS_ROLE))
        icon.paint(painter, option.rect, Qt.AlignmentFlag.AlignCenter)

class DownloadWindow(QDockWidget):
    """Dock widget showing the download queue.

    Games added from the library list are handed to a
    ``DownloadScheduler``. Scheduler signals update each row's status
    dot, progress fill and size text, as well as the overall progress
    bar.

    Scheduler signals name a game by its product ID. Each game's row items
    are kept in a map keyed by product ID, so a signal finds its row
    wherever that row sits in the table. Every place that removes rows
    from the table removes them from the map too.

    Attributes:
        current_state (DownloadState): State of the queue.
        scheduler (DownloadScheduler): Scheduler running the downloads.
        clear_queue (bool): Clear the table once a pending stop completes.
        game_succeeded (Signal('qlonglong')): Emitted with the product ID of
            a game that finished downloading.
        busy_changed (Signal(bool)): Emitted whenever ``current_state`` is
            set. True while downloads are running or paused, False once
            the queue is idle.
    """

    game_succeeded = Signal('qlonglong')
    busy_changed = Signal(bool)

    def __init__(self, parent=None):
        """Build the queue table, controls and scheduler.

        Args:
            parent (QWidget): Optional parent widget.
        """
        super().__init__(parent)

        self.__current_state = DownloadState.IDLE
        self.__priority_counter = 0
        self.scheduler = None
        self.clear_queue = False
        self._disk_space_error = False
        self.__queue_map = {}

        self._reset_scheduler()

        self.setWindowTitle("Download Queue")
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        # self.setMinimumHeight(400)

        self.main_widget = QWidget()
        self.window_layout = QVBoxLayout()
        self.main_widget.setLayout(self.window_layout)

        self.game_queue_table = QTableWidget()
        self.game_queue_table.setColumnCount(len(Column))
        self.game_queue_table.setHorizontalHeaderLabels(['', 'Title', 'Progress'])
        self.game_queue_table.setAlternatingRowColors(True)
        self.game_queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.game_queue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.game_queue_table.verticalHeader().setVisible(False)
        self.game_queue_table.horizontalHeader().setMinimumSectionSize(16)
        self.game_queue_table.setColumnWidth(Column.STATUS, 24)
        self.game_queue_table.horizontalHeader().setSectionResizeMode(Column.STATUS, QHeaderView.ResizeMode.Fixed)
        self.game_queue_table.horizontalHeader().setSectionResizeMode(Column.TITLE, QHeaderView.ResizeMode.Stretch)  
        self.game_queue_table.horizontalHeader().setSectionResizeMode(Column.PROGRESS, QHeaderView.ResizeMode.ResizeToContents)  
        self.game_queue_table.setItemDelegateForColumn(Column.TITLE, TitleDelegate())
        self.game_queue_table.setItemDelegateForColumn(Column.STATUS, StatusDelegate(self.game_queue_table))
        self.window_layout.addWidget(self.game_queue_table)

        # Clear Queue Button
        self.clear_queue_button = QPushButton("Clear Queue")
        self.clear_queue_button.clicked.connect(self.clear_all)
        self.clear_queue_button.setIcon(get_icon('trash.svg'))
        self.clear_queue_button.setProperty('iconFile', 'trash.svg')

        # Start Downloads Button
        self.start_button = QPushButton("Start Downloads")
        self.start_button.clicked.connect(self._onclick_start_button)
        self.start_button.setIcon(get_icon('start_download.svg'))
        self.start_button.setProperty('iconFile', 'start_download.svg')

        # Cancel Downloads Button
        self.stop_button = QPushButton("Cancel Downloads")
        self.stop_button.clicked.connect(self.stop_downloads)
        self.stop_button.setIcon(get_icon('stop.svg'))
        self.stop_button.setProperty('iconFile', 'stop.svg')

        # Remove Selected Button
        self.remove_button = QPushButton("Remove Selection")
        self.remove_button.clicked.connect(self._onclick_remove_button)
        self.remove_button.setIcon(get_icon('dequeue.svg'))
        self.remove_button.setProperty('iconFile', 'dequeue.svg')
        self.remove_button.setToolTip("Remove selected items from queue (Del)")
        self.remove_shortcut = QShortcut(self.game_queue_table)
        self.remove_shortcut.setKey(QKeySequence(QKeySequence.StandardKey.Delete))
        self.remove_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self.remove_shortcut.activated.connect(self._onclick_remove_button)

        self.downloads_status = QLabel()
        self._reset_status()
        self.window_layout.addWidget(self.downloads_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.window_layout.addWidget(self.progress_bar)

        self.dialog_buttons = QDialogButtonBox()
        self.dialog_buttons.addButton(self.start_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.dialog_buttons.addButton(self.stop_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.dialog_buttons.addButton(self.clear_queue_button, QDialogButtonBox.ButtonRole.ResetRole)
        self.dialog_buttons.addButton(self.remove_button, QDialogButtonBox.ButtonRole.ResetRole)
        self.window_layout.addWidget(self.dialog_buttons)

        self.setWidget(self.main_widget)
        QApplication.instance().styleHints().colorSchemeChanged.connect(self._color_scheme_refresh)
        self._color_scheme_refresh()
        self._update_progress_bar()

    @property
    def current_state(self):
        """DownloadState: State of the queue.

        Setting it emits ``busy_changed``, True for anything but
        ``DownloadState.IDLE``.
        """
        return self.__current_state

    @current_state.setter
    def current_state(self, value: DownloadState):
        self.__current_state = value
        self.busy_changed.emit(value != DownloadState.IDLE)

    def _color_scheme_refresh(self) -> None:
        """Reload button icons for the current color scheme.

        Status dots need no reload, ``StatusDelegate`` draws them in the
        current scheme on every paint.
        """
        for button in self.dialog_buttons.buttons():
            if not button.icon(): continue
            button.setIcon(get_icon(button.property('iconFile')))

    def _reset_scheduler(self):
        """Replace the scheduler with a new one and connect its signals."""
        self.scheduler = DownloadScheduler()
        self.scheduler.game_succeeded.connect(self._on_game_succeeded)
        self.scheduler.game_failed.connect(self._on_game_failed)
        self.scheduler.progress_updated.connect(self._on_progress)
        self.scheduler.finished.connect(self._on_finished)
        self.scheduler.game_stopped.connect(self._on_game_stopped)
        self.scheduler.stopped.connect(self._on_stopped)
        self.scheduler.paused.connect(self._on_paused)
        self.scheduler.game_paused.connect(self._on_game_paused)
        self.scheduler.game_started.connect(self._on_game_started)
        self.scheduler.low_disk_space.connect(self._on_low_disk_space, Qt.ConnectionType.QueuedConnection)
        self.scheduler.disk_full.connect(self._on_disk_full, Qt.ConnectionType.QueuedConnection)
        self.scheduler.connection_lost.connect(self._on_connection_error, Qt.ConnectionType.QueuedConnection)

    def add_to_queue(self, row_data: dict) -> int:
        """Add a game to the queue.

        If the game is already queued, its row is selected instead. The
        row is filled in before the scheduler gets the game, and while
        downloads are running the scheduler is then asked to start it if
        there is a free slot.

        Args:
            row_data (dict): Game with ``product_id`` and ``title``.

        Returns:
            int: The game's row index, or -1 if the queue is not accepting
            games while downloads are pausing or stopping.
        """
        if not self.start_button.isEnabled():
            return -1
        if row_data['product_id'] in self.__queue_map:
            row_idx = self.__queue_map[row_data['product_id']][Column.TITLE].row()
            self.game_queue_table.selectRow(row_idx)
            return row_idx

        row_idx = self.game_queue_table.rowCount()
        self.game_queue_table.insertRow(row_idx)
        column_data = []
        column_data.append(QTableWidgetItem(''))
        column_data[Column.STATUS].setToolTip('Queued')
        column_data.append(QTableWidgetItem(row_data['title']))
        column_data[Column.TITLE].setData(UserRole.PRODUCT_ID_ROLE, row_data['product_id'])
        column_data.append(QTableWidgetItem(""))
        self.__queue_map[row_data['product_id']] = column_data
        for i in range(len(column_data)):
            self.game_queue_table.setItem(row_idx, i, column_data[i])
        self.set_progress(row_data['product_id'], 0)
        self.set_row_status(row_data['product_id'], 'base')
        self.game_queue_table.selectRow(row_idx)
        estimated_size = self.scheduler.enqueue({
            'priority': self.__priority_counter,
            'product_id': row_data['product_id']
        })
        self.__priority_counter += 1
        self._on_progress(row_data['product_id'], 0, estimated_size)
        if self.current_state == DownloadState.RUNNING:
            self.scheduler.schedule()
        self._update_progress_bar()
        return row_idx

    def set_row_status(self, pid: int, color: str):
        """Set a row's status dot.

        Only the color is stored, ``StatusDelegate`` draws the dot from it.

        Args:
            pid (int): Product ID of the game.
            color (str): Status color, see ``icon_utils.status_indicator``.
        """
        self.__queue_map[pid][Column.STATUS].setData(UserRole.STATUS_ROLE, color)

    def _onclick_start_button(self):
        """Start, pause or resume downloads depending on the current state."""
        if self.current_state == DownloadState.IDLE:
            self.start_downloads()
        elif self.current_state == DownloadState.RUNNING:
            self.pause_downloads()
        elif self.current_state == DownloadState.PAUSED:
            self.start_downloads()

    def _onclick_remove_button(self):
        """Remove the selected games from the queue.

        Does nothing while downloads are running, so they have to be paused
        or cancelled first. Each selected game is removed from the
        scheduler, which deletes the partial files of a paused game. A
        game that finished or failed earlier in a paused run is no longer
        in the scheduler, so only its row is removed. If the table ends up
        empty, the window returns to the idle state.
        """
        if self.current_state == DownloadState.RUNNING:
            return
        removed_pids = []
        for pid, row_item in self.__queue_map.items():
            if row_item[Column.TITLE].isSelected():
                removed = self.scheduler.dequeue(pid)
                if (
                    removed or 
                    row_item[Column.STATUS].data(UserRole.STATUS_ROLE) == 'green' or
                    row_item[Column.STATUS].data(UserRole.STATUS_ROLE) == 'red'
                ):
                    self.game_queue_table.removeRow(row_item[Column.TITLE].row())
                    removed_pids.append(pid)
        self._update_progress_bar()
        for pid in removed_pids:
            self.__queue_map.pop(pid)
        if len(self.__queue_map) == 0:
            self._reset_all()
            self._reset_status()

    def start_downloads(self):
        """Start or resume downloads.

        When starting from idle, failed rows are reset and the user is asked
        whether to remove completed rows. Does nothing if the queue is empty
        or already running.

        The window switches to the running state before the scheduler is
        asked to start. If there is nothing left to download, the scheduler
        finishes during that call, and the window ends up idle instead of
        stuck on "Downloading...".
        """
        completed_downloads = []
        if self.game_queue_table.rowCount() == 0 or self.current_state == DownloadState.RUNNING:
            return
        if self.current_state == DownloadState.IDLE:
            for pid, row_items in self.__queue_map.items():
                if row_items[Column.STATUS].data(UserRole.STATUS_ROLE) == 'green':
                    completed_downloads.append(pid)
                elif row_items[Column.STATUS].data(UserRole.STATUS_ROLE) == 'red':
                    self._on_game_stopped(pid)
            if completed_downloads:
                confirmation = QMessageBox(self)
                confirmation.setWindowTitle("Start Downloads")
                confirmation.setText("Remove completed downloads from the queue?")
                confirmation.setInformativeText("This will remove completed downloads from queue before starting.")
                confirmation.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                confirmation.setDefaultButton(QMessageBox.StandardButton.Yes)
                confirmation.setIcon(QMessageBox.Icon.Information)
                ans = confirmation.exec()
                if ans == QMessageBox.StandardButton.Yes:
                    for pid in completed_downloads:
                        row_items = self.__queue_map.pop(pid)
                        self.game_queue_table.removeRow(row_items[Column.TITLE].row())
                    self._reset_all()
                    if self.game_queue_table.rowCount() == 0:
                        return
                else:
                    for pid in completed_downloads:
                        self._on_game_stopped(pid)
                    self._update_progress_bar()
        concurrency = read_setting('download_concurrency')
        self.scheduler.set_concurrency(concurrency)
        self.downloads_status.setText("Downloading...")
        self.remove_button.setDisabled(True)
        self.remove_button.setToolTip("Pause or Cancel Downloads before removing")
        was_paused = self.current_state == DownloadState.PAUSED
        self.current_state = DownloadState.RUNNING
        self.start_button.setText('Pause Downloads')
        self.start_button.setIcon(get_icon('pause.svg'))
        self.start_button.setProperty('iconFile', 'pause.svg')
        if was_paused:
            self._disk_space_error = False
            self.scheduler.resume_all()
        else:
            self.scheduler.schedule()

    def pause_downloads(self):
        """Ask the scheduler to pause all downloads.

        The buttons stay disabled until the scheduler reports that it has
        paused.
        """
        if self.current_state == DownloadState.PAUSED:
            return
        self.start_button.setDisabled(True)
        self.clear_queue_button.setDisabled(True)
        self.downloads_status.setText("Pausing. Please wait...")
        self.scheduler.pause_all()

    def stop_downloads(self):
        """Ask the scheduler to cancel all downloads. Does nothing while idle."""
        if self.current_state == DownloadState.IDLE:
            return
        self.downloads_status.setText("Stopping. Please wait...")
        self.start_button.setDisabled(True)
        self.scheduler.stop_all()

    def _update_progress_bar(self):
        """Recalculate the overall progress bar from all rows."""
        total_size = 0
        fetched_size = 0
        for idx in range(self.game_queue_table.rowCount()):
            current_total_size = self.game_queue_table.item(idx, Column.PROGRESS).data(UserRole.TOTAL_SIZE)
            current_fetched_size = self.game_queue_table.item(idx, Column.PROGRESS).data(UserRole.FETCHED_SIZE)
            total_size = total_size + current_total_size
            fetched_size = fetched_size + current_fetched_size
        if total_size == 0:
            self.progress_bar.setValue(0)
        else:
            self.progress_bar.setValue(fetched_size * 100 / total_size)

    def _on_progress(self, pid, fetched, total):
        """Update a row's progress.

        Args:
            pid (int): Product ID of the game.
            fetched (float): Bytes downloaded so far.
            total (float): Total bytes for the game.
        """
        if total == 0:
            self.set_progress(pid, 0)
        else:
            self.set_progress(pid, fetched*100/total)
        row_items = self.__queue_map[pid]
        row_items[Column.PROGRESS].setText(f"{humanize.naturalsize(fetched)} / {humanize.naturalsize(total)}")
        row_items[Column.PROGRESS].setData(UserRole.FETCHED_SIZE, fetched)
        row_items[Column.PROGRESS].setData(UserRole.TOTAL_SIZE, total)
        self._update_progress_bar()
        return

    def _on_game_started(self, pid):
        """Mark a row as downloading.

        Args:
            pid (int): Product ID of the game.
        """
        self.set_row_status(pid, 'blue')
        self.__queue_map[pid][Column.STATUS].setToolTip('Downloading')

    def _on_game_succeeded(self, pid):
        """Mark a row as finished.

        Args:
            pid (int): Product ID of the game.
        """
        self.set_progress(pid, 100)
        row_items = self.__queue_map[pid]
        total = row_items[Column.PROGRESS].data(UserRole.TOTAL_SIZE)
        row_items[Column.PROGRESS].setData(UserRole.FETCHED_SIZE, total)
        row_items[Column.PROGRESS].setText(f"{humanize.naturalsize(total)} / {humanize.naturalsize(total)}")
        self.set_row_status(pid, 'green')
        row_items[Column.STATUS].setToolTip('Finished')
        self.game_succeeded.emit(pid)

    def _on_game_failed(self, pid, msg):
        """Mark a row as failed and reset its progress.

        Args:
            pid (int): Product ID of the game.
            msg (str): Error shown in the status tooltip.
        """
        self.set_progress(pid, 0)
        row_items = self.__queue_map[pid]
        total = row_items[Column.PROGRESS].data(UserRole.TOTAL_SIZE)
        row_items[Column.PROGRESS].setText(f"{humanize.naturalsize(0)} / {humanize.naturalsize(total)}")
        row_items[Column.PROGRESS].setData(UserRole.FETCHED_SIZE, 0)
        self.set_row_status(pid, 'red')
        row_items[Column.STATUS].setToolTip(f'Failed: {msg}')

    def _on_game_stopped(self, pid):
        """Reset a row to the queued state.

        Args:
            pid (int): Product ID of the game.
        """
        self.set_progress(pid, 0)
        row_items = self.__queue_map[pid]
        total = row_items[Column.PROGRESS].data(UserRole.TOTAL_SIZE)
        row_items[Column.PROGRESS].setText(f"{humanize.naturalsize(0)} / {humanize.naturalsize(total)}")
        row_items[Column.PROGRESS].setData(UserRole.FETCHED_SIZE, 0)
        self.set_row_status(pid, 'base')
        row_items[Column.STATUS].setToolTip('Queued')

    def _on_game_paused(self, pid):
        """Mark a row as paused.

        Args:
            pid (int): Product ID of the game.
        """
        self.set_row_status(pid, 'yellow')
        self.__queue_map[pid][Column.STATUS].setToolTip('Paused')

    def _reset_all(self):
        """Return to the idle state with a new scheduler.

        Re-enables the buttons and queues every row still in the table on
        the new scheduler, with its current row as its priority. Games
        added later get priorities that continue after the last row.
        """
        self.start_button.setDisabled(False)
        self.clear_queue_button.setDisabled(False)
        self.remove_button.setDisabled(False)
        self.remove_button.setToolTip("Remove selected items from queue (Del)")
        self.current_state = DownloadState.IDLE
        self.start_button.setText("Start Downloads")
        self.start_button.setIcon(get_icon('start_download.svg'))
        self.start_button.setProperty('iconFile', 'start_download.svg')
        self._reset_scheduler()
        for pid, row_items in self.__queue_map.items():
            estimated_size = self.scheduler.enqueue({
                'priority': row_items[Column.TITLE].row(),
                'product_id': pid
            })
            if row_items[Column.STATUS].data(UserRole.STATUS_ROLE) != 'green':
                self._on_progress(pid, 0, estimated_size)
        self._update_progress_bar()
        self._disk_space_error = False
        self.__priority_counter = self.game_queue_table.rowCount()

    def clear_all(self):
        """Remove all games from the queue.

        If downloads are running or paused, asks for confirmation and stops
        them first. The table is cleared once the scheduler has stopped.
        """
        self.clear_queue_button.setDisabled(True)
        if self.current_state == DownloadState.RUNNING or self.current_state == DownloadState.PAUSED:
            confirmation = QMessageBox(self)
            confirmation.setWindowTitle("Clear Queue")
            confirmation.setText("Are you sure you want to clear the queue?")
            confirmation.setInformativeText("This action will stop all downloads and clear the download queue.")
            confirmation.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            confirmation.setDefaultButton(QMessageBox.StandardButton.No)
            confirmation.setIcon(QMessageBox.Icon.Warning)
            ans = confirmation.exec()
            if ans == QMessageBox.StandardButton.No:
                self.clear_queue_button.setDisabled(False)
                return
            self.clear_queue = True
            self.stop_downloads()
        else:
            self.game_queue_table.setRowCount(0)
            self.__queue_map.clear()
            self._reset_all()

    def _on_stopped(self):
        """Clear the table if requested and return to the idle state."""
        self.downloads_status.setText("Downloads stopped")
        QTimer.singleShot(5000, self._reset_status)
        if self.clear_queue:
            self.clear_queue = False
            self.game_queue_table.setRowCount(0)
            self.__queue_map.clear()
        self._reset_all()

    def _on_paused(self):
        """Switch to the paused state once all active downloads have paused."""
        self.downloads_status.setText("Downloads paused")
        self.remove_button.setDisabled(False)
        self.remove_button.setToolTip("Remove selected items from queue (Del)")
        self.current_state = DownloadState.PAUSED
        self.start_button.setText('Resume Downloads')
        self.start_button.setIcon(get_icon('resume.svg'))
        self.start_button.setProperty('iconFile', 'resume.svg')
        self.start_button.setDisabled(False)
        self.clear_queue_button.setDisabled(False)


    def _on_finished(self):
        """Show a summary of failed downloads and return to the idle state."""
        failed_count = 0
        for row_idx in range(self.game_queue_table.rowCount()):
            if self.game_queue_table.item(row_idx, Column.STATUS).data(UserRole.STATUS_ROLE) == 'red':
                failed_count += 1
        if failed_count == 1:
            self.downloads_status.setText(f"Finished with {failed_count} failure")
        elif failed_count > 1:
            self.downloads_status.setText(f"Finished with {failed_count} failures")
        else:
            self.downloads_status.setText("Downloads complete")
        QTimer.singleShot(5000, self._reset_status)
        self._reset_all()

    def _on_low_disk_space(self, required, free):
        """Ask whether to download anyway when the queue does not fit on the disk.

        Connected as a queued connection, so it runs after the current
        start or schedule call has finished. Only the first warning after
        a start or a resume shows a dialog. Download anyway turns off the
        free space check for the rest of the run and starts the waiting
        downloads. Pause pauses all downloads and keeps their partial
        files, so they can be resumed once there is more space.

        Args:
            required (float): Bytes still to be downloaded.
            free (float): Free space in the download folder, in bytes.
        """
        if self._disk_space_error:
            return
        self._disk_space_error = True
        disk_space_error = QMessageBox(self)
        disk_space_error.setWindowTitle("Low Disk Space")
        disk_space_error.setText("The queue doesn't fit on disk.")
        disk_space_error.setInformativeText(f"The download folder has {humanize.naturalsize(free)} free but the "
                                            f"queued downloads require {humanize.naturalsize(required)}. "
                                            "Ignore this error and download anyway, or pause while you free "
                                            "up some space?")
        disk_space_error.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        disk_space_error.button(QMessageBox.StandardButton.Yes).setText("&Download anyway")
        disk_space_error.button(QMessageBox.StandardButton.No).setText("&Pause")
        disk_space_error.setDefaultButton(QMessageBox.StandardButton.No)
        disk_space_error.setIcon(QMessageBox.Icon.Warning)
        ans = disk_space_error.exec()
        if ans == QMessageBox.StandardButton.No:
            self.pause_downloads()
        else:
            self.scheduler.free_space_check = False
            self.scheduler.schedule()

    def _on_disk_full(self):
        """Tell the user that downloads paused because the disk filled up.

        Connected as a queued connection, so it runs after the scheduler
        has finished handling the full disk. The window switches to the
        pausing state if other downloads are still pausing. The free space
        check is turned back on, even if the user chose to download anyway
        earlier in the run, so resuming checks the space first.
        """
        self.pause_downloads()
        self.scheduler.free_space_check = True
        if self.current_state != DownloadState.PAUSED:
            self.downloads_status.setText("Download folder is full. Pausing...")
        confirmation = QMessageBox(self)
        confirmation.setWindowTitle("Download Folder Full")
        confirmation.setText("The download folder ran out of space.")
        confirmation.setInformativeText("Downloads have been paused and downloaded "
                                        "content has not been removed. Clear some disk space "
                                        "before resuming.")
        confirmation.setStandardButtons(QMessageBox.StandardButton.Ok)
        confirmation.setIcon(QMessageBox.Icon.Warning)
        confirmation.exec()

    def _on_connection_error(self):
        """Tell the user that downloads paused because the connection dropped.

        Connected as a queued connection, so it runs after the scheduler
        has finished handling the dropped connection. The window switches
        to the pausing state if other downloads are still pausing.
        """
        self.pause_downloads()
        if self.current_state != DownloadState.PAUSED:
            self.downloads_status.setText("Connection lost. Pausing...")
        QMessageBox(
            QMessageBox.Icon.Warning,
            "Network Connection Lost",
            "Connection to GOG lost.",
            QMessageBox.StandardButton.Ok,
            self,
            informativeText="Downloads have been paused and downloaded "
                "content has not been removed. Check your internet connection "
                "and ensure you can log in to GOG.com from your web browser "
                "before resuming."
        ).exec()

    def _reset_status(self):
        """Show the ready message if the queue is idle."""
        if self.current_state == DownloadState.IDLE:
            self.downloads_status.setText("Ready!")

    def set_progress(self, pid, percent = 0):
        """Store a row's progress for the title cell delegate.

        Args:
            pid (int): Product ID of the game.
            percent (float): Progress from 0 to 100.
        """
        item = self.__queue_map[pid][Column.TITLE]
        item.setData(UserRole.PROGRESS_ROLE, percent)

