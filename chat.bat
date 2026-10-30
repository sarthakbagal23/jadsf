@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "C:\Users\sarth\.gemini\antigravity\scratch\edith"
call .venv\Scripts\activate.bat
python chat.py
