@echo off
REM Arranca Kevil Studio en Windows.
REM
REM La primera vez sale esta consola mientras se instala todo (tarda unos
REM minutos). Despues se esconde sola y solo queda la ventana de Kevil.
REM Ademas se crea un acceso directo en el escritorio: a partir de ahi puedes
REM abrirlo desde ahi y olvidarte de esta carpeta.
cd /d "%~dp0"
title Kevil Studio

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 run.py %*
  goto :fin
)

where python >nul 2>nul
if %errorlevel%==0 (
  python run.py %*
  goto :fin
)

echo.
echo   No se encuentra Python en este equipo.
echo   Instalalo desde https://www.python.org/downloads/
echo   IMPORTANTE: marca la casilla "Add Python to PATH" al instalarlo.
echo.
pause
goto :eof

:fin
if errorlevel 1 (
  echo.
  echo   Kevil ha terminado con un error. Lo de arriba dice por que.
  echo   Si no se entiende, ejecuta:  python run.py --diagnostico
  echo.
  pause
)
