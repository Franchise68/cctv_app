from PySide6.QtCore import QThread, Signal
import time
from urllib.request import urlopen, Request
import cv2
import numpy as np


class HttpSnapshotWorker(QThread):
    frame_ready = Signal(object, int)  # (frame ndarray, camera_id)
    status = Signal(int, str)

    def __init__(self, camera_id: int, url: str, fps: float = 6.0):
        super().__init__()
        self.camera_id = camera_id
        self.url = url
        self._running = False
        self._interval = 1.0 / max(0.5, float(fps))

    def stop(self):
        self._running = False

    def run(self):
        self._running = True
        last_status = 0.0
        while self._running:
            t0 = time.time()
            try:
                req = Request(self.url, headers={'User-Agent': 'Mozilla/5.0'})
                with urlopen(req, timeout=5) as resp:
                    data = resp.read()
                arr = np.frombuffer(data, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is not None:
                    self.frame_ready.emit(frame, self.camera_id)
                    if time.time() - last_status > 5:
                        self.status.emit(self.camera_id, "HTTP snapshot streaming")
                        last_status = time.time()
                else:
                    self.status.emit(self.camera_id, "Snapshot decode failed")
            except Exception as e:
                self.status.emit(self.camera_id, f"HTTP snapshot error: {e}")
                time.sleep(0.5)
            # pacing
            dt = time.time() - t0
            if dt < self._interval:
                time.sleep(self._interval - dt)
