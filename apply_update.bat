@echo off
rem  Aplica a atualizacao baixada em _update\ e reinicia o servidor.
rem  Chamado automaticamente pelo botao "Atualizar" da interface.
rem  %1 = PID do servidor    %2 = porta
cd /d "%~dp0"
set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"
set "PID=%~1"
set "PORT=%~2"
if "%PORT%"=="" set "PORT=8765"
set "LOG=%HERE%\update.log"
echo [%date% %time%] inicio pid=%PID% porta=%PORT%> "%LOG%"

rem  espera ~2s (ping funciona sem console, ao contrario do timeout)
ping -n 3 127.0.0.1 >nul

rem  encerra o servidor atual (pelo PID e, por garantia, pela porta)
if not "%PID%"=="" taskkill /F /PID %PID% >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /r /c:":%PORT% .*LISTENING"') do taskkill /F /PID %%a >nul 2>&1
ping -n 3 127.0.0.1 >nul

if not exist "_update\Etiqueta-NS\server.py" (
  echo [%time%] pacote invalido>> "%LOG%"
  goto :relaunch
)

rem  nunca sobrescreve a configuracao local
if exist "_update\Etiqueta-NS\config.json" del /q "_update\Etiqueta-NS\config.json"

rem  robocopy nao pede confirmacao (xcopy trava sem console)
echo [%time%] copiando>> "%LOG%"
robocopy "_update\Etiqueta-NS" "%HERE%" /E /IS /IT /NFL /NDL /NJH /NJS /NP /R:2 /W:1 /XF config.json update.log server.log _run_update.bat >> "%LOG%" 2>&1
echo [%time%] robocopy rc=%errorlevel%>> "%LOG%"

rmdir /S /Q "_update" >nul 2>&1
del /q "_update.zip" >nul 2>&1

:relaunch
echo [%time%] religando>> "%LOG%"
ping -n 2 127.0.0.1 >nul
start "" wscript.exe "%HERE%\iniciar_oculto.vbs"
echo [%time%] fim>> "%LOG%"
