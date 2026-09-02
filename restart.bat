@echo off
rem  Encerra o servidor e liga de novo. Usado pela atualizacao in-app.
rem  %1 = PID do servidor    %2 = porta
cd /d "%~dp0"
set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"
set "PID=%~1"
set "PORT=%~2"
if "%PORT%"=="" set "PORT=8765"
echo [%date% %time%] restart pid=%PID% porta=%PORT%> "%HERE%\update.log"

ping -n 3 127.0.0.1 >nul
if not "%PID%"=="" taskkill /F /PID %PID% >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /r /c:":%PORT% .*LISTENING"') do taskkill /F /PID %%a >nul 2>&1
ping -n 3 127.0.0.1 >nul

echo [%time%] religando>> "%HERE%\update.log"
start "" wscript.exe "%HERE%\iniciar_oculto.vbs"
echo [%time%] fim>> "%HERE%\update.log"
