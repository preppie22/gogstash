import sys

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QTableWidget,
    QTableView,
    QAbstractItemView,
    QHeaderView,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QDialogButtonBox
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

        self.file_queue_table = QTableWidget()
        self.file_queue_table.setColumnCount(2)
        self.file_queue_table.setHorizontalHeaderLabels(['File Name', 'Size'])
        self.file_queue_table.setAlternatingRowColors(True)
        self.file_queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.file_queue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.file_queue_table.verticalHeader().setVisible(False)
        self.file_queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  
        self.file_queue_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)        

        self.clear_queue_button = QPushButton("Clear Queue")
        self.pause_button = QPushButton("Pause Downloads")
        self.stop_button = QPushButton("Stop Downloads")

        self.table_layout = QHBoxLayout()
        self.table_layout.addWidget(self.game_queue_table)
        self.table_layout.addWidget(self.file_queue_table)
        self.window_layout.addLayout(self.table_layout)

        self.dialog_buttons = QDialogButtonBox()
        self.dialog_buttons.addButton(self.pause_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.dialog_buttons.addButton(self.stop_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.dialog_buttons.addButton(self.clear_queue_button, QDialogButtonBox.ButtonRole.ResetRole)
        self.window_layout.addWidget(self.dialog_buttons)

        self.setLayout(self.window_layout)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    dialog = DownloadWindow()
    dialog.exec()

