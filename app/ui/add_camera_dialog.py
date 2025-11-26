from PySide6.QtWidgets import QDialog, QVBoxLayout, QLineEdit, QLabel, QComboBox, QPushButton, QHBoxLayout


class AddCameraDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Camera")
        self.resize(420, 200)
        layout = QVBoxLayout(self)

        self.name_edit = QLineEdit()
        self.url_edit = QLineEdit()
        self.type_combo = QComboBox()
        self.type_combo.addItems(["rtsp", "http", "http-snapshot", "usb"]) 

        layout.addWidget(QLabel("Name"))
        layout.addWidget(self.name_edit)
        layout.addWidget(QLabel("URL or Index (e.g., rtsp://..., http://.../video or /shot.jpg, or 0 for USB)"))
        layout.addWidget(self.url_edit)
        layout.addWidget(QLabel("Type"))
        layout.addWidget(self.type_combo)

        row = QHBoxLayout()
        btn_ok = QPushButton("OK")
        btn_cancel = QPushButton("Cancel")
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        row.addWidget(btn_ok)
        row.addWidget(btn_cancel)
        layout.addLayout(row)

    def get_values(self):
        return self.name_edit.text().strip(), self.url_edit.text().strip(), self.type_combo.currentText()
