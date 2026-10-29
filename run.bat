@echo off
setlocal enabledelayedexpansion
title Return & Refund Chaser Launcher

echo ========================================================
echo   Return & Refund Chaser - 1-Click Desktop Launcher
echo ========================================================
echo.

:: 1. Detect Python executable
set "PY_CMD="

py --version >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set "PY_CMD=py"
    goto :PYTHON_FOUND
)

python --version >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set "PY_CMD=python"
    goto :PYTHON_FOUND
)

python3 --version >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set "PY_CMD=python3"
    goto :PYTHON_FOUND
)

echo [ERROR] Python was not found on your system!
echo Please install Python 3.10 or newer from https://www.python.org/downloads/
echo (Ensure "Add Python to PATH" is checked during installation).
echo.
pause
exit /b 1

:PYTHON_FOUND
echo [OK] Detected Python: !PY_CMD!

:: 2. Check / Create Virtual Environment
if not exist ".venv\Scripts\activate.bat" (
    echo [INFO] Creating local virtual environment in .venv ...
    !PY_CMD! -m venv .venv
    if errorlevel 1 (
        echo [WARNING] Could not create virtual environment. Using system Python directly.
    )
)

if exist ".venv\Scripts\activate.bat" (
    echo [INFO] Activating virtual environment...
    call .venv\Scripts\activate.bat
    set "RUN_PY=python"
) else (
    set "RUN_PY=!PY_CMD!"
)

:: 3. Install dependencies
echo [INFO] Checking dependencies from requirements.txt ...
%RUN_PY% -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo [WARNING] Encountered an issue during dependency installation, proceeding anyway...
)

:: 4. Launch browser after a short delay
echo [INFO] Server starting at http://localhost:8000 ...
echo [INFO] Opening your web browser ...
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:8000"

:: 5. Launch FastAPI Backend + Pre-Built Frontend
%RUN_PY% main.py --server

pause
