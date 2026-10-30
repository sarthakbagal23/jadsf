@echo off
title EDITH Voice
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
call .venv\Scripts\activate.bat
"%~dp0.venv\Scripts\python.exe" edith.py --voice
pause
