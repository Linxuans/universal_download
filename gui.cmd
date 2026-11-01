@echo off
setlocal
set "ROOT=%~dp0"
set "PYTHONPATH=%ROOT%tools\pylibs;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
pythonw "%ROOT%scripts\gui.py" %*
