@echo off
setlocal
cd /d "%~dp0"
set "GG_DESKTOP_PYTHON=%~dp0.venv-windows\Scripts\python.exe"
if not exist "%GG_DESKTOP_PYTHON%" set "GG_DESKTOP_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%GG_DESKTOP_PYTHON%" (
  echo Run setup-windows.cmd first.
  pause
  exit /b 2
)
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"
if not defined QT_QPA_PLATFORM set "QT_QPA_PLATFORM=windows"
"%GG_DESKTOP_PYTHON%" -B "%~dp0startup.py" %*
if errorlevel 1 (
  echo GG AI Desktop stopped with an error.
  pause
  exit /b 1
)
exit /b 0
