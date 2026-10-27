@echo off
title JARVIS Controller
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: .venv not found.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"

if "%1"=="" goto menu
python jarvis.py %*
goto end

:menu
cls
echo ========================================================
echo                   J.A.R.V.I.S. CONTROLLER               
echo ========================================================
echo.
echo   [1] Full Voice Mode        (Say "Hey Jarvis" in terminal)
echo   [2] Push-to-Talk           (Press Enter, speak, talks back)
echo   [3] Text Mode              (Type prompts, talks back)
echo   [4] Launch Web Server      (Dark phone/browser UI on port 8765)
echo   [5] Start Background Mode  (Runs Web + Voice silently in background)
echo   [6] Enable Auto-Start      (Start JARVIS on Windows Boot)
echo   [7] Disable Auto-Start     (Remove from Windows Boot)
echo   [8] Stop Background JARVIS (Shut down running background service)
echo   [9] Exit
echo.
set /p opt="Select mode (1-9): "

if "%opt%"=="1" (
    cls
    echo Starting Full Voice Mode with openWakeWord...
    python jarvis.py --voice
    goto end
)
if "%opt%"=="2" (
    cls
    echo Starting Push-to-Talk Mode...
    python jarvis.py --talk
    goto end
)
if "%opt%"=="3" (
    cls
    echo Starting Text Mode...
    python jarvis.py
    goto end
)
if "%opt%"=="4" (
    cls
    echo Starting Web Server...
    start http://localhost:8765
    python server.py
    goto end
)
if "%opt%"=="5" (
    cls
    echo Starting JARVIS silently in the background...
    wscript.exe "start_background.vbs"
    echo JARVIS is now running 24/7!
    echo - Voice wake word: "Hey Jarvis" is listening.
    echo - Web chat UI: http://localhost:8765
    goto end
)
if "%opt%"=="6" (
    cls
    echo Enabling auto-start on Windows boot...
    powershell -Command "$s = (New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup') + '\JARVIS_AutoStart.lnk'); $s.TargetPath = 'wscript.exe'; $s.Arguments = '\"%~dp0start_background.vbs\"'; $s.WorkingDirectory = '%~dp0'; $s.Save()"
    echo.
    echo SUCCESS: JARVIS will now automatically boot with Windows!
    goto end
)
if "%opt%"=="7" (
    cls
    echo Removing JARVIS from Windows boot...
    powershell -Command "Remove-Item \"$([Environment]::GetFolderPath('Startup'))\JARVIS_AutoStart.lnk\" -ErrorAction SilentlyContinue"
    echo Done.
    goto end
)
if "%opt%"=="8" (
    cls
    call stop_jarvis.bat
    goto end
)
if "%opt%"=="9" exit

:end
echo.
pause
