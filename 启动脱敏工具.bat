@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
title 法律文档脱敏工具
cd /d "%~dp0"
set "PYTHON_CMD=.venv\Scripts\python.exe"

echo.
echo   ========================================
echo     法律文档脱敏工具 - 正在启动...
echo   ========================================
echo.

"%PYTHON_CMD%" -c "import sys; assert sys.version_info ^>= (3,10); import flask, fitz, docx, PIL, reportlab" >nul 2>&1
if errorlevel 1 (
    echo   [..] 首次运行或环境不完整，开始自动安装...
    call setup.bat
    if errorlevel 1 goto :failed
)

"%PYTHON_CMD%" -c "import sys; assert sys.version_info ^>= (3,10); import flask, fitz, docx, PIL, reportlab" >nul 2>&1
if errorlevel 1 goto :failed
for /f "tokens=*" %%i in ('"%PYTHON_CMD%" --version 2^>^&1') do echo   [OK] 运行环境就绪（%%i）

if not exist inbox mkdir inbox
if not exist output mkdir output
if not exist uploads mkdir uploads
if "%HF_ENDPOINT%"=="" set "HF_ENDPOINT=https://hf-mirror.com"

if not exist .user_config (
    echo ENABLE_OPENAI=0>.user_config
    echo   [OK] 默认启用中文本地识别；英文大模型可按 README 另行开启。
)
for /f "tokens=2 delims==" %%i in (.user_config) do set "ENABLE_OPENAI=%%i"
if "%ENABLE_OPENAI%"=="" set "ENABLE_OPENAI=0"

"%PYTHON_CMD%" -c "import torch, transformers" >nul 2>&1
if errorlevel 1 (
    echo   [!] NER 运行时未安装，本次使用规则识别；可重新运行 setup.bat。
) else (
    if not exist .cn_model_ready (
        echo   [..] 首次下载中文 NER 模型（约 400 MB）...
        "%PYTHON_CMD%" -c "import os; os.environ.setdefault('HF_ENDPOINT','https://hf-mirror.com'); from transformers import AutoTokenizer, AutoModelForTokenClassification; n='uer/roberta-base-finetuned-cluener2020-chinese'; AutoTokenizer.from_pretrained(n); AutoModelForTokenClassification.from_pretrained(n)"
        if not errorlevel 1 echo ready>.cn_model_ready
    )
)

echo.
echo   [..] 启动服务，关闭本窗口即可停止服务...
"%PYTHON_CMD%" web_app.py
echo.
echo   服务已停止。
pause
exit /b 0

:failed
echo.
echo   [X] 环境安装或验证失败，服务不会强行启动。
echo       请查看项目目录下的 .setup.log。
echo.
pause
exit /b 1
