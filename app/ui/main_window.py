from PySide6.QtWidgets import QMainWindow, QWidget, QGridLayout, QLabel, QToolBar, QFileDialog, QMessageBox, QScrollArea, QComboBox, QSplitter, QVBoxLayout, QToolButton, QLineEdit, QStyle, QListWidget, QListWidgetItem
from PySide6.QtGui import QAction, QIcon, QPainter, QBrush, QColor, QPixmap
from PySide6.QtCore import Qt, QSettings, QTimer
import math
import cv2

from ..config import AppConfig
from ..alert_system import AlertSystem
from ..database.db import Database
from .add_camera_dialog import AddCameraDialog
from .settings_dialog import SettingsDialog
from .about_dialog import AboutDialog
from .recording_manager import RecordingManagerDialog


class MainWindow(QMainWindow):
    def __init__(self, cfg: AppConfig, db: Database):
        super().__init__()
        self.cfg = cfg
        self.db = db
        self.setWindowTitle("CCTV Manager")
        self.resize(1200, 800)
        self._autostart_ids = set()
        self._start_after_add_id = None
        self._fixed_cols = 0  # 0 = Auto
        self._broadcast_on = False
        self._prev_sidebar_open = None
        self._selected_camera_id = None
        self._active_icon = None

        # Alerts system
        try:
            self.alerts = AlertSystem(self.cfg.recordings_dir, str(self.cfg.db_path))
            self.alerts.status.connect(lambda s: self.statusBar().showMessage(s, 3000))
            self.alerts.start()
        except Exception:
            self.alerts = None

        self._build_toolbar()
        self._build_central()
        self.statusBar().showMessage("Ready")

        self.refresh_grid()

    def _build_toolbar(self):
        tb = QToolBar("Main")
        self.addToolBar(tb)

        act_add = QAction("Add Camera", self)
        act_add.triggered.connect(self.add_camera)
        tb.addAction(act_add)

        act_refresh = QAction("Refresh", self)
        act_refresh.triggered.connect(self.refresh_grid)
        tb.addAction(act_refresh)

        act_scan = QAction("Scan USB", self)
        act_scan.setToolTip("Scan local USB cameras and add them")
        act_scan.triggered.connect(self.scan_usb_cameras)
        tb.addAction(act_scan)

        tb.addSeparator()
        act_start_all = QAction("Start All", self)
        act_start_all.triggered.connect(self.start_all)
        tb.addAction(act_start_all)

        act_stop_all = QAction("Stop All", self)
        act_stop_all.triggered.connect(self.stop_all)
        tb.addAction(act_stop_all)

        act_snap_all = QAction("Snapshot All", self)
        act_snap_all.triggered.connect(self.snapshot_all)
        tb.addAction(act_snap_all)

        # Fixed columns selector
        tb.addSeparator()
        self.cols_combo = QComboBox()
        self.cols_combo.addItems(["Auto", "2", "3", "4"]) 
        self.cols_combo.currentIndexChanged.connect(self._on_cols_changed)
        tb.addWidget(QLabel("Columns:"))
        tb.addWidget(self.cols_combo)

        # Search/filter
        tb.addSeparator()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search cameras...")
        self.search_edit.textChanged.connect(self.refresh_grid)
        tb.addWidget(self.search_edit)

        # Sidebar toggle
        self.act_sidebar = QAction("Sidebar", self)
        self.act_sidebar.setCheckable(True)
        self.act_sidebar.setShortcut("Ctrl+B")
        self.act_sidebar.triggered.connect(self.toggle_sidebar)
        tb.addAction(self.act_sidebar)

        # Settings accessible via sidebar only (single entry)

        act_recs = QAction("Recordings", self)
        act_recs.triggered.connect(self.open_recordings)
        tb.addAction(act_recs)

        act_about = QAction("About", self)
        act_about.triggered.connect(self.open_about)
        tb.addAction(act_about)

        self.act_broadcast = QAction("Broadcast Mode", self)
        self.act_broadcast.setCheckable(True)
        self.act_broadcast.triggered.connect(self.toggle_broadcast)
        tb.addAction(self.act_broadcast)

    def _build_central(self):
        # Left sidebar
        self.sidebar = QWidget()
        s_lay = QVBoxLayout(self.sidebar)
        s_lay.setContentsMargins(8, 8, 8, 8)
        s_lay.setSpacing(6)
        # Sidebar buttons with icons
        def mk_btn(text, icon):
            b = QToolButton()
            b.setText(text)
            b.setIcon(self.style().standardIcon(icon))
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setAutoRaise(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(28)
            return b

        self.btn_dash = mk_btn("Dashboard", QStyle.SP_ComputerIcon)
        self.btn_cams = mk_btn("Cameras", QStyle.SP_DirHomeIcon)
        self.btn_settings = mk_btn("Settings", QStyle.SP_FileDialogDetailedView)
        # Override with a custom drawn gear icon for clarity
        try:
            self.btn_settings.setIcon(self._make_gear_icon())
        except Exception:
            pass
        self.btn_alerts = mk_btn("Alerts", QStyle.SP_MessageBoxWarning)
        for btn in [self.btn_dash, self.btn_cams, self.btn_settings, self.btn_alerts]:
            s_lay.addWidget(btn)
        # Cameras list shown when Cameras is selected
        self.cam_list = QListWidget()
        self.cam_list.setVisible(False)
        s_lay.addWidget(self.cam_list)
        s_lay.addStretch(1)

        # Main scroll area with grid
        container = QWidget()
        self.grid = QGridLayout(container)
        self.grid.setSpacing(6)
        self.grid.setContentsMargins(8, 8, 8, 8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        # Hide scrollbars; we will auto-fit tiles to viewport
        try:
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        except Exception:
            pass
        # Keep a reference for sizing
        self.scroll = scroll

        self.splitter = QSplitter()
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(scroll)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.setCentralWidget(self.splitter)

        # Re-fit grid when splitter is moved (sidebar show/hide or resize)
        try:
            self.splitter.splitterMoved.connect(lambda _pos, _idx: self._fit_grid_to_viewport())
        except Exception:
            pass

        # Restore sidebar state
        self.settings = QSettings("cctv_app", "cctv_manager")
        sidebar_open = self.settings.value("ui/sidebar_open", True, bool)
        self.sidebar.setVisible(bool(sidebar_open))
        if hasattr(self, 'act_sidebar'):
            self.act_sidebar.setChecked(bool(sidebar_open))
        # Restore splitter sizes and sidebar width
        try:
            w = int(self.settings.value("ui/sidebar_width", 180))
        except Exception:
            w = 180
        total = max(600, self.width())
        self.splitter.setSizes([w if sidebar_open else 0, total - (w if sidebar_open else 0)])
        self._apply_sidebar_compact_mode()

        # Sidebar actions
        self.btn_dash.clicked.connect(self.on_nav_dashboard)
        self.btn_cams.clicked.connect(self.on_nav_cameras)
        self.btn_settings.clicked.connect(self.open_settings)
        self.btn_alerts.clicked.connect(self.on_nav_alerts)
        self.cam_list.itemDoubleClicked.connect(self.on_camera_list_activated)
        try:
            self.cam_list.currentItemChanged.connect(self.on_camera_list_changed)
        except Exception:
            pass

        # Initial fit after UI build
        QTimer.singleShot(0, self._fit_grid_to_viewport)

    def _make_gear_icon(self, size: int = 18) -> QIcon:
        px = QPixmap(size, size)
        px.fill(Qt.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.Antialiasing, True)
        center = size / 2.0
        r_outer = size * 0.42
        r_inner = size * 0.24
        teeth = 6
        p.setBrush(QBrush(QColor(70, 70, 70)))
        p.setPen(Qt.NoPen)
        for i in range(teeth):
            angle = (i * (360.0 / teeth)) * 3.14159 / 180.0
            x = center + (r_outer * 0.9) * float(math.cos(angle))
            y = center + (r_outer * 0.9) * float(math.sin(angle))
            w = size * 0.16
            h = size * 0.26
            p.save()
            p.translate(x, y)
            p.rotate(i * (360.0 / teeth))
            p.drawRoundedRect(-w/2, -h/2, w, h, 2, 2)
            p.restore()
        p.setBrush(QBrush(QColor(100, 100, 100)))
        p.drawEllipse(int(center - r_outer), int(center - r_outer), int(r_outer*2), int(r_outer*2))
        p.setBrush(QBrush(QColor(200, 200, 200)))
        p.drawEllipse(int(center - r_inner), int(center - r_inner), int(r_inner*2), int(r_inner*2))
        p.end()
        return QIcon(px)

    def refresh_grid(self):
        # collect which cameras are currently running
        prev_running = set()
        for i in range(self.grid.count()):
            item = self.grid.itemAt(i)
            if not item:
                continue
            w = item.widget()
            if w and hasattr(w, "worker") and getattr(w.worker, "isRunning", lambda: False)():
                prev_running.add(getattr(w, "camera_id", -1))
        # clear grid safely
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w and hasattr(w, "stop"):
                try:
                    w.stop()
                except Exception:
                    pass
            if w:
                w.setParent(None)

        cams = self.db.list_cameras()
        # Apply filter
        q = (self.search_edit.text().strip().lower() if hasattr(self, 'search_edit') and self.search_edit else "")
        if q:
            def match(row):
                cid, name, url, type_ = row
                return q in (name or '').lower() or q in (url or '').lower() or q in (type_ or '').lower()
            cams = [row for row in cams if match(row)]
        if not cams:
            self.grid.addWidget(QLabel("No cameras. Use 'Add Camera' to create one."), 0, 0)
            return

        from .ui_components.camera_tile import CameraTile
        # Determine columns based on viewport to avoid scrolling
        if self._fixed_cols and self._fixed_cols > 0:
            cols = self._fixed_cols
        else:
            cols = self._suggest_cols(len(cams))
        for idx, (cid, name, url, type_) in enumerate(cams):
            tile = CameraTile(cid, name, url, type_, self.cfg, self.db)
            # hand over alerts reference for motion notifications
            if hasattr(self, 'alerts') and self.alerts is not None:
                try:
                    tile.alerts = self.alerts
                except Exception:
                    pass
            # apply broadcast UI state to new tiles
            try:
                if hasattr(tile, 'set_broadcast'):
                    tile.set_broadcast(bool(self._broadcast_on))
            except Exception:
                pass
            try:
                if hasattr(tile, 'selected'):
                    tile.selected.connect(self.on_tile_selected)
            except Exception:
                pass
            tile.deleted.connect(self.on_tile_deleted)
            # DnD reorder signal
            if hasattr(tile, 'reorder_request'):
                tile.reorder_request.connect(self.on_reorder_request)
            r, c = divmod(idx, cols)
            self.grid.addWidget(tile, r, c)
            # auto-start if it was previously running or is the newly added one
            if cid in prev_running or (self._start_after_add_id is not None and cid == self._start_after_add_id):
                tile.start()
            try:
                if self._selected_camera_id is not None and hasattr(tile, 'set_selected'):
                    tile.set_selected(tile.camera_id == int(self._selected_camera_id))
            except Exception:
                pass
        # Fit sizes once tiles are placed
        self._fit_grid_to_viewport()
        # reset the one-time autostart id after refresh
        self._start_after_add_id = None
        try:
            self._update_sidebar_active_indicator()
        except Exception:
            pass

    def _suggest_cols(self, n: int) -> int:
        if n <= 0:
            return 1
        try:
            vp = getattr(self, 'scroll', None).viewport() if hasattr(self, 'scroll') else None
            if vp is None:
                return max(1, int(math.ceil(math.sqrt(n))))
            W = max(1, vp.width())
            H = max(1, vp.height())
            # grid margins/spacings
            margins = 8 * 2
            spacing = self.grid.spacing() if hasattr(self, 'grid') else 6
            best_c = 1
            best_w = 0.0
            for c in range(1, n + 1):
                rows = int(math.ceil(n / float(c)))
                tile_w = (W - (c - 1) * spacing - margins) / float(c)
                tile_h = tile_w * 9.0 / 16.0
                total_h = rows * tile_h + (rows - 1) * spacing + margins
                if tile_w > 0 and total_h <= H and tile_w > best_w:
                    best_w, best_c = tile_w, c
            if best_c >= 1:
                return best_c
            # Fallback if none fit height: choose c that yields widest tiles, we'll downscale in _fit
            best_w = -1.0
            for c in range(1, n + 1):
                tile_w = (W - (c - 1) * spacing - margins) / float(c)
                if tile_w > best_w:
                    best_w, best_c = tile_w, c
            return max(1, best_c)
        except Exception:
            return max(1, int(math.ceil(math.sqrt(n))))

    def _fit_grid_to_viewport(self):
        try:
            if not hasattr(self, 'scroll') or self.scroll is None:
                return
            vp = self.scroll.viewport()
            W = max(1, vp.width())
            H = max(1, vp.height())
            n = sum(1 for i in range(self.grid.count()) if self.grid.itemAt(i) and self.grid.itemAt(i).widget())
            if n == 0:
                return
            spacing = self.grid.spacing()
            margins = 8 * 2
            cols = self._fixed_cols if (self._fixed_cols and self._fixed_cols > 0) else self._suggest_cols(n)
            rows = int(math.ceil(n / float(cols)))
            # base tile width/height by 16:9, adjust to fill height if needed
            tile_w = (W - (cols - 1) * spacing - margins) / float(cols)
            tile_h = tile_w * 9.0 / 16.0
            total_h = rows * tile_h + (rows - 1) * spacing + margins
            if total_h > H and total_h > 0:
                scale = (H - margins - (rows - 1) * spacing) / (rows * tile_h)
                scale = max(0.2, min(1.0, scale))
                tile_w *= scale
                tile_h *= scale
            # Reflow widgets into the computed column count and set sizes
            tiles = [self.grid.itemAt(i).widget() for i in range(self.grid.count()) if self.grid.itemAt(i).widget()]
            for idx, w in enumerate(tiles):
                r, c = divmod(idx, cols)
                try:
                    self.grid.addWidget(w, r, c)
                except Exception:
                    pass
                try:
                    w.setFixedWidth(int(tile_w))
                    # ensure the video area respects 16:9; label holds the frame
                    if hasattr(w, 'label'):
                        w.label.setFixedHeight(int(tile_h))
                    # include small layout margins inside the tile
                    w.setFixedHeight(int(tile_h) + 12)
                except Exception:
                    pass
        except Exception:
            pass

    def resizeEvent(self, event):
        try:
            self._fit_grid_to_viewport()
        except Exception:
            pass
        return super().resizeEvent(event)

    def toggle_broadcast(self, checked: bool):
        self._broadcast_on = bool(checked)
        try:
            if self._broadcast_on:
                self._prev_sidebar_open = bool(self.sidebar.isVisible())
                if self._prev_sidebar_open:
                    self.toggle_sidebar(False)
            else:
                if self._prev_sidebar_open is not None:
                    self.toggle_sidebar(bool(self._prev_sidebar_open))
        except Exception:
            pass
        try:
            for i in range(self.grid.count()):
                item = self.grid.itemAt(i)
                w = item.widget() if item else None
                if w and hasattr(w, 'set_broadcast'):
                    w.set_broadcast(self._broadcast_on)
        except Exception:
            pass
        try:
            self._fit_grid_to_viewport()
        except Exception:
            pass

    def on_tile_deleted(self, cam_id: int):
        self.statusBar().showMessage(f"Camera deleted: {cam_id}", 3000)
        self.refresh_grid()

    def add_camera(self):
        dlg = AddCameraDialog(self)
        if dlg.exec():
            name, url, type_ = dlg.get_values()
            if name and url:
                new_id = self.db.add_camera(name, url, type_)
                self._start_after_add_id = new_id
                self.statusBar().showMessage(f"Camera added: {name}", 3000)
                self.refresh_grid()

    def _apply_sidebar_compact_mode(self):
        # Switch to icon-only when narrow or hidden
        try:
            width = self.sidebar.width() if self.sidebar.isVisible() else 0
            icon_only = (width < 100)
            style = Qt.ToolButtonIconOnly if icon_only else Qt.ToolButtonTextBesideIcon
            for b in [self.btn_dash, self.btn_cams, self.btn_settings, self.btn_alerts]:
                b.setToolButtonStyle(style)
        except Exception:
            pass

    def open_settings(self):
        dlg = SettingsDialog(self.cfg, self.db, self, alerts=getattr(self, 'alerts', None))
        dlg.exec()
        self.refresh_grid()

    def open_about(self):
        AboutDialog(self).exec()

    def open_recordings(self):
        dlg = RecordingManagerDialog(self.cfg.recordings_dir, self)
        dlg.exec()

    def _iter_tiles(self):
        for i in range(self.grid.count()):
            item = self.grid.itemAt(i)
            w = item.widget()
            if w and hasattr(w, "start"):
                yield w

    def start_all(self):
        for tile in self._iter_tiles():
            try:
                tile.start()
            except Exception:
                pass

    def stop_all(self):
        for tile in self._iter_tiles():
            try:
                tile.stop()
            except Exception:
                pass

    def snapshot_all(self):
        for tile in self._iter_tiles():
            try:
                tile.snapshot()
            except Exception:
                pass

    def scan_usb_cameras(self):
        # Probe indices 0..10 and add as USB cameras if not present
        try:
            existing = {(str(url), (type_ or '').lower()) for (_, _, url, type_) in self.db.list_cameras()}
        except Exception:
            existing = set()
        found = []
        added = 0
        for idx in range(0, 11):
            cap = None
            try:
                cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
                if not cap or not cap.isOpened():
                    if cap:
                        cap.release()
                    cap = cv2.VideoCapture(idx)
                ok = bool(cap and cap.isOpened())
            except Exception:
                ok = False
            try:
                if cap:
                    cap.release()
            except Exception:
                pass
            if ok:
                found.append(idx)
                key = (str(idx), 'usb')
                if key not in existing:
                    try:
                        name = f"USB Camera {idx}"
                        self.db.add_camera(name, str(idx), 'usb')
                        existing.add(key)
                        added += 1
                    except Exception:
                        pass
        msg = "No USB cameras found" if not found else f"Found: {found}. Added {added} new camera(s)."
        try:
            QMessageBox.information(self, "USB Scan", msg)
        except Exception:
            pass
        self.refresh_grid()

    def _on_cols_changed(self):
        txt = self.cols_combo.currentText()
        if txt == "Auto":
            self._fixed_cols = 0
        else:
            try:
                self._fixed_cols = int(txt)
            except Exception:
                self._fixed_cols = 0
        self.refresh_grid()

    def toggle_sidebar(self, checked: bool):
        self.sidebar.setVisible(bool(checked))
        try:
            self.settings.setValue("ui/sidebar_open", bool(checked))
        except Exception:
            pass
        if hasattr(self, 'act_sidebar') and self.act_sidebar.isChecked() != bool(checked):
            self.act_sidebar.setChecked(bool(checked))
        # Update splitter sizes and compact mode
        sizes = self.splitter.sizes()
        if checked:
            # restore last width or default
            try:
                w = int(self.settings.value("ui/sidebar_width", 180))
            except Exception:
                w = 180
            self.splitter.setSizes([w, max(200, sum(sizes) - w)])
        else:
            # save current width, then collapse
            self.settings.setValue("ui/sidebar_width", sizes[0] if sizes and sizes[0] > 0 else 180)
            self.splitter.setSizes([0, max(200, sum(sizes))])
        self._apply_sidebar_compact_mode()
        # Re-fit grid after sidebar toggle
        try:
            self._fit_grid_to_viewport()
        except Exception:
            pass

    def on_reorder_request(self, source_id: int, target_id: int):
        # Build current ordered list
        ids = [self.grid.itemAt(i).widget().camera_id for i in range(self.grid.count()) if hasattr(self.grid.itemAt(i).widget(), 'camera_id')]
        if source_id in ids and target_id in ids and source_id != target_id:
            s_idx = ids.index(source_id)
            t_idx = ids.index(target_id)
            ids.insert(t_idx, ids.pop(s_idx))
            try:
                self.db.update_order(ids)
            except Exception:
                pass
            self.refresh_grid()

    # Sidebar navigation handlers
    def on_nav_dashboard(self):
        # For now, dashboard shows all cameras and clears search
        if hasattr(self, 'search_edit'):
            self.search_edit.setText("")
        # Hide camera list on dashboard
        try:
            self.cam_list.setVisible(False)
        except Exception:
            pass
        self.refresh_grid()

    def on_nav_cameras(self):
        # Show cameras in sidebar for quick selection/edit
        try:
            self.populate_camera_list()
            self.cam_list.setVisible(True)
        except Exception:
            pass
        if hasattr(self, 'search_edit'):
            self.search_edit.setText("")
        self.refresh_grid()

    def populate_camera_list(self):
        self.cam_list.clear()
        try:
            cams = self.db.list_cameras()
            for cid, name, url, type_ in cams:
                txt = f"{name}"
                item = QListWidgetItem(txt)
                item.setData(Qt.UserRole, cid)
                self.cam_list.addItem(item)
        except Exception:
            pass
        try:
            self._update_sidebar_active_indicator()
        except Exception:
            pass

    def on_camera_list_activated(self, item: QListWidgetItem):
        try:
            cid = item.data(Qt.UserRole)
            # find camera details
            cams = self.db.list_cameras()
            rec = next((r for r in cams if r[0] == cid), None)
            if not rec:
                return
            _, name, url, type_ = rec
            from .edit_camera_dialog import EditCameraDialog
            # current policy
            try:
                pol = self.db.get_camera_policy(cid)
            except Exception:
                pol = 'manual'
            dlg = EditCameraDialog(name, url, type_, self, policy=pol)
            if dlg.exec():
                new_name, new_url, new_type, new_policy = dlg.get_values()
                # Save updates
                try:
                    if (new_name, new_url, new_type) != (name, url, type_):
                        self.db.update_camera(cid, new_name, new_url, new_type)
                    if hasattr(self.db, 'set_camera_policy'):
                        self.db.set_camera_policy(cid, new_policy)
                except Exception:
                    pass
                # Reflect changes
                self.populate_camera_list()
                self.refresh_grid()
        except Exception:
            pass

    def on_camera_list_changed(self, cur: QListWidgetItem, prev: QListWidgetItem | None):
        try:
            if not cur:
                return
            cid = cur.data(Qt.UserRole)
            self._selected_camera_id = int(cid)
            # update tiles selection
            for i in range(self.grid.count()):
                it = self.grid.itemAt(i)
                w = it.widget() if it else None
                try:
                    if w and hasattr(w, 'set_selected'):
                        w.set_selected(getattr(w, 'camera_id', -1) == self._selected_camera_id)
                except Exception:
                    pass
            self._update_sidebar_active_indicator()
        except Exception:
            pass

    def on_tile_selected(self, cam_id: int):
        try:
            self._selected_camera_id = int(cam_id)
            # mark tiles
            for i in range(self.grid.count()):
                it = self.grid.itemAt(i)
                w = it.widget() if it else None
                try:
                    if w and hasattr(w, 'set_selected'):
                        w.set_selected(getattr(w, 'camera_id', -1) == self._selected_camera_id)
                except Exception:
                    pass
            # reflect in sidebar list
            self._update_sidebar_active_indicator()
            try:
                # also select corresponding item in the sidebar list
                for i in range(self.cam_list.count()):
                    it = self.cam_list.item(i)
                    if int(it.data(Qt.UserRole)) == self._selected_camera_id:
                        self.cam_list.setCurrentItem(it)
                        break
            except Exception:
                pass
        except Exception:
            pass

    def _make_active_icon(self, size: int = 10) -> QIcon:
        try:
            px = QPixmap(size, size)
            px.fill(Qt.transparent)
            p = QPainter(px)
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setBrush(QBrush(QColor(42, 163, 255)))
            p.setPen(Qt.NoPen)
            r = int(size * 0.8)
            off = (size - r) // 2
            p.drawEllipse(off, off, r, r)
            p.end()
            return QIcon(px)
        except Exception:
            return QIcon()

    def _update_sidebar_active_indicator(self):
        try:
            if self._active_icon is None:
                self._active_icon = self._make_active_icon(10)
            for i in range(self.cam_list.count()):
                it = self.cam_list.item(i)
                cid = it.data(Qt.UserRole)
                if self._selected_camera_id is not None and int(cid) == int(self._selected_camera_id):
                    it.setIcon(self._active_icon)
                else:
                    it.setIcon(QIcon())
        except Exception:
            pass

    def on_nav_alerts(self):
        try:
            from ..alert_system import AlertsPanel
            dlg = AlertsPanel(str(self.cfg.db_path), self)
            dlg.setWindowTitle("Recent Alerts")
            dlg.resize(720, 420)
            dlg.show()
        except Exception:
            QMessageBox.information(self, "Alerts", "Alerts center coming soon (motion/person events).")

    # Logs and AI removed from sidebar per request

    def closeEvent(self, event):
        try:
            # Stop all camera tiles
            for tile in self._iter_tiles():
                try:
                    tile.stop()
                except Exception:
                    pass
        except Exception:
            pass
        # Stop alerts system
        try:
            if hasattr(self, 'alerts') and self.alerts is not None:
                self.alerts.stop()
        except Exception:
            pass
        return super().closeEvent(event)
