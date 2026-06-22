@echo off
title Perseus Minimalist v0.1
cd /d "%~dp0"

echo ========================================
echo  Perseus Minimalist v0.1
echo ========================================
echo.

:: Step 1: Check venv
echo [1/3] Checking environment...
if not exist ".venv\Scripts\python.exe" (
    echo   Virtual environment not found.
    echo   Please run "setup.bat" first.
    echo.
    pause
    exit /b 1
)
echo   Environment OK.
echo.

:: Step 2: Check data
echo [2/3] Checking data...
if not exist "perseus_data\perseus_index.db" (
    echo   No data found. Downloading from Perseus now...
    echo   (This happens once — ~930 MB, may take 10 minutes)
    echo.
    .venv\Scripts\python.exe perseus_offline.py download
    if !ERRORLEVEL! neq 0 (
        echo   Download failed. Check your internet connection.
        pause
        exit /b 1
    )
)
echo   Data OK.
echo.

:: Step 3: Launch
echo [3/3] Starting server...
echo.

:: Keep Stanza models inside project folder
set "STANZA_RESOURCES_DIR=%~dp0perseus_data\stanza_cache"

echo ========================================
echo  Your browser will open automatically.
echo  Keep this window open while reading.
echo  Press Ctrl+C to stop the server.
echo ========================================
echo.
start "" http://127.0.0.1:8080
.venv\Scripts\python.exe perseus_offline.py serve

echo.
echo ========================================
echo  Server stopped.
echo  Close this window or press any key.
echo ========================================
pause
