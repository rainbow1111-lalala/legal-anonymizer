@echo off
chcp 65001 >nul 2>&1
title Legal Anonymizer - environment setup
cd /d "%~dp0"

echo.
echo   ========================================
echo     Legal Anonymizer - auto env setup
echo        by Lingbao Huang
echo   ========================================
echo.

:: Check whether the virtual environment already exists
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -c "import flask, fitz, docx" >nul 2>&1
    if not errorlevel 1 (
        echo   [OK] Environment ready; skipping installation
        echo.
        goto :end
    )
    echo   [..] Environment incomplete; reinstalling dependencies...
    goto :install_deps
)

:: Detect Python
set PYTHON_CMD=
where python3 >nul 2>&1 && set PYTHON_CMD=python3
if "%PYTHON_CMD%"=="" (
    where python >nul 2>&1 && set PYTHON_CMD=python
)
if "%PYTHON_CMD%"=="" (
    echo   [!] Python not found. Please install it first:
    echo.
    echo       1. Go to https://www.python.org/downloads/
    echo       2. Download the latest version
    echo       3. Be sure to check "Add Python to PATH" during installation
    echo       4. Run this script again after installing
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('%PYTHON_CMD% --version 2^>^&1') do set PYVER=%%i
echo   [OK] %PYVER%

:: Create the virtual environment
echo   [..] Creating the isolated runtime environment...
%PYTHON_CMD% -m venv .venv
if errorlevel 1 (
    echo   [!] Virtual environment creation failed; using global Python
    goto :install_global
)
echo   [OK] Runtime environment ready

:install_deps
echo.
echo   [..] Installing dependency packages (about 3-5 minutes the first time)...
.venv\Scripts\pip.exe install --upgrade pip -q >nul 2>&1
.venv\Scripts\pip.exe install -r requirements.txt -q
if errorlevel 1 (
    echo   [!] Some dependencies failed to install; please check the error messages
) else (
    echo   [OK] Dependencies installed
)

:: Verify
echo.
.venv\Scripts\python.exe -c "import flask, fitz, docx" >nul 2>&1
if not errorlevel 1 (
    echo   [OK] Core components verified
) else (
    echo   [!] Some core dependencies were not installed successfully
)
goto :end

:install_global
echo.
echo   [..] Installing dependency packages into global Python...
%PYTHON_CMD% -m pip install -r requirements.txt -q
echo   [OK] Installation complete

:end
:: Create the directories
if not exist inbox mkdir inbox
if not exist output mkdir output
if not exist uploads mkdir uploads

echo.
echo   ========================================
echo     Installation complete!
echo   ========================================
echo.
pause
