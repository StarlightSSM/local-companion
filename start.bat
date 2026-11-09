@echo off
rem Local Companion launcher (ASCII only on purpose)
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [setup] creating Python environment...
  where uv >nul 2>nul
  if %errorlevel%==0 (
    uv venv --python 3.12 .venv
    uv pip install --python .venv\Scripts\python.exe -r requirements.txt
  ) else (
    py -3.12 -m venv .venv || python -m venv .venv
    .venv\Scripts\python.exe -m pip install -r requirements.txt
  )
)
where ollama >nul 2>nul && (tasklist /FI "IMAGENAME eq ollama.exe" | find /I "ollama.exe" >nul || start "" /B ollama serve)
set PYTHONUTF8=1
.venv\Scripts\python.exe run.py %*
pause
