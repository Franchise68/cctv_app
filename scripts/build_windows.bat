@echo off
setlocal

REM Create venv if missing (optional)
IF NOT EXIST .venv (
  py -3 -m venv .venv
)

CALL .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

REM Clean previous builds
IF EXIST build RMDIR /S /Q build
IF EXIST dist RMDIR /S /Q dist

REM Build using the spec
pyinstaller cctv_app.spec

ECHO.
ECHO Build complete. Artifacts in dist\CCTVManager
ECHO Copy your .env and update SMTP credentials on the target machine.
ECHO If using YOLO, place yolov8n.pt next to CCTVManager.exe or in a models folder.
ECHO.
PAUSE
