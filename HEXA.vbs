Option Explicit

Dim shell, fso, root, readyMarker, pythonw, bootstrap, command, exitCode

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

root = fso.GetParentFolderName(WScript.ScriptFullName)
readyMarker = fso.BuildPath(root, ".venv\.hexa-desktop-ready-v4")
pythonw = fso.BuildPath(root, ".venv\Scripts\pythonw.exe")
bootstrap = fso.BuildPath(root, "HEXA.bat")

If (Not fso.FileExists(readyMarker)) Or (Not fso.FileExists(pythonw)) Then
    exitCode = shell.Run(Quote(bootstrap), 1, True)
    WScript.Quit exitCode
End If

shell.CurrentDirectory = root
command = Quote(pythonw) & " -m app.desktop.main"
shell.Run command, 0, False

Function Quote(value)
    Quote = Chr(34) & value & Chr(34)
End Function
