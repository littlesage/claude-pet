@echo off
rem Launch Claude Pet (duplicate launch is self-guarded)
cd /d "%~dp0"
where pythonw.exe >nul 2>&1 && (start "" pythonw.exe "pet.pyw" & exit /b)
where pyw.exe >nul 2>&1 && (start "" pyw.exe "pet.pyw" & exit /b)
echo Python not found. Install from https://www.python.org and retry.
pause
