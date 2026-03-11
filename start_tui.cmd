@echo off
setlocal

REM Launch prompt_voice Textual TUI in a new console window.
REM Prefers local venv if available.

cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  start "prompt_voice (TUI)" cmd /k ".venv\Scripts\python.exe tui_main.py"
) else (
  start "prompt_voice (TUI)" cmd /k "python tui_main.py"
)

endlocal
