@echo off
echo ============================================
echo RadioPro - Docker Image fuer Plesk bauen
echo ============================================
echo.

REM Zum Projektverzeichnis wechseln
cd /d "%~dp0"

echo [1/3] Baue Docker Image...
docker build -t radio-automation:latest .

if %ERRORLEVEL% NEQ 0 (
    echo FEHLER: Docker Build fehlgeschlagen!
    pause
    exit /b 1
)

echo.
echo [2/3] Exportiere Image als .tar Datei...
docker save radio-automation:latest -o radio-automation.tar

if %ERRORLEVEL% NEQ 0 (
    echo FEHLER: Image-Export fehlgeschlagen!
    pause
    exit /b 1
)

echo.
echo [3/3] Fertig!
echo.
echo ============================================
echo Die folgenden Dateien zum Server hochladen:
echo ============================================
echo.
echo   1. radio-automation.tar        (Docker Image)
echo   2. docker-compose.production.yml
echo   3. .env.production.example     (als .env umbenennen und anpassen)
echo   4. DEPLOYMENT.md               (Anleitung)
echo.
echo Groesse des Images:
for %%A in (radio-automation.tar) do echo   %%~zA Bytes (%%A)
echo.
echo ============================================
pause
