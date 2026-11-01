@echo off
setlocal
cd /d "%~dp0"
set "PYTHON_EXE="
set "PROBE=import sys; MIN=(3,10); print(sys.executable if sys.version_info >= MIN else '')"
for /f "delims=" %%P in ('py -3 -c "%PROBE%" 2^>nul') do (
    if exist "%%P" set "PYTHON_EXE=%%P"
)
if defined PYTHON_EXE goto launch
for /f "delims=" %%P in ('python -c "%PROBE%" 2^>nul') do (
    if exist "%%P" set "PYTHON_EXE=%%P"
)
if defined PYTHON_EXE goto launch
echo Python 3.10+ was not found. 1>&2
echo Install Python from https://www.python.org/downloads/windows/ 1>&2
exit /b 1

:launch
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
"%PYTHON_EXE%" -m apt_graph %*
exit /b %errorlevel%
