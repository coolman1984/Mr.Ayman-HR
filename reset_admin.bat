@echo off
title Break Area Management System - Reset administrator password
cd /d "%~dp0"
set "PY=%~dp0runtime\python\python.exe"
if not exist "%PY%" set "PY=python"
echo This gives the administrator account a new temporary password.
echo Use it only when the administrator password is lost.
echo.
pause
"%PY%" "%~dp0server\auth.py" reset-admin
echo.
pause
