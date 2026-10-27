@echo off
cd /d "%~dp0prototype"
call npm.cmd run dev:workstation
if errorlevel 1 pause
