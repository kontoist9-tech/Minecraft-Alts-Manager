@echo off
:: ─────────────────────────────────────────────────────────────
::  Minecraft Account Manager 2.0 — Installer for Windows
:: ─────────────────────────────────────────────────────────────
title Minecraft Account Manager 2.0 — Installer
color 0B

echo.
echo ══════════════════════════════════════════════════
echo   Minecraft Account Manager 2.0 — Installer
echo ══════════════════════════════════════════════════
echo.

:: Check Python
py --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found!
    echo.
    echo Please install Python 3.10+ from: https://www.python.org/downloads/
    echo IMPORTANT: Check "Add Python to PATH" during installation!
    echo.
    pause
    start https://www.python.org/downloads/
    exit /b 1
)

for /f "tokens=*" %%V in ('py --version 2^>^&1') do set PY_VER=%%V
echo [OK] %PY_VER% found

echo.
echo [..] Installing required packages...
echo.

py -m pip install --upgrade pip --quiet
py -m pip install customtkinter pillow requests minecraft-launcher-lib --quiet

if %errorlevel% neq 0 (
    echo [ERROR] Package installation failed!
    pause
    exit /b 1
)

echo.
echo [OK] All packages installed successfully!
echo.
echo [..] Launching Minecraft Account Manager...
echo.

py "%~dp0app.py"
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to start the app.
    echo Make sure Python 3.10+ is installed and all packages are available.
    pause
)
