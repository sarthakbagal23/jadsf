@echo off
title JARVIS Chat
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python chat.py
pause
