@echo off
title Refresh Contacts Data
color 0E

if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

echo.
echo  Refreshing contacts from CSV...
echo.
python import_csv.py
echo.
pause
