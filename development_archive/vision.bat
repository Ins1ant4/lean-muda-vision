@echo off
setlocal
:: 1. Setup paths
set PY_EXE=C:\Users\pc\AppData\Local\Programs\Python\Python311\python.exe
set SCRIPT=vision_loop.py
set LOG_FILE=vision_launcher_log.txt

:: Move to the correct directory
cd /d "c:\Users\pc\OneDrive\Bureau\VISION_AB"

echo [SYSTEM] FORVIA Smart Monitor - Industrial Launcher Active.
echo [SYSTEM] Waiting 10 seconds for network and GPU to initialize...
timeout /t 10 /nobreak > nul

:RESTART_LOOP
echo [%DATE% %TIME%] Starting Vision Brain... >> %LOG_FILE%
echo [RUNNING] Vision Loop is active. Press Ctrl+C to stop the launcher.

:: Run the script
"%PY_EXE%" "%SCRIPT%"

:: If the script reaches here, it crashed or closed
echo [%DATE% %TIME%] CRASH DETECTED. Restarting in 5 seconds... >> %LOG_FILE%
echo [ERROR] System crashed! Restarting in 5 seconds...
timeout /t 5 /nobreak > nul
goto RESTART_LOOP
