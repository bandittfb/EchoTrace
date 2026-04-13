@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 goto error
)
call .venv\Scripts\activate.bat
.venv\Scripts\python.exe -c "import PySide6, faster_whisper, docx, fpdf" 2>nul
if errorlevel 1 (
    echo Installing dependencies...
    pip install -r requirements.txt
    if errorlevel 1 goto error
)
.venv\Scripts\python.exe transcribe_app.py
if errorlevel 1 goto error
exit /b 0

:error
echo.
echo ======================================
echo  Something went wrong. See above.
echo ======================================
pause
