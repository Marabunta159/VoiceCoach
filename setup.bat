@echo off
setlocal EnableDelayedExpansion
echo.
echo ╔══════════════════════════════════════════╗
echo ║       VoiceCoach - Setup                 ║
echo ║  Erstellt isolierte Python-Umgebung      ║
echo ╚══════════════════════════════════════════╝
echo.

REM ── Python prüfen ──────────────────────────────────────────
python --version >NUL 2>&1
if errorlevel 1 (
    echo [FEHLER] Python wurde nicht gefunden!
    echo Bitte von https://www.python.org/downloads/ installieren.
    echo Wichtig: Haken bei "Add Python to PATH" setzen!
    pause & exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo [OK] Python %PY_VER% gefunden.

REM ── Virtuelle Umgebung erstellen ───────────────────────────
if exist "venv\" (
    echo [INFO] venv\ existiert bereits, wird übersprungen.
) else (
    echo [....] Erstelle virtuelle Umgebung in .\venv\ ...
    python -m venv venv
    if errorlevel 1 (
        echo [FEHLER] venv konnte nicht erstellt werden.
        pause & exit /b 1
    )
    echo [OK] venv erstellt.
)

REM ── venv aktivieren ────────────────────────────────────────
call venv\Scripts\activate.bat
echo [OK] venv aktiviert.

REM ── pip updaten ────────────────────────────────────────────
echo [....] Aktualisiere pip ...
python -m pip install --upgrade pip --quiet

REM ── Abhängigkeiten installieren ────────────────────────────
echo.
echo [....] Installiere Pakete (kann 2-5 Minuten dauern) ...
echo.

pip install faster-whisper
pip install pyaudiowpatch
pip install sounddevice
pip install numpy
pip install requests
pip install keyboard

echo.
echo [OK] Alle Pakete installiert.

REM ── FFmpeg prüfen ──────────────────────────────────────────
echo.
ffmpeg -version >NUL 2>&1
if errorlevel 1 (
    echo [WARNUNG] FFmpeg nicht im PATH gefunden!
    echo faster-whisper benötigt FFmpeg für manche Audioformate.
    echo.
    echo Schnellste Installation via winget:
    echo   winget install Gyan.FFmpeg
    echo.
    echo Oder manuell: https://ffmpeg.org/download.html
    echo Nach der Installation dieses Fenster neu öffnen.
) else (
    echo [OK] FFmpeg gefunden.
)

REM ── Modell-Hinweis ─────────────────────────────────────────
echo.
echo [INFO] Das Whisper-Modell wird beim ersten Start
echo        automatisch von HuggingFace heruntergeladen.
echo        (~1.6 GB, nur einmalig)

REM ── Abschluss ──────────────────────────────────────────────
echo.
echo ╔══════════════════════════════════════════╗
echo ║        Setup abgeschlossen!              ║
echo ║                                          ║
echo ║  Nächste Schritte:                       ║
echo ║  1. config.py öffnen                     ║
echo ║  2. API_PROVIDER setzen:                 ║
echo ║     "openrouter" oder "gemini"           ║
echo ║  3. API-Key eintragen                    ║
echo ║  4. Starten mit: start.bat               ║
echo ╚══════════════════════════════════════════╝
echo.
pause