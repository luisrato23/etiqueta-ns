' Sobe o Etiqueta - NS (NS Label) em segundo plano, sem janela.
' Procura o Python de forma robusta e registra o que fez em _boot.log
' para diagnostico caso nao suba.
Option Explicit
Dim sh, fso, here, pyw, logf, i, cand, pats, folder, f

Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = here
logf = here & "\_boot.log"

Sub Note(msg)
  Dim t
  On Error Resume Next
  Set t = fso.OpenTextFile(logf, 2, True)   ' 2 = sobrescreve (so a ultima execucao)
  t.WriteLine Now & "  " & msg
  t.Close
  On Error Goto 0
End Sub

' 1) caminhos fixos mais provaveis (o real .exe, nao os "shim")
Dim fixed
fixed = Array( _
  sh.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe"), _
  sh.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"), _
  sh.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"), _
  sh.ExpandEnvironmentStrings("%PROGRAMFILES%\Python314\pythonw.exe"), _
  sh.ExpandEnvironmentStrings("%PROGRAMFILES%\Python313\pythonw.exe"), _
  sh.ExpandEnvironmentStrings("%PROGRAMFILES%\Python312\pythonw.exe") )

pyw = ""
For i = 0 To UBound(fixed)
  If fso.FileExists(fixed(i)) Then pyw = fixed(i) : Exit For
Next

' 2) Python Install Manager (py 3.14+): %LOCALAPPDATA%\Python\pythoncore-*-64\pythonw.exe
If pyw = "" Then
  folder = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%\Python")
  If fso.FolderExists(folder) Then
    Dim sub1
    For Each sub1 In fso.GetFolder(folder).SubFolders
      If LCase(Left(sub1.Name, 10)) = "pythoncore" Then
        cand = sub1.Path & "\pythonw.exe"
        If fso.FileExists(cand) Then pyw = cand : Exit For
      End If
    Next
  End If
End If

' 3) shim do Install Manager (funciona, mas menos confiavel no boot)
If pyw = "" Then
  cand = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%\Python\bin\pythonw.exe")
  If fso.FileExists(cand) Then pyw = cand
End If

' 4) ultimo recurso: pythonw no PATH (evita o stub da Microsoft Store)
If pyw = "" Then
  On Error Resume Next
  cand = sh.RegRead("HKLM\SOFTWARE\Python\PythonCore\3.14\InstallPath\ExecutablePath")
  On Error Goto 0
  If cand <> "" And fso.FileExists(fso.GetParentFolderName(cand) & "\pythonw.exe") Then
    pyw = fso.GetParentFolderName(cand) & "\pythonw.exe"
  End If
End If
If pyw = "" Then pyw = "pythonw.exe"

Note "usando: " & pyw
sh.Run """" & pyw & """ """ & here & "\server.py""", 0, False
