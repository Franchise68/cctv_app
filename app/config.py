import os
from pathlib import Path


class AppConfig:
    def __init__(self):
        self.root = Path(os.environ.get("CCTV_APP_ROOT", Path(__file__).resolve().parents[1]))
        self.data_dir = self.root
        self.db_path = self.data_dir / "cctv.db"
        self.recordings_dir = self.root / "recordings"
        self.resources_dir = self.root / "resources"
        self.theme = os.environ.get("CCTV_THEME", "dark")  # "dark" or "light"

        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        (self.resources_dir / "sounds").mkdir(parents=True, exist_ok=True)


class ThemeLoader:
    @staticmethod
    def apply_theme(app, theme_name: str):
        theme_file = Path(__file__).resolve().parent / "ui" / "themes" / f"{theme_name}.qss"
        if theme_file.exists():
            with open(theme_file, "r", encoding="utf-8") as f:
                app.setStyleSheet(f.read())
