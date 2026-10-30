import win32com.client
from pathlib import Path

DIR = Path(r"C:\Users\sarth\Downloads\edith")
DESKTOP = Path(r"C:\Users\sarth\Desktop")

sh = win32com.client.Dispatch("WScript.Shell")

# 1. EDITH Text Chat
s1 = sh.CreateShortcut(str(DESKTOP / "EDITH.lnk"))
s1.TargetPath = r"C:\Windows\System32\cmd.exe"
s1.Arguments = f'/k ""{DIR / "start_chat.bat"}""'
s1.WorkingDirectory = str(DIR)
s1.IconLocation = "shell32.dll,25"
s1.Save()

# 2. EDITH Voice Mode
s2 = sh.CreateShortcut(str(DESKTOP / "EDITH Voice Mode.lnk"))
s2.TargetPath = r"C:\Windows\System32\cmd.exe"
s2.Arguments = f'/k ""{DIR / "start_voice.bat"}""'
s2.WorkingDirectory = str(DIR)
s2.IconLocation = "shell32.dll,168"
s2.Save()

# 3. EDITH Controller Menu
s3 = sh.CreateShortcut(str(DESKTOP / "EDITH Menu.lnk"))
s3.TargetPath = r"C:\Windows\System32\cmd.exe"
s3.Arguments = f'/k ""{DIR / "run.bat"}""'
s3.WorkingDirectory = str(DIR)
s3.IconLocation = "shell32.dll,246"
s3.Save()

print("Shortcuts updated to Downloads folder successfully!")
