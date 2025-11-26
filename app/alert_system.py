import os
import json
import threading
import queue
import time
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Any, Dict, Optional, List, Tuple

from PySide6.QtCore import QObject, Signal, QThread
from PySide6.QtWidgets import QWidget
from dotenv import load_dotenv

try:
    from twilio.rest import Client as TwilioClient  # type: ignore
except Exception:
    TwilioClient = None  # type: ignore

try:
    from google.oauth2.credentials import Credentials  # type: ignore
    from googleapiclient.discovery import build  # type: ignore
    from googleapiclient.errors import HttpError  # type: ignore
except Exception:
    Credentials = None  # type: ignore
    build = None  # type: ignore
    HttpError = Exception  # type: ignore

import sqlite3
import base64
import mimetypes


class AlertWorker(QThread):
    status = Signal(str)

    def __init__(self, cfg_path: Path, alerts_dir: Path, db_path: str):
        super().__init__()
        self._q: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._running = False
        self.cfg_path = cfg_path
        self.alerts_dir = alerts_dir
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self._config: Dict[str, Any] = {}
        self._email_ready = False
        self._twilio_ready = False
        # cooldown map: camera_id -> last email timestamp
        self._last_email_ts: Dict[int, float] = {}
        self._email_cooldown_sec: int = 30
        # config reload control
        self._last_cfg_load_ts: float = 0.0
        self._cfg_reload_sec: int = 5

    def stop(self):
        self._running = False
        try:
            self._q.put_nowait({"_stop": True})
        except Exception:
            pass

    def enqueue(self, event: Dict[str, Any]):
        try:
            self._q.put_nowait(event)
        except Exception:
            pass

    def _load_config(self):
        try:
            if self.cfg_path.exists():
                self._config = json.loads(self.cfg_path.read_text(encoding="utf-8"))
            else:
                self._config = {
                    "alert_active_hours": {"start": "00:00", "end": "05:00"},
                    "restricted_zones": [],
                    "admin_email": "",
                    "admin_phone": "",
                }
        except Exception:
            self._config = {
                "alert_active_hours": {"start": "00:00", "end": "05:00"},
                "restricted_zones": [],
                "admin_email": "",
                "admin_phone": "",
            }

    def _time_in_window(self, now: datetime) -> bool:
        try:
            ah = self._config.get("alert_active_hours", {})
            s_txt = ah.get("start", "00:00")
            e_txt = ah.get("end", "05:00")
            s_h, s_m = [int(x) for x in s_txt.split(":", 1)]
            e_h, e_m = [int(x) for x in e_txt.split(":", 1)]
            start_t = dtime(s_h, s_m)
            end_t = dtime(e_h, e_m)
            now_t = now.time()
            if start_t <= end_t:
                return start_t <= now_t <= end_t
            else:
                return now_t >= start_t or now_t <= end_t
        except Exception:
            return True

    def _match_zone(self, cam_id: int) -> Optional[Dict[str, Any]]:
        try:
            zones: List[Dict[str, Any]] = self._config.get("restricted_zones", [])
            for z in zones:
                if int(z.get("camera_id", -1)) == int(cam_id):
                    return z
        except Exception:
            pass
        return None

    def _init_email(self):
        if self._email_ready:
            return
        load_dotenv()
        self._gmail_token = os.getenv("GMAIL_TOKEN_JSON", "token.json")
        self._gmail_creds = os.getenv("GMAIL_CREDENTIALS_JSON", "credentials.json")
        sender_addr = os.getenv("GMAIL_SENDER", self._config.get("admin_email", ""))
        # Use friendly display name
        self._gmail_sender = f"CCTV SYSTEM ALERT <{sender_addr}>" if sender_addr else "CCTV SYSTEM ALERT"
        # SMTP fallback (free Gmail via App Password)
        self._smtp_user = os.getenv("SMTP_USERNAME", self._gmail_sender)
        self._smtp_pass = os.getenv("SMTP_PASSWORD", "")
        self._smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        try:
            self._smtp_port = int(os.getenv("SMTP_PORT", "587"))
        except Exception:
            self._smtp_port = 587
        self._email_ready = True

    def _init_twilio(self):
        if self._twilio_ready:
            return
        load_dotenv()
        self._tw_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
        self._tw_token = os.getenv("TWILIO_AUTH_TOKEN", "")
        self._tw_from = os.getenv("TWILIO_FROM", "")
        self._tw_client = None
        if TwilioClient and self._tw_sid and self._tw_token:
            try:
                self._tw_client = TwilioClient(self._tw_sid, self._tw_token)
            except Exception:
                self._tw_client = None
        self._twilio_ready = True

    def _gmail_service(self):
        try:
            if not Credentials or not build:
                return None
            token_path = Path(self._gmail_token)
            creds_path = Path(self._gmail_creds)
            if token_path.exists():
                creds = Credentials.from_authorized_user_file(str(token_path), ["https://www.googleapis.com/auth/gmail.send"])
            elif creds_path.exists():
                return None
            else:
                return None
            service = build("gmail", "v1", credentials=creds, cache_discovery=False)
            return service
        except Exception:
            return None

    def _build_email(self, to_addr: str, subject: str, message: str, attach_path: Optional[Path]) -> str:
        boundary = "===============%d==" % int(time.time())
        parts: List[bytes] = []
        parts.append(f"From: {self._gmail_sender}\r\n".encode())
        parts.append(f"To: {to_addr}\r\n".encode())
        parts.append(f"Subject: {subject}\r\n".encode())
        parts.append(f"MIME-Version: 1.0\r\n".encode())
        parts.append(f"Content-Type: multipart/mixed; boundary=\"{boundary}\"\r\n\r\n".encode())
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(b"Content-Type: text/plain; charset=utf-8\r\n\r\n")
        parts.append(message.encode("utf-8") + b"\r\n")
        if attach_path and attach_path.exists():
            ctype, _ = mimetypes.guess_type(str(attach_path))
            ctype = ctype or "application/octet-stream"
            parts.append(f"--{boundary}\r\n".encode())
            parts.append(f"Content-Type: {ctype}; name=\"{attach_path.name}\"\r\n".encode())
            parts.append(b"Content-Transfer-Encoding: base64\r\n")
            parts.append(f"Content-Disposition: attachment; filename=\"{attach_path.name}\"\r\n\r\n".encode())
            data = attach_path.read_bytes()
            b64 = base64.b64encode(data)
            for i in range(0, len(b64), 76):
                parts.append(b64[i:i+76] + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        raw = b"".join(parts)
        return base64.urlsafe_b64encode(raw).decode("utf-8")

    def _send_email(self, subject: str, body: str, image_path: Optional[Path]) -> Tuple[bool, str]:
        try:
            self._init_email()
            to_addr = self._config.get("admin_email", "")
            if not to_addr:
                return False, "admin_email not set"
            svc = self._gmail_service()
            if svc is not None:
                raw = self._build_email(to_addr, subject, body, image_path)
                msg = {"raw": raw}
                svc.users().messages().send(userId="me", body=msg).execute()
                return True, "sent (gmail api)"
            # Fallback to SMTP (free Gmail with App Password)
            ok, msg = self._send_email_smtp(to_addr, subject, body, image_path)
            return ok, msg
        except HttpError as he:  # type: ignore
            return False, f"gmail http error: {he}"
        except Exception as e:
            return False, f"gmail error: {e}"

    def _send_email_smtp(self, to_addr: str, subject: str, body: str, image_path: Optional[Path]) -> Tuple[bool, str]:
        try:
            import smtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            from email.mime.base import MIMEBase
            from email import encoders
            if not self._smtp_user or not self._smtp_pass:
                return False, "SMTP not configured (set SMTP_USERNAME and SMTP_PASSWORD)"
            msg = MIMEMultipart()
            # preserve display name
            from_hdr = self._gmail_sender if self._gmail_sender else (self._smtp_user or "")
            msg["From"] = from_hdr
            msg["To"] = to_addr
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain", _charset="utf-8"))
            if image_path and image_path.exists():
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(image_path.read_bytes())
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', f'attachment; filename="{image_path.name}"')
                msg.attach(part)
            with smtplib.SMTP(self._smtp_server, self._smtp_port, timeout=20) as server:
                server.ehlo()
                server.starttls()
                server.login(self._smtp_user, self._smtp_pass)
                server.sendmail(msg["From"], [to_addr], msg.as_string())
            return True, "sent (smtp)"
        except Exception as e:
            return False, f"smtp error: {e}"

    def _call_twilio(self, text: str) -> Tuple[bool, str]:
        try:
            self._init_twilio()
            phone_to = self._config.get("admin_phone", "")
            if not (self._tw_client and phone_to and self._tw_from):
                return False, "twilio not configured"
            twiml = f"""<?xml version='1.0' encoding='UTF-8'?><Response><Say>{text}</Say></Response>"""
            call = self._tw_client.calls.create(to=phone_to, from_=self._tw_from, twiml=twiml)  # type: ignore
            if getattr(call, 'sid', None):
                return True, "call placed"
            return False, "call failed"
        except Exception as e:
            return False, f"twilio error: {e}"


    def _ensure_alerts_table(self):
        if not self.conn:
            return
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              timestamp TEXT NOT NULL,
              camera_id INTEGER,
              zone_name TEXT,
              alert_type TEXT,
              image_path TEXT,
              status TEXT
            )
            """
        )
        self.conn.commit()

    def _save_alert(self, ts: str, cam_id: int, zone_name: str, alert_type: str, image_path: Optional[Path], status: str):
        if not self.conn:
            return
        self.conn.execute(
            "INSERT INTO alerts(timestamp, camera_id, zone_name, alert_type, image_path, status) VALUES(?,?,?,?,?,?)",
            (ts, cam_id, zone_name, alert_type, str(image_path) if image_path else None, status),
        )
        self.conn.commit()

    def _write_frame(self, frame, base_dir: Path) -> Optional[Path]:
        try:
            import cv2
            base_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            p = base_dir / f"alert_{ts}.jpg"
            cv2.imwrite(str(p), frame)
            return p
        except Exception:
            return None

    def run(self):
        self._running = True
        self._load_config()
        try:
            self.conn = sqlite3.connect(self.db_path)
            self._ensure_alerts_table()
        except Exception as e:
            self.status.emit(f"Alert DB error: {e}")
            self.conn = None
        self.status.emit("Alert worker started")
        while self._running:
            try:
                item = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            if item.get("_stop"):
                break
            try:
                cam_id = int(item.get("camera_id"))
                frame = item.get("frame")
                severity = item.get("severity", "normal")
                now = datetime.now()
                # Periodically reload config so UI changes take effect without restart
                try:
                    if (time.time() - self._last_cfg_load_ts) >= self._cfg_reload_sec:
                        self._load_config()
                        self._last_cfg_load_ts = time.time()
                except Exception:
                    pass
                if not self._time_in_window(now):
                    self.status.emit("Alert skipped: outside active hours")
                    continue
                zone = self._match_zone(cam_id)
                if not zone:
                    # Fall back to full field-of-view so alerts can still send
                    zone = {"name": "Full View", "camera_id": cam_id}
                # cooldown (bypass for emergency)
                tnow = time.time()
                last = self._last_email_ts.get(cam_id, 0.0)
                if str(severity).lower() != "emergency" and (tnow - last) < self._email_cooldown_sec:
                    # skip to prevent spamming
                    self.status.emit(f"Alert skipped: cooldown active for camera {cam_id}")
                    continue
                ts_txt = now.strftime("%Y-%m-%d %H:%M:%S")
                img_path = self._write_frame(frame, self.alerts_dir / now.strftime("%Y-%m-%d")) if frame is not None else None
                sev_low = str(severity).lower()
                if sev_low == "emergency":
                    subj = f"EMERGENCY: Person Extremely Close (Cam {cam_id})"
                    body = (
                        f"Timestamp: {ts_txt}\n"
                        f"Camera ID: {cam_id}\n"
                        f"Message: Person extremely close to the camera (potential intrusion).\n"
                        f"Note: An image captured at detection time is attached when available."
                    )
                elif sev_low == "high":
                    subj = f"Person Detected Near Restricted {zone.get('name','Zone')}"
                    body = (
                        f"Timestamp: {ts_txt}\n"
                        f"Camera ID: {cam_id}\n"
                        f"Message: Person detected near a restricted area.\n"
                        f"Note: An image captured at detection time is attached when available."
                    )
                else:
                    subj = f"Motion Detected Near Restricted {zone.get('name','Zone')}"
                    body = (
                        f"Timestamp: {ts_txt}\n"
                        f"Camera ID: {cam_id}\n"
                        f"Message: Motion detected near a restricted area.\n"
                        f"Note: An image captured at detection time is attached when available."
                    )
                ok_e, msg_e = self._send_email(subj, body, img_path)
                self._save_alert(ts_txt, cam_id, zone.get('name', ''), "email", img_path, "ok" if ok_e else msg_e)
                if ok_e:
                    self._last_email_ts[cam_id] = tnow
                if sev_low in ("high", "emergency"):
                    ok_c, msg_c = self._call_twilio("Intrusion detected at the main door")
                    self._save_alert(ts_txt, cam_id, zone.get('name', ''), "call", img_path, "ok" if ok_c else msg_c)
                self.status.emit(f"Alert handled for camera {cam_id}")
            except Exception as e:
                self.status.emit(f"Alert error: {e}")
        self.status.emit("Alert worker stopped")
        try:
            if self.conn:
                self.conn.close()
        except Exception:
            pass


class AlertSystem(QObject):
    status = Signal(str)

    def __init__(self, recordings_dir: Path, db_path: str, config_path: Optional[Path] = None):
        super().__init__()
        self.recordings_dir = Path(recordings_dir)
        self.alerts_dir = self.recordings_dir / "alerts"
        base_cfg = Path(config_path) if config_path else Path.cwd() / "config.json"
        self.worker = AlertWorker(base_cfg, self.alerts_dir, db_path)
        self.worker.status.connect(self.status)

    def start(self):
        if not self.worker.isRunning():
            self.worker.start()

    def stop(self):
        self.worker.stop()
        self.worker.wait(2000)

    def notify_motion(self, camera_id: int, frame: Any = None, severity: str = "normal"):
        evt = {"camera_id": camera_id, "frame": frame, "severity": severity}
        self.worker.enqueue(evt)


class AlertsPanel(QWidget):
    def __init__(self, db_path: str, parent=None):
        from PySide6.QtWidgets import QVBoxLayout, QTableWidget, QTableWidgetItem, QPushButton, QHBoxLayout
        super().__init__(parent)
        self.db_path = db_path
        lay = QVBoxLayout(self)
        self.table = QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(["Time", "Camera", "Zone", "Type", "Image", "Status"])
        row = QHBoxLayout()
        btn = QPushButton("Refresh")
        btn.clicked.connect(self.refresh)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        lay.addWidget(self.table)
        row.addWidget(btn)
        row.addStretch(1)
        row.addWidget(btn_close)
        lay.addLayout(row)
        self.refresh()

    def refresh(self):
        from PySide6.QtWidgets import QTableWidgetItem
        rows = []
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.execute("SELECT timestamp, camera_id, zone_name, alert_type, image_path, status FROM alerts ORDER BY id DESC LIMIT 50")
            rows = list(cur.fetchall())
            conn.close()
        except Exception:
            rows = []
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, v in enumerate(r):
                self.table.setItem(i, j, QTableWidgetItem(str(v) if v is not None else ""))
