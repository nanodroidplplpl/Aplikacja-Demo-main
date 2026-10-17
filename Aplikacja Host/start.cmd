@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo Brak srodowiska .venv - uruchom najpierw Skrypty\instaluj-host.ps1
    pause
    exit /b 1
)
.venv\Scripts\python.exe host.py %*
if errorlevel 1 pause
