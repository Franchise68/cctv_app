from PySide6.QtWidgets import QDialog, QVBoxLayout, QListWidget, QPushButton, QHBoxLayout, QLabel, QMessageBox, QSplitter, QWidget, QFormLayout, QSpinBox, QDialogButtonBox
from PySide6.QtCore import Qt, QUrl, QTimer, QPoint
from PySide6.QtGui import QDesktopServices, QPixmap, QImage
from pathlib import Path
import os
import cv2
import math
import time


class RecordingManagerDialog(QDialog):
    def __init__(self, recordings_dir: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Recording Manager")
        self.resize(900, 520)
        self.recordings_dir = Path(recordings_dir)
        self.recordings_dir.mkdir(parents=True, exist_ok=True)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Folder: {self.recordings_dir}"))

        split = QSplitter()
        layout.addWidget(split)

        # Left: list
        left = QWidget()
        l_lay = QVBoxLayout(left)
        self.listw = QListWidget()
        l_lay.addWidget(self.listw)
        btn_row = QHBoxLayout()
        self.btn_open = QPushButton("Open File")
        self.btn_play_inside = QPushButton("Play Inside")
        self.btn_folder = QPushButton("Open Folder")
        self.btn_delete = QPushButton("Delete Selected")
        self.btn_cleanup = QPushButton("Clean Up…")
        self.btn_close = QPushButton("Close")
        btn_row.addWidget(self.btn_open)
        btn_row.addWidget(self.btn_play_inside)
        btn_row.addWidget(self.btn_folder)
        btn_row.addWidget(self.btn_delete)
        btn_row.addWidget(self.btn_cleanup)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_close)
        l_lay.addLayout(btn_row)
        split.addWidget(left)

        # Right: preview + metadata
        right = QWidget()
        r_lay = QVBoxLayout(right)
        self.preview = QLabel("Select a file to preview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(260)
        r_lay.addWidget(self.preview)
        form = QFormLayout()
        self.meta_name = QLabel("")
        self.meta_size = QLabel("")
        self.meta_dur = QLabel("")
        self.meta_cam = QLabel("")
        self.meta_date = QLabel("")
        form.addRow("Name:", self.meta_name)
        form.addRow("Size:", self.meta_size)
        form.addRow("Duration:", self.meta_dur)
        form.addRow("Camera:", self.meta_cam)
        form.addRow("Date:", self.meta_date)
        r_lay.addLayout(form)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)

        self.btn_open.clicked.connect(self.open_file)
        self.btn_play_inside.clicked.connect(self._open_player)
        self.btn_folder.clicked.connect(self.open_folder)
        self.btn_delete.clicked.connect(self.delete_selected)
        self.listw.currentItemChanged.connect(self._on_select)
        self.btn_cleanup.clicked.connect(self._open_cleanup)
        self.listw.itemDoubleClicked.connect(lambda _i: self._open_player())
        self.btn_close.clicked.connect(self.close)

        self.refresh()

    def refresh(self):
        self.listw.clear()
        exts = {".mp4", ".avi", ".mov", ".mkv"}
        if self.recordings_dir.exists():
            for p in sorted(self.recordings_dir.glob("*")):
                if p.is_file() and p.suffix.lower() in exts:
                    self.listw.addItem(str(p))

    def _selected_path(self) -> Path | None:
        item = self.listw.currentItem()
        if not item:
            return None
        return Path(item.text())

    def _on_select(self):
        p = self._selected_path()
        if not p or not p.exists():
            self.preview.setText("Select a file to preview")
            self._set_meta(None)
            return
        self._set_meta(p)
        # Try to extract first frame as thumbnail
        thumb = None
        try:
            cap = cv2.VideoCapture(str(p))
            ok, frame = cap.read()
            cap.release()
            if ok and frame is not None:
                # Convert BGR->RGB for QImage
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb.shape
                qi = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()
                thumb = QPixmap.fromImage(qi)
        except Exception:
            thumb = None
        if thumb is None:
            self.preview.setText("No preview available")
        else:
            self.preview.setPixmap(thumb.scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _set_meta(self, p: Path | None):
        if not p or not p.exists():
            self.meta_name.setText("")
            self.meta_size.setText("")
            self.meta_dur.setText("")
            self.meta_cam.setText("")
            self.meta_date.setText("")
            return
        st = p.stat()
        size_mb = st.st_size / (1024 * 1024.0)
        # duration via OpenCV if possible
        dur_txt = ""
        try:
            cap = cv2.VideoCapture(str(p))
            n = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
            fps = cap.get(cv2.CAP_PROP_FPS) or 0
            cap.release()
            if n > 0 and fps > 0:
                secs = int(n / fps)
                mm = secs // 60
                ss = secs % 60
                dur_txt = f"{mm:02d}:{ss:02d}"
        except Exception:
            pass
        # camera from filename pattern cam<ID>_...
        cam_txt = ""
        name = p.name
        if name.startswith("cam"):
            try:
                cam_id_part = "".join(ch for ch in name[3:] if ch.isdigit())
                if cam_id_part:
                    cam_txt = f"Camera {cam_id_part}"
            except Exception:
                cam_txt = ""
        dt_txt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))
        self.meta_name.setText(name)
        self.meta_size.setText(f"{size_mb:.2f} MB")
        self.meta_dur.setText(dur_txt or "—")
        self.meta_cam.setText(cam_txt or "—")
        self.meta_date.setText(dt_txt)

    def open_file(self):
        p = self._selected_path()
        if not p:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def _open_player(self):
        p = self._selected_path()
        if not p or not p.exists():
            return
        dlg = VideoPlayerDialog(str(p), self)
        dlg.resize(900, 600)
        dlg.exec()

    def open_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.recordings_dir)))

    def delete_selected(self):
        p = self._selected_path()
        if not p:
            return
        if not p.exists():
            self.refresh()
            return
        ret = QMessageBox.question(self, "Delete Recording", f"Delete file:\n{p.name}?", QMessageBox.Yes | QMessageBox.No)
        if ret == QMessageBox.Yes:
            try:
                os.remove(p)
            except Exception as e:
                QMessageBox.warning(self, "Delete Failed", str(e))
            self.refresh()

    # Retention cleanup
    def _open_cleanup(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Retention Cleanup")
        v = QVBoxLayout(dlg)
        form = QFormLayout()
        days = QSpinBox()
        days.setRange(0, 3650)
        days.setValue(0)
        gb = QSpinBox()
        gb.setRange(0, 10000)
        gb.setValue(0)
        form.addRow("Max Age (days, 0 = ignore):", days)
        form.addRow("Max Size (GB, 0 = ignore):", gb)
        v.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        v.addWidget(btns)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        if not dlg.exec():
            return
        self._run_cleanup(days.value(), gb.value())

    def _run_cleanup(self, max_days: int, max_gb: int):
        # Collect files
        files = []
        exts = {".mp4", ".avi", ".mov", ".mkv"}
        total_size = 0
        now = time.time()
        for p in self.recordings_dir.glob("*"):
            if p.is_file() and p.suffix.lower() in exts:
                st = p.stat()
                files.append((p, st.st_mtime, st.st_size))
                total_size += st.st_size
        deleted = []
        # 1) Delete older than max_days
        if max_days > 0:
            cutoff = now - max_days * 86400
            for (p, mtime, size) in list(files):
                if mtime < cutoff and p.exists():
                    try:
                        os.remove(p)
                        deleted.append(p.name)
                        total_size -= size
                        files.remove((p, mtime, size))
                    except Exception:
                        pass
        # 2) Enforce max size (trim oldest first)
        if max_gb > 0:
            max_bytes = max_gb * 1024 * 1024 * 1024
            if total_size > max_bytes:
                files.sort(key=lambda x: x[1])  # by mtime, oldest first
                for (p, mtime, size) in files:
                    if total_size <= max_bytes:
                        break
                    if p.exists():
                        try:
                            os.remove(p)
                            deleted.append(p.name)
                            total_size -= size
                        except Exception:
                            pass
        self.refresh()
        if deleted:
            QMessageBox.information(self, "Cleanup Complete", f"Deleted {len(deleted)} file(s).")
        else:
            QMessageBox.information(self, "Cleanup", "No files were deleted.")


class _VideoView(QLabel):
    def __init__(self, parent):
        super().__init__("No Video")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(360)
        self.parent_dlg = parent
        self._dragging = False
        self._last_pos = QPoint()

    def wheelEvent(self, e):
        if e.angleDelta().y() > 0:
            self.parent_dlg.zoom_in()
        else:
            self.parent_dlg.zoom_out()

    def mousePressEvent(self, e):
        if e.button() == 1:
            self._dragging = True
            self._last_pos = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._dragging = False
        super().mouseReleaseEvent(e)

    def mouseMoveEvent(self, e):
        if self._dragging:
            cur = e.position().toPoint()
            delta = cur - self._last_pos
            self._last_pos = cur
            self.parent_dlg.pan_by(delta.x(), delta.y())
        super().mouseMoveEvent(e)


class VideoPlayerDialog(QDialog):
    def __init__(self, video_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Player - {Path(video_path).name}")
        self._path = video_path
        self._cap = cv2.VideoCapture(video_path)
        self._fps = float(self._cap.get(cv2.CAP_PROP_FPS) or 25.0)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._playing = False
        self._speed = 1.0  # 0.25, 0.5, 1.0, 2.0
        self._zoom = 1.0
        self._pan_x = 0
        self._pan_y = 0
        self._last_frame = None

        v = QVBoxLayout(self)
        self.view = _VideoView(self)
        v.addWidget(self.view)

        # Controls
        row = QHBoxLayout()
        self.btn_play = QPushButton("Play")
        self.btn_pause = QPushButton("Pause")
        self.btn_step = QPushButton("Step ▶")
        self.btn_slower = QPushButton("0.5x")
        self.btn_normal = QPushButton("1x")
        self.btn_faster = QPushButton("2x")
        self.btn_zoom_in = QPushButton("Zoom +")
        self.btn_zoom_out = QPushButton("Zoom -")
        self.btn_reset = QPushButton("Reset View")
        self.btn_close = QPushButton("Close")
        for b in [self.btn_play, self.btn_pause, self.btn_step, self.btn_slower, self.btn_normal, self.btn_faster, self.btn_zoom_in, self.btn_zoom_out, self.btn_reset, self.btn_close]:
            row.addWidget(b)
        v.addLayout(row)

        self.btn_play.clicked.connect(self.play)
        self.btn_pause.clicked.connect(self.pause)
        self.btn_step.clicked.connect(self.step)
        self.btn_slower.clicked.connect(lambda: self.set_speed(0.5))
        self.btn_normal.clicked.connect(lambda: self.set_speed(1.0))
        self.btn_faster.clicked.connect(lambda: self.set_speed(2.0))
        self.btn_zoom_in.clicked.connect(self.zoom_in)
        self.btn_zoom_out.clicked.connect(self.zoom_out)
        self.btn_reset.clicked.connect(self.reset_view)
        self.btn_close.clicked.connect(self.close)

        # Start paused with first frame
        self.step()

    def closeEvent(self, e):
        try:
            self._timer.stop()
        except Exception:
            pass
        try:
            if self._cap:
                self._cap.release()
        except Exception:
            pass
        return super().closeEvent(e)

    def _on_tick(self):
        if not self._playing:
            return
        ok, frame = self._cap.read()
        if not ok:
            self.pause()
            return
        self._last_frame = frame
        self._draw(frame)

    def _draw(self, frame):
        try:
            # Convert BGR->RGB
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            # Apply zoom and pan by cropping from a scaled image
            scale = max(0.25, min(6.0, float(self._zoom)))
            sw = int(w * scale)
            sh = int(h * scale)
            rgb_s = cv2.resize(rgb, (sw, sh), interpolation=cv2.INTER_LINEAR)
            view_w = max(1, self.view.width())
            view_h = max(1, self.view.height())
            cx = sw // 2 + int(self._pan_x)
            cy = sh // 2 + int(self._pan_y)
            x0 = max(0, min(sw - view_w, cx - view_w // 2))
            y0 = max(0, min(sh - view_h, cy - view_h // 2))
            x1 = x0 + view_w
            y1 = y0 + view_h
            if x1 > sw or y1 > sh:
                x0 = max(0, sw - view_w)
                y0 = max(0, sh - view_h)
                x1 = min(sw, x0 + view_w)
                y1 = min(sh, y0 + view_h)
            crop = rgb_s[y0:y1, x0:x1]
            if crop.size == 0:
                crop = rgb_s
            ch = crop.shape[2]
            qi = QImage(crop.data, crop.shape[1], crop.shape[0], ch * crop.shape[1], QImage.Format_RGB888).copy()
            self.view.setPixmap(QPixmap.fromImage(qi))
        except Exception:
            pass

    def play(self):
        if self._playing:
            return
        self._playing = True
        self._start_timer()

    def pause(self):
        self._playing = False
        self._timer.stop()

    def step(self):
        self.pause()
        ok, frame = self._cap.read()
        if ok:
            self._last_frame = frame
            self._draw(frame)

    def _start_timer(self):
        delay_ms = int(max(5.0, (1000.0 / max(1.0, self._fps)) / max(0.1, self._speed)))
        self._timer.start(delay_ms)

    def set_speed(self, s: float):
        self._speed = max(0.1, min(4.0, float(s)))
        if self._playing:
            self._start_timer()

    def zoom_in(self):
        self._zoom = min(6.0, self._zoom * 1.2)
        if self._last_frame is not None:
            self._draw(self._last_frame)

    def zoom_out(self):
        self._zoom = max(0.25, self._zoom / 1.2)
        if self._last_frame is not None:
            self._draw(self._last_frame)

    def reset_view(self):
        self._zoom = 1.0
        self._pan_x = 0
        self._pan_y = 0
        if self._last_frame is not None:
            self._draw(self._last_frame)

    def pan_by(self, dx: int, dy: int):
        # pan in screen coordinates; adjust directly in scaled space
        self._pan_x += dx
        self._pan_y += dy
        if self._last_frame is not None:
            self._draw(self._last_frame)
