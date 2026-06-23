@echo off
title Perseus Minimalist v0.1 — Setup
cd /d "%~dp0"

:: ── Timestamp helper ──
setlocal enabledelayedexpansion
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value 2^>nul') do set "dt=%%I"
set "start_time=%dt:~8,2%:%dt:~10,2%:%dt:~12,2%"

echo ========================================
echo  Perseus Minimalist v0.1 — First-Time Setup
echo  Started at %start_time%
echo ========================================
echo.

:: Step 1: Check Python
set "step=1"
echo [%step%/4] Checking for Python...
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo.
    echo   Python not found!
    echo   Please install Python 3.11 or later from:
    echo     https://www.python.org/downloads/
    echo.
    echo   Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)
for /f "delims=" %%V in ('python --version 2^>^&1') do echo   Found: %%V
echo.

:: Step 2: Virtual environment
set /a "step+=1"
echo [%step%/4] Setting up virtual environment...
if exist ".venv\Scripts\python.exe" (
    echo   Virtual environment already exists — skipping.
) else (
    python -m venv .venv
    if !ERRORLEVEL! neq 0 (
        echo   Failed to create virtual environment!
        pause
        exit /b 1
    )
    echo   Done.
)
echo.

:: Step 3: Install packages
set /a "step+=1"
echo [%step%/4] Installing Python packages — this downloads ~770 MB...
echo   (This will take 5-10 minutes depending on your internet)
echo   If it seems stuck, press any key to see details.
echo.
set "STANZA_RESOURCES_DIR=%~dp0perseus_data\stanza_cache"
.venv\Scripts\python.exe -m pip install cltk[stanza]
if !ERRORLEVEL! neq 0 (
    echo.
    echo   Package installation had issues!
    echo   Try running: pip install cltk[stanza]
    pause
    exit /b 1
)
echo   Packages installed successfully.
echo.

:: Step 4: Download Perseus data (skip if already done)
set /a "step+=1"
echo [%step%/4] Checking for existing data...
if exist "perseus_data\perseus_index.db" (
    echo   Database found — data already downloaded, skipping.
    echo   To re-download, delete perseus_data\perseus_index.db and run again.
) else (
    echo   Downloading texts and dictionaries from Perseus...
    echo   This downloads ~930 MB of Greek and Latin texts.
    echo   The script will also build the search index afterward.
    echo.
    set "STANZA_RESOURCES_DIR=%~dp0perseus_data\stanza_cache"
    .venv\Scripts\python.exe perseus_offline.py download
    if !ERRORLEVEL! neq 0 (
        echo.
        echo   Data download had issues. Check your internet connection.
        echo   If the repos are already downloaded, just run "start.bat".
        pause
        exit /b 1
    )
)

:: Done
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value 2^>nul') do set "dt=%%I"
set "end_time=%dt:~8,2%:%dt:~10,2%:%dt:~12,2%"

echo.
echo ========================================
echo  Setup complete!
echo  Started: %start_time%
echo  Finished: %end_time%
echo.
echo  Now run "start.bat" to launch the viewer.
echo ========================================
echo.
pause
