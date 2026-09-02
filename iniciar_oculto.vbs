' Sobe o Etiqueta - NS em segundo plano, sem janela.
Dim sh, fso, here, pyw, cands, i
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = here

cands = Array( _
  sh.ExpandEnvironmentStrings("%LOCALAPPDATA%\Python\bin\pythonw.exe"), _
  sh.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"), _
  sh.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"), _
  sh.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"), _
  sh.ExpandEnvironmentStrings("%PROGRAMFILES%\Python313\pythonw.exe"), _
  sh.ExpandEnvironmentStrings("%PROGRAMFILES%\Python312\pythonw.exe"))

pyw = "pythonw.exe"
For i = 0 To UBound(cands)
  If fso.FileExists(cands(i)) Then
    pyw = cands(i)
    Exit For
  End If
Next

sh.Run """" & pyw & """ """ & here & "\server.py""", 0, False
