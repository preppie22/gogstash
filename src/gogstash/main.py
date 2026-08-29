import sys

from PySide6.QtWidgets import QApplication, QWidget, QMainWindow, QLabel, QPushButton, QVBoxLayout, QDialog, QListWidget, QErrorMessage

from gogstash import gog_auth
from gogstash.gog_api import LibraryFetchThread
from gogstash.login_window import LoginWindow

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GogStash")
        self.resize(800, 600)
        self.status_label = QLabel()
        self.error_message = QErrorMessage()

        self.login_button = QPushButton("Login")
        self.login_button.clicked.connect(self.open_login_window)

        self.fetch_games_button = QPushButton("Fetch Games")
        self.fetch_games_button.clicked.connect(self.fetch_games)

        self.games_list = QListWidget()

        self.window_layout = QVBoxLayout()
        self.window_layout.addWidget(self.games_list)
        self.window_layout.addWidget(self.status_label)
        self.window_layout.addWidget(self.fetch_games_button)
        self.window_layout.addWidget(self.login_button)
        self.container = QWidget()
        self.container.setLayout(self.window_layout)
        self.setCentralWidget(self.container)
        
        self._update_login_status()

    def _update_login_status(self):
        token = gog_auth.get_valid_token()
        if token:
            self.status_label.setText("Logged in")
        else:
            self.status_label.setText("Not logged in")

    def open_login_window(self):
        login_window = LoginWindow(self)
        if login_window.exec() == QDialog.DialogCode.Accepted:
            self._update_login_status()

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
        self.games_list.clear()
        for game in result["products"]:
            self.games_list.addItem(game["title"])
            
        

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())