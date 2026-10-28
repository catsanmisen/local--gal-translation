@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONDONTWRITEBYTECODE=1
echo 本窗口需保持打开。停止服务请运行“停止GalTransl翻译.cmd”。
python -B "%~dp0gal_service.py" run
pause
