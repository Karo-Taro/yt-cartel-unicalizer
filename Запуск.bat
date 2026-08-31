@echo off
rem Soderzhimoe etogo fayla namerenno tolko na latinice.
rem cmd chitaet .bat v kodovoy stranice OEM, i kirillica vnutri lomaet razbor.
cd /d "%~dp0"

where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "run.pyw"
    exit /b 0
)

where py >nul 2>nul
if %errorlevel%==0 (
    start "" py -3 "run.pyw"
    exit /b 0
)

echo.
echo   Python not found.
echo.
echo   Install Python 3.10 or newer from https://python.org
echo   and enable "Add Python to PATH" during setup.
echo.
echo   See "PROCHTI MENYA.md" for details.
echo.
pause
