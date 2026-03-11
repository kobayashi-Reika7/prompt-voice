@echo off
chcp 65001 >nul
cd /d "%~dp0"
python tui_main.py %*
if errorlevel 1 pause
