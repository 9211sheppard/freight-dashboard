@echo off
title WFA Contacts Dashboard
color 0B

REM Works from any location on any PC
cd /d "%~dp0"

REM Run setup automatically if venv doesn't exist yet
if not exist "venv\Scripts\python.exe" (
    echo.
    echo  First-time setup needed. Running setup...
    echo.
    call setup.bat
)

REM Auto-restart loop - restarts automatically if it ever crashes
:loop
echo.
echo  ============================================
echo   WFA Contacts Dashboard  ^|  Auto-Restart ON
echo   Open your browser to: http://127.0.0.1:5000
echo   Press Ctrl+C to stop completely.
echo  ============================================
echo.
venv\Scripts\python.exe app.py
echo.
echo  [!] Dashboard stopped. Restarting in 3 seconds...
echo      Press Ctrl+C now to exit instead.
echo.
timeout /t 3 /nobreak >nul
goto loop
