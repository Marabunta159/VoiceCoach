@echo off
REM Startet VoiceCoach innerhalb der isolierten venv
if not exist "venv\Scripts\activate.bat" (
    echo [FEHLER] venv nicht gefunden.
    echo Bitte zuerst setup.bat ausfuehren!
    pause & exit /b 1
)
call venv\Scripts\activate.bat
python app.py
pause