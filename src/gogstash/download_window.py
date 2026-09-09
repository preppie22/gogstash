import sys
from random import randint
import platformdirs
from enum import Enum
import humanize

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
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
    QLabel
)
from PySide6.QtCore import ( 
    Qt,
    QModelIndex,
    QRect,
    QTimer,
    Signal
)
from PySide6.QtGui import (
    QPainter,
    QColor,
    QShortcut,
    QKeySequence,
)
from gogstash.icon_utils import get_icon
from gogstash.download_queue import DownloadScheduler, estimate_download_size
from gogstash.settings import read_setting


LIGHT_FILL_COLOR = QColor("#4CAF50")
DARK_FILL_COLOR = QColor("#1B5E20")

class UserRole(Enum):
    PROGRESS_ROLE = Qt.ItemDataRole.UserRole + 1
    PRODUCT_ID_ROLE = Qt.ItemDataRole.UserRole + 2
    TOTAL_SIZE = Qt.ItemDataRole.UserRole + 3
    FETCHED_SIZE = Qt.ItemDataRole.UserRole + 4

class RowItemDelegate(QStyledItemDelegate):
    def __init__(self):
        super().__init__()

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        progress = index.sibling(index.row(), 0).data(UserRole.PROGRESS_ROLE.value) or 0
        fill_width = int(option.rect.width() * progress / 100)
        scheme = QApplication.instance().styleHints().colorScheme()
        fill_color = LIGHT_FILL_COLOR if scheme == Qt.ColorScheme.Light else DARK_FILL_COLOR
        painter.fillRect(
            QRect(option.rect.x(), option.rect.y() + 4 , fill_width, option.rect.height() - 8),
            fill_color
        )
        painter.drawText(
            option.rect,
            Qt.AlignmentFlag.AlignVCenter,
            index.data(Qt.ItemDataRole.DisplayRole)
        )

class DownloadWindow(QDialog):
    queue_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Download Queue")
        self.setMinimumHeight(400)

        self.log_file = platformdirs.user_config_path(appname='gogstash') / 'downloads.log'
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        self.window_layout = QVBoxLayout()

        self.game_queue_table = QTableWidget()
        self.game_queue_table.setColumnCount(2)
        self.game_queue_table.setHorizontalHeaderLabels(['Product', 'Progress'])
        self.game_queue_table.setAlternatingRowColors(True)
        self.game_queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.game_queue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.game_queue_table.verticalHeader().setVisible(False)
        self.game_queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  
        self.game_queue_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  
        self.game_queue_table.setItemDelegateForColumn(0, RowItemDelegate())
        self.window_layout.addWidget(self.game_queue_table)

        self.clear_queue_button = QPushButton("Clear Queue")
        self.clear_queue_button.setIcon(get_icon('trash.svg'))
        self.clear_queue_button.setProperty('iconFile', 'trash.svg')
        self.start_pause_button = QPushButton("Start Downloads")
        self.start_pause_button.clicked.connect(self.start_downloads)
        self.start_pause_button.setIcon(get_icon('start_download.svg'))
        self.start_pause_button.setProperty('iconFile', 'start_download.svg')
        self.stop_button = QPushButton("Stop Downloads")
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
        self.dialog_buttons.addButton(self.start_pause_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.dialog_buttons.addButton(self.stop_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.dialog_buttons.addButton(self.clear_queue_button, QDialogButtonBox.ButtonRole.ResetRole)
        self.window_layout.addWidget(self.dialog_buttons)

        self.setLayout(self.window_layout)
        QApplication.instance().styleHints().colorSchemeChanged.connect(self._color_scheme_refresh)
        self._color_scheme_refresh()

    def _color_scheme_refresh(self) -> None:
        for button in self.dialog_buttons.buttons():
            if not button.icon(): continue
            button.setIcon(get_icon(button.property('iconFile')))


    def add_to_queue(self, row_data: dict) -> int:
        row_idx = self.game_queue_table.rowCount()
        self.game_queue_table.insertRow(row_idx)
        estimated_size = estimate_download_size(row_data['product_id'])
        column_data = []
        column_data.append(QTableWidgetItem(row_data['title']))
        column_data[0].setData(UserRole.PRODUCT_ID_ROLE.value, row_data['product_id'])
        column_data.append(QTableWidgetItem(f"0 / {humanize.naturalsize(estimated_size)}"))
        column_data[1].setData(UserRole.TOTAL_SIZE.value, estimated_size)
        column_data[1].setData(UserRole.FETCHED_SIZE.value, 0)
        for i in range(len(column_data)):
            self.game_queue_table.setItem(row_idx, i, column_data[i])
        self.set_progress(row_idx, 0)
        self.game_queue_table.selectRow(row_idx)
        self.queue_changed.emit(row_idx + 1)
        return row_idx

    def start_downloads(self):
        concurrency = read_setting('download_concurrency')
        product_queue = []
        for idx in range(self.game_queue_table.rowCount()):
            product_queue.append({
                'idx': idx,
                'product_id': self.game_queue_table.item(idx, 0).data(UserRole.PRODUCT_ID_ROLE.value)
            })
        self.scheduler = DownloadScheduler(product_queue, concurrency)
        self.scheduler.game_succeeded.connect(self._on_game_succeeded)
        self.scheduler.game_failed.connect(self._on_game_failed)
        self.scheduler.progress_updated.connect(self._on_progress)
        self.scheduler.finished.connect(self._on_finished)
        self.scheduler.game_stopped.connect(self._on_game_stopped)
        self.scheduler.stopped.connect(self._on_stopped)
        self.start_pause_button.setDisabled(True)
        self.scheduler.schedule()
        self.downloads_status.setText("Downloading...")

    def stop_downloads(self):
        try:
            self.scheduler.stop_all()
        except AttributeError:
            return

    def _on_progress(self, row_idx, fetched, total):
        self.set_progress(row_idx, fetched*100/total)
        self.game_queue_table.item(row_idx, 1).setText(f"{humanize.naturalsize(fetched)} / {humanize.naturalsize(total)}")
        self.game_queue_table.item(row_idx, 1).setData(UserRole.FETCHED_SIZE.value, fetched)
        self.game_queue_table.item(row_idx, 1).setData(UserRole.TOTAL_SIZE.value, total)
        total_size = 0
        fetched_size = 0
        for idx in range(self.game_queue_table.rowCount()):
            current_total_size = self.game_queue_table.item(idx, 1).data(UserRole.TOTAL_SIZE.value)
            current_fetched_size = self.game_queue_table.item(idx, 1).data(UserRole.FETCHED_SIZE.value)
            total_size = total_size + current_total_size
            fetched_size = fetched_size + current_fetched_size
        self.progress_bar.setValue(fetched_size * 100 / total_size)
        return

    def _on_game_succeeded(self, row_idx, fetched_list):
        print(fetched_list)
        self.set_progress(row_idx, 100)
        total = self.game_queue_table.item(row_idx, 1).data(UserRole.TOTAL_SIZE.value)
        self.game_queue_table.item(row_idx, 1).setData(UserRole.FETCHED_SIZE.value, total)
        self.game_queue_table.item(row_idx, 1).setText(f"{humanize.naturalsize(total)} / {humanize.naturalsize(total)}")
        with open(self.log_file, 'a') as fp:
            for item in fetched_list:
                fp.write(f"{item[0]} : {item[1]}\n")

    def _on_game_failed(self, row_idx, msg, fetched_list):
        print(fetched_list)
        self.game_queue_table.item(row_idx,0).setToolTip(msg)
        with open(self.log_file, 'a') as fp:
            for item in fetched_list:
                if len(item) > 2:
                    fp.write(f"{item[0]}; Failed; expected={item[2]}; fetched={item[3]}\n")
                else:
                    fp.write(f"{item[0]} : {item[1]}\n")

    def _on_game_stopped(self, row_idx, fetched_list):
        print(fetched_list)
        self.set_progress(row_idx, 0)
        total = self.game_queue_table.item(row_idx, 1).data(UserRole.TOTAL_SIZE.value)
        self.game_queue_table.item(row_idx, 1).setText(f"0 / {humanize.naturalsize(total)}")
        self.game_queue_table.item(row_idx, 1).setData(UserRole.FETCHED_SIZE.value, 0)
        with open(self.log_file, 'a') as fp:
            for item in fetched_list:
                if len(item) > 2:
                    fp.write(f"{item[0]}; Failed; expected={item[2]}; fetched={item[3]}\n")
                else:
                    fp.write(f"{item[0]} : {item[1]}\n")

    def _on_stopped(self):
        self.scheduler = None
        self.progress_bar.setValue(0)
        self.downloads_status.setText("Downloads stopped")
        QTimer().singleShot(5000, self._reset_status)
        self.start_pause_button.setDisabled(False)

    def _on_finished(self):
        self.start_pause_button.setDisabled(False)
        self.progress_bar.setValue(self.progress_bar.maximum())

    def _reset_status(self):
        self.downloads_status.setText("Ready!")

    def set_progress(self, row, percent = 0):
        item = self.game_queue_table.item(row, 0)
        item.setData(UserRole.PROGRESS_ROLE.value, percent)
     

if __name__ == "__main__":
    app = QApplication(sys.argv)
    dialog = DownloadWindow()
    progress = {}
    for i in range(5):
        dialog.add_to_queue(f"Game {i}")
        progress[i] = 0

    def move_progress():
        for key in progress:
            progress[key] = min(progress[key] + randint(1,5), 100)
            dialog.set_progress(key, progress[key])

    def swap_theme():
        if app.styleHints().colorScheme() == Qt.ColorScheme.Light:
            app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
        else: 
            app.styleHints().setColorScheme(Qt.ColorScheme.Light)

    progress_timer = QTimer()
    progress_timer.timeout.connect(move_progress)

    def toggle_timer():
        if progress_timer.isActive():
            progress_timer.stop()
        else: progress_timer.start(200)

    toggle_shortcut = QShortcut(QKeySequence("F5"), dialog)
    toggle_shortcut.activated.connect(swap_theme)
    timer_toggle_shortcut = QShortcut(QKeySequence("s"), dialog)
    timer_toggle_shortcut.activated.connect(toggle_timer)
        
    dialog.exec()

