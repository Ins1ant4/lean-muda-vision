@echo off
echo Starting SMART Productivity Monitor...
cd /d "%~dp0"
py -3.13 vision_loop.py
pause
