from PySide6.QtCore import QUrl, QUrlQuery
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QDialog
from gogstash import gog_auth


class LoginWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GOG Login")
        self.resize(600, 700)
        self.web_view = QWebEngineView()

        self.window_layout = QVBoxLayout()
        self.window_layout.addWidget(self.web_view)
        self.setLayout(self.window_layout)

        self.web_view.load(QUrl(gog_auth.build_auth_uri()))
        self.web_view.urlChanged.connect(self.on_url_changed)

    def on_url_changed(self, url):
        if url.host() == "embed.gog.com" and url.path() == "/on_login_success":
            code = QUrlQuery(url).queryItemValue("code")
            token = gog_auth.fetch_token(code)
            gog_auth.save_token(token)
            self.accept()