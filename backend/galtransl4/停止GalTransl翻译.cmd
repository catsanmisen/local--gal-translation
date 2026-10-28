@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONDONTWRITEBYTECODE=1
python -B "%~dp0gal_service.py" stop
pause
