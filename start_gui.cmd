@echo off
setlocal

REM Launch prompt_voice desktop GUI (tkinter) in a new window.
REM Prefers local venv if available.

cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  start "prompt_voice (GUI)" ".venv\Scripts\python.exe" "gui.py"
) else (
  start "prompt_voice (GUI)" python "gui.py"
)

endlocal
