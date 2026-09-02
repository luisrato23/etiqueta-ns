' Sobe o Etiqueta - NS em segundo plano, sem janela.
' Usado pela inicializacao automatica do Windows (e pode rodar manualmente).
Dim sh, fso, here, pyw
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = here

' pythonw.exe: tenta o shim estavel do gerenciador; senao usa o do PATH
pyw = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%\Python\bin\pythonw.exe")
If Not fso.FileExists(pyw) Then pyw = "pythonw.exe"

sh.Run """" & pyw & """ """ & here & "\server.py""", 0, False
