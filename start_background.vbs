Set WshShell = CreateObject("WScript.Shell")
strPath = WshShell.CurrentDirectory
WshShell.Run """" & strPath & "\.venv\Scripts\pythonw.exe"" """ & strPath & "\service.py""", 0, False
