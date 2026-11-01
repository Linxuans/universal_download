@echo off
setlocal
chcp 65001 >nul
set "ROOT=%~dp0"
set "PYTHONPATH=%ROOT%tools\pylibs;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
python "%ROOT%scripts\scout.py" %*
exit /b %errorlevel%
