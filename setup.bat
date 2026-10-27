@echo off
REM JARVIS one-time setup (Windows)
python --version >nul 2>&1 || (echo Install Python 3.12+ from python.org first, tick "Add to PATH". & pause & exit /b 1)
python -m venv .venv
call .venv\Scripts\activate
pip install -r requirements.txt
echo.
echo Next steps:
echo   1. Install Ollama: https://ollama.com/download/windows
echo   2. Run: ollama pull llama3.1:8b
echo   3. Run: run.bat
echo.
echo For voice mode also run: pip install -r requirements-voice.txt
pause
