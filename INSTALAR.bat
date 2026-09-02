@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Etiqueta - NS  -  Instalacao

echo ============================================================
echo    Etiqueta - NS   -   instalacao
echo ============================================================
echo.
echo  Este sistema le iPads/iPhones pelo cabo USB e imprime uma
echo  etiqueta com o numero de serie, saude e ciclos da bateria.
echo.
echo  Requisitos:
echo   1) Ter o 3uTools (ou iTunes / Apple Devices) instalado -
echo      e o que faz o Windows enxergar o aparelho na USB.
echo   2) Python 3  (o instalador tenta colocar sozinho).
echo.
pause
echo.

rem ---------- 1. procura o Python ----------
set "PY="
for /f "delims=" %%P in ('where python 2^>nul') do if not defined PY set "PY=%%P"
if not defined PY for /f "delims=" %%P in ('where py 2^>nul') do if not defined PY set "PY=py"
for %%V in (313 312 311 3) do (
  if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
)

if not defined PY (
  echo Python nao encontrado. Instalando pelo winget...
  echo.
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
  echo.
  echo ------------------------------------------------------------
  echo   O Python foi instalado.
  echo   FECHE esta janela e rode o INSTALAR.bat de novo
  echo   para terminar.
  echo ------------------------------------------------------------
  pause
  exit /b
)

echo Python encontrado: %PY%
"%PY%" --version
echo.

rem ---------- 2. inicializacao automatica ----------
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
> "%STARTUP%\Etiqueta - NS.vbs" echo ' Etiqueta - NS - inicializacao automatica
>> "%STARTUP%\Etiqueta - NS.vbs" echo CreateObject("WScript.Shell").Run "wscript.exe ""%~dp0iniciar_oculto.vbs""", 0, False
echo [ok] liga sozinho quando o Windows inicia

rem ---------- 3. atalho na area de trabalho ----------
set "DESK=%USERPROFILE%\Desktop"
if exist "%USERPROFILE%\OneDrive\Desktop" set "DESK=%USERPROFILE%\OneDrive\Desktop"
> "%DESK%\Etiqueta - NS.url" echo [InternetShortcut]
>> "%DESK%\Etiqueta - NS.url" echo URL=http://localhost:8765
echo [ok] atalho "Etiqueta - NS" na area de trabalho

rem ---------- 4. liga agora ----------
echo.
echo Iniciando...
start "" wscript.exe "%~dp0iniciar_oculto.vbs"
timeout /t 4 >nul
start "" http://localhost:8765

echo.
echo ============================================================
echo   Pronto.  Abre em:   http://localhost:8765
echo   Fixe essa aba no navegador (botao direito na aba - Fixar).
echo ============================================================
echo.
echo   Ligue os iPads no cabo. Na 1a vez toque em CONFIAR no
echo   aparelho. Depois e so clicar em Imprimir.
echo.
pause
