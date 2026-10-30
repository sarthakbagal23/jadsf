@echo off
title Stop EDITH
chcp 65001 >nul
echo Stopping all EDITH background processes...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*service.py*' -or $_.CommandLine -like '*server.py*' -or $_.CommandLine -like '*edith.py*' -or $_.CommandLine -like '*voice.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('Stopped process PID ' + $_.ProcessId + ' (' + $_.ProcessName + ')') -ForegroundColor Yellow }"
echo.
echo EDITH is completely stopped.
pause
