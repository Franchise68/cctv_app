from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout
from PySide6.QtCore import Qt


class LoginDialog(QDialog):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.setWindowTitle("Login")
        self.setModal(True)
        self.resize(360, 160)

        layout = QVBoxLayout(self)

        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("Username")
        self.pass_edit = QLineEdit()
        self.pass_edit.setPlaceholderText("Password")
        self.pass_edit.setEchoMode(QLineEdit.Password)

        form = QVBoxLayout()
        form.addWidget(QLabel("Username"))
        form.addWidget(self.user_edit)
        form.addWidget(QLabel("Password"))
        form.addWidget(self.pass_edit)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        self.btn_login = QPushButton("Login")
        self.btn_cancel = QPushButton("Cancel")
        btn_row.addWidget(self.btn_login)
        btn_row.addWidget(self.btn_cancel)
        layout.addLayout(btn_row)

        self.btn_login.clicked.connect(self.do_login)
        self.btn_cancel.clicked.connect(self.reject)

    def do_login(self):
        u = self.user_edit.text().strip()
        p = self.pass_edit.text().strip()
        if self.db.validate_user(u, p):
            self.accept()
        else:
            self.user_edit.setStyleSheet("border:1px solid #d33;")
            self.pass_edit.setStyleSheet("border:1px solid #d33;")
