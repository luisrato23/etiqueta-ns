@echo off
rem  Encerra o servidor, religa e reverte se a nova versao nao subir.
rem  %1 = PID do servidor    %2 = porta
cd /d "%~dp0"
set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"
set "PID=%~1"
set "PORT=%~2"
if "%PORT%"=="" set "PORT=8765"
set "LOG=%HERE%\update.log"
echo [%date% %time%] restart pid=%PID% porta=%PORT%> "%LOG%"

ping -n 3 127.0.0.1 >nul
if not "%PID%"=="" taskkill /F /PID %PID% >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /r /c:":%PORT% .*LISTENING"') do taskkill /F /PID %%a >nul 2>&1
ping -n 3 127.0.0.1 >nul

echo [%time%] religando>> "%LOG%"
start "" wscript.exe "%HERE%\iniciar_oculto.vbs"

rem  espera o servidor responder na porta (ate ~25s)
set "OK="
powershell -NoProfile -Command "for($i=0;$i -lt 25;$i++){Start-Sleep 1; try{$c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',%PORT%); $c.Close(); exit 0}catch{}}; exit 1"
if %errorlevel%==0 (
  echo [%time%] servidor OK>> "%LOG%"
  rmdir /S /Q "%HERE%\_backup" >nul 2>&1
  goto :end
)

echo [%time%] nova versao NAO subiu - revertendo>> "%LOG%"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /r /c:":%PORT% .*LISTENING"') do taskkill /F /PID %%a >nul 2>&1
ping -n 2 127.0.0.1 >nul
if exist "%HERE%\_backup\server.py"        copy /Y "%HERE%\_backup\server.py"        "%HERE%\server.py"        >nul
if exist "%HERE%\_backup\static\index.html" copy /Y "%HERE%\_backup\static\index.html" "%HERE%\static\index.html" >nul
if exist "%HERE%\_backup\static\app.js"     copy /Y "%HERE%\_backup\static\app.js"     "%HERE%\static\app.js"     >nul
if exist "%HERE%\_backup\static\style.css"  copy /Y "%HERE%\_backup\static\style.css"  "%HERE%\static\style.css"  >nul
rmdir /S /Q "%HERE%\_backup" >nul 2>&1
ping -n 2 127.0.0.1 >nul
start "" wscript.exe "%HERE%\iniciar_oculto.vbs"
echo [%time%] revertido>> "%LOG%"

:end
echo [%time%] fim>> "%LOG%"
