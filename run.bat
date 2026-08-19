@echo off
REM ---------------------------------------------------------------
REM  LostArk Auction Comparer - launcher
REM
REM  This file is intentionally ASCII-only.
REM  cmd.exe re-reads a .bat line by line and desyncs on multi-byte
REM  characters after `chcp`, which corrupts parsing. Korean strings
REM  live in the Python side instead.
REM ---------------------------------------------------------------
chcp 65001 >nul
set "PYTHONUTF8=1"
setlocal
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo [1/3] Creating virtual environment...
    where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
    if not exist "%PY%" (
        echo.
        echo FAILED: could not create .venv
        echo Install Python 3.11+ from https://www.python.org/downloads/
        goto :halt
    )
)

REM Running pip every launch is slow. Probe the imports instead.
"%PY%" -c "import PySide6, requests, dotenv" >nul 2>nul
if errorlevel 1 (
    echo [2/3] Installing dependencies... this runs once, 1-2 min
    "%PY%" -m pip install -q --upgrade pip
    "%PY%" -m pip install -q -r requirements.txt
    if errorlevel 1 (
        echo.
        echo FAILED: dependency install. Check your network.
        goto :halt
    )
)

echo [3/3] Starting...
echo.
"%PY%" -m app
if errorlevel 1 goto :halt
goto :eof

:halt
echo.
pause
