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
    QModelIndex,
    QRect,
    QTimer,
)
from PySide6.QtGui import (
    QPainter,
    QColor,
)
from gogstash.icon_utils import get_icon, status_indicator
from gogstash.download_queue import DownloadScheduler, estimate_download_size
from gogstash.settings import read_setting


LIGHT_FILL_COLOR = QColor("#4CAF50")
DARK_FILL_COLOR = QColor("#1B5E20")

class UserRole(IntEnum):
    STATUS_ROLE = Qt.ItemDataRole.UserRole + 0
    PROGRESS_ROLE = Qt.ItemDataRole.UserRole + 1
    PRODUCT_ID_ROLE = Qt.ItemDataRole.UserRole + 2
    TOTAL_SIZE = Qt.ItemDataRole.UserRole + 3
    FETCHED_SIZE = Qt.ItemDataRole.UserRole + 4

class Column(IntEnum):
    STATUS = 0
    TITLE = 1
    PROGRESS = 2

class DownloadState(Enum):
    IDLE = 0
    RUNNING = 1
    PAUSED = 2

class RowItemDelegate(QStyledItemDelegate):
    def __init__(self):
        super().__init__()

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
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

class DownloadWindow(QDockWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.current_state = DownloadState.IDLE
        self.scheduler = None
        self.clear_queue = False

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
        self.game_queue_table.setColumnWidth(Column.STATUS, 20)
        self.game_queue_table.horizontalHeader().setSectionResizeMode(Column.STATUS, QHeaderView.ResizeMode.Fixed)
        self.game_queue_table.horizontalHeader().setSectionResizeMode(Column.TITLE, QHeaderView.ResizeMode.Stretch)  
        self.game_queue_table.horizontalHeader().setSectionResizeMode(Column.PROGRESS, QHeaderView.ResizeMode.ResizeToContents)  
        self.game_queue_table.setItemDelegateForColumn(Column.TITLE, RowItemDelegate())
        self.window_layout.addWidget(self.game_queue_table)

        self.clear_queue_button = QPushButton("Clear Queue")
        self.clear_queue_button.clicked.connect(self.clear_all)
        self.clear_queue_button.setIcon(get_icon('trash.svg'))
        self.clear_queue_button.setProperty('iconFile', 'trash.svg')
        self.start_button = QPushButton("Start Downloads")
        self.start_button.clicked.connect(self._onclick_start_button)
        self.start_button.setIcon(get_icon('start_download.svg'))
        self.start_button.setProperty('iconFile', 'start_download.svg')
        self.stop_button = QPushButton("Cancel Downloads")
        self.stop_button.clicked.connect(self.stop_downloads)
        self.stop_button.setIcon(get_icon('stop.svg'))
        self.stop_button.setProperty('iconFile', 'stop.svg')

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
        self.window_layout.addWidget(self.dialog_buttons)

        self.setWidget(self.main_widget)
        QApplication.instance().styleHints().colorSchemeChanged.connect(self._color_scheme_refresh)
        self._color_scheme_refresh()

    def _color_scheme_refresh(self) -> None:
        for button in self.dialog_buttons.buttons():
            if not button.icon(): continue
            button.setIcon(get_icon(button.property('iconFile')))
        for row_idx in range(self.game_queue_table.rowCount()):
            self.set_row_status(row_idx,
                                self.game_queue_table.item(row_idx, Column.STATUS).data(UserRole.STATUS_ROLE))

    def _reset_scheduler(self):
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

    def add_to_queue(self, row_data: dict) -> int:
        if not self.start_button.isEnabled():
            return -1
        for row_idx in range(self.game_queue_table.rowCount()):
            if self.game_queue_table.item(row_idx, Column.TITLE).data(UserRole.PRODUCT_ID_ROLE) == row_data['product_id']:
                self.game_queue_table.selectRow(row_idx)
                return row_idx
        row_idx = self.game_queue_table.rowCount()
        self.game_queue_table.insertRow(row_idx)
        estimated_size = estimate_download_size(row_data['product_id'])
        column_data = []
        column_data.append(QTableWidgetItem(''))
        column_data[Column.STATUS].setToolTip('Queued')
        column_data.append(QTableWidgetItem(row_data['title']))
        column_data[Column.TITLE].setData(UserRole.PRODUCT_ID_ROLE, row_data['product_id'])
        column_data.append(QTableWidgetItem(f"0 / {humanize.naturalsize(estimated_size)}"))
        column_data[Column.PROGRESS].setData(UserRole.TOTAL_SIZE, estimated_size)
        column_data[Column.PROGRESS].setData(UserRole.FETCHED_SIZE, 0)
        for i in range(len(column_data)):
            self.game_queue_table.setItem(row_idx, i, column_data[i])
        self.set_progress(row_idx, 0)
        self.set_row_status(row_idx, 'base')
        self.game_queue_table.selectRow(row_idx)
        self.scheduler.enqueue({
            'idx': row_idx,
            'product_id': row_data['product_id']
        })
        self._update_progress_bar()
        return row_idx

    def set_row_status(self, row: int, color: str):
        self.game_queue_table.item(row, Column.STATUS).setData(UserRole.STATUS_ROLE, color)
        self.game_queue_table.item(row, Column.STATUS).setIcon(status_indicator(color))

    def _onclick_start_button(self):
        if self.current_state == DownloadState.IDLE:
            self.start_downloads()
        elif self.current_state == DownloadState.RUNNING:
            self.pause_downloads()
        elif self.current_state == DownloadState.PAUSED:
            self.start_downloads()

    def start_downloads(self):
        completed_downloads = []
        if self.game_queue_table.rowCount() == 0 or self.current_state == DownloadState.RUNNING:
            return
        if self.current_state == DownloadState.IDLE:
            for row_idx in range(self.game_queue_table.rowCount()):
                if self.game_queue_table.item(row_idx, Column.STATUS).data(UserRole.STATUS_ROLE) == 'green':
                    completed_downloads.append(row_idx)
                elif self.game_queue_table.item(row_idx, Column.STATUS).data(UserRole.STATUS_ROLE) == 'red':
                    self._on_game_stopped(row_idx)
            if completed_downloads:
                confirmation = QMessageBox(self)
                confirmation.setText("Remove completed downloads from the queue?")
                confirmation.setInformativeText("This will remove completed downloads from queue before starting.")
                confirmation.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                confirmation.setDefaultButton(QMessageBox.StandardButton.Yes)
                ans = confirmation.exec()
                if ans == QMessageBox.StandardButton.Yes:
                    completed_downloads.sort(reverse=True)
                    for row_idx in completed_downloads:
                        self.game_queue_table.removeRow(row_idx)
                    self._reset_all()
                    if self.game_queue_table.rowCount() == 0:
                        return
                else:
                    for row_idx in completed_downloads:
                        self._on_game_stopped(row_idx)
                    self._update_progress_bar()
        concurrency = read_setting('download_concurrency')
        self.scheduler.set_concurrency(concurrency)
        if self.current_state == DownloadState.PAUSED:
            self.scheduler.resume_all()
        else:
            self.scheduler.schedule()
        self.downloads_status.setText("Downloading...")
        self.current_state = DownloadState.RUNNING
        self.start_button.setText('Pause Downloads')
        self.start_button.setIcon(get_icon('pause.svg'))
        self.start_button.setProperty('iconFile', 'pause.svg')

    def pause_downloads(self):
        if self.current_state == DownloadState.PAUSED:
            return
        self.start_button.setDisabled(True)
        self.clear_queue_button.setDisabled(True)
        self.downloads_status.setText("Pausing. Please wait...")
        self.scheduler.pause_all()

    def stop_downloads(self):
        if self.current_state == DownloadState.IDLE:
            return
        self.downloads_status.setText("Stopping. Please wait...")
        self.scheduler.stop_all()
        self.start_button.setDisabled(True)

    def _update_progress_bar(self):
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

    def _on_progress(self, row_idx, fetched, total):
        self.set_progress(row_idx, fetched*100/total)
        self.game_queue_table.item(row_idx, Column.PROGRESS).setText(f"{humanize.naturalsize(fetched)} / {humanize.naturalsize(total)}")
        self.game_queue_table.item(row_idx, Column.PROGRESS).setData(UserRole.FETCHED_SIZE, fetched)
        self.game_queue_table.item(row_idx, Column.PROGRESS).setData(UserRole.TOTAL_SIZE, total)
        self._update_progress_bar()
        return

    def _on_game_started(self, row_idx):
        self.set_row_status(row_idx, 'blue')
        self.game_queue_table.item(row_idx, Column.STATUS).setToolTip('Downloading')

    def _on_game_succeeded(self, row_idx):
        self.set_progress(row_idx, 100)
        total = self.game_queue_table.item(row_idx, Column.PROGRESS).data(UserRole.TOTAL_SIZE)
        self.game_queue_table.item(row_idx, Column.PROGRESS).setData(UserRole.FETCHED_SIZE, total)
        self.game_queue_table.item(row_idx, Column.PROGRESS).setText(f"{humanize.naturalsize(total)} / {humanize.naturalsize(total)}")
        self.set_row_status(row_idx, 'green')
        self.game_queue_table.item(row_idx, Column.STATUS).setToolTip('Finished')

    def _on_game_failed(self, row_idx, msg):
        self.set_progress(row_idx, 0)
        total = self.game_queue_table.item(row_idx, Column.PROGRESS).data(UserRole.TOTAL_SIZE)
        self.game_queue_table.item(row_idx, Column.PROGRESS).setText(f"0 / {humanize.naturalsize(total)}")
        self.game_queue_table.item(row_idx, Column.PROGRESS).setData(UserRole.FETCHED_SIZE, 0)
        self.set_row_status(row_idx, 'red')
        self.game_queue_table.item(row_idx, Column.STATUS).setToolTip(f'Failed: {msg}')

    def _on_game_stopped(self, row_idx):
        self.set_progress(row_idx, 0)
        total = self.game_queue_table.item(row_idx, Column.PROGRESS).data(UserRole.TOTAL_SIZE)
        self.game_queue_table.item(row_idx, Column.PROGRESS).setText(f"0 / {humanize.naturalsize(total)}")
        self.game_queue_table.item(row_idx, Column.PROGRESS).setData(UserRole.FETCHED_SIZE, 0)
        self.set_row_status(row_idx, 'base')
        self.game_queue_table.item(row_idx, Column.STATUS).setToolTip('Queued')

    def _on_game_paused(self, row_idx):
        self.set_row_status(row_idx, 'yellow')
        self.game_queue_table.item(row_idx, Column.STATUS).setToolTip('Paused')

    def _reset_all(self):
        self.start_button.setDisabled(False)
        self.clear_queue_button.setDisabled(False)
        self.current_state = DownloadState.IDLE
        self.start_button.setText("Start Downloads")
        self.start_button.setIcon(get_icon('start_download.svg'))
        self.start_button.setProperty('iconFile', 'start_download.svg')
        self._reset_scheduler()
        for row_idx in range(self.game_queue_table.rowCount()):
            self.scheduler.enqueue({
                'idx': row_idx,
                'product_id': self.game_queue_table.item(row_idx, Column.TITLE).data(UserRole.PRODUCT_ID_ROLE)
            })
        self._update_progress_bar()

    def clear_all(self):
        self.clear_queue_button.setDisabled(True)
        if self.current_state == DownloadState.RUNNING or self.current_state == DownloadState.PAUSED:
            confirmation = QMessageBox(self)
            confirmation.setText("Are you sure?")
            confirmation.setInformativeText("This action will stop all downloads and clear the download queue.")
            confirmation.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            confirmation.setDefaultButton(QMessageBox.StandardButton.No)
            ans = confirmation.exec()
            if ans == QMessageBox.StandardButton.No:
                self.clear_queue_button.setDisabled(False)
                return
            self.clear_queue = True
            self.stop_downloads()
        else:
            self.game_queue_table.setRowCount(0)
            self._reset_all()

    def _on_stopped(self):
        self.downloads_status.setText("Downloads stopped")
        QTimer.singleShot(5000, self._reset_status)
        if self.clear_queue:
            self.clear_queue = False
            self.game_queue_table.setRowCount(0)
        self._reset_all()

    def _on_paused(self):
        self.downloads_status.setText("Downloads paused")
        self.current_state = DownloadState.PAUSED
        self.start_button.setText('Resume Downloads')
        self.start_button.setIcon(get_icon('resume.svg'))
        self.start_button.setProperty('iconFile', 'resume.svg')
        self.start_button.setDisabled(False)
        self.clear_queue_button.setDisabled(False)

    def _on_finished(self):
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

    def _reset_status(self):
        if self.current_state == DownloadState.IDLE:
            self.downloads_status.setText("Ready!")

    def set_progress(self, row, percent = 0):
        item = self.game_queue_table.item(row, Column.TITLE)
        item.setData(UserRole.PROGRESS_ROLE, percent)

