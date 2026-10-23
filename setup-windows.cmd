@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
if exist ".venv-windows\Scripts\python.exe" goto install
if exist ".runtime\Python313\python.exe" (
  ".runtime\Python313\python.exe" -m venv ".venv-windows"
) else (
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3 -m venv ".venv-windows"
  ) else (
    python -m venv ".venv-windows"
  )
)
if errorlevel 1 goto fail
:install
".venv-windows\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto fail
".venv-windows\Scripts\python.exe" -B gg-setup --prepare
if errorlevel 1 goto fail
echo GG AI Desktop dependencies are ready. Run run-gg-ai-desktop.cmd.
exit /b 0
:fail
echo Setup failed. Python 3.12 or newer is required.
pause
exit /b 1
