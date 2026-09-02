@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Iniciando o Etiqueta - NS...
start "" http://localhost:8765
python server.py
echo.
echo Servidor encerrado.
pause
