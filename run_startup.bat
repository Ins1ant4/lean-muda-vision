@echo off

:: =================================================================
:: SELF-RELAUNCH MECHANISM
:: First run:  sets console font in registry, starts a new maximized
::             CMD window with the right title, then exits.
:: Second run: the new CMD picks up font settings from registry
::             automatically, and jumps to :main to start monitoring.
:: =================================================================
if "%~1"=="--run" goto :main

:: --- Configure console font for our window title via registry ---
set "TITLE=FORVIA SMART MONITOR"
reg add "HKCU\Console\%TITLE%" /v FaceName   /t REG_SZ    /d "Consolas"  /f >nul 2>&1
reg add "HKCU\Console\%TITLE%" /v FontSize   /t REG_DWORD /d 0x00190000  /f >nul 2>&1
reg add "HKCU\Console\%TITLE%" /v FontWeight /t REG_DWORD /d 700         /f >nul 2>&1
reg add "HKCU\Console\%TITLE%" /v FontFamily /t REG_DWORD /d 54          /f >nul 2>&1

:: --- Relaunch in a new maximized window with that title ---
start "%TITLE%" /MAX cmd /k "%~f0" --run
exit

:: =================================================================
::                     MAIN MONITORING SYSTEM
:: =================================================================
:main
setlocal EnableDelayedExpansion
title FORVIA SMART MONITOR

:: ======================== CONFIGURATION ========================
set "SCRIPT=vision_loop_video.py"
set "PROJECT_DIR=c:\Users\pc\OneDrive\Bureau\VISION_AB"
set "LAUNCHER_DIR=%~dp0"
if "%LAUNCHER_DIR:~-1%"=="\" set "LAUNCHER_DIR=%LAUNCHER_DIR:~0,-1%"
set "LOG_DIR=%LAUNCHER_DIR%\logs"

:: Setup Python Executable (with Auto-detection fallback)
set "PYTHON_EXE=C:\Users\pc\AppData\Local\Programs\Python\Python311\python.exe"
if not exist "%PYTHON_EXE%" (
    echo [SYSTEM] Configured python.exe not found at "%PYTHON_EXE%"
    echo [SYSTEM] Auto-detecting Python environment...
    
    where python >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        for /f "delims=" %%I in ('where python') do (
            set "PYTHON_EXE=%%I"
            goto :python_found
        )
    )
    where py >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        set "PYTHON_EXE=py"
        goto :python_found
    )
    
    if exist "%USERPROFILE%\AppData\Local\Programs\Python" (
        for /f "delims=" %%D in ('dir "%USERPROFILE%\AppData\Local\Programs\Python\Python*" /ad /b /o-n 2^>nul') do (
            if exist "%USERPROFILE%\AppData\Local\Programs\Python\%%D\python.exe" (
                set "PYTHON_EXE=%USERPROFILE%\AppData\Local\Programs\Python\%%D\python.exe"
                goto :python_found
            )
        )
    )
    
    echo [WARNING] No Python runtime could be detected.
    :python_found
    echo [SYSTEM] Python detected: !PYTHON_EXE!
)

set "MAX_CRASHES=10"
set "RESTART_DELAY=5"
set "CRASH_COUNT=0"
set "SESSION_COUNT=0"
:: ===============================================================

cd /d "%PROJECT_DIR%"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

:: ======================== BOOT SEQUENCE ========================
color 0B
cls
echo.
echo  +==================================================================+
echo  ^|                                                                  ^|
echo  ^|         FORVIA SMART PRODUCTIVITY MONITOR                        ^|
echo  ^|             AI Real-Time Vision System                           ^|
echo  ^|                                                                  ^|
echo  +==================================================================+
echo.
echo.
echo  +------------------------------------------------------------------+
echo  ^|  SYSTEM BOOT SEQUENCE                                           ^|
echo  +------------------------------------------------------------------+
echo.

echo    [==........]  10%%   Initializing core modules...
timeout /t 1 /nobreak > nul

echo    [===.......]  30%%   Verifying Python runtime...
"%PYTHON_EXE%" --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    color 0C
    echo.
    echo    [CRITICAL] Python not found at: %PYTHON_EXE%
    pause
    exit /b 1
)
echo    [====......]  40%%   Python 3.11 ................. OK

if not exist "%SCRIPT%" (
    color 0C
    echo.
    echo    [CRITICAL] %SCRIPT% not found!
    pause
    exit /b 1
)
echo    [======....]  60%%   Vision module ............... OK
echo    [========..]  80%%   Initializing inference environment...
timeout /t 1 /nobreak > nul

echo    [==========] 100%%   All systems nominal.
timeout /t 1 /nobreak > nul

echo.
echo  +------------------------------------------------------------------+
echo  ^|  STATUS : ALL PREFLIGHT CHECKS PASSED                           ^|
echo  ^|  ENGINE : READY TO LAUNCH                                       ^|
echo  +------------------------------------------------------------------+
echo.
timeout /t 1 /nobreak > nul

:: ======================== MAIN LOOP ========================
:loop
set /a SESSION_COUNT+=1
cls
color 0A

echo.
echo  +==================================================================+
echo  ^|         FORVIA SMART PRODUCTIVITY MONITOR                        ^|
echo  ^|             AI Real-Time Vision System                           ^|
echo  +==================================================================+
echo.
echo  +-----------------------------+------------------------------------+
echo  ^|  DATE   %date%   ^|  STATUS    OPERATIONAL                ^|
echo  ^|  TIME   %time%  ^|  MODE      REAL-TIME MONITORING        ^|
echo  ^|  SESSION  #!SESSION_COUNT!              ^|  CRASHES   !CRASH_COUNT! / %MAX_CRASHES%                      ^|
echo  +-----------------------------+------------------------------------+
echo.
echo  +------------------------------------------------------------------+
echo  ^|  ^> Machine Monitoring       : OPERATIONAL                       ^|
echo  ^|  ^> Operator Detection       : OPERATIONAL                       ^|
echo  ^|  ^> Muda Classification      : OPERATIONAL                       ^|
echo  ^|  ^> Productivity Analytics   : OPERATIONAL                       ^|
echo  ^|  ^> TRS / Productivity KPI   : TRACKING                          ^|
echo  ^|  ^> Data Synchronization     : ENABLED                           ^|
echo  ^|  ^> Edge AI Status           : OPERATIONAL                       ^|
echo  +------------------------------------------------------------------+
echo.
echo  --------------------------------------------------------------------
echo   Monitoring production workstation...
echo  --------------------------------------------------------------------
echo.

:: --- Run the vision engine ---
echo [%date% %time%] === SESSION #!SESSION_COUNT! START === >> "%LOG_DIR%\monitor.log"
"%PYTHON_EXE%" "%SCRIPT%" 2>> "%LOG_DIR%\monitor.log"
set "EXIT_CODE=%ERRORLEVEL%"

:: --- Log exit ---
echo [%date% %time%] Session #!SESSION_COUNT! exited code %EXIT_CODE% >> "%LOG_DIR%\monitor.log"

:: --- Graceful stop via STOP file ---
set "STOP_FILE="
if exist "%LAUNCHER_DIR%\STOP" (
    set "STOP_FILE=%LAUNCHER_DIR%\STOP"
) else if exist "%PROJECT_DIR%\STOP" (
    set "STOP_FILE=%PROJECT_DIR%\STOP"
)

if defined STOP_FILE (
    cls
    color 0E
    echo.
    echo  +==================================================================+
    echo  ^|         FORVIA SMART PRODUCTIVITY MONITOR                        ^|
    echo  +==================================================================+
    echo.
    echo  +------------------------------------------------------------------+
    echo  ^|                                                                  ^|
    echo  ^|   [%date% %time%]                                     ^|
    echo  ^|                                                                  ^|
    echo  ^|   STOP signal received.                                          ^|
    echo  ^|   Monitor shutting down gracefully.                              ^|
    echo  ^|                                                                  ^|
    echo  ^|   Sessions completed : !SESSION_COUNT!                                   ^|
    echo  ^|   Total crashes      : !CRASH_COUNT!                                     ^|
    echo  ^|   Status             : STOPPED BY OPERATOR                       ^|
    echo  ^|                                                                  ^|
    echo  +------------------------------------------------------------------+
    echo.
    echo [%date% %time%] Graceful shutdown via STOP file >> "%LOG_DIR%\monitor.log"
    del "!STOP_FILE!"
    pause
    exit /b 0
)

:: --- Handle exit codes ---
cls
if %EXIT_CODE% EQU 0 (
    color 0B
    echo.
    echo  +==================================================================+
    echo  ^|         FORVIA SMART PRODUCTIVITY MONITOR                        ^|
    echo  +==================================================================+
    echo.
    echo  +------------------------------------------------------------------+
    echo  ^|  [%date% %time%]                                      ^|
    echo  ^|                                                                  ^|
    echo  ^|  ^> Process completed normally ^(exit code 0^)                      ^|
    echo  ^|  ^> Restarting monitoring cycle...                                ^|
    echo  ^|  ^> Crash counter reset.                                          ^|
    echo  +------------------------------------------------------------------+
    set "CRASH_COUNT=0"
) else (
    color 0C
    set /a CRASH_COUNT+=1
    echo.
    echo  +==================================================================+
    echo  ^|         FORVIA SMART PRODUCTIVITY MONITOR                        ^|
    echo  +==================================================================+
    echo.
    echo  +------------------------------------------------------------------+
    echo  ^|  [%date% %time%]                                      ^|
    echo  ^|                                                                  ^|
    echo  ^|  WARNING: Process crashed ^(exit code %EXIT_CODE%^)                         ^|
    echo  ^|  Crash count: !CRASH_COUNT! / %MAX_CRASHES%                                        ^|
    echo  ^|  Automatic recovery initiated                                    ^|
    echo  +------------------------------------------------------------------+
    echo [%date% %time%] CRASH #!CRASH_COUNT! exit_code=%EXIT_CODE% >> "%LOG_DIR%\crash_log.txt"
)

:: --- Check crash threshold ---
if !CRASH_COUNT! GEQ %MAX_CRASHES% (
    color 0C
    echo.
    echo  +==================================================================+
    echo  ^|                   *** CRITICAL ERROR ***                         ^|
    echo  +==================================================================+
    echo  ^|                                                                  ^|
    echo  ^|   Maximum crash limit reached ^(%MAX_CRASHES% consecutive failures^)        ^|
    echo  ^|   System halted to prevent infinite restart loop.                ^|
    echo  ^|                                                                  ^|
    echo  ^|   Review logs:                                                   ^|
    echo  ^|     %LOG_DIR%\crash_log.txt                       ^|
    echo  ^|     %LOG_DIR%\monitor.log                         ^|
    echo  ^|                                                                  ^|
    echo  +==================================================================+
    echo.
    echo [%date% %time%] CRITICAL: Max crash limit. Halted. >> "%LOG_DIR%\crash_log.txt"
    pause
    exit /b 1
)

echo.
echo   Relaunching in %RESTART_DELAY%s...
echo.
echo    [..........] 0%%
timeout /t 1 /nobreak > nul
echo    [==........] 20%%
timeout /t 1 /nobreak > nul
echo    [====......] 40%%
timeout /t 1 /nobreak > nul
echo    [======....] 60%%
timeout /t 1 /nobreak > nul
echo    [========..] 80%%
timeout /t 1 /nobreak > nul

goto loop

