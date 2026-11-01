@echo off
setlocal
set "ROOT=%~dp0"
set "PYTHONPATH=%ROOT%tools\pylibs;%PYTHONPATH%"
set "PATH=%ROOT%tools\ffmpeg\bin;%ROOT%tools\aria2;%PATH%"
set "PYTHONIOENCODING=utf-8"
python "%ROOT%.dsh\skills\download\scripts\dl.py" %*
exit /b %errorlevel%
