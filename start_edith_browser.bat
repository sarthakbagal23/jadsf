@echo off
setlocal
set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" (
  echo Google Chrome was not found.
  pause
  exit /b 1
)
set "PROFILE=%~dp0data\edith_chrome_profile"
if not exist "%PROFILE%" mkdir "%PROFILE%"
start "EDITH Browser" "%CHROME%" --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --user-data-dir="%PROFILE%" --no-first-run "https://launchpad.classlink.com/forsyth"
