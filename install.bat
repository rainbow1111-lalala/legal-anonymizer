@echo off
REM Legal Anonymizer - Windows install script

echo ========================================
echo Legal Anonymizer - install
echo ========================================

REM Check Python
echo.
echo Checking the Python version...
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python not found. Please install Python 3.7+ first.
    pause
    exit /b 1
)

python --version

REM Upgrade pip
echo.
echo Upgrading pip...
python -m pip install --upgrade pip

REM Install the base dependencies
echo.
echo Installing the base dependencies...
pip install -r requirements.txt

REM Ask whether to install OCR dependencies
echo.
set /p INSTALL_OCR="Install OCR support (for scanned PDFs)? (y/n, default n): "
if "%INSTALL_OCR%"=="" set INSTALL_OCR=n

if /i "%INSTALL_OCR%"=="y" (
    echo Installing OCR dependencies...
    pip install pillow pytesseract
    echo.
    echo Note: you also need to install the Tesseract OCR engine
    echo Download from: https://github.com/UB-Mannheim/tesseract/wiki
)

REM Ask whether to run the tests
echo.
set /p RUN_TEST="Run the tests? (y/n, default y): "
if "%RUN_TEST%"=="" set RUN_TEST=y

if /i "%RUN_TEST%"=="y" (
    echo.
    echo Running the tests...
    python test.py
)

echo.
echo ========================================
echo Installation complete!
echo ========================================
echo.
echo Quick start:
echo   Show help:        python cli.py --help
echo   Anonymize a file: python cli.py anonymize input.pdf -o output.pdf
echo   Analyze a file:   python cli.py analyze input.pdf
echo   List the types:   python cli.py list-types
echo.
echo See the examples\ directory for more examples
echo.
pause
