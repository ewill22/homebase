' run-hidden.vbs — Launch a batch file with no visible console window.
' Usage: wscript run-hidden.vbs "C:\path\to\script.bat"

If WScript.Arguments.Count = 0 Then
    WScript.Quit 1
End If

Set WshShell = CreateObject("WScript.Shell")
WshShell.Run chr(34) & WScript.Arguments(0) & chr(34), 0, True
Set WshShell = Nothing
