@echo off
rem  Aplica a atualizacao baixada em _update\ e reinicia o servidor.
rem  Chamado automaticamente pelo botao "Atualizar" da interface.
cd /d "%~dp0"

rem  espera o servidor terminar de responder o pedido
timeout /t 2 /nobreak >nul

rem  encerra o servidor atual (quem estiver na porta 8765)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /r /c:":8765 .*LISTENING"') do taskkill /F /PID %%a >nul 2>&1
timeout /t 1 /nobreak >nul

if not exist "_update\Etiqueta-NS\server.py" (
  echo pacote de atualizacao invalido> _update_error.txt
  goto :relaunch
)

rem  nunca sobrescreve a configuracao local
if exist "_update\Etiqueta-NS\config.json" del /q "_update\Etiqueta-NS\config.json"

rem  copia os arquivos novos por cima
xcopy /E /Y /Q "_update\Etiqueta-NS\*" "%~dp0" >nul

rem  limpa
rmdir /S /Q "_update" >nul 2>&1
del /q "_update.zip" >nul 2>&1

:relaunch
start "" wscript.exe "%~dp0iniciar_oculto.vbs"
