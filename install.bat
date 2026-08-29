@echo off
REM 兼容旧入口：统一交给经过验证的一键安装器。
cd /d "%~dp0"
call setup.bat
exit /b %errorlevel%
