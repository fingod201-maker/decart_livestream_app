@echo off
REM ============================================================
REM  Build a standalone Windows .exe with PyInstaller.
REM  Output: dist\DecartLivestreamStudio\DecartLivestreamStudio.exe
REM ============================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
)
call ".venv\Scripts\activate.bat"

echo Installing dependencies + PyInstaller...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo [ERROR] Dependency installation failed.
    pause
    exit /b 1
)

echo(
echo Building executable...
pyinstaller --noconfirm --clean --windowed ^
    --name "DecartLivestreamStudio" ^
    --icon "assets\app.ico" ^
    --add-data "assets;assets" ^
    --collect-all decart ^
    --collect-all livekit ^
    --collect-all cv2 ^
    --collect-submodules livekit ^
    --hidden-import livekit.rtc ^
    --hidden-import av ^
    app.py

if errorlevel 1 (
    echo [ERROR] Build failed.
    pause
    exit /b 1
)

echo(
echo ============================================================
echo  Build complete!
echo  Executable: dist\DecartLivestreamStudio\DecartLivestreamStudio.exe
echo ============================================================
pause
endlocal
