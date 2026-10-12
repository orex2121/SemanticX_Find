@echo off
setlocal
title SemanticX Find Setup
cd /d "%~dp0"

echo SemanticX Find setup
echo This will install a portable Python runtime, application libraries,
echo EmbeddingGemma 2 and OCR models inside this folder.
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup.ps1"
if errorlevel 1 (
  echo.
  echo Setup failed. Review the error above and run Setup.bat again.
  pause
  exit /b 1
)

echo.
echo Setup completed successfully. Run RUN.bat to start SemanticX Find.
pause
