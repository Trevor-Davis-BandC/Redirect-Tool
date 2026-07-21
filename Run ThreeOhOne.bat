@echo off
REM Double-click this file to launch ThreeOhOne.
REM First run sets up a private Python environment and installs dependencies;
REM later runs start almost instantly.

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found on this computer.
    echo Install it from https://www.python.org/downloads/ ^(check "Add python.exe to PATH" during install^) and try again.
    pause
    exit /b 1
)

if not exist ".venv" (
    echo Setting up ThreeOhOne for the first time ^(this can take a minute^)...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

REM Skip Streamlit's first-run "welcome email" prompt, which would otherwise
REM block this window waiting for input.
if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
    echo [general] > "%USERPROFILE%\.streamlit\credentials.toml"
    echo email = "" >> "%USERPROFILE%\.streamlit\credentials.toml"
)

echo Checking dependencies...
python -m pip install -q --upgrade pip
pip install -q -r requirements.txt

echo Starting ThreeOhOne... your browser will open automatically.
streamlit run app.py

echo.
echo ThreeOhOne has stopped.
pause
