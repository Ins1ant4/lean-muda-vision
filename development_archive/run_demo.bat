@echo off
set PY_EXE=C:\Users\pc\AppData\Local\Programs\Python\Python311\python.exe

echo Starting FORVIA SMART Monitor Video Loop...
start cmd /k "%PY_EXE% vision_loop_video.py"

echo Starting FORVIA Dashboard...
start cmd /k "%PY_EXE% Dashboard\main.py"

echo Both applications are launching using Python 3.11!
