from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel
import platform


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About CCTV Manager")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("CCTV Management System"))
        layout.addWidget(QLabel("PySide6-based modern UI"))
        layout.addWidget(QLabel(f"Python: {platform.python_version()}"))
        layout.addWidget(QLabel(f"OS: {platform.platform()}"))
