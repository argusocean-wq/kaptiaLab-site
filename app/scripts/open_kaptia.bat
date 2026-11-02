@echo off
setlocal
cd /d "%~dp0.."

where py >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python launcher not found. Install Python 3.10 or 3.11.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [INFO] Creating Kaptia Python environment...
  py -3.11 -m venv .venv
  if errorlevel 1 (
    py -3.10 -m venv .venv
    if errorlevel 1 (
      echo [ERROR] Could not create Python environment.
      pause
      exit /b 1
    )
  )
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 exit /b 1

python -c "import torch, transformers, accelerate" >nul 2>nul
if errorlevel 1 (
  echo [INFO] Installing Kaptia Qwen runtime dependencies.
  python -m pip install --upgrade pip
  if errorlevel 1 goto :failed
  python -m pip install -r requirements.txt
  if errorlevel 1 goto :failed
)

rem The desktop assistant downloads the configured Qwen model on first use; no training is performed.

python scripts\chat.py
if errorlevel 1 (
  echo [ERROR] Kaptia stopped with an error. Read the output above.
  pause
  exit /b 1
)
endlocal
exit /b 0

:failed
echo [ERROR] Assistant runtime setup failed. Check Python, CUDA, network, disk space, and the error above.
pause
exit /b 1
