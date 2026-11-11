@echo off
cd /d "%~dp0scripts"
where python >nul 2>nul || goto nopython
python -c "import sys" >nul 2>nul || goto nopython
rem First run: install pywebview (the pretty window). If it cannot install, perf_web.py opens the plain window instead.
python -c "import webview" >nul 2>nul || (
  echo Installing pywebview for the window, first run only...
  python -m pip install --user pywebview
)
start "" pythonw perf_web.py
exit /b

:nopython
echo.
echo  Python was not found.
echo  Install Python 3 from https://www.python.org/downloads/
echo  and tick "Add python.exe to PATH" during setup, then run this file again.
echo.
pause
