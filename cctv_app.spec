# -*- mode: python ; coding: utf-8 -*-

import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# App metadata
app_name = 'CCTVManager'
entry_script = 'app/main.py'

# Hidden imports to ensure PySide6/OpenCV glue is bundled
hidden = [
    'cv2',
    'dotenv',
    'PySide6',
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
]

# Optional: if you use ultralytics/torch, uncomment the following lines.
# hidden += collect_submodules('ultralytics')
# hidden += collect_submodules('torch')

# Data files (Windows path separator in runtime; spec uses host separators)
# dest is relative to the dist/<app_name> folder.
datas = []

# Always include base config.json so app starts with defaults
if os.path.exists('config.json'):
    datas.append(('config.json', '.'))

# Bundle UI resources (icons/images) if present
if os.path.isdir('app/ui'):
    datas.append(('app/ui', 'app/ui'))
if os.path.isdir('app/resources'):
    datas.append(('app/resources', 'app/resources'))

# If you keep the YOLO model next to the executable, you can skip bundling it.
# Otherwise, to bundle a small model file, uncomment and adjust:
# if os.path.exists('yolov8n.pt'):
#     datas.append(('yolov8n.pt', '.'))

block_cipher = None


a = Analysis(
    [entry_script],
    pathex=[os.getcwd()],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # set True if you want a console window for logs
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=app_name,
)
