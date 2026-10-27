@echo off
title Stop JARVIS
echo Stopping all JARVIS background processes...
powershell -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*service.py*' -or $_.CommandLine -like '*server.py*' -or $_.CommandLine -like '*jarvis.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; echo \"Stopped PID $($_.ProcessId)\" }"
echo.
echo JARVIS stopped.
pause
