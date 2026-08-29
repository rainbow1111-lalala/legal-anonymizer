@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
title 法律文档脱敏工具 - 环境安装
cd /d "%~dp0"
set "LOG=.setup.log"
echo setup started: %date% %time%>"%LOG%"

echo.
echo   ========================================
echo     法律文档脱敏工具 - 环境自动安装
echo   ========================================
echo.

set "VENV_PY=.venv\Scripts\python.exe"
if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import sys; assert sys.version_info ^>= (3,10)" >nul 2>&1
    if not errorlevel 1 goto :reuse_venv
    echo   [..] 旧环境的 Python 版本过低，正在保留备份...
    ren .venv ".venv.incompatible.%RANDOM%" >>"%LOG%" 2>&1
    if errorlevel 1 goto :backup_failed
)

set "PYTHON_CMD="
py -3.11 -c "import sys; assert sys.version_info ^>= (3,10)" >nul 2>&1 && set "PYTHON_CMD=py -3.11"
if not defined PYTHON_CMD py -3.10 -c "import sys; assert sys.version_info ^>= (3,10)" >nul 2>&1 && set "PYTHON_CMD=py -3.10"
if not defined PYTHON_CMD python3 -c "import sys; assert sys.version_info ^>= (3,10)" >nul 2>&1 && set "PYTHON_CMD=python3"
if not defined PYTHON_CMD python -c "import sys; assert sys.version_info ^>= (3,10)" >nul 2>&1 && set "PYTHON_CMD=python"
if not defined PYTHON_CMD goto :no_python

for /f "tokens=*" %%i in ('%PYTHON_CMD% --version 2^>^&1') do echo   [OK] 使用 %%i
echo   [..] 创建独立运行环境...
%PYTHON_CMD% -m venv .venv >>"%LOG%" 2>&1
if errorlevel 1 goto :venv_failed

:reuse_venv
echo   [..] 更新安装工具...
"%VENV_PY%" -m pip install --upgrade pip setuptools wheel >>"%LOG%" 2>&1
if errorlevel 1 goto :pip_failed

echo   [..] 1/3 安装核心组件（网页、PDF、Word）...
"%VENV_PY%" -m pip install -r requirements-core.txt >>"%LOG%" 2>&1
if errorlevel 1 goto :core_failed
"%VENV_PY%" -c "import flask, fitz, docx, PIL, reportlab" >>"%LOG%" 2>&1
if errorlevel 1 goto :core_failed
echo   [OK] 核心组件已就绪

set "OCR_READY=0"
echo   [..] 2/3 安装 RapidOCR...
"%VENV_PY%" -m pip install -r requirements-ocr.txt >>"%LOG%" 2>&1
if errorlevel 1 goto :ocr_warning
"%VENV_PY%" -c "import rapidocr, onnxruntime" >>"%LOG%" 2>&1
if errorlevel 1 goto :ocr_warning
set "OCR_READY=1"
echo   [OK] RapidOCR 已就绪
goto :install_ai
:ocr_warning
echo   [!] RapidOCR 未安装；文字 PDF 和 Word 仍可使用，详情见 .setup.log

:install_ai
set "AI_READY=0"
echo   [..] 3/3 安装中文 NER 运行时...
"%VENV_PY%" -m pip install -r requirements-ai.txt >>"%LOG%" 2>&1
if errorlevel 1 goto :ai_warning
"%VENV_PY%" -c "import torch, transformers" >>"%LOG%" 2>&1
if errorlevel 1 goto :ai_warning
set "AI_READY=1"
echo   [OK] 中文 NER 运行时已就绪
goto :success
:ai_warning
echo   [!] NER 运行时未安装；规则识别仍可使用，详情见 .setup.log

:success
if not exist inbox mkdir inbox
if not exist output mkdir output
if not exist uploads mkdir uploads
for /f "tokens=*" %%i in ('"%VENV_PY%" -c "import platform; print(platform.python_version())"') do set "PYVER=%%i"
(
  echo PYTHON_VERSION=%PYVER%
  echo CORE_READY=1
  echo OCR_READY=%OCR_READY%
  echo AI_READY=%AI_READY%
)> .setup_status
echo.
echo   [OK] 基础环境安装成功
echo.
pause
exit /b 0

:no_python
echo   [X] 需要 Python 3.10 或更高版本。
echo       请从 https://www.python.org/downloads/ 安装，务必勾选 Add Python to PATH。
goto :failed
:backup_failed
echo   [X] 无法备份旧环境，请关闭正在运行的工具后重试。
goto :failed
:venv_failed
echo   [X] 虚拟环境创建失败，详情见 .setup.log。
goto :failed
:pip_failed
echo   [X] pip 更新失败，详情见 .setup.log。
goto :failed
:core_failed
echo   [X] 核心组件安装失败，工具不会强行启动，详情见 .setup.log。
:failed
echo.
pause
exit /b 1
