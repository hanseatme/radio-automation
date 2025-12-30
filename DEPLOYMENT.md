# RadioPro - Plesk Deployment Anleitung

## Voraussetzungen

- Plesk Server mit Docker-Extension
- Mindestens 1GB RAM empfohlen
- Offene Ports: 8080 (Web), 8000 (Stream), 9999 (Mikrofon)

---

## Schritt 1: Image bauen

Auf deinem lokalen Rechner oder dem Server:

```bash
# In das Projektverzeichnis wechseln
cd /pfad/zu/stream_server

# Docker Image bauen
docker build -t radio-automation:latest .

# Image als .tar exportieren (fuer Upload zu Plesk)
docker save radio-automation:latest -o radio-automation.tar
```

---

## Schritt 2: Verzeichnisse auf dem Server erstellen

Erstelle die notwendigen Ordner auf deinem Server:

```bash
# Beispiel-Pfade (anpassen!)
mkdir -p /var/www/vhosts/deinedomain.de/radio/media
mkdir -p /var/www/vhosts/deinedomain.de/radio/data

# Media-Unterordner erstellen
mkdir -p /var/www/vhosts/deinedomain.de/radio/media/{music,jingles,promos,ads,random-moderation,planned-moderation,musicbeds}

# Berechtigungen setzen
chmod -R 755 /var/www/vhosts/deinedomain.de/radio
```

---

## Schritt 3: In Plesk deployen

### Option A: Via Plesk Docker UI

1. Gehe zu **Docker** in Plesk
2. Klicke auf **Image hinzufuegen** > **Aus Datei importieren**
3. Lade `radio-automation.tar` hoch
4. Klicke auf **Container erstellen**
5. Konfiguriere den Container:

**Port-Mapping:**
| Container Port | Host Port | Beschreibung |
|---------------|-----------|--------------|
| 8080 | 8080 | Web Admin |
| 8000 | 8000 | Stream |
| 9999 | 9999 | Mikrofon |

**Volume-Mapping:**
| Container Pfad | Host Pfad |
|---------------|-----------|
| /media | /var/www/vhosts/deinedomain.de/radio/media |
| /data | /var/www/vhosts/deinedomain.de/radio/data |

**Umgebungsvariablen:**
| Variable | Wert |
|----------|------|
| FLASK_ENV | production |
| SECRET_KEY | (langer zufaelliger String) |
| ADMIN_USERNAME | admin |
| ADMIN_PASSWORD | (sicheres Passwort) |
| TZ | Europe/Berlin |

### Option B: Via docker-compose

1. Lade `docker-compose.production.yml` und `.env.production.example` auf den Server
2. Benenne `.env.production.example` in `.env` um und passe die Werte an
3. Fuehre aus:

```bash
# Image laden (falls als .tar hochgeladen)
docker load -i radio-automation.tar

# Container starten
docker-compose -f docker-compose.production.yml up -d
```

---

## Schritt 4: Firewall konfigurieren

Oeffne die benoetigten Ports in der Firewall:

```bash
# UFW (Ubuntu/Debian)
ufw allow 8080/tcp  # Web Admin
ufw allow 8000/tcp  # Stream
ufw allow 9999/tcp  # Mikrofon

# oder firewalld (CentOS/RHEL)
firewall-cmd --permanent --add-port=8080/tcp
firewall-cmd --permanent --add-port=8000/tcp
firewall-cmd --permanent --add-port=9999/tcp
firewall-cmd --reload
```

---

## Schritt 5: Zugriff testen

- **Web Admin:** http://deine-server-ip:8080
- **Stream URL:** http://deine-server-ip:8000/stream
- **Login:** Mit den konfigurierten Admin-Zugangsdaten

---

## Port-Uebersicht

| Port | Protokoll | Verwendung |
|------|-----------|------------|
| **8080** | HTTP | Web-Admin-Interface |
| **8000** | HTTP | Icecast Stream (Listener) |
| **9999** | TCP | Live-Mikrofon Input (Butt, etc.) |

---

## Reverse Proxy (Optional)

Fuer HTTPS mit einer Domain, richte einen Reverse Proxy in Plesk ein:

### Nginx Proxy-Konfiguration:

```nginx
# Fuer domain.de -> Web Admin
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

# Fuer stream.domain.de -> Icecast
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_buffering off;  # Wichtig fuer Streaming!
}
```

---

## Troubleshooting

### Container startet nicht
```bash
# Logs anzeigen
docker logs radio-automation

# Container Status pruefen
docker ps -a
```

### Keine Verbindung zum Stream
- Pruefe ob Port 8000 offen ist: `netstat -tlnp | grep 8000`
- Pruefe Firewall-Regeln

### Datenbank-Fehler
- Stelle sicher, dass der data-Ordner beschreibbar ist
- Pruefe Berechtigungen: `ls -la /pfad/zum/data`

### Media-Dateien werden nicht gefunden
- Pruefe Volume-Mapping im Container
- Stelle sicher, dass Unterordner existieren (music, jingles, etc.)

---

## Backup

Sichere regelmaessig:
- `/pfad/zum/data/` (Datenbank)
- `/pfad/zum/media/` (Audiodateien)

```bash
# Beispiel Backup-Script
tar -czf radio-backup-$(date +%Y%m%d).tar.gz \
    /var/www/vhosts/deinedomain.de/radio/data \
    /var/www/vhosts/deinedomain.de/radio/media
```

---

## Updates

```bash
# Neues Image bauen und hochladen
docker build -t radio-automation:latest .
docker save radio-automation:latest -o radio-automation.tar

# Auf Server: Container stoppen und neu starten
docker stop radio-automation
docker rm radio-automation
docker load -i radio-automation.tar
docker-compose -f docker-compose.production.yml up -d
```
