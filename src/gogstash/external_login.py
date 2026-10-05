"""Dialog for signing in to GOG with the system's own web browser.

A fallback for when the embedded login window doesn't work: the user logs
in to GOG in their browser and pastes the address of the success page
back into GogStash.
"""

import requests

from PySide6.QtCore import QUrl
from gogstash import gog_auth
from PySide6.QtWidgets import (
    QFormLayout,
    QDialog,
    QVBoxLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QIcon,
    QGuiApplication,
    QDesktopServices
)

class ExternalLoginDialog(QDialog):
    """Two-step dialog that logs in to GOG through the user's browser.

    Step 1 opens the GOG login page in the default browser, with the
    address shown for copying in case the browser doesn't open. Step 2
    takes the address of the page GOG redirects to after login, exchanges
    its authorization code for a token, saves the token and accepts the
    dialog. If anything goes wrong the dialog shows a warning and stays
    open so the user can try again.
    """
    def __init__(self, parent=None):
        """Create the dialog with both login steps.

        Args:
            parent (QWidget): Optional parent widget.
        """
        super().__init__(parent)

        self.setWindowTitle("Browser Login")
        self.resize(500, 500)

        self.window_layout = QFormLayout()
        self.window_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.setLayout(self.window_layout)

        # Step 1
        self.step1 = QGroupBox("Step 1: Log in to GOG from your browser")
        self.step1_layout = QVBoxLayout()
        self.step1.setLayout(self.step1_layout)
        self.step1_url = QLineEdit(readOnly=True)
        self.step1_url.setText(gog_auth.build_auth_uri())
        self.step1_url.setCursorPosition(0)
        self.copy_action = self.step1_url.addAction(QIcon.fromTheme('edit-copy'), QLineEdit.ActionPosition.TrailingPosition)
        self.copy_action.triggered.connect(
            lambda: QGuiApplication.clipboard().setText(self.step1_url.text())
        )
        self.step1_browser_button = QPushButton("Open in Browser")
        self.step1_browser_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(gog_auth.build_auth_uri()))
        )
        self.step1_browser_button.setAutoDefault(False)

        self.step1_layout.addWidget(QLabel("""
        <p>Click <b>Open in Browser</b> to open GOG's login page in your web browser.
        Log in there as you normally would, then go to <b>Step 2</b>.</p>
        """, wordWrap=True))
        self.step1_layout.addWidget(self.step1_browser_button)
        self.step1_layout.addWidget(QLabel("""
        <p>If your browser doesn't open,
        copy the address below and paste it into your browser's address bar.</p>
        """, wordWrap=True))
        self.step1_layout.addWidget(self.step1_url)

        # Step 2
        self.step2 = QGroupBox("Step 2: Paste the address here")
        self.step2_layout = QVBoxLayout()
        self.step2.setLayout(self.step2_layout)
        self.step2_url = QLineEdit()
        self.paste_action = self.step2_url.addAction(QIcon.fromTheme('edit-paste'), QLineEdit.ActionPosition.TrailingPosition)
        self.paste_action.triggered.connect(
            lambda: self.step2_url.setText(QGuiApplication.clipboard().text())
        )
        self.step2_login_button = QPushButton("Log In")
        self.step2_login_button.clicked.connect(self._on_click_login)
        self.step2_login_button.setDefault(True)

        self.step2_layout.addWidget(QLabel("""
        <p>After you log in, your browser will show a <b>blank page</b>.
        That's normal, it means the login worked.</p>
        <p>If you were already logged in to GOG, it may go straight to that page.</p>
        <p>Copy the full address from your browser's address bar and paste it
        below, then click <b>Log In</b>. The address should start with
        <b>https://embed.gog.com/on_login_success</b>.</p>
        """, wordWrap=True))
        self.step2_layout.addWidget(self.step2_url)
        self.step2_layout.addWidget(QLabel("""
        <p>The address only works once. If logging in fails, start again from Step 1.</p>
        """, wordWrap=True))
        self.step2_layout.addWidget(self.step2_login_button)

        self.window_layout.addRow(self.step1)
        self.window_layout.addRow(self.step2)

    def _on_click_login(self):
        """Finish the login with the address pasted in Step 2.

        Shows a warning and keeps the dialog open if the address isn't the
        login success page, if GOG can't be reached, or if GOG rejects the
        code because it expired or was already used.
        """
        code =gog_auth.extract_code(self.step2_url.text().strip())
        if code is None:
            QMessageBox(
                QMessageBox.Icon.Warning,
                "Login Error",
                "That's not the right address.\n"
                "Copy the whole address from the blank page "
                "your web browser shows after logging in.",
                QMessageBox.StandardButton.Ok,
                self
            ).show()
            return
        try:
            token = gog_auth.fetch_token(code)
            gog_auth.save_token(token)
        except requests.RequestException as e:
            QMessageBox(
                QMessageBox.Icon.Warning,
                "Login Error",
                """
                <p>GogStash couldn't reach GOG.com.</p>
                <p>If your browser can open GOG, a firewall, proxy or antivirus may be
                blocking GogStash. Try again in a few minutes.</p>
                """,
                QMessageBox.StandardButton.Ok,
                self,
                detailedText=f"{type(e).__name__}: {str(e)}",
                textFormat=Qt.TextFormat.RichText
            ).show()
            return
        except KeyError as e:
            QMessageBox(
                QMessageBox.Icon.Warning,
                "Login Error",
                """
                <p>This address has expired or was already used.</p>
                <p>Follow <b>Step 1</b> to log in again.</p>
                """,
                QMessageBox.StandardButton.Ok,
                self,
                detailedText=f"{type(e).__name__}: {str(e)}",
                textFormat=Qt.TextFormat.RichText
            ).show()
            return
        self.accept()