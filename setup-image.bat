@echo off
rem Optional: realistic image generation (Stable Diffusion SD-Turbo, CPU). ~5GB download, 30s-2min per image.
cd /d "%~dp0"
where uv >nul 2>nul
if %errorlevel%==0 (
  uv pip install --python .venv\Scripts\python.exe torch --index-url https://download.pytorch.org/whl/cpu
  uv pip install --python .venv\Scripts\python.exe diffusers transformers accelerate
) else (
  .venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
  .venv\Scripts\python.exe -m pip install diffusers transformers accelerate
)
echo Done. Restart the app and choose "Stable Diffusion" in the drawing tab.
pause
