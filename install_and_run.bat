@echo off
title XAUUSD SMC+ICT Bot - Setup & Run
echo [1/3] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python is not installed or not in PATH.
    pause
    exit /b
)

echo [2/3] Installing/Updating requirements...
pip install --upgrade pip
pip install -r requirements.txt

echo [3/3] Starting the Bot...
python main.py
pause
