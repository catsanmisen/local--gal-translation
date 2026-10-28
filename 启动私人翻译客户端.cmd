@echo off
cd /d "%~dp0"
py -3 -B backend\src\server.py --open
if errorlevel 1 pause
