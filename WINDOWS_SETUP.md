# CCTV Manager - Windows Setup Guide

This guide helps you build and run the Windows executable.

## 1) Prerequisites (on the build machine)
- Windows 10/11 x64
- Python 3.10 or 3.11 (64-bit)
- Visual C++ Redistributable (most systems have this)

## 2) Create venv and install deps
```
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller
```

## 3) Build the app
You can use the script:
```
scripts\build_windows.bat
```
Or run directly:
```
.venv\Scripts\pyinstaller --noconsole --name CCTVManager ^
  --add-data "config.json;." ^
  --add-data "app/ui;app/ui" ^
  --add-data "app/resources;app/resources" ^
  --hidden-import PySide6.QtCore --hidden-import PySide6.QtGui --hidden-import PySide6.QtWidgets ^
  --hidden-import dotenv --hidden-import cv2 ^
  app\main.py
```
Artifacts will be in `dist\CCTVManager`.

## 4) Prepare for distribution
Copy to the target Windows machine:
- The `CCTVManager` folder from `dist` (contains `CCTVManager.exe`).
- `config.json` (already bundled, but you can replace with your own).
- Create a `.env` in the same folder as the EXE with:
```
SMTP_USERNAME=your_gmail_address
SMTP_PASSWORD=your_app_password
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
GMAIL_SENDER=your_gmail_address
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM=
```
(Leave Twilio blank if unused.)

If you use YOLO person detection:
- Install `ultralytics` and `torch` on the build machine before packaging.
- Place `yolov8n.pt` next to `CCTVManager.exe` after build (or bundle it and update paths in code).

## 5) Running
Double-click `CCTVManager.exe`.
- USB cameras on Windows use the DirectShow backend. If a camera index fails, try unplug/replug.
- Alerts require proper `.env` and `config.json` (admin_email, alert hours, etc.).

## 6) Troubleshooting
- Missing DLLs: install latest Microsoft Visual C++ Redistributable (x64).
- Antivirus false positives: add `CCTVManager` folder to exceptions.
- Black camera preview: try a different index (0,1,2) or ensure the device is not in use by another app.
- Large EXE size: avoid bundling YOLO/torch unless needed.
