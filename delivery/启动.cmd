@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 goto error
)
if not exist ".venv\.f1-ready" (
  .venv\Scripts\python.exe -m pip install -r requirements-runtime.txt
  if errorlevel 1 goto error
  for %%f in (wheel\*.whl) do .venv\Scripts\python.exe -m pip install --no-deps "%%f"
  if errorlevel 1 goto error
  echo ready> .venv\.f1-ready
)
.venv\Scripts\python.exe start.py %*
if errorlevel 1 goto error
exit /b 0
:error
echo Startup failed. Keep this error for diagnosis.
pause
exit /b 1
