from PySide6.QtWidgets import QApplication, QWidget, QMainWindow, QLabel, QPushButton, QVBoxLayout, QDialog, QLineEdit, QFormLayout
import sys

class LoginWindow(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GOG Login")
        self.resize(400,300)
        self.username_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.loginButton = QPushButton("Login")

        self.windowLayout = QFormLayout()
        self.windowLayout.addRow(self.username_edit)
        self.windowLayout.addRow(self.password_edit)
        self.windowLayout.addRow(self.loginButton)
        self.setLayout(self.windowLayout)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("gogrepo GUI")
        self.resize(800, 600)
        self.label = QLabel("Nothing here yet...")
        self.testButton = QPushButton("Click me")
        self.testButton.clicked.connect(self.on_button_clicked)
        self.boxLayout = QVBoxLayout()
        self.boxLayout.addWidget(self.label)
        self.boxLayout.addWidget(self.testButton)
        self.container = QWidget()
        self.container.setLayout(self.boxLayout)
        self.setCentralWidget(self.container)

    def on_button_clicked(self):
        self.label.setText("Clicked!")
        

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LoginWindow()
    window.show()
    # sys.exit(0)
    sys.exit(app.exec())