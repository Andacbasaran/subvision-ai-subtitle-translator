@echo off
chcp 65001 >nul
title SubVision AI - Anlik Ekran Altyazi Cevirici (EN - TR)
cd /d "%~dp0.."

if exist "%~dp0..\SubVisionAI.exe" (
    start "" "%~dp0..\SubVisionAI.exe"
    exit /b 0
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_bootstrap.ps1"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [HATA] Kurulum veya baslatma sirasinda bir sorun olustu.
    pause
)
