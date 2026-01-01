@echo off
setlocal enabledelayedexpansion
echo ============================================
echo RadioPro - Docker Image fuer Plesk bauen
echo ============================================
echo.

REM Zum Projektverzeichnis wechseln
cd /d "%~dp0"

REM Version manuell setzen (sollte mit app/__init__.py VERSION synchron gehalten werden)
echo [0/4] Extrahiere Version...
set VERSION=2.0.14
echo Version: !VERSION!
echo.
echo WICHTIG: Stelle sicher dass VERSION in app/__init__.py auch !VERSION! ist!
echo.

echo [1/4] Baue Docker Image...
docker build -t radio-automation:latest -t radio-automation:!VERSION! .

if %ERRORLEVEL% NEQ 0 (
    echo FEHLER: Docker Build fehlgeschlagen!
    pause
    exit /b 1
)

echo.
echo [2/4] Exportiere Image als .tar Datei...
docker save radio-automation:latest radio-automation:!VERSION! -o radio-automation-v!VERSION!-plesk.tar

if %ERRORLEVEL% NEQ 0 (
    echo FEHLER: Image-Export fehlgeschlagen!
    pause
    exit /b 1
)

echo.
echo [3/4] Verschiebe Build in builds/ Verzeichnis...
if not exist builds mkdir builds
move /Y radio-automation-v!VERSION!-plesk.tar builds\

if %ERRORLEVEL% NEQ 0 (
    echo FEHLER: Verschieben fehlgeschlagen!
    pause
    exit /b 1
)

echo.
echo [4/4] Fertig!
echo.
echo ============================================
echo Die folgenden Dateien zum Server hochladen:
echo ============================================
echo.
echo   1. builds\radio-automation-v!VERSION!-plesk.tar  (Docker Image mit Version !VERSION!)
echo   2. docker-compose.production.yml
echo   3. .env.production.example     (als .env umbenennen und anpassen)
echo   4. DEPLOYMENT.md               (Anleitung)
echo.
echo Groesse des Images:
for %%A in (builds\radio-automation-v!VERSION!-plesk.tar) do echo   %%~zA Bytes (%%~nxA)
echo.
echo WICHTIG: Das Docker Image enthaelt folgende Tags:
echo   - radio-automation:latest
echo   - radio-automation:!VERSION!
echo.
echo ============================================
pause
