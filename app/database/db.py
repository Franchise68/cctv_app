import sqlite3
from pathlib import Path
from typing import Optional, List, Tuple

from ..config import AppConfig


class Database:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.conn: Optional[sqlite3.Connection] = None

    def initialize(self):
        first_time = not Path(self.cfg.db_path).exists()
        self.conn = sqlite3.connect(self.cfg.db_path)
        self.conn.execute("PRAGMA foreign_keys=ON;")
        self._init_schema()
        self._maybe_add_sort_order()
        self._maybe_add_record_policy()
        self._maybe_add_global_record_policy()
        if first_time:
            self.conn.commit()

    def _init_schema(self):
        schema_path = Path(__file__).with_name("schema.sql")
        with open(schema_path, "r", encoding="utf-8") as f:
            sql = f.read()
        self.conn.executescript(sql)
        self.conn.commit()

    def _maybe_add_sort_order(self):
        # Add sort_order column to cameras if missing, and initialize with id
        try:
            cur = self.conn.execute("PRAGMA table_info(cameras)")
            cols = [r[1] for r in cur.fetchall()]
            if "sort_order" not in cols:
                self.conn.execute("ALTER TABLE cameras ADD COLUMN sort_order INTEGER")
                # initialize
                self.conn.execute("UPDATE cameras SET sort_order = id WHERE sort_order IS NULL")
                self.conn.commit()
        except Exception:
            pass

    def _maybe_add_global_record_policy(self):
        # Add record_policy_default column to preferences if missing
        try:
            cur = self.conn.execute("PRAGMA table_info(preferences)")
            cols = [r[1] for r in cur.fetchall()]
            if "record_policy_default" not in cols:
                self.conn.execute("ALTER TABLE preferences ADD COLUMN record_policy_default TEXT")
                self.conn.execute("UPDATE preferences SET record_policy_default='manual' WHERE record_policy_default IS NULL")
                self.conn.commit()
        except Exception:
            pass

    def _maybe_add_record_policy(self):
        # Add record_policy column to cameras if missing (manual|always|motion|person)
        try:
            cur = self.conn.execute("PRAGMA table_info(cameras)")
            cols = [r[1] for r in cur.fetchall()]
            if "record_policy" not in cols:
                self.conn.execute("ALTER TABLE cameras ADD COLUMN record_policy TEXT")
                self.conn.execute("UPDATE cameras SET record_policy='manual' WHERE record_policy IS NULL")
                self.conn.commit()
        except Exception:
            pass

    def validate_user(self, username: str, password: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM users WHERE username=? AND password=?", (username, password))
        return cur.fetchone() is not None

    def list_cameras(self) -> List[Tuple[int, str, str, str]]:
        cur = self.conn.execute("SELECT id, name, url, type FROM cameras ORDER BY COALESCE(sort_order, id) ASC, id ASC")
        return list(cur.fetchall())

    def add_camera(self, name: str, url: str, type_: str = "rtsp") -> int:
        # determine next sort_order
        curmax = self.conn.execute("SELECT COALESCE(MAX(sort_order), 0) FROM cameras")
        next_order = (curmax.fetchone()[0] or 0) + 1
        cur = self.conn.execute("INSERT INTO cameras(name, url, type, sort_order) VALUES(?,?,?,?)", (name, url, type_, next_order))
        self.conn.commit()
        return cur.lastrowid

    def remove_camera(self, cam_id: int):
        self.conn.execute("DELETE FROM cameras WHERE id=?", (cam_id,))
        self.conn.commit()

    def update_camera(self, cam_id: int, name: str, url: str, type_: str):
        self.conn.execute("UPDATE cameras SET name=?, url=?, type=? WHERE id=?", (name, url, type_, cam_id))
        self.conn.commit()

    def get_camera_policy(self, cam_id: int) -> str:
        try:
            cur = self.conn.execute("SELECT COALESCE(record_policy, 'manual') FROM cameras WHERE id=?", (cam_id,))
            row = cur.fetchone()
            return row[0] if row and row[0] else 'manual'
        except Exception:
            return 'manual'

    def set_camera_policy(self, cam_id: int, policy: str):
        if policy not in ('manual', 'always', 'motion', 'person'):
            policy = 'manual'
        self.conn.execute("UPDATE cameras SET record_policy=? WHERE id=?", (policy, cam_id))
        self.conn.commit()

    def update_order(self, ordered_ids: List[int]):
        # assign incremental sort_order based on list order
        for idx, cid in enumerate(ordered_ids, start=1):
            self.conn.execute("UPDATE cameras SET sort_order=? WHERE id=?", (idx, cid))
        self.conn.commit()

    def get_preferences(self):
        cur = self.conn.execute("SELECT recording_path, theme, video_codec FROM preferences WHERE id=1")
        return cur.fetchone()

    def update_preferences(self, recording_path: Optional[str], theme: Optional[str], video_codec: Optional[str]):
        rp, th, vc = self.get_preferences()
        rp = recording_path or rp
        th = theme or th
        vc = video_codec or vc
        self.conn.execute(
            "UPDATE preferences SET recording_path=?, theme=?, video_codec=? WHERE id=1",
            (rp, th, vc),
        )
        self.conn.commit()

    # Global recording policy
    def get_global_policy(self) -> str:
        try:
            cur = self.conn.execute("SELECT COALESCE(record_policy_default, 'manual') FROM preferences WHERE id=1")
            row = cur.fetchone()
            return row[0] if row and row[0] else 'manual'
        except Exception:
            return 'manual'

    def set_global_policy(self, policy: str):
        if policy not in ('manual', 'always', 'motion', 'person'):
            policy = 'manual'
        self.conn.execute("UPDATE preferences SET record_policy_default=? WHERE id=1", (policy,))
        self.conn.commit()
