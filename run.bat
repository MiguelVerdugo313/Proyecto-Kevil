@echo off
REM Arranca Kevil Studio en Windows.
cd /d "%~dp0"

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

echo No se encuentra Python. Instalalo desde https://www.python.org/downloads/
pause

:fin
if errorlevel 1 pause
