@echo off
setlocal
cd /d "%~dp0"
if exist "f1_strategy\Scripts\python.exe" (
    "f1_strategy\Scripts\python.exe" -X utf8 main.py menu
) else if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -X utf8 main.py menu
) else (
    python -X utf8 main.py menu
)
if errorlevel 1 pause
