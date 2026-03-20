@echo off
title WFA Contacts Dashboard - First-Time Setup
color 0A

REM Works from any location on any PC
cd /d "%~dp0"

echo.
echo  ============================================
echo   WFA Contacts Dashboard - Setup
echo  ============================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python is not installed or not on PATH.
    echo.
    echo  Please download and install Python 3.9 or later:
    echo  https://www.python.org/downloads/
    echo.
    echo  IMPORTANT: During install, tick "Add Python to PATH"
    echo.
    pause
    exit /b 1
)
echo  [1/4] Python found.

REM Create virtual environment
if not exist "venv" (
    echo  [2/4] Creating virtual environment...
    python -m venv venv
) else (
    echo  [2/4] Virtual environment ready.
)

REM Install dependencies
echo  [3/4] Installing required packages...
venv\Scripts\python.exe -m pip install -q --upgrade pip
venv\Scripts\python.exe -m pip install -q -r requirements.txt
echo        Done.

REM Initial database setup (no CSV needed - team uses Import CSV button)
echo  [4/4] Setting up database...
venv\Scripts\python.exe -c "from database import init_db; init_db(); print('  Database ready.')"

echo.
echo  ============================================
echo   Setup complete!
echo.
echo   Double-click run.bat to start the dashboard.
echo   Use the [Import CSV] button to load your data.
echo  ============================================
echo.
pause
