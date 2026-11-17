@echo off
REM ==========================================================================
REM  Build LabLayoutPlanner.exe
REM
REM  Result:
REM    dist\LabLayoutPlanner\LabLayoutPlanner.exe
REM    dist\LabLayoutPlanner\Library\          (component library, editable)
REM    dist\LabLayoutPlanner\_internal\        (bundled runtime - leave as is)
REM
REM  Copy/zip the whole dist\LabLayoutPlanner folder to distribute it.
REM ==========================================================================
setlocal
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"

if exist "%PY%" (
    echo [1/5] Using existing virtual environment .venv
    goto :venv_ok
)

echo [1/5] No .venv found - creating local virtual environment ...
REM Prefer the Windows "py" launcher (Python 3.12), then any "python" on PATH
set "BASEPY="
py -3.12 -c "import sys" >nul 2>&1 && set "BASEPY=py -3.12"
if not defined BASEPY py -3 -c "import sys" >nul 2>&1 && set "BASEPY=py -3"
if not defined BASEPY python -c "import sys" >nul 2>&1 && set "BASEPY=python"
if not defined BASEPY (
    echo ERROR: Python was not found. Install Python 3.12 from python.org
    echo        ^(tick "Add python.exe to PATH"^) and run this script again.
    goto :error
)
echo       using: %BASEPY%
%BASEPY% -m venv .venv || goto :error
if not exist "%PY%" (
    echo ERROR: virtual environment creation failed.
    goto :error
)

:venv_ok

echo [2/5] Installing dependencies ...
"%PY%" -m pip install --upgrade pip >nul
"%PY%" -m pip install -r requirements.txt pyinstaller matplotlib pillow || goto :error

echo [3/5] Generating icon ...
"%PY%" assets\make_icon.py || goto :error

echo [4/5] Running PyInstaller (this can take several minutes) ...
"%PY%" -m PyInstaller --noconfirm --clean lab_layout.spec || goto :error

echo [5/5] Copying Library folder next to the exe ...
if exist "dist\LabLayoutPlanner\Library" rmdir /s /q "dist\LabLayoutPlanner\Library"
xcopy /e /i /y /q "Library" "dist\LabLayoutPlanner\Library" >nul || goto :error

echo.
echo Build complete: %~dp0dist\LabLayoutPlanner\LabLayoutPlanner.exe
endlocal
exit /b 0

:error
echo.
echo *** Build FAILED (exit code %errorlevel%) ***
endlocal
exit /b 1
