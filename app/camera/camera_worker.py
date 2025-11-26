from PySide6.QtCore import QThread, Signal
import cv2
import time
from pathlib import Path


class CameraWorker(QThread):
    frame_ready = Signal(object, int)  # (frame: numpy array, camera_id)
    status = Signal(int, str)  # (camera_id, message)

    def __init__(self, camera_id: int, url: str, recordings_dir: Path, cam_type: str = "rtsp"):
        super().__init__()
        self.camera_id = camera_id
        self.url = url
        self.recordings_dir = recordings_dir
        self.cam_type = (cam_type or "rtsp").lower()
        self._running = False
        self._recording = False
        self._writer = None
        self._fps = 25.0
        self._size = (1280, 720)

    def run(self):
        # Open capture depending on type/backends
        cap = None
        opened = False
        def gst_available():
            try:
                info = cv2.getBuildInformation()
                return ("GStreamer" in info) or hasattr(cv2, "CAP_GSTREAMER")
            except Exception:
                return False

        def ffmpeg_available():
            try:
                info = cv2.getBuildInformation()
                return ("FFMPEG:" in info and "YES" in info.split("FFMPEG:",1)[1][:40]) or hasattr(cv2, "CAP_FFMPEG")
            except Exception:
                return False

        def try_gstreamer(url: str, cam_type: str):
            # Build flexible pipelines; return opened cap or None
            try:
                if not gst_available():
                    return None
                # Use uridecodebin which handles RTSP/HTTP/FILE
                # appsink caps left flexible; drop buffers to reduce lag
                if url.lower().startswith("rtsp"):
                    pipe = f"uridecodebin uri={url} ! videoconvert ! appsink sync=false drop=true max-buffers=1"
                elif url.lower().startswith("http"):
                    pipe = f"uridecodebin uri={url} ! videoconvert ! appsink sync=false drop=true max-buffers=1"
                else:
                    pipe = f"uridecodebin uri={url} ! videoconvert ! appsink sync=false drop=true max-buffers=1"
                c = cv2.VideoCapture(pipe, cv2.CAP_GSTREAMER)
                if c is not None and c.isOpened():
                    return c
            except Exception:
                return None
            return None
        # Try USB index with V4L2 first (Linux), then default
        if self.cam_type == "usb":
            try:
                index = int(self.url)
            except Exception:
                index = 0
            self.status.emit(self.camera_id, f"Opening USB camera index {index} (V4L2)...")
            cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
            # Request modest resolution to reduce CPU
            try:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                cap.set(cv2.CAP_PROP_FPS, 15)
            except Exception:
                pass
            opened = cap.isOpened()
            if not opened:
                self.status.emit(self.camera_id, "V4L2 open failed, trying default backend...")
                cap.release()
                cap = cv2.VideoCapture(index)
                opened = cap.isOpened()
        else:
            # Network sources: try GStreamer (if available) then FFmpeg then default
            cap = None
            if gst_available():
                self.status.emit(self.camera_id, "Opening network stream (GStreamer)…")
                cap = try_gstreamer(self.url, self.cam_type)
                opened = bool(cap and cap.isOpened())
                if not opened and cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass
            if not opened:
                # Try default backend first to avoid FFmpeg 'capture by name' warnings
                self.status.emit(self.camera_id, "Opening network stream (Default)…")
                cap = cv2.VideoCapture(self.url)
                opened = cap.isOpened()
            # Only try FFmpeg if explicitly enabled via env
            import os
            if not opened and ffmpeg_available() and os.environ.get("OPENCV_USE_FFMPEG", "0") == "1":
                self.status.emit(self.camera_id, "Opening network stream (FFmpeg)…")
                try:
                    cap.release()
                except Exception:
                    pass
                cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
                opened = cap.isOpened()
        if not cap.isOpened():
            self.status.emit(self.camera_id, "Camera open failed")
            return
        self._running = True
        self.status.emit(self.camera_id, "Camera started")

        fps = cap.get(cv2.CAP_PROP_FPS)
        try:
            fps = float(fps)
            if fps <= 1 or fps != fps:  # NaN or invalid
                fps = 25.0
        except Exception:
            fps = 25.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1280)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 720)
        self._fps = fps
        self._size = (width, height)

        last_emit = 0.0
        emit_interval = 1.0 / 12.0  # throttle UI updates ~12 FPS
        while self._running:
            ok, frame = cap.read()
            if not ok:
                self.status.emit(self.camera_id, "Frame read failed; retrying...")
                time.sleep(0.1)
                continue

            # timestamp overlay
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            cv2.putText(frame, ts, (10, self._size[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2, cv2.LINE_AA)

            if self._recording and self._writer is not None:
                self._writer.write(frame)

            now = time.time()
            if (now - last_emit) >= emit_interval:
                last_emit = now
                try:
                    self.frame_ready.emit(frame, self.camera_id)
                except Exception:
                    pass

        cap.release()
        if self._writer is not None:
            self._writer.release()
        self.status.emit(self.camera_id, "Camera stopped")

    def stop(self):
        self._running = False

    def start_recording(self, name_prefix: str = "rec", codec: str = "mp4", out_dir: Path | None = None):
        if self._recording:
            return
        target_dir = out_dir if out_dir is not None else self.recordings_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        use_avi = (str(codec).lower() == "avi")
        ext = ".avi" if use_avi else ".mp4"
        fourcc = cv2.VideoWriter_fourcc(*("MJPG" if use_avi else "mp4v"))
        out_path = target_dir / f"{name_prefix}_{ts}{ext}"
        self._writer = cv2.VideoWriter(str(out_path), fourcc, float(self._fps or 25.0), self._size)
        if self._writer is not None and self._writer.isOpened():
            self._recording = True
            self.status.emit(self.camera_id, f"Recording: {out_path}")

    def stop_recording(self):
        if not self._recording:
            return
        self._recording = False
        if self._writer is not None:
            self._writer.release()
            self._writer = None
        self.status.emit(self.camera_id, "Recording stopped")
