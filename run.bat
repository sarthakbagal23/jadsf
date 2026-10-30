@echo off
title EDITH Controller
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: .venv not found.
    pause
    exit /b 1
)

if "%1"=="" goto menu
"%~dp0.venv\Scripts\python.exe" edith.py %*
goto end

:menu
cls
echo ========================================================
echo                   E.D.I.T.H. CONTROLLER
echo ========================================================
echo.
echo   [1] Full Voice Mode        (Say "Hey EDITH" in terminal)
echo   [2] Push-to-Talk           (Press Enter, speak, talks back)
echo   [3] Text Mode              (Type prompts, talks back)
echo   [4] Launch Web Server      (Dark phone/browser UI on port 8765)
echo   [5] Start Background Mode  (Runs Web + Voice silently in background)
echo   [6] Enable Auto-Start      (Start EDITH on Windows Boot)
echo   [7] Disable Auto-Start     (Remove from Windows Boot)
echo   [8] Stop Background EDITH (Shut down running background service)
echo   [9] Exit
echo.
set /p opt="Select mode (1-9): "

if "%opt%"=="1" (
    cls
    echo Starting Full Voice Mode with openWakeWord...
    "%~dp0.venv\Scripts\python.exe" edith.py --voice
    goto end
)
if "%opt%"=="2" (
    cls
    echo Starting Push-to-Talk Mode...
    "%~dp0.venv\Scripts\python.exe" edith.py --talk
    goto end
)
if "%opt%"=="3" (
    cls
    echo Starting Text Mode...
    "%~dp0.venv\Scripts\python.exe" chat.py
    goto end
)
if "%opt%"=="4" (
    cls
    echo Starting Web Server...
    start http://localhost:8765
    "%~dp0.venv\Scripts\python.exe" server.py
    goto end
)
if "%opt%"=="5" (
    cls
    echo Starting EDITH silently in the background...
    wscript.exe "start_background.vbs"
    echo EDITH is now running in the background!
    echo - Voice wake word: "Hey EDITH" is listening.
    echo - Web chat UI: http://localhost:8765
    goto end
)
if "%opt%"=="6" (
    cls
    echo Enabling auto-start on Windows boot...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts_autostart.ps1" enable
    goto end
)
if "%opt%"=="7" (
    cls
    echo Removing EDITH from Windows boot...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts_autostart.ps1" disable
    goto end
)
if "%opt%"=="8" (
    cls
    call "%~dp0stop_edith.bat"
    goto end
)
if "%opt%"=="9" exit

:end
echo.
pause
