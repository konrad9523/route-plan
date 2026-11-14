@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title G4 All Services

set "RUN_PYTHON=E:\app\python\python.exe"
if not exist "%RUN_PYTHON%" set "RUN_PYTHON="
if not defined RUN_PYTHON (
  where python >nul 2>&1
  if not errorlevel 1 set "RUN_PYTHON=python"
)
if not defined RUN_PYTHON goto :failed

"%RUN_PYTHON%" -B start-all.py
set "EXIT_CODE=%errorlevel%"
echo.
if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%

:failed
echo Python was not found. Services cannot start.
pause
exit /b 1
