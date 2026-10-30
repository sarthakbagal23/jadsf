@echo off
title EDITH Chat
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
call .venv\Scripts\activate.bat
"%~dp0.venv\Scripts\python.exe" chat.py
pause
