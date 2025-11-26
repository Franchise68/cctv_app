from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QPushButton, QDialog, QToolButton, QStyle, QMessageBox
from PySide6.QtGui import QImage, QPixmap, QIcon, QGuiApplication, QColor, QPainter, QPen, QBrush
from PySide6.QtCore import Qt, Signal, QEasingCurve, QPropertyAnimation, QTimer, QSize
from PySide6.QtWidgets import QGraphicsDropShadowEffect
import numpy as np
import cv2
from pathlib import Path
import time

from ...camera.camera_worker import CameraWorker
from ...camera.http_mjpeg_worker import HttpMJPEGWorker
from ...camera.http_snapshot_worker import HttpSnapshotWorker
from ...camera.motion import SimpleMotionDetector
from ...config import AppConfig


class CameraTile(QWidget):
    deleted = Signal(int)  # camera_id
    reorder_request = Signal(int, int)  # (source_id, target_id)
    selected = Signal(int)  # camera_id

    def __init__(self, camera_id: int, name: str, url: str, cam_type: str, cfg: AppConfig, db):
        super().__init__()
        self.camera_id = camera_id
        self.name = name
        self.url = url
        self.cam_type = (cam_type or "rtsp").lower()
        self.cfg = cfg
        self.db = db
        self.worker = None
        self._last_frame = None
        self._motion = SimpleMotionDetector()
        self._last_motion_ts = 0.0
        self._motion_record = False  # whether current recording was auto-started by motion
        self._enable_motion_autorec = False  # disable by default for stability; can be toggled later
        self._last_paint_ts = 0.0
        # Tile-level recording (for HTTP workers)
        self._tile_recording = False
        self._tile_writer = None
        self._tile_writer_fps = 8.0
        self._tile_writer_size = None
        self._rec_start_ts = 0.0  # for recording timer
        self._last_status_kind = ""  # LIVE/REC/ERR
        self.fullscreen = None
        self._hovered = False
        self._last_frame_ts = 0.0
        self._retry_count = 0
        self._next_retry_ts = 0.0
        self._detect_people = False
        self._hog = None
        self._record_policy = getattr(self.db, 'get_camera_policy', lambda _cid: 'manual')(self.camera_id)
        self._global_policy = getattr(self.db, 'get_global_policy', lambda: 'manual')()
        self._person_count_last = 0
        self._yolo = None
        self._yolo_available = False
        self._yolo_tried = False
        # AI throttling to avoid UI hangs when enabled on many tiles
        self._ai_last_ts = 0.0
        self._ai_min_interval = 0.6  # seconds between AI runs per tile
        self.setProperty("class", "camera-tile")
        self._last_alert_ts = 0.0
        self._broadcast_ui = False
        self._selected = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        self.label = QLabel("No Signal")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setMinimumHeight(220)
        layout.addWidget(self.label)

        self.status_lbl = QLabel("")
        layout.addWidget(self.status_lbl)
        self.status_lbl.setVisible(False)

        # Status chip (overlay on video, top-right)
        self.chip = QLabel("IDLE", self.label)
        self.chip.setAlignment(Qt.AlignCenter)
        self.chip.setStyleSheet("padding:2px 6px; border-radius:10px; background:rgba(0,0,0,0.6); color:#fff; font-weight:bold;")
        self.chip.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        # Bottom overlay bar (inside video) with FPS/Res and Reconnect
        self.overlay_bar = QWidget(self.label)
        self.overlay_bar.setStyleSheet("background:rgba(0,0,0,0.35);")
        self.overlay_bar.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        ob_lay = QHBoxLayout(self.overlay_bar)
        ob_lay.setContentsMargins(8, 2, 8, 2)
        ob_lay.setSpacing(6)
        self.lbl_fps = QLabel("")
        self.lbl_fps.setStyleSheet("color:#ddd;")
        self.lbl_res = QLabel("")
        self.lbl_res.setStyleSheet("color:#ddd;")
        self.btn_reconnect = QToolButton(self.overlay_bar)
        try:
            self.btn_reconnect.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        except Exception:
            self.btn_reconnect.setIcon(self.style().standardIcon(QStyle.SP_BrowserStop))
        self.btn_reconnect.setToolTip("Reconnect")
        self.btn_reconnect.clicked.connect(self._reconnect)
        self.btn_reconnect.setVisible(False)
        # AI toggle (person detection)
        self.btn_ai = QToolButton(self.overlay_bar)
        try:
            self.btn_ai.setIcon(self.style().standardIcon(QStyle.SP_DialogYesButton))
        except Exception:
            pass
        self.btn_ai.setToolTip("Toggle Person Detection")
        self.btn_ai.setText("AI")
        self.btn_ai.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_ai.setObjectName("aiBtn")
        # Highlight when toggled on
        try:
            self.btn_ai.setStyleSheet(
                "QToolButton#aiBtn { padding: 2px 8px; } "
                "QToolButton#aiBtn:checked { background: rgba(0, 170, 0, 80); color: #eaffea; border-radius: 4px; }"
            )
        except Exception:
            pass
        self.btn_ai.setCheckable(True)
        self.btn_ai.toggled.connect(self._toggle_ai)
        ob_lay.addWidget(self.lbl_fps)
        ob_lay.addStretch(1)
        ob_lay.addWidget(self.lbl_res)
        ob_lay.addWidget(self.btn_ai)
        ob_lay.addWidget(self.btn_reconnect)

        # Icon toolbar (hidden until hover)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.btn_start = QToolButton()
        # Triangular play icon for Start
        try:
            self.btn_start.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        except Exception:
            self.btn_start.setIcon(self.style().standardIcon(QStyle.SP_ArrowRight))
        self.btn_start.setToolTip("Start")
        self.btn_stop = QToolButton()
        # Media stop icon for Stop
        try:
            self.btn_stop.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        except Exception:
            self.btn_stop.setIcon(self.style().standardIcon(QStyle.SP_DialogCancelButton))
        self.btn_stop.setToolTip("Stop")
        self.btn_snapshot = QToolButton()
        # Camera icon for snapshot (drawn)
        try:
            self.btn_snapshot.setIcon(self._make_camera_icon())
        except Exception:
            self.btn_snapshot.setIcon(self.style().standardIcon(QStyle.SP_DesktopIcon))
        self.btn_snapshot.setToolTip("Capture Image (Snapshot)")
        self.btn_record = QToolButton()
        # Red dot icon for Record (drawn)
        try:
            self.btn_record.setIcon(self._make_red_dot_icon())
        except Exception:
            self.btn_record.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
        self.btn_record.setToolTip("Start/Stop Recording")
        self.btn_edit = QToolButton()
        # Gear icon for settings/edit
        try:
            self.btn_edit.setIcon(self._make_gear_icon())
        except Exception:
            self.btn_edit.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        self.btn_edit.setToolTip("Settings")
        self.btn_delete = QToolButton()
        self.btn_delete.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        self.btn_delete.setToolTip("Delete")
        # Reorder controls
        self.btn_move_left = QToolButton()
        self.btn_move_left.setIcon(self.style().standardIcon(QStyle.SP_ArrowLeft))
        self.btn_move_left.setToolTip("Move Left")
        self.btn_move_right = QToolButton()
        self.btn_move_right.setIcon(self.style().standardIcon(QStyle.SP_ArrowRight))
        self.btn_move_right.setToolTip("Move Right")

        for b in [self.btn_start, self.btn_stop, self.btn_snapshot, self.btn_record, self.btn_edit, self.btn_delete, self.btn_move_left, self.btn_move_right]:
            row.addWidget(b)
        row.addStretch(1)
        self.controls_row = QWidget()
        self.controls_row.setLayout(row)
        self.controls_row.setVisible(False)
        layout.addWidget(self.controls_row)

        self.btn_start.clicked.connect(self.start)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_snapshot.clicked.connect(self.snapshot)
        self.btn_record.clicked.connect(self.toggle_record)
        self.btn_delete.clicked.connect(self.delete_camera)
        self.btn_edit.clicked.connect(self.edit_camera)
        self.btn_move_left.clicked.connect(lambda: self._request_move(-1))
        self.btn_move_right.clicked.connect(lambda: self._request_move(+1))

    def mousePressEvent(self, e):
        try:
            if e.button() == Qt.LeftButton:
                self.selected.emit(self.camera_id)
        except Exception:
            pass
        return super().mousePressEvent(e)

    def set_selected(self, sel: bool):
        self._selected = bool(sel)
        try:
            if self._selected:
                self.setStyleSheet("border: 2px solid #2aa3ff; border-radius: 6px;")
            else:
                self.setStyleSheet("")
        except Exception:
            pass

    def start(self):
        if self.worker and self.worker.isRunning():
            return
        # Choose worker based on type/URL
        if self.cam_type == "http-snapshot" or self.url.lower().endswith("shot.jpg"):
            self.worker = HttpSnapshotWorker(self.camera_id, self.url)
            self.btn_record.setEnabled(True)
            self.btn_record.setToolTip("Tile recording enabled for HTTP Snapshot source")
            self._tile_writer_fps = 6.0
        elif self.cam_type == "http" or self.url.lower().startswith("http"):
            self.worker = HttpMJPEGWorker(self.camera_id, self.url)
            self.btn_record.setEnabled(True)
            self.btn_record.setToolTip("Tile recording enabled for HTTP MJPEG source")
            self._tile_writer_fps = 10.0
        else:
            self.worker = CameraWorker(self.camera_id, self.url, self.cfg.recordings_dir, self.cam_type)
            self.btn_record.setEnabled(True)
            self.btn_record.setToolTip("")
        self.worker.frame_ready.connect(self.on_frame)
        self.worker.status.connect(self.on_status)
        self.worker.start()

    def stop(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait(1000)
        # stop tile-level writer
        if self._tile_recording:
            self._tile_recording = False
        if self._tile_writer is not None:
            try:
                self._tile_writer.release()
            except Exception:
                pass
            self._tile_writer = None
        self._update_chip(kind="IDLE")
        self.controls_row.setVisible(False)
        if hasattr(self, "btn_reconnect"):
            self.btn_reconnect.setVisible(True)
        self._schedule_health_timer()

    def snapshot(self):
        if self._last_frame is None:
            return
        snap_dir = Path(self.cfg.recordings_dir) / "snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        out_path = snap_dir / f"cam{self.camera_id}_{ts}.jpg"
        cv2.imwrite(str(out_path), self._last_frame)
        self.setToolTip(f"Snapshot saved: {out_path}")

    def toggle_record(self):
        if not self.worker:
            return
        # Only CameraWorker supports recording
        if isinstance(self.worker, CameraWorker):
            if getattr(self.worker, "_recording", False):
                self.worker.stop_recording()
                self._rec_start_ts = 0.0
            else:
                # get preferred codec from preferences
                try:
                    rp, th, vc = self.db.get_preferences()
                except Exception:
                    vc = "mp4"
                self.worker.start_recording(name_prefix=f"cam{self.camera_id}", codec=vc or "mp4")
                self._rec_start_ts = time.time()
            
        else:
            # Tile-level recording for HTTP workers
            if self._tile_recording:
                self._tile_recording = False
                if self._tile_writer is not None:
                    try:
                        self._tile_writer.release()
                    except Exception:
                        pass
                    self._tile_writer = None
                self.status_lbl.setText("Recording stopped")
                self._rec_start_ts = 0.0
            else:
                # Open writer lazily on first frame to know size
                self._tile_recording = True
                self._tile_writer = None
                self._tile_writer_size = None
                self.status_lbl.setText("Recording starting...")
                self._rec_start_ts = time.time()

    def on_status(self, cam_id: int, msg: str):
        self.setToolTip(msg)
        self.status_lbl.setText(msg)
        low = (msg or "").lower()
        if any(k in low for k in ["error", "failed", "can't open", "stopped"]):
            self._update_chip(kind="ERR")
            if hasattr(self, "btn_reconnect"):
                self.btn_reconnect.setVisible(True)
        else:
            if hasattr(self, "btn_reconnect"):
                self.btn_reconnect.setVisible(False)

    def on_frame(self, frame, cam_id: int):
        self._last_frame = frame.copy()
        self._last_frame_ts = time.time()
        # Motion detection
        try:
            motion, _ = self._motion.detect(frame)
        except Exception:
            motion = False
        now = time.time()
        if motion:
            self._last_motion_ts = now
            self.status_lbl.setText("Motion detected")
            # For alerting, require a person detection (lightweight HOG check here, no drawing)
            person_present = False
            emergency_close = False
            try:
                if self._hog is None:
                    self._hog = cv2.HOGDescriptor()
                    self._hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
                target_w = max(1, self.label.width())
                target_h = max(1, self.label.height())
                disp_small = self._last_frame
                if disp_small is not None:
                    # respect AI throttle
                    if (now - self._ai_last_ts) >= self._ai_min_interval:
                        self._ai_last_ts = now
                        scale = 0.5 if max(target_w, target_h) > 640 else 1.0
                        if scale != 1.0:
                            disp_small = cv2.resize(self._last_frame, (int(self._last_frame.shape[1]*scale), int(self._last_frame.shape[0]*scale)), interpolation=cv2.INTER_AREA)
                        rects_tmp, _ = self._hog.detectMultiScale(disp_small, winStride=(8,8), padding=(8,8), scale=1.05)
                        person_present = len(rects_tmp) > 0
                    else:
                        person_present = (self._person_count_last > 0)
                    if person_present:
                        # Compute proximity by largest bounding box area relative to frame
                        fh = float(disp_small.shape[0]); fw = float(disp_small.shape[1])
                        farea = max(1.0, fh * fw)
                        max_area = 0.0
                        max_h_frac = 0.0
                        for (x, y, w0, h0) in rects_tmp:
                            area = float(w0 * h0)
                            if area > max_area:
                                max_area = area
                                max_h_frac = float(h0) / max(1.0, fh)
                        # Mark emergency if person is very close (large on frame)
                        # thresholds: area > 22% of frame OR height > 45% of frame
                        emergency_close = (max_area / farea) > 0.22 or max_h_frac > 0.45
            except Exception:
                person_present = False
                emergency_close = False
            # Notify alert system (throttle to once every 5s per tile)
            try:
                if hasattr(self, 'alerts'):
                    sev = "emergency" if emergency_close else ("high" if person_present else "normal")
                    # bypass local throttle for emergency
                    if sev == "emergency" or (now - self._last_alert_ts) > 5.0:
                        self._last_alert_ts = now
                        self.alerts.notify_motion(self.camera_id, frame=self._last_frame, severity=sev)
            except Exception:
                pass
            # Auto-record start for CameraWorker (optional)
            if self._enable_motion_autorec and isinstance(self.worker, CameraWorker) and not getattr(self.worker, "_recording", False):
                try:
                    rp, th, vc = self.db.get_preferences()
                except Exception:
                    vc = "mp4"
                self.worker.start_recording(name_prefix=f"cam{self.camera_id}_motion", codec=vc or "mp4")
                self._motion_record = True
        else:
            # stop auto recording 10s after last motion
            if self._motion_record and isinstance(self.worker, CameraWorker):
                if now - self._last_motion_ts > 10:
                    self.worker.stop_recording()
                    self._motion_record = False

        # Throttle painting to ~15 FPS
        if time.time() - self._last_paint_ts < (1.0/15.0):
            return
        self._last_paint_ts = time.time()

        # Downscale to label size before converting to QImage to reduce CPU
        target_w = max(1, self.label.width())
        target_h = max(1, self.label.height())
        if frame.shape[1] > 0 and frame.shape[0] > 0 and (frame.shape[1] != target_w or frame.shape[0] != target_h):
            disp = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)
        else:
            disp = frame
        # Apply subtle hover zoom (1.02x) by scaling and center-cropping
        if self._hovered:
            try:
                zoom_w = int(target_w * 1.02)
                zoom_h = int(target_h * 1.02)
                z = cv2.resize(disp, (zoom_w, zoom_h), interpolation=cv2.INTER_CUBIC)
                x0 = (zoom_w - target_w) // 2
                y0 = (zoom_h - target_h) // 2
                disp = z[y0:y0+target_h, x0:x0+target_w]
            except Exception:
                pass
        # Person detection (HOG). Compute count if policy requires OR overlay toggle is on; draw only if overlay is on.
        self._person_count_last = 0
        # Determine effective policy (camera override; if manual, use global)
        eff_policy = self._record_policy if self._record_policy != 'manual' else self._global_policy
        need_person = (eff_policy == 'person') or self._detect_people
        rects = []
        if need_person:
            try:
                # YOLO is only allowed when overlay is toggled ON (to avoid heavy memory when only policy triggers)
                if self._detect_people:
                    if not self._yolo_tried:
                        self._yolo_tried = True
                        try:
                            from ultralytics import YOLO  # type: ignore
                            self._yolo = YOLO("yolov8n.pt")
                            self._yolo_available = True
                        except Exception:
                            self._yolo = None
                            self._yolo_available = False
                    if self._yolo_available and self._yolo is not None and (time.time() - self._ai_last_ts) >= self._ai_min_interval:
                        self._ai_last_ts = time.time()
                        rgb = cv2.cvtColor(disp, cv2.COLOR_BGR2RGB)
                        h0, w0 = rgb.shape[:2]
                        side = 320
                        scale = min(1.0, side / max(1, max(w0, h0)))
                        rgb_s = cv2.resize(rgb, (int(w0 * scale), int(h0 * scale)), interpolation=cv2.INTER_AREA)
                        results = self._yolo(rgb_s, verbose=False)
                        boxes = []
                        if results:
                            r0 = results[0]
                            names = getattr(r0, 'names', {0: 'person'})
                            for b in getattr(r0, 'boxes', []):
                                try:
                                    cls = int(b.cls[0]) if hasattr(b, 'cls') else None
                                    if names.get(cls, '') == 'person' or cls == 0:
                                        xyxy = b.xyxy[0].tolist()
                                        boxes.append(xyxy)
                                except Exception:
                                    pass
                        self._person_count_last = len(boxes)
                        if boxes:
                            sx = w0 / max(1, rgb_s.shape[1]); sy = h0 / max(1, rgb_s.shape[0])
                            for (x1, y1, x2, y2) in boxes:
                                x1 = int(x1 * sx); y1 = int(y1 * sy); x2 = int(x2 * sx); y2 = int(y2 * sy)
                                cv2.rectangle(disp, (x1, y1), (x2, y2), (0,255,0), 2)
                            cv2.putText(disp, f"Persons: {self._person_count_last}", (10, target_h-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2, cv2.LINE_AA)
                    else:
                        # If YOLO not available, fall through to HOG drawing
                        pass
                # HOG path (used for policy evaluation and overlay when YOLO is off/unavailable)
                if not self._detect_people or not (self._yolo_available and self._yolo is not None):
                    if (time.time() - self._ai_last_ts) >= self._ai_min_interval:
                        self._ai_last_ts = time.time()
                        if self._hog is None:
                            self._hog = cv2.HOGDescriptor()
                            self._hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
                        scale = 0.5 if max(target_w, target_h) > 640 else 1.0
                        small = disp if scale == 1.0 else cv2.resize(disp, (int(target_w*scale), int(target_h*scale)), interpolation=cv2.INTER_AREA)
                        rects, _ = self._hog.detectMultiScale(small, winStride=(8,8), padding=(8,8), scale=1.05)
                        self._person_count_last = len(rects)
                        if self._detect_people and rects:  # draw only if overlay ON
                            for (x, y, w0, h0) in rects:
                                x = int(x/scale); y = int(y/scale); w0 = int(w0/scale); h0 = int(h0/scale)
                                cv2.rectangle(disp, (x, y), (x+w0, y+h0), (0,255,0), 2)
                            cv2.putText(disp, f"Persons: {self._person_count_last}", (10, target_h-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2, cv2.LINE_AA)
            except Exception:
                self._person_count_last = 0
                # Graceful notice once when YOLO first requested but missing
                if self._detect_people and self._yolo is None and not getattr(self, '_yolo_notice_shown', False):
                    try:
                        from PySide6.QtWidgets import QMessageBox
                        QMessageBox.information(self, "YOLO Not Available", "YOLO model not available. Install 'ultralytics' and 'torch' and place yolov8n.pt to enable. Falling back to classic detector.")
                    except Exception:
                        pass
                    self._yolo_notice_shown = True
        # Ensure C-contiguous memory before building QImage (cropping can create non-contiguous views)
        if not getattr(disp.flags, 'c_contiguous', True):
            disp = np.ascontiguousarray(disp)
        h, w, ch = disp.shape
        bytes_per_line = ch * w
        # Initialize tile-level writer if needed
        if self._tile_recording:
            if self._tile_writer is None or self._tile_writer_size != (disp.shape[1], disp.shape[0]):
                # open writer with current frame size
                try:
                    rp, th, vc = self.db.get_preferences()
                except Exception:
                    vc = "mp4"
                use_avi = (str(vc).lower() == "avi")
                fourcc = cv2.VideoWriter_fourcc(*("MJPG" if use_avi else "mp4v"))
                ext = ".avi" if use_avi else ".mp4"
                out_dir = Path(self.cfg.recordings_dir)
                out_dir.mkdir(parents=True, exist_ok=True)
                ts = time.strftime("%Y%m%d_%H%M%S")
                out_path = out_dir / f"cam{self.camera_id}_tile_{ts}{ext}"
                self._tile_writer = cv2.VideoWriter(str(out_path), fourcc, float(self._tile_writer_fps), (disp.shape[1], disp.shape[0]))
                self._tile_writer_size = (disp.shape[1], disp.shape[0])
                self.status_lbl.setText(f"Recording: {out_path.name}")
            if self._tile_writer is not None and self._tile_writer.isOpened():
                try:
                    self._tile_writer.write(disp)
                except Exception:
                    pass

        # Update chip (LIVE/REC + timer)
        is_rec = (isinstance(self.worker, CameraWorker) and getattr(self.worker, "_recording", False)) or self._tile_recording
        if is_rec:
            self._update_chip(kind="REC")
        else:
            self._update_chip(kind="LIVE")
        # Draw small red REC dot on the frame (top-left) when recording
        if is_rec:
            try:
                cv2.circle(disp, (12, 12), 6, (0, 0, 255), thickness=-1)
            except Exception:
                pass
        # Update info labels
        try:
            self.lbl_res.setText(f"{w}x{h}")
            # We keep FPS label subtle to avoid noise; can be improved by measuring frames/sec
            self.lbl_fps.setText("")
        except Exception:
            pass

        # Detach to avoid referencing temporary NumPy buffer
        qimg = QImage(disp.data, w, h, bytes_per_line, QImage.Format_BGR888).copy()
        self.label.setPixmap(QPixmap.fromImage(qimg))

        # Apply recording policy (do not override manual)
        try:
            eff_policy = self._record_policy if self._record_policy != 'manual' else self._global_policy
            should_rec = False
            if eff_policy == 'always':
                should_rec = True
            elif eff_policy == 'motion':
                should_rec = bool(motion)
            elif eff_policy == 'person':
                should_rec = (self._person_count_last > 0)
            # Start/stop recording depending on worker type; if manual, do nothing
            from ...camera.camera_worker import CameraWorker as _CW
            if isinstance(self.worker, _CW):
                if eff_policy != 'manual' and should_rec and not getattr(self.worker, '_recording', False):
                    try:
                        self.worker.start_recording(name_prefix=f"cam{self.camera_id}")
                    except Exception:
                        pass
                elif eff_policy != 'manual' and (not should_rec) and getattr(self.worker, '_recording', False):
                    try:
                        self.worker.stop_recording()
                    except Exception:
                        pass
            else:
                # HTTP snapshot tile-level writer
                if eff_policy != 'manual' and should_rec and not self._tile_recording:
                    self._tile_recording = True
                    self._tile_writer = None
                    self._tile_writer_size = None
                    self.status_lbl.setText("Recording starting...")
                    self._rec_start_ts = time.time()
                elif eff_policy != 'manual' and (not should_rec) and self._tile_recording:
                    self._tile_recording = False
        except Exception:
            pass

    def _toggle_ai(self, checked: bool):
        self._detect_people = bool(checked)

    # Hover behavior to show controls and enable zoom effect
    def enterEvent(self, e):
        # Subtle hover emphasis via drop shadow animation
        try:
            if not hasattr(self, "_shadow"):
                self._shadow = QGraphicsDropShadowEffect(self)
                self._shadow.setBlurRadius(12)
                self._shadow.setOffset(0, 0)
                self._shadow.setColor(QColor(0, 0, 0, 140))
                self.setGraphicsEffect(self._shadow)
            if not hasattr(self, "_shadow_anim"):
                self._shadow_anim = QPropertyAnimation(self._shadow, b"blurRadius", self)
                self._shadow_anim.setDuration(150)
                self._shadow_anim.setEasingCurve(QEasingCurve.InOutQuad)
            self._shadow_anim.stop()
            self._shadow_anim.setStartValue(self._shadow.blurRadius())
            self._shadow_anim.setEndValue(24)
            self._shadow_anim.start()
        except Exception:
            pass
        self._hovered = True
        if not self._broadcast_ui:
            try:
                if hasattr(self, "controls_row"):
                    self.controls_row.setVisible(True)
                if hasattr(self, "status_lbl"):
                    self.status_lbl.setVisible(True)
            except Exception:
                pass
        super().enterEvent(e)

    def leaveEvent(self, e):
        try:
            if hasattr(self, "_shadow"):
                if not hasattr(self, "_shadow_anim"):
                    self._shadow_anim = QPropertyAnimation(self._shadow, b"blurRadius", self)
                    self._shadow_anim.setDuration(150)
                    self._shadow_anim.setEasingCurve(QEasingCurve.InOutQuad)
                self._shadow_anim.stop()
                self._shadow_anim.setStartValue(self._shadow.blurRadius())
                self._shadow_anim.setEndValue(12)
                self._shadow_anim.start()
        except Exception:
            pass
        self._hovered = False
        try:
            if hasattr(self, "controls_row"):
                self.controls_row.setVisible(False)
            if hasattr(self, "status_lbl"):
                self.status_lbl.setVisible(False)
        except Exception:
            pass
        super().leaveEvent(e)

    def set_broadcast(self, on: bool):
        self._broadcast_ui = bool(on)
        try:
            if hasattr(self, "chip"):
                self.chip.setVisible(not self._broadcast_ui)
        except Exception:
            pass
        try:
            if hasattr(self, "overlay_bar"):
                self.overlay_bar.setVisible(not self._broadcast_ui)
        except Exception:
            pass
        try:
            if hasattr(self, "controls_row"):
                self.controls_row.setVisible(False)
        except Exception:
            pass
        try:
            if hasattr(self, "status_lbl"):
                self.status_lbl.setVisible(False)
        except Exception:
            pass

    def edit_camera(self):
        from ..edit_camera_dialog import EditCameraDialog
        # pass current policy to dialog
        dlg = EditCameraDialog(self.name, self.url, self.cam_type, self, policy=self._record_policy)
        if dlg.exec():
            new_name, new_url, new_type, new_policy = dlg.get_values()
            if (new_name, new_url, new_type) != (self.name, self.url, self.cam_type):
                # ask confirm if url/type changed
                if (new_url != self.url) or (new_type != self.cam_type):
                    r = QMessageBox.question(self, "Confirm Changes", "Save changes to this camera's configuration?", QMessageBox.Yes | QMessageBox.No)
                    if r != QMessageBox.Yes:
                        return
                self.name, self.url, self.cam_type = new_name, new_url, new_type
                try:
                    self.db.update_camera(self.camera_id, self.name, self.url, self.cam_type)
                except Exception:
                    pass
                # restart if running
                was_running = bool(self.worker and self.worker.isRunning())
                if was_running:
                    self.stop()
                    self.start()
            # Save policy regardless
            try:
                if hasattr(self.db, 'set_camera_policy'):
                    self.db.set_camera_policy(self.camera_id, new_policy)
                    self._record_policy = new_policy
                    # refresh global in case user changed via settings separately
                    self._global_policy = getattr(self.db, 'get_global_policy', lambda: 'manual')()
            except Exception:
                pass

    def _request_move(self, direction: int):
        # Ask parent to reorder this tile with neighbor target
        parent = self.parentWidget()
        siblings = []
        if parent and hasattr(parent, 'layout'):
            lay = parent.layout()
            for i in range(lay.count()):
                w = lay.itemAt(i).widget()
                if hasattr(w, 'camera_id'):
                    siblings.append(w)
        idx = next((i for i, w in enumerate(siblings) if w is self), -1)
        target_idx = idx + direction
        if idx >= 0 and 0 <= target_idx < len(siblings):
            target_id = siblings[target_idx].camera_id
            self.reorder_request.emit(self.camera_id, target_id)

    def resizeEvent(self, e):
        # Keep video area proportional (16:9) for a professional, consistent grid
        try:
            w = max(1, self.width())
            h = int(w * 9 / 16)
            # Reserve some space for chip/labels/controls
            h = max(180, h)
            self.label.setFixedHeight(h)
            # position status chip at top-right of the video
            if hasattr(self, "chip"):
                self.chip.adjustSize()
                cx = max(8, self.label.width() - self.chip.width() - 8)
                cy = 8
                self.chip.move(cx, cy)
            # position overlay bar at bottom
            if hasattr(self, "overlay_bar"):
                bar_h = 24
                self.overlay_bar.setGeometry(0, self.label.height() - bar_h, self.label.width(), bar_h)
            # adjust icon sizes based on tile width for automatic responsiveness
            icon_px = max(18, min(28, w // 24))
            icon_sz = Qt.QSize(icon_px, icon_px) if hasattr(Qt, 'QSize') else None
            try:
                from PySide6.QtCore import QSize
                icon_sz = QSize(icon_px, icon_px)
            except Exception:
                icon_sz = None
            if icon_sz is not None:
                for b in [self.btn_start, self.btn_stop, self.btn_snapshot, self.btn_record, self.btn_edit, self.btn_delete, self.btn_move_left, self.btn_move_right]:
                    try:
                        b.setIconSize(icon_sz)
                    except Exception:
                        pass
        except Exception:
            pass
        super().resizeEvent(e)

    def _make_red_dot_icon(self, size: int = 18) -> QIcon:
        px = QPixmap(size, size)
        px.fill(Qt.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.Antialiasing, True)
        br = QBrush(QColor(220, 0, 0))
        p.setBrush(br)
        p.setPen(Qt.NoPen)
        r = int(size * 0.65)
        off = (size - r) // 2
        p.drawEllipse(off, off, r, r)
        p.end()
        return QIcon(px)

    def _make_camera_icon(self, size: int = 18) -> QIcon:
        px = QPixmap(size, size)
        px.fill(Qt.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.Antialiasing, True)
        # body
        body = QColor(40, 40, 40)
        lens = QColor(200, 200, 200)
        accent = QColor(70, 70, 70)
        p.setPen(Qt.NoPen)
        p.setBrush(body)
        bw = int(size * 0.8)
        bh = int(size * 0.55)
        bx = (size - bw) // 2
        by = (size - bh) // 2
        p.drawRoundedRect(bx, by, bw, bh, 3, 3)
        # lens
        p.setBrush(lens)
        lr = int(min(bw, bh) * 0.45)
        lx = bx + bw//2 - lr//2
        ly = by + bh//2 - lr//2
        p.drawEllipse(lx, ly, lr, lr)
        # top bar
        p.setBrush(accent)
        th = max(2, size // 9)
        p.drawRect(bx + 2, by - th//2, bw - 4, th)
        p.end()
        return QIcon(px)

    def _update_chip(self, kind: str):
        if kind == "REC":
            bg = "#b00020"
            txt = "REC"
            if self._rec_start_ts:
                elapsed = int(time.time() - self._rec_start_ts)
                mm = elapsed // 60
                ss = elapsed % 60
                txt = f"REC {mm:02d}:{ss:02d}"
        elif kind == "ERR":
            bg = "#b00020"
            txt = "ERR"
        elif kind == "LIVE":
            bg = "#2e7d32"
            txt = "LIVE"
        else:
            bg = "#555"
            txt = "IDLE"
        if kind != self._last_status_kind or True:
            self.chip.setText(txt)
            self.chip.setStyleSheet(f"padding:2px 6px; border-radius:8px; background:{bg}; color:#fff; font-weight:bold;")
            self._last_status_kind = kind

    # Fullscreen viewer
    def mouseDoubleClickEvent(self, e):
        if not self.fullscreen:
            self.fullscreen = _FullscreenViewer(self.name)
            # mirror frames
            if self.worker:
                self.worker.frame_ready.connect(self.fullscreen.on_frame)
        self.fullscreen.showFullScreen()
        super().mouseDoubleClickEvent(e)

    def _reconnect(self):
        try:
            self.stop()
        except Exception:
            pass
        # slight delay to ensure thread stops before restart
        try:
            QTimer.singleShot(150, self.start)
        except Exception:
            self.start()

    def _schedule_health_timer(self):
        # periodic health check to auto-reconnect with backoff if no frames
        if not hasattr(self, "_health_timer"):
            self._health_timer = QTimer(self)
            self._health_timer.timeout.connect(self._health_check)
            self._health_timer.start(2000)

    def _health_check(self):
        now = time.time()
        # If worker is running but we haven't received frames recently, attempt reconnect with backoff
        if self.worker and self.worker.isRunning():
            stale_secs = 8
            if self._last_frame_ts and (now - self._last_frame_ts) > stale_secs:
                if now >= self._next_retry_ts:
                    self._retry_count = min(self._retry_count + 1, 6)
                    delay = min(30, 2 ** self._retry_count)
                    self._next_retry_ts = now + delay
                    self._update_chip(kind="ERR")
                    self.status_lbl.setText("Stream stale, reconnecting...")
                    self._reconnect()
        else:
            # Not running; reduce retry backoff gradually
            if self._retry_count > 0 and now >= self._next_retry_ts:
                self._retry_count -= 1

    def delete_camera(self):
        ret = QMessageBox.question(self, "Delete Camera", f"Delete camera '{self.name}'?", QMessageBox.Yes | QMessageBox.No)
        if ret == QMessageBox.Yes:
            self.stop()
            try:
                self.db.remove_camera(self.camera_id)
            finally:
                self.deleted.emit(self.camera_id)


class _FullscreenViewer(QDialog):
    def __init__(self, title: str):
        super().__init__()
        self.setWindowTitle(title)
        self.setModal(False)
        self.label = QLabel("No Signal")
        self.label.setAlignment(Qt.AlignCenter)
        lay = QVBoxLayout(self)
        lay.addWidget(self.label)

    def on_frame(self, frame, cam_id: int):
        try:
            if not getattr(frame.flags, 'c_contiguous', True):
                frame = np.ascontiguousarray(frame)
            h, w, ch = frame.shape
            bytes_per_line = ch * w
            qimg = QImage(frame.data, w, h, bytes_per_line, QImage.Format_BGR888).copy()
            self.label.setPixmap(QPixmap.fromImage(qimg).scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception:
            pass

    def closeEvent(self, e):
        self.stop()
        super().closeEvent(e)

    def delete_camera(self):
        # Stop worker and remove from DB, then notify parent
        from PySide6.QtWidgets import QMessageBox
        ret = QMessageBox.question(self, "Delete Camera", f"Delete camera '{self.name}'?", QMessageBox.Yes | QMessageBox.No)
        if ret == QMessageBox.Yes:
            self.stop()
            try:
                self.db.remove_camera(self.camera_id)
            finally:
                self.deleted.emit(self.camera_id)
