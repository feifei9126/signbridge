@echo off
REM SignBridge Demo 2.1.1 - double-click to start.
setlocal
title SignBridge Demo 2.1.1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0serve.ps1"
if errorlevel 1 pause
endlocal
