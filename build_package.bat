@echo off
title Building WFA Dashboard Team Package...
color 0A
cd /d "%~dp0"

echo.
echo  ============================================
echo   Building team package...
echo  ============================================
echo.

set "ZIPNAME=%USERPROFILE%\Desktop\WFA-Dashboard-Package.zip"
set "TEMP_DIR=%TEMP%\wfa-dashboard-build"
set "DEST_DIR=%TEMP_DIR%\contact-dashboard"

REM Clean up any previous temp build
if exist "%TEMP_DIR%" rmdir /s /q "%TEMP_DIR%"
mkdir "%DEST_DIR%"

echo  Copying files...

REM Copy all project files except venv, data, db files, cache
robocopy "%~dp0" "%DEST_DIR%" /E ^
  /XD venv data __pycache__ .git ^
  /XF *.db *.pyc *.sqlite build_package.bat ^
  /NFL /NDL /NJH /NJS /NP >nul

echo  Creating zip...

REM Delete old zip if exists then create fresh
powershell -NoProfile -Command "if (Test-Path '%ZIPNAME%') { Remove-Item '%ZIPNAME%' }; Compress-Archive -Path '%TEMP_DIR%\*' -DestinationPath '%ZIPNAME%' -Force; Write-Host '  Zip created.'"

REM Clean up temp folder
rmdir /s /q "%TEMP_DIR%"

echo.
echo  ============================================
echo   DONE! Package saved to your Desktop:
echo.
echo   WFA-Dashboard-Package.zip
echo.
echo   Email this to your team.
echo   They:
echo     1. Extract the zip to their Desktop
echo     2. Double-click setup.bat  (once only)
echo     3. Double-click run.bat    (every time)
echo     4. Click [Import CSV] to load data
echo  ============================================
echo.
pause
