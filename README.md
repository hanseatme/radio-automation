# Radio Automation Server

Ein vollständiger Docker-basierter Audiostreaming-Automation-Server mit Web-Verwaltungsoberfläche.

## Features

- **Automatische Rotation**: Musik, Jingles, Promos, Werbung und Moderationen nach konfigurierbaren Regeln
- **Sendungsplanung**: Sendungen zusammenstellen und zeitgesteuert abspielen
- **Icecast Streaming**: MP3-Stream auf Port 8000
- **Web-Admin-Interface**: Vollständige Verwaltung über den Browser
- **Echtzeit-Updates**: WebSocket-basierte Live-Anzeige des aktuellen Titels

## Schnellstart

### 1. Voraussetzungen

- Docker und Docker Compose installiert
- Mindestens 1GB RAM
- Freie Ports: 8080 (Admin), 8000 (Stream)

### 2. Installation

```bash
# Repository klonen oder Dateien kopieren
cd streamserver

# Container starten
docker-compose up -d

# Logs anzeigen
docker-compose logs -f
```

### 3. Zugang

- **Admin-Interface**: http://localhost:8080
- **Stream-URL**: http://localhost:8000/stream
- **Standard-Login**: admin / admin

## Verzeichnisstruktur

```
streamserver/
├── media/                  # Audio-Dateien (wird in Docker gemounted)
│   ├── music/             # Musiktitel
│   ├── promos/            # Promos
│   ├── jingles/           # Jingles
│   ├── ads/               # Werbung
│   ├── random-moderation/ # Zufällige Moderationen
│   └── planned-moderation/# Geplante Moderationen
└── data/                   # SQLite-Datenbank
```

## Musik hinzufügen

### Methode 1: Direkt in Ordner kopieren
```bash
# MP3-Dateien in den entsprechenden Ordner kopieren
cp /pfad/zu/musik/*.mp3 ./media/music/
```

### Methode 2: Über Web-Interface
1. Im Admin-Interface zu "Dateien" navigieren
2. Kategorie auswählen
3. Datei(en) hochladen

## Rotationsregeln

### Regeltypen

1. **Nach X Songs**: Fügt Element nach einer bestimmten Anzahl Musiktitel ein
   - Beispiel: "Jingle nach jedem 3. Song"

2. **Zur Minute**: Fügt Element zu einer bestimmten Minute jeder Stunde ein
   - Beispiel: "Nachrichten zur vollen Stunde (Minute 0)"

3. **Intervall**: Fügt Element alle X Minuten ein
   - Beispiel: "Werbung alle 15 Minuten"

### Zeiträume

Jede Regel kann auf bestimmte Zeiträume und Wochentage beschränkt werden:
- Startzeit und Endzeit
- Wochentage (Mo-So)

### Prioritäten

Bei mehreren gleichzeitig aktiven Regeln gewinnt die mit der höchsten Priorität.

## Sendungen erstellen

1. **Sendungen** → **Neue Sendung**
2. Dateien per Drag & Drop in die Sendung ziehen
3. Reihenfolge anpassen
4. Speichern

### Sendung planen

1. **Zeitplan** → **Neue Planung**
2. Sendung auswählen
3. Datum und Uhrzeit festlegen
4. Wiederholungstyp wählen:
   - Einmalig
   - Täglich
   - Wöchentlich

## Konfiguration

### Umgebungsvariablen

```yaml
# docker-compose.yml
environment:
  - SECRET_KEY=mein-geheimer-schluessel
  - ADMIN_USERNAME=admin
  - ADMIN_PASSWORD=mein-passwort
  - TZ=Europe/Berlin
```

### Passwort ändern

1. Im Admin-Interface zu "Einstellungen" navigieren
2. Aktuelles und neues Passwort eingeben
3. Speichern

## Stream-Integration

### VLC Player
```
vlc http://localhost:8000/stream
```

### HTML5 Audio
```html
<audio controls>
  <source src="http://localhost:8000/stream" type="audio/mpeg">
</audio>
```

### Winamp / Foobar2000
Stream-URL: `http://localhost:8000/stream`

## Wartung

### Logs anzeigen
```bash
docker-compose logs -f
```

### Container neustarten
```bash
docker-compose restart
```

### Datenbank-Backup
```bash
cp ./data/streamserver.db ./backup/
```

### Update
```bash
docker-compose pull
docker-compose up -d --build
```

## Fehlerbehebung

### Kein Audio-Stream
1. Prüfen ob MP3-Dateien in `/media/music/` vorhanden sind
2. Logs prüfen: `docker-compose logs liquidsoap`
3. Icecast-Status: http://localhost:8000

### Login funktioniert nicht
1. Standard-Credentials: admin / admin
2. Bei Änderungen: Container neu starten

### Dateien werden nicht erkannt
- Nur MP3-Dateien werden unterstützt
- Dateien werden alle 5 Minuten automatisch gescannt
- Alternativ: Seite "Dateien" öffnen für sofortigen Scan

## Technische Details

- **Backend**: Python 3.11 + Flask
- **Audio-Engine**: Liquidsoap
- **Streaming**: Icecast2
- **Datenbank**: SQLite
- **Frontend**: Bootstrap 5

## Lizenz

MIT License
