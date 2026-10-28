@echo off
cd /d "%~dp0"
py -3 -B backend\src\control.py shutdown
if errorlevel 1 pause
