from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox, QPushButton, QFrame
from PySide6.QtCore import Qt
from urllib.request import urlopen, Request
import cv2
import numpy as np


class EditCameraDialog(QDialog):
    def __init__(self, name: str, url: str, type_: str, parent=None, policy: str = "manual"):
        super().__init__(parent)
        self.setWindowTitle("Edit Camera")
        self.resize(520, 360)
        self._orig = (name, url, type_)

        lay = QVBoxLayout(self)

        # Fields
        self.name_edit = QLineEdit(name)
        self.url_edit = QLineEdit(url)
        self.type_combo = QComboBox()
        self.type_combo.addItems(["rtsp", "http", "http-snapshot", "usb"]) 
        # select current
        idx = self.type_combo.findText((type_ or "rtsp").lower())
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)

        lay.addWidget(QLabel("Name"))
        lay.addWidget(self.name_edit)
        lay.addWidget(QLabel("URL or Index"))
        lay.addWidget(self.url_edit)
        lay.addWidget(QLabel("Type"))
        lay.addWidget(self.type_combo)

        # Record When policy
        lay.addWidget(QLabel("Record When"))
        self.policy_combo = QComboBox()
        self.policy_combo.addItems(["manual", "always", "motion", "person"])  # manual = use default or manual
        try:
            self.policy_combo.setCurrentText(policy)
        except Exception:
            pass
        lay.addWidget(self.policy_combo)

        # Preview area
        self.preview = QLabel("No preview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(180)
        self.preview.setFrameShape(QFrame.StyledPanel)
        lay.addWidget(self.preview)

        # Buttons
        row = QHBoxLayout()
        self.btn_test = QPushButton("Test Connection")
        self.btn_ok = QPushButton("Save")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_test.clicked.connect(self.test_connection)
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        row.addWidget(self.btn_test)
        row.addStretch(1)
        row.addWidget(self.btn_ok)
        row.addWidget(self.btn_cancel)
        lay.addLayout(row)

    def get_values(self):
        return (
            self.name_edit.text().strip(),
            self.url_edit.text().strip(),
            self.type_combo.currentText().strip().lower(),
            self.policy_combo.currentText().strip().lower(),
        )

    def test_connection(self):
        url = self.url_edit.text().strip()
        type_ = self.type_combo.currentText().strip().lower()
        frame = None
        try:
            if type_ == "http-snapshot" or url.lower().endswith("shot.jpg"):
                req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urlopen(req, timeout=5) as resp:
                    data = resp.read()
                arr = np.frombuffer(data, np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            elif type_ == "http" or url.lower().startswith("http"):
                # try reading once as jpeg
                req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urlopen(req, timeout=5) as resp:
                    data = resp.read(512*1024)  # read chunk and attempt to find jpeg
                start = data.find(b"\xff\xd8")
                end = data.find(b"\xff\xd9", start+2)
                if start != -1 and end != -1:
                    arr = np.frombuffer(data[start:end+2], np.uint8)
                    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            else:
                # usb or rtsp via OpenCV
                cap = cv2.VideoCapture(int(url) if type_ == "usb" else url)
                ok, frame = cap.read()
                cap.release()
        except Exception:
            frame = None

        if frame is None:
            self.preview.setText("Failed to get preview")
        else:
            try:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            except Exception:
                rgb = frame
            h, w, ch = rgb.shape
            from PySide6.QtGui import QImage, QPixmap
            qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()
            self.preview.setPixmap(QPixmap.fromImage(qimg).scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
