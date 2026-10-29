@echo off
setlocal
where py >nul 2>nul
if errorlevel 1 goto usepython
py -3 "%~dp0..\install.py" --platform windows %*
exit /b %errorlevel%
:usepython
python "%~dp0..\install.py" --platform windows %*
exit /b %errorlevel%
