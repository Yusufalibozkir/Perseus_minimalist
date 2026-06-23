@echo off
setlocal enabledelayedexpansion
title Perseus Minimalist v0.1 — Rebuild
cd /d "%~dp0"

echo ========================================
echo  Perseus Minimalist v0.1 — Rebuild Index
echo ========================================
echo.

:: Check venv
if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found.
    echo Please run "setup.bat" first.
    pause
    exit /b 1
)

:: Check repos
if not exist "perseus_data\repos\greek\data" (
    echo No downloaded repos found. Run "setup.bat" first.
    pause
    exit /b 1
)

echo [1/2] Clearing old database...
if exist "perseus_data\perseus_index.db" del "perseus_data\perseus_index.db"
if exist "perseus_data\perseus_index.db-journal" del "perseus_data\perseus_index.db-journal"
if exist "perseus_data\perseus_index.db-wal" del "perseus_data\perseus_index.db-wal"
if exist "perseus_data\perseus_index.db-shm" del "perseus_data\perseus_index.db-shm"
echo   Done.

echo [2/2] Rebuilding index from existing repos...
echo.
.venv\Scripts\python.exe perseus_offline.py rebuild

echo.
echo ========================================
echo  Rebuild complete!
echo  Run "start.bat" to launch the viewer.
echo ========================================
echo.
pause
