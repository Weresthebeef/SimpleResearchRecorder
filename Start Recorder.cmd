@echo off
if exist "%~dp0.venv\Scripts\pythonw.exe" (
  start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0screen_recorder.py"
) else (
  pyw -3 "%~dp0screen_recorder.py"
)
