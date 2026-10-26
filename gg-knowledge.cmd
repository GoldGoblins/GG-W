@echo off
setlocal
set "GG_CLI_PYTHON=%~dp0.venv-windows\Scripts\python.exe"
if not exist "%GG_CLI_PYTHON%" set "GG_CLI_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%GG_CLI_PYTHON%" (
  echo Run setup-windows.cmd first.
  exit /b 2
)
"%GG_CLI_PYTHON%" -X utf8 -B "%~dp0gg-knowledge" %*
exit /b %errorlevel%
