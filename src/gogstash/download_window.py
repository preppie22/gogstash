import sys
from random import randint

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QTableWidget,
    QTableView,
    QTableWidgetItem,
    QAbstractItemView,
    QHeaderView,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QDialogButtonBox,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)
from PySide6.QtCore import ( 
    Qt,
    QModelIndex,
    QRect,
    QTimer
)
from PySide6.QtGui import (
    QPainter,
    QColor,
    QShortcut,
    QKeySequence
)

PROGRESS_ROLE = Qt.ItemDataRole.UserRole + 1
LIGHT_FILL_COLOR = QColor("#4CAF50")
DARK_FILL_COLOR = QColor("#1B5E20")

class RowItemDelegate(QStyledItemDelegate):
    def __init__(self):
        super().__init__()

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        progress = index.sibling(index.row(), 0).data(PROGRESS_ROLE) or 0
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
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Downloads")

        self.window_layout = QVBoxLayout()

        self.game_queue_table = QTableWidget()
        self.game_queue_table.setColumnCount(2)
        self.game_queue_table.setHorizontalHeaderLabels(['Product', 'Size'])
        self.game_queue_table.setAlternatingRowColors(True)
        self.game_queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.game_queue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.game_queue_table.verticalHeader().setVisible(False)
        self.game_queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  
        self.game_queue_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  
        self.game_queue_table.setItemDelegateForColumn(0, RowItemDelegate())
        self.window_layout.addWidget(self.game_queue_table)

        self.clear_queue_button = QPushButton("Clear Queue")
        self.pause_button = QPushButton("Pause Downloads")
        self.stop_button = QPushButton("Stop Downloads")

        self.dialog_buttons = QDialogButtonBox()
        self.dialog_buttons.addButton(self.pause_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.dialog_buttons.addButton(self.stop_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.dialog_buttons.addButton(self.clear_queue_button, QDialogButtonBox.ButtonRole.ResetRole)
        self.window_layout.addWidget(self.dialog_buttons)

        self.setLayout(self.window_layout)

    def add_to_queue(self, title: str) -> int:
        row_idx = self.game_queue_table.rowCount()
        self.game_queue_table.insertRow(row_idx)
        self.game_queue_table.setItem(row_idx, 0, QTableWidgetItem(title))
        self.game_queue_table.setItem(row_idx, 1, QTableWidgetItem('N/A'))
        self.set_progress(row_idx, 0)
        self.game_queue_table.selectRow(row_idx)
        return row_idx

    def set_progress(self, row, percent = 0):
        item = self.game_queue_table.item(row, 0)
        item.setData(PROGRESS_ROLE, percent)

        

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

