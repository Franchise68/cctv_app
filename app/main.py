import os
# Set env BEFORE any potential OpenCV import in submodules
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
os.environ.setdefault("OPENCV_USE_FFMPEG", "0")  # avoid forcing FFmpeg capture-by-name
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
import sys

from .config import AppConfig, ThemeLoader
from .database.db import Database
from .ui.login import LoginDialog
from .ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("CCTV Manager")
    # Reduce OpenCV log noise (secondary safeguard)
    try:
        import cv2
        from cv2 import utils as _cvutils
        _cvutils.logging.setLogLevel(_cvutils.logging.LOG_LEVEL_ERROR)
        try:
            cv2.setNumThreads(1)
        except Exception:
            pass
    except Exception:
        pass

    cfg = AppConfig()
    ThemeLoader.apply_theme(app, cfg.theme)

    db = Database(cfg)
    db.initialize()

    login = LoginDialog(db)
    if login.exec() == LoginDialog.Accepted:
        mw = MainWindow(cfg, db)
        mw.show()
        sys.exit(app.exec())
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
