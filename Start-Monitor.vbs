Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "pythonw monitor.py", 0, False
Set WshShell = Nothing
