@echo off
setlocal EnableExtensions
title SemanticX Find Updater
cd /d "%~dp0"

set "REPOSITORY=https://github.com/orex2121/SemanticX_Find.git"
set "ARCHIVE_URL=https://github.com/orex2121/SemanticX_Find/archive/refs/heads/main.zip"
set "UPDATE_ROOT=%TEMP%\SemanticX_Find_Update_%RANDOM%_%RANDOM%"
set "UPDATE_SOURCE=%UPDATE_ROOT%\repository"

echo.
echo SemanticX Find updater
echo ======================
echo Close SemanticX Find before continuing.
echo Local settings, catalogs, indexes, models and caches will be preserved.
echo.
pause

mkdir "%UPDATE_ROOT%" >nul 2>nul
if errorlevel 1 goto :temp_error

where git.exe >nul 2>nul
if errorlevel 1 goto :download_archive

echo [1/3] Downloading the latest version with Git...
git clone --depth 1 "%REPOSITORY%" "%UPDATE_SOURCE%"
if errorlevel 1 goto :download_error
goto :copy_files

:download_archive
echo [1/3] Git was not found. Downloading the repository archive...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri '%ARCHIVE_URL%' -OutFile '%UPDATE_ROOT%\source.zip'; Expand-Archive -LiteralPath '%UPDATE_ROOT%\source.zip' -DestinationPath '%UPDATE_ROOT%\unpacked' -Force; $source=Get-ChildItem -LiteralPath '%UPDATE_ROOT%\unpacked' -Directory | Select-Object -First 1; if(-not $source){throw 'The downloaded repository archive is empty.'}; Move-Item -LiteralPath $source.FullName -Destination '%UPDATE_SOURCE%'"
if errorlevel 1 goto :download_error

:copy_files
if not exist "%UPDATE_SOURCE%\run.py" goto :invalid_source

echo [2/3] Updating application files...
robocopy "%UPDATE_SOURCE%" "%~dp0" /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP /XD ".git" "runtime" "models" "indexes" "config" "cache" "logs" "temp" ".semantic_index" "checkpoint_tmp" /XF "UPDATE.bat"
set "COPY_RESULT=%ERRORLEVEL%"
if %COPY_RESULT% GEQ 8 goto :copy_error

echo [3/3] Synchronizing libraries and models...
if exist "%~dp0Setup.bat" (
  call "%~dp0Setup.bat"
) else if exist "%~dp0Setup.ps1" (
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup.ps1"
)
if errorlevel 1 goto :setup_error

call :cleanup
echo.
echo Update completed successfully.
echo You can now start SemanticX Find.
pause
exit /b 0

:temp_error
echo.
echo ERROR: Unable to create the temporary update folder.
goto :failed

:download_error
echo.
echo ERROR: Unable to download the repository.
echo Check the internet connection and try again.
goto :failed

:invalid_source
echo.
echo ERROR: The downloaded repository does not contain SemanticX Find.
goto :failed

:copy_error
echo.
echo ERROR: Some application files could not be updated.
echo Make sure SemanticX Find is closed and try again.
goto :failed

:setup_error
echo.
echo ERROR: The files were updated, but dependency setup failed.
echo Run Setup.bat manually to finish the update.
goto :failed

:failed
call :cleanup
pause
exit /b 1

:cleanup
if defined UPDATE_ROOT if exist "%UPDATE_ROOT%" rmdir /s /q "%UPDATE_ROOT%"
exit /b 0
