@echo off
rem ============================================================================
rem  Paper Forge launcher for Windows.
rem
rem    run.bat            portable mode (default): everything is kept inside
rem                       this folder (runtime\). Nothing is installed system-wide.
rem    run.bat docker     use Docker Desktop instead, if you already have it.
rem    run.bat reset      delete runtime\ (Python, Tectonic, caches) and exit.
rem    run.bat zip        make paper-forge.zip next to this folder to share: no
rem                       runtime\, settings, API key or jobs.
rem
rem  First start needs internet (about 100 MB of downloads, see SETUP.md).
rem  Later starts work offline.
rem ============================================================================
setlocal EnableExtensions
cd /d "%~dp0"
title Paper Forge

set "PF_HOME=%~dp0"
if "%PF_HOME:~-1%"=="\" set "PF_HOME=%PF_HOME:~0,-1%"
set "RUNTIME=%PF_HOME%\runtime"
set "DOWNLOADS=%RUNTIME%\downloads"
set "PY_VER=3.12.10"
set "PY_DIR=%RUNTIME%\python"
set "PY=%PY_DIR%\python.exe"
set "TECT_VER=0.15.0"
set "TECT_DIR=%RUNTIME%\tectonic"
set "PF_PORT=8000"
if not "%PAPERFORGE_PORT%"=="" set "PF_PORT=%PAPERFORGE_PORT%"

if /i "%~1"=="docker" goto :docker
if /i "%~1"=="reset" goto :reset
if /i "%~1"=="zip" goto :zip

rem ---- Keep every download, cache and temp file inside this folder ----------
set "TEMP=%RUNTIME%\tmp"
set "TMP=%RUNTIME%\tmp"
set "PIP_CACHE_DIR=%RUNTIME%\pip-cache"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "PYTHONNOUSERSITE=1"
set "PYTHONDONTWRITEBYTECODE=1"
set "TECTONIC_CACHE_DIR=%RUNTIME%\tectonic-cache"
set "PAPERFORGE_TECTONIC=%TECT_DIR%\tectonic.exe"
set "PAPERFORGE_TMP=%RUNTIME%\tmp"
if not exist "%RUNTIME%" mkdir "%RUNTIME%"
if not exist "%DOWNLOADS%" mkdir "%DOWNLOADS%"
if not exist "%TEMP%" mkdir "%TEMP%"

where curl.exe >nul 2>nul || (echo [ERROR] curl.exe was not found. Paper Forge needs Windows 10 version 1803 or newer. & goto :fail)
where tar.exe >nul 2>nul || (echo [ERROR] tar.exe was not found. Paper Forge needs Windows 10 version 1803 or newer. & goto :fail)

echo.
echo  Paper Forge - portable mode
echo  Files stay in: %PF_HOME%
echo.

rem ---- 1. Private Python (embeddable, about 11 MB) ---------------------------
if exist "%PY%" goto :have_python
echo [1/4] Downloading Python %PY_VER% (embeddable, about 11 MB)...
curl.exe -L --fail --retry 3 -o "%DOWNLOADS%\python.zip" "https://www.python.org/ftp/python/%PY_VER%/python-%PY_VER%-embed-amd64.zip" || (echo [ERROR] Could not download Python. Check your internet connection. & goto :fail)
mkdir "%PY_DIR%" 2>nul
tar.exe -xf "%DOWNLOADS%\python.zip" -C "%PY_DIR%" || (echo [ERROR] Could not unpack Python. & goto :fail)
rem Allow site-packages and make the Paper Forge folder importable.
(
  echo python312.zip
  echo .
  echo Lib\site-packages
  echo ..\..
  echo import site
) > "%PY_DIR%\python312._pth"
del "%DOWNLOADS%\python.zip" 2>nul
:have_python

rem ---- 2. pip and the Python packages (about 30 MB) --------------------------
if exist "%PY_DIR%\Scripts\pip.exe" goto :have_pip
echo [2/4] Setting up pip...
curl.exe -L --fail --retry 3 -o "%DOWNLOADS%\get-pip.py" "https://bootstrap.pypa.io/get-pip.py" || (echo [ERROR] Could not download pip. & goto :fail)
"%PY%" "%DOWNLOADS%\get-pip.py" --no-warn-script-location --no-cache-dir || (echo [ERROR] pip setup failed. & goto :fail)
del "%DOWNLOADS%\get-pip.py" 2>nul
:have_pip

fc /b "%PF_HOME%\requirements.txt" "%RUNTIME%\requirements.installed" >nul 2>nul
if not errorlevel 1 goto :have_deps
echo [3/4] Installing Python packages (about 30 MB, first start only)...
"%PY%" -m pip install --no-warn-script-location --no-cache-dir --only-binary :all: --find-links "%PF_HOME%\vendor\wheels" -r "%PF_HOME%\requirements.txt" || (echo [ERROR] Installing Python packages failed. See SETUP.md, "Troubleshooting". & goto :fail)
copy /y "%PF_HOME%\requirements.txt" "%RUNTIME%\requirements.installed" >nul
:have_deps

rem ---- 3. Tectonic LaTeX compiler (about 20 MB) ------------------------------
if exist "%TECT_DIR%\tectonic.exe" goto :have_tectonic
echo [4/4] Downloading the Tectonic LaTeX compiler %TECT_VER% (about 20 MB)...
curl.exe -L --fail --retry 3 -o "%DOWNLOADS%\tectonic.zip" "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%%40%TECT_VER%/tectonic-%TECT_VER%-x86_64-pc-windows-msvc.zip" || (echo [ERROR] Could not download Tectonic. & goto :fail)
mkdir "%TECT_DIR%" 2>nul
tar.exe -xf "%DOWNLOADS%\tectonic.zip" -C "%TECT_DIR%" || (echo [ERROR] Could not unpack Tectonic. & goto :fail)
del "%DOWNLOADS%\tectonic.zip" 2>nul
:have_tectonic

rem ---- 4. Warm-up: cache each venue's LaTeX packages for offline use (once per venue)
rem      runtime\warmup.ok lists the venues already cached, so this is quick after the first start.
"%PY%" "%PF_HOME%\scripts\warmup.py" "%RUNTIME%\warmup.ok"
if errorlevel 1 (
  echo [WARNING] Warm-up did not finish. Paper Forge will still start and download
  echo           LaTeX packages the first time you format a paper.
)

echo.
echo ============================================================
echo   Paper Forge is starting at  http://localhost:%PF_PORT%
echo   Keep this window open. Press Ctrl+C to stop.
echo ============================================================
echo.
start "" /min cmd /c "timeout /t 4 /nobreak >nul & start "" http://localhost:%PF_PORT%"
set "PAPERFORGE_PORT=%PF_PORT%"
"%PY%" -m app.main
if errorlevel 1 (
  echo.
  echo [ERROR] Paper Forge stopped with an error. If port %PF_PORT% is busy, run:
  echo         set PAPERFORGE_PORT=8001 ^&^& run.bat
  goto :fail
)
goto :end

rem ---- Docker mode ------------------------------------------------------------
:docker
where docker >nul 2>nul || (echo [ERROR] Docker is not installed. Use "run.bat" without "docker" for portable mode. & goto :fail)
docker info >nul 2>nul || (echo [ERROR] Docker is installed but not running. Start Docker Desktop and try again. & goto :fail)
echo Starting Paper Forge with Docker (the first build takes a few minutes)...
docker compose up -d --build || (echo [ERROR] docker compose failed. & goto :fail)
echo.
echo Paper Forge is running at http://localhost:8000
echo Stop it with:  docker compose down
start "" http://localhost:8000
goto :end

:zip
if not exist "%PY%" (
  echo Start Paper Forge once with run.bat first: the ZIP is made with the Python it downloads.
  goto :fail
)
"%PY%" "%PF_HOME%\scripts\make_zip.py"
pause
goto :end

:reset
echo This deletes "%RUNTIME%" (private Python, Tectonic and caches). Your jobs in "output" are kept.
choice /m "Continue"
if errorlevel 2 goto :end
rmdir /s /q "%RUNTIME%"
echo Done. The next run.bat will download everything again.
goto :end

:fail
echo.
pause
exit /b 1

:end
endlocal
