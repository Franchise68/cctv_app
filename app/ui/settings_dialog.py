from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QComboBox, QFileDialog, QHBoxLayout, QMessageBox
from pathlib import Path
import json


class SettingsDialog(QDialog):
    def __init__(self, cfg, db, parent=None, alerts=None):
        super().__init__(parent)
        self.cfg = cfg
        self.db = db
        self.alerts = alerts
        self.setWindowTitle("Settings")
        self.resize(520, 280)

        layout = QVBoxLayout(self)

        self.path_edit = QLineEdit(str(self.cfg.recordings_dir))
        btn_browse = QPushButton("Browse")
        row1 = QHBoxLayout()
        row1.addWidget(self.path_edit)
        row1.addWidget(btn_browse)

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["dark", "light"])
        self.theme_combo.setCurrentText(self.cfg.theme)

        self.codec_combo = QComboBox()
        self.codec_combo.addItems(["mp4", "avi"]) 

        # Global recording policy
        self.policy_combo = QComboBox()
        self.policy_combo.addItems(["manual", "always", "motion", "person"])  # default policy
        try:
            cur = getattr(self.db, 'get_global_policy', lambda: 'manual')()
            self.policy_combo.setCurrentText(cur)
        except Exception:
            pass

        layout.addWidget(QLabel("Recording Location"))
        layout.addLayout(row1)
        layout.addWidget(QLabel("Theme"))
        layout.addWidget(self.theme_combo)
        layout.addWidget(QLabel("Video Format"))
        layout.addWidget(self.codec_combo)
        layout.addWidget(QLabel("Default Record When"))
        layout.addWidget(self.policy_combo)

        # Alerts configuration (from config.json)
        layout.addWidget(QLabel("Alerts: Active Hours (24h HH:MM)"))
        row_hours = QHBoxLayout()
        self.alert_start = QLineEdit()
        self.alert_start.setPlaceholderText("00:00")
        self.alert_end = QLineEdit()
        self.alert_end.setPlaceholderText("05:00")
        row_hours.addWidget(QLabel("Start"))
        row_hours.addWidget(self.alert_start)
        row_hours.addWidget(QLabel("End"))
        row_hours.addWidget(self.alert_end)
        layout.addLayout(row_hours)

        layout.addWidget(QLabel("Alerts: Admin Contacts"))
        self.admin_email = QLineEdit()
        self.admin_email.setPlaceholderText("admin@example.com")
        self.admin_phone = QLineEdit()
        self.admin_phone.setPlaceholderText("+2547XXXXXXXX")
        layout.addWidget(QLabel("Admin Email"))
        layout.addWidget(self.admin_email)
        layout.addWidget(QLabel("Admin Phone (E.164)"))
        layout.addWidget(self.admin_phone)

        # Test email button
        row_tests = QHBoxLayout()
        self.btn_test_email = QPushButton("Test Email")
        row_tests.addWidget(self.btn_test_email)
        layout.addLayout(row_tests)

        btn_save = QPushButton("Save")
        layout.addWidget(btn_save)

        btn_browse.clicked.connect(self.browse)
        btn_save.clicked.connect(self.save)
        self.btn_test_email.clicked.connect(self.test_email)

        # Load config.json values
        self._cfg_path = Path.cwd() / "config.json"
        self._load_alert_config()

    def browse(self):
        d = QFileDialog.getExistingDirectory(self, "Select Recording Folder", str(self.cfg.recordings_dir))
        if d:
            self.path_edit.setText(d)

    def save(self):
        path = self.path_edit.text().strip()
        theme = self.theme_combo.currentText()
        codec = self.codec_combo.currentText()
        self.db.update_preferences(path, theme, codec)
        try:
            if hasattr(self.db, 'set_global_policy'):
                self.db.set_global_policy(self.policy_combo.currentText())
        except Exception:
            pass
        # Save alerts to config.json
        try:
            data = {}
            if self._cfg_path.exists():
                data = json.loads(self._cfg_path.read_text(encoding="utf-8"))
            data.setdefault("alert_active_hours", {})
            data["alert_active_hours"]["start"] = self.alert_start.text().strip() or "00:00"
            data["alert_active_hours"]["end"] = self.alert_end.text().strip() or "05:00"
            data["admin_email"] = self.admin_email.text().strip()
            data["admin_phone"] = self.admin_phone.text().strip()
            # preserve restricted_zones
            if "restricted_zones" not in data:
                data["restricted_zones"] = []
            self._cfg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            QMessageBox.warning(self, "Save Error", f"Failed to save alert settings: {e}")
        self.accept()

    def _load_alert_config(self):
        try:
            if self._cfg_path.exists():
                data = json.loads(self._cfg_path.read_text(encoding="utf-8"))
                ah = data.get("alert_active_hours", {})
                self.alert_start.setText(str(ah.get("start", "00:00")))
                self.alert_end.setText(str(ah.get("end", "05:00")))
                self.admin_email.setText(str(data.get("admin_email", "")))
                self.admin_phone.setText(str(data.get("admin_phone", "")))
        except Exception:
            pass

    def test_email(self):
        if not self.alerts or not getattr(self.alerts, 'worker', None):
            QMessageBox.information(self, "Alerts", "Alert system is not running.")
            return
        try:
            subj = "CCTV Test Email"
            body = "This is a test alert from CCTV Manager."
            ok, msg = self.alerts.worker._send_email(subj, body, None)  # type: ignore
            QMessageBox.information(self, "Test Email", f"Result: {msg}")
        except Exception as e:
            QMessageBox.warning(self, "Test Email", f"Failed: {e}")

        # SMS test removed
