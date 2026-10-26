@echo off
setlocal
cd /d "%~dp0"
set "CLAUDE_MODE=true"
for /f "usebackq tokens=1,2 delims== " %%A in (`findstr /b /i "CLAUDE_MODE" "capri_config.txt"`) do set "CLAUDE_MODE=%%B"
if /i "%CLAUDE_MODE%"=="false" goto console
where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw -3 -u main.py %* >> "capri.log" 2>&1
    goto :eof
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw -u main.py %* >> "capri.log" 2>&1
    goto :eof
)
:console
set "CAPRI_LAUNCHER=start.bat"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 main.py %*
) else (
    python main.py %*
)
if errorlevel 1 pause
endlocal
