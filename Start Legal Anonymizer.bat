@echo off
chcp 65001 >nul 2>&1
title Legal Anonymizer - by Lingbao Huang
cd /d "%~dp0"

echo.
echo   ========================================
echo     Legal Anonymizer - starting...
echo        by Lingbao Huang
echo   ========================================
echo.

:: Detect Python
set PYTHON_CMD=
where python3 >nul 2>&1 && set PYTHON_CMD=python3
if "%PYTHON_CMD%"=="" (
    where python >nul 2>&1 && set PYTHON_CMD=python
)
if "%PYTHON_CMD%"=="" (
    echo   [!] Python not found. Please install it first:
    echo.
    echo       Download and install from https://www.python.org
    echo       Be sure to check "Add Python to PATH" during installation
    echo.
    echo   After installing, just double-click this file again.
    echo.
    pause
    exit /b 1
)

:: Verify the Python version
for /f "tokens=*" %%i in ('%PYTHON_CMD% --version 2^>^&1') do set PYVER=%%i
echo   [OK] %PYVER%

:: Check whether a virtual environment exists
if exist ".venv\Scripts\python.exe" (
    set PYTHON_CMD=.venv\Scripts\python.exe
    echo   [OK] Using the virtual environment
)

:: Check and install dependencies
echo   [..] Checking dependencies...
%PYTHON_CMD% -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo   [..] First run: installing dependencies (one time only)...
    echo   [..] This may take a few minutes; please wait...
    %PYTHON_CMD% -m pip install -q -r requirements.txt
    if errorlevel 1 (
        echo   [!] Dependency install failed; trying --user mode...
        %PYTHON_CMD% -m pip install --user -q -r requirements.txt
    )
    echo   [OK] Dependencies installed
) else (
    echo   [OK] Dependencies ready
)

:: Create the required directories
if not exist inbox mkdir inbox
if not exist output mkdir output
if not exist uploads mkdir uploads

:: Set the HuggingFace mirror (for mainland China)
if "%HF_ENDPOINT%"=="" set HF_ENDPOINT=https://hf-mirror.com

:: First-launch prompt: whether to handle English documents
if not exist .user_config (
    echo.
    echo   ========================================
    echo     First-launch setup (one time only)
    echo   ========================================
    echo.
    echo   By default the tool detects Chinese sensitive information.
    echo   Enable English detection too? (requires downloading the 2.6 GB English model)
    echo.
    set /p ENABLE_EN="  Do you frequently handle English / cross-border legal documents? (y/n, default n): "
    if /i "%ENABLE_EN%"=="y" (
        echo ENABLE_OPENAI=1>.user_config
        echo   [OK] English model enabled
    ) else (
        echo ENABLE_OPENAI=0>.user_config
        echo   [OK] Chinese-only mode
    )
    echo.
)

:: Read the config
for /f "tokens=2 delims==" %%i in (.user_config) do set ENABLE_OPENAI=%%i
if "%ENABLE_OPENAI%"=="" set ENABLE_OPENAI=0

:: Pre-download the AI models (first time)
if not exist .models_downloaded (
    echo.
    echo   ========================================
    echo     Downloading AI models (first time only)
    echo   ========================================
    echo.
    echo   Downloading the Chinese NER model (about 400 MB)...
    echo   This is the core detection capability; please wait 1-3 minutes...
    echo.
    %PYTHON_CMD% -c "import os; os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com'); from transformers import AutoTokenizer, AutoModelForTokenClassification; AutoTokenizer.from_pretrained('uer/roberta-base-finetuned-cluener2020-chinese'); AutoModelForTokenClassification.from_pretrained('uer/roberta-base-finetuned-cluener2020-chinese'); print('  [OK] Chinese NER model download complete')"

    if "%ENABLE_OPENAI%"=="1" (
        echo.
        echo   Downloading the English model (about 2.6 GB, please wait 5-15 minutes)...
        %PYTHON_CMD% -c "import os; os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com'); from transformers import AutoTokenizer, AutoModelForTokenClassification; AutoTokenizer.from_pretrained('openai/privacy-filter'); AutoModelForTokenClassification.from_pretrained('openai/privacy-filter'); print('  [OK] English model download complete')"
    )
    echo.>.models_downloaded
    echo   [OK] All models are ready
    echo.
)

:: Start the service (web_app.py opens the browser automatically)
echo.
echo   [..] Starting the service...
echo.
echo   ========================================
echo     The browser will open automatically; work in the web page
echo.
echo     Close this window to stop the service
echo   ========================================
echo.

%PYTHON_CMD% web_app.py

echo.
echo   Service stopped.
pause
