#!/bin/bash
echo "============================================"
echo "RadioPro - Docker Image fuer Plesk bauen"
echo "============================================"
echo ""

# Zum Projektverzeichnis wechseln
cd "$(dirname "$0")"

echo "[1/3] Baue Docker Image..."
docker build -t radio-automation:latest .

if [ $? -ne 0 ]; then
    echo "FEHLER: Docker Build fehlgeschlagen!"
    exit 1
fi

echo ""
echo "[2/3] Exportiere Image als .tar Datei..."
docker save radio-automation:latest -o radio-automation.tar

if [ $? -ne 0 ]; then
    echo "FEHLER: Image-Export fehlgeschlagen!"
    exit 1
fi

echo ""
echo "[3/3] Fertig!"
echo ""
echo "============================================"
echo "Die folgenden Dateien zum Server hochladen:"
echo "============================================"
echo ""
echo "  1. radio-automation.tar        (Docker Image)"
echo "  2. docker-compose.production.yml"
echo "  3. .env.production.example     (als .env umbenennen und anpassen)"
echo "  4. DEPLOYMENT.md               (Anleitung)"
echo ""
echo "Groesse des Images:"
ls -lh radio-automation.tar 2>/dev/null | awk '{print "  " $5 " (" $9 ")"}'
echo ""
echo "============================================"
