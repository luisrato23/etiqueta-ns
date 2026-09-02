@echo off
chcp 65001 >nul
echo Parando o Etiqueta - NS (porta 8765)...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /r /c:":8765 .*LISTENING"') do taskkill /F /PID %%a >nul 2>&1
echo Pronto.
timeout /t 2 >nul
