@echo off
title Break Area Management System - Server
cd /d "%~dp0"

set "PY=%~dp0runtime\python\python.exe"
if not exist "%PY%" (
  where python >nul 2>&1 && set "PY=python"
)
if not exist "%PY%" if not "%PY%"=="python" (
  echo Python was not found. The folder runtime\python is missing from this copy of the system.
  pause
  exit /b 1
)

"%PY%" "%~dp0server\app.py"
if errorlevel 1 (
  echo.
  echo The server stopped with an error. Details are in data\logs\server.log
  pause
)
