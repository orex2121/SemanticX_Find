@echo off
setlocal
cd /d "%~dp0"

if not exist "%~dp0runtime\pythonw.exe" (
  echo SemanticX Find is not installed yet. Run Setup.bat first.
  pause
  exit /b 1
)

set PYTHONNOUSERSITE=1
set PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
start "SemanticX Find" /b "%~dp0runtime\pythonw.exe" "%~dp0run.py"
