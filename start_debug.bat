@echo off
title Nifty Bot FINAL - Fixed
color 0A
echo ========================================
echo Nifty Bot - Python Auto Detect
echo ========================================
echo Current folder: %cd%
echo.
set PYTHON_CMD=py
py --version >nul 2>&1
if %errorlevel% NEQ 0 (
    set PYTHON_CMD=python
)
echo Using: %PYTHON_CMD%
%PYTHON_CMD% --version
echo.
echo Checking files...
if exist bot_live_1lot.py (echo FOUND: bot_live_1lot.py) else (echo NOT FOUND: bot_live_1lot.py)
if exist config.json (echo FOUND: config.json) else (echo NOT FOUND: config.json)
echo.
echo Installing libs...
%PYTHON_CMD% -m pip install smartapi-python pyotp requests --quiet
echo.
echo Starting Bot...
echo ========================================
%PYTHON_CMD% bot_live_1lot.py
echo.
echo Bot stopped.
pause
