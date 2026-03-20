@echo off
cd /d "%~dp0"
title Contact Verifier
color 0A

echo.
echo  ============================================================
echo    Automated Contact Verifier
echo  ============================================================
echo.
echo  Installing required libraries...
venv\Scripts\pip install duckduckgo-search requests beautifulsoup4 --quiet
echo.

if "%1"=="--reset" (
    echo  Re-verifying ALL contacts from scratch...
    echo.
    venv\Scripts\python verify_contacts.py --reset
) else (
    echo  Starting / resuming verification...
    echo  Press Ctrl+C at any time — progress is saved automatically.
    echo.
    venv\Scripts\python verify_contacts.py
)

echo.
pause
