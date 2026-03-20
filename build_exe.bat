@echo off
cd /d "%~dp0"

echo.
echo  =====================================================
echo    Contact Dashboard  —  Build Portable .exe
echo  =====================================================
echo.

:: ── Step 1: Install PyInstaller ──────────────────────
echo  [1/4]  Installing PyInstaller into venv...
venv\Scripts\pip install pyinstaller --quiet
if errorlevel 1 (
    echo.
    echo  ERROR: Could not install PyInstaller.
    echo  Make sure you have run the dashboard at least once so the venv exists.
    echo.
    pause
    exit /b 1
)
echo         Done.
echo.

:: ── Step 2: Build the .exe ───────────────────────────
echo  [2/4]  Building .exe  (takes 1-3 minutes, please wait)...
venv\Scripts\pyinstaller dashboard.spec --clean --noconfirm
if errorlevel 1 (
    echo.
    echo  ERROR: Build failed. Read the output above for details.
    echo.
    pause
    exit /b 1
)
echo         Done.
echo.

:: ── Step 3: Assemble the output folder ───────────────
echo  [3/4]  Assembling output folder...
if not exist "dist\DashboardApp" mkdir "dist\DashboardApp"

:: Copy the .exe
copy /Y "dist\ContactDashboard.exe" "dist\DashboardApp\ContactDashboard.exe" >nul
echo         Copied ContactDashboard.exe

:: Copy the database (contacts)
if exist "data\contacts.db" (
    if not exist "dist\DashboardApp\data" mkdir "dist\DashboardApp\data"
    copy /Y "data\contacts.db" "dist\DashboardApp\data\contacts.db" >nul
    echo         Copied contacts.db
) else (
    echo         WARNING: data\contacts.db not found.
    echo         Team members will see an empty database.
    echo         Run the dashboard once first to create the database.
)
echo.

:: ── Step 4: Done ─────────────────────────────────────
echo  [4/4]  Build complete!
echo.
echo  =====================================================
echo    OUTPUT FOLDER:  dist\DashboardApp\
echo  -----------------------------------------------------
echo    1. Zip the entire "DashboardApp" folder
echo    2. Send the zip to your team
echo    3. They unzip and double-click ContactDashboard.exe
echo    4. Browser opens automatically — done!
echo.
echo    No Python needed on their machines.
echo  =====================================================
echo.
pause
exit /b 0
