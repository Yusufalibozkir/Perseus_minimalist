@echo off
setlocal enabledelayedexpansion
title Perseus Minimalist v0.1 — Fresh Rebuild
cd /d "%~dp0"

echo ========================================
echo  Perseus Minimalist v0.1 — Fresh Rebuild
echo  This will delete ALL data and re-download
echo  everything from Perseus (~930 MB).
echo ========================================
echo.

:: Check venv
if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found.
    echo Please run "setup.bat" first.
    pause
    exit /b 1
)

echo Press Ctrl+C to cancel, or any key to continue...
pause >nul

echo.
echo [1/3] Deleting all old data...
if exist "perseus_data\perseus_index.db" del "perseus_data\perseus_index.db"
if exist "perseus_data\perseus_index.db-journal" del "perseus_data\perseus_index.db-journal"
if exist "perseus_data\perseus_index.db-wal" del "perseus_data\perseus_index.db-wal"
if exist "perseus_data\perseus_index.db-shm" del "perseus_data\perseus_index.db-shm"
if exist "perseus_data\repos" rmdir /s /q "perseus_data\repos"
if exist "perseus_data\stanza_cache" rmdir /s /q "perseus_data\stanza_cache"
echo   Done. All data cleared.

echo.
echo [2/3] Downloading fresh data from Perseus...
.venv\Scripts\python.exe perseus_offline.py download
if !ERRORLEVEL! neq 0 (
    echo   Download failed. Check your internet connection.
    pause
    exit /b 1
)

echo.
echo [3/3] Done!
echo.
echo ========================================
echo  Fresh rebuild complete!
echo  Run "start.bat" to launch the viewer.
echo ========================================
echo.
pause
