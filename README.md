# CCTV Management System (PySide6)

A modern, threaded CCTV management app with multi-camera support, recording, snapshots, motion detection, and a clean dark UI.

## Quick Start

1. Create venv and install deps

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Run the app

```bash
python -m app.main
```

3. Default login

- Username: `admin`
- Password: `admin`

## Project Structure

- app/
  - main.py (entry)
  - config.py
  - database/
  - camera/
  - ui/
- recordings/
- resources/

## Notes

- Recording path defaults to `recordings/`. Change in Settings.
- This is an MVP scaffold; camera features and motion detection are implemented in dedicated modules.
