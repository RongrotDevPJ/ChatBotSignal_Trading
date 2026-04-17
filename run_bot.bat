@echo off
title XAUUSD SMC+ICT Bot - Active
:start
echo [%date% %time%] Starting XAUUSD SMC+ICT Signal Bot...

python main.py

echo.
echo Bot stopped or crashed. Restarting in 10 seconds...
echo Press Ctrl+C to stop the auto-restart.
timeout /t 10
goto start
