#!/bin/bash
# Legal Anonymizer - install script

set -e

echo "========================================"
echo "Legal Anonymizer - install"
echo "========================================"

# Detect the Python version
echo ""
echo "Checking the Python version..."
if command -v python3 &> /dev/null; then
    PYTHON_CMD=python3
elif command -v python &> /dev/null; then
    PYTHON_CMD=python
else
    echo "Error: Python not found. Please install Python 3.7+ first."
    exit 1
fi

PYTHON_VERSION=$($PYTHON_CMD --version | cut -d' ' -f2)
echo "  Python version: $PYTHON_VERSION"

# Create a virtual environment (optional)
echo ""
read -p "Create a virtual environment? (y/n, default n): " CREATE_VENV
CREATE_VENV=${CREATE_VENV:-n}

if [ "$CREATE_VENV" = "y" ] || [ "$CREATE_VENV" = "Y" ]; then
    echo "Creating the virtual environment..."
    $PYTHON_CMD -m venv .venv
    echo "Activating the virtual environment..."
    if [[ "$OSTYPE" == "darwin"* ]] || [[ "$OSTYPE" == "linux-gnu"* ]]; then
        source .venv/bin/activate
        PYTHON_CMD=.venv/bin/python
        PIP_CMD=.venv/bin/pip
    else
        echo "On Windows, activate the virtual environment manually: .venv\Scripts\activate"
    fi
    echo "Virtual environment created"
else
    PIP_CMD=pip
fi

# Upgrade pip
echo ""
echo "Upgrading pip..."
$PYTHON_CMD -m pip install --upgrade pip

# Install the base dependencies
echo ""
echo "Installing the base dependencies..."
$PIP_CMD install -r requirements.txt

# Ask whether to install OCR dependencies
echo ""
read -p "Install OCR support (for scanned PDFs)? (y/n, default n): " INSTALL_OCR
INSTALL_OCR=${INSTALL_OCR:-n}

if [ "$INSTALL_OCR" = "y" ] || [ "$INSTALL_OCR" = "Y" ]; then
    echo "Installing OCR dependencies..."
    $PIP_CMD install pillow pytesseract

    echo ""
    echo "Note: you also need to install the Tesseract OCR engine:"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "  macOS: brew install tesseract"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        echo "  Ubuntu/Debian: sudo apt install tesseract-ocr"
    else
        echo "  Windows: download and install from https://github.com/UB-Mannheim/tesseract/wiki"
    fi
fi

# Run the tests
echo ""
read -p "Run the tests? (y/n, default y): " RUN_TEST
RUN_TEST=${RUN_TEST:-y}

if [ "$RUN_TEST" = "y" ] || [ "$RUN_TEST" = "Y" ]; then
    echo ""
    echo "Running the tests..."
    $PYTHON_CMD test.py
fi

echo ""
echo "========================================"
echo "Installation complete!"
echo "========================================"
echo ""
echo "Quick start:"
echo "  Show help:       $PYTHON_CMD cli.py --help"
echo "  Anonymize a file: $PYTHON_CMD cli.py anonymize input.pdf -o output.pdf"
echo "  Analyze a file:   $PYTHON_CMD cli.py analyze input.pdf"
echo "  List the types:   $PYTHON_CMD cli.py list-types"
echo ""
echo "See the examples/ directory for more examples"
echo ""
