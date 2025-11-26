from PySide6.QtCore import QThread, Signal
import time
from urllib.request import urlopen, Request


class HttpMJPEGWorker(QThread):
    frame_ready = Signal(object, int)  # (frame ndarray, camera_id)
    status = Signal(int, str)

    def __init__(self, camera_id: int, url: str):
        super().__init__()
        self.camera_id = camera_id
        self.url = url
        self._running = False

    def stop(self):
        self._running = False

    def _readline(self, resp):
        # Read a single CRLF-terminated line
        line = b""
        while True:
            ch = resp.read(1)
            if not ch:
                break
            line += ch
            if line.endswith(b"\r\n"):
                break
        return line

    def run(self):
        import cv2
        import numpy as np

        self._running = True
        reconnect_delay = 1.0
        while self._running:
            self.status.emit(self.camera_id, "Opening HTTP MJPEG stream...")
            req = Request(self.url, headers={'User-Agent': 'Mozilla/5.0'})
            try:
                resp = urlopen(req, timeout=10)
                ct = resp.info().get('Content-Type', '')
                boundary = None
                if 'multipart' in ct and 'boundary=' in ct:
                    boundary = ct.split('boundary=')[-1].strip()
                    if boundary.startswith('"') and boundary.endswith('"'):
                        boundary = boundary[1:-1]
                    if not boundary.startswith('--'):
                        boundary = '--' + boundary
                    boundary = boundary.encode('utf-8')
                else:
                    # Some servers don't send multipart header; we'll still try to parse parts by headers
                    boundary = None
            except Exception as e:
                self.status.emit(self.camera_id, f"HTTP open failed: {e}")
                time.sleep(reconnect_delay)
                reconnect_delay = min(8.0, reconnect_delay * 2)
                continue

            reconnect_delay = 1.0
            last_status = time.time()
            try:
                while self._running:
                    # Find multipart boundary (if provided)
                    if boundary is not None:
                        # consume until boundary line
                        line = self._readline(resp)
                        while self._running and line and boundary not in line:
                            line = self._readline(resp)
                        if not line:
                            raise IOError('Stream ended')

                    # Read part headers
                    headers = {}
                    while self._running:
                        line = self._readline(resp)
                        if not line:
                            raise IOError('Stream ended while reading headers')
                        line = line.strip()
                        if not line:
                            break
                        if b":" in line:
                            k, v = line.split(b":", 1)
                            headers[k.strip().lower()] = v.strip()

                    # Determine content length
                    clen = None
                    if b'content-length' in headers:
                        try:
                            clen = int(headers[b'content-length'])
                        except Exception:
                            clen = None

                    # Read payload
                    if clen is not None and clen > 0:
                        jpg = b""
                        to_read = clen
                        while self._running and to_read > 0:
                            chunk = resp.read(to_read)
                            if not chunk:
                                raise IOError('Stream ended during payload')
                            jpg += chunk
                            to_read -= len(chunk)
                    else:
                        # Fallback: read until JPEG EOI
                        buf = b""
                        while self._running:
                            chunk = resp.read(4096)
                            if not chunk:
                                raise IOError('Stream ended during scan')
                            buf += chunk
                            start = buf.find(b"\xff\xd8")
                            end = buf.find(b"\xff\xd9")
                            if start != -1 and end != -1 and end > start:
                                jpg = buf[start:end+2]
                                # leave remainder in buf for next boundary seek by pushing back? Not possible with urllib.
                                # We'll reset buffer next loop; boundary seek will resync.
                                break

                    # Decode JPEG
                    try:
                        arr = np.frombuffer(jpg, dtype=np.uint8)
                        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                        if frame is not None:
                            self.frame_ready.emit(frame, self.camera_id)
                            if time.time() - last_status > 5:
                                self.status.emit(self.camera_id, "HTTP MJPEG streaming")
                                last_status = time.time()
                        else:
                            self.status.emit(self.camera_id, "Decode failed; skipping frame")
                    except Exception as e:
                        self.status.emit(self.camera_id, f"Decode error: {e}")
                        time.sleep(0.05)
            except Exception as e:
                if self._running:
                    self.status.emit(self.camera_id, f"HTTP stream error: {e}; reconnecting...")
                time.sleep(reconnect_delay)
                reconnect_delay = min(8.0, reconnect_delay * 2)
            finally:
                try:
                    resp.close()
                except Exception:
                    pass
                self.status.emit(self.camera_id, "HTTP stream closed")
