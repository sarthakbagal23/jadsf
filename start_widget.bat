@echo off
cd /d "%~dp0"
call ".venv\Scripts\activate.bat"
start "" pythonw widget.py
