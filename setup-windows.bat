@echo off
cd /d "%~dp0"
if not exist ".setup-venv\Scripts\python.exe" python -m venv .setup-venv
if errorlevel 1 goto :error
.setup-venv\Scripts\python.exe -c "import playwright" >nul 2>nul
if errorlevel 1 .setup-venv\Scripts\pip.exe install -r requirements.txt
if errorlevel 1 goto :error
.setup-venv\Scripts\python.exe -m playwright install chromium
if errorlevel 1 goto :error
.setup-venv\Scripts\python.exe scripts\setup_wizard.py
goto :eof
:error
echo Setup failed. Check Python and network access, then try again.
pause
