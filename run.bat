@echo off
REM ============================================================
REM  Decart Livestream Studio - Windows launcher
REM  Creates a local virtual environment, installs dependencies,
REM  then starts the app.
REM ============================================================
setlocal
cd /d "%~dp0"

echo(
echo === Decart Livestream Studio ===
echo(

REM --- locate Python -------------------------------------------------
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found on PATH.
    echo         Install Python 3.10+ from https://www.python.org/downloads/
    echo         and tick "Add python.exe to PATH" during setup.
    pause
    exit /b 1
)

REM --- create the virtual environment --------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment ^(.venv^)...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create the virtual environment.
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"

REM --- install / update dependencies ---------------------------------
echo Installing dependencies ^(first run can take a few minutes^)...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Dependency installation failed.
    pause
    exit /b 1
)

REM --- run -----------------------------------------------------------
echo(
echo Starting Decart Livestream Studio...
echo(
python app.py

echo(
echo App closed.
pause
endlocal
