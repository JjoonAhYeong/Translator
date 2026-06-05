@echo off
cd /d "%~dp0"
python sync-env.py >nul 2>&1
start "" http://127.0.0.1:8765
python -m http.server 8765
