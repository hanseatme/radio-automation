# RadioPro API Documentation

**Version:** 2.0.15
**Base URL:** `http://your-server:8080/api`

## Authentication

All API endpoints (except public ones) require authentication. You can authenticate in two ways:

### 1. Session Authentication (Browser)
If you're logged into the web interface, your browser session automatically authenticates API requests.

### 2. API Key Authentication (External Tools)
For external tools and scripts, use the API key generated in Settings > Integrationen > MCP Server.

**Header Options:**
```
X-API-Key: your-api-key
```
or
```
Authorization: Bearer your-api-key
```

**Example with curl:**
```bash
curl -X POST http://localhost:8080/api/skip \
  -H "X-API-Key: your-api-key"
```

**Example with Python:**
```python
import requests

headers = {"X-API-Key": "your-api-key"}
response = requests.post("http://localhost:8080/api/skip", headers=headers)
print(response.json())
```

**Unauthorized Response (401):**
```json
{
  "success": false,
  "error": "Authentication required",
  "message": "Please provide a valid API key via X-API-Key header or login via the web interface"
}
```

---

## Public Endpoints (No Authentication Required)

### Get Now Playing
```
GET /api/nowplaying
GET /api/nowplaying.json
```
Returns current track information.

**Response:**
```json
{
  "title": "Song Title",
  "artist": "Artist Name",
  "filename": "song.mp3",
  "category": "music",
  "duration": 180.5,
  "started_at": "2024-01-15T10:30:00"
}
```

### Get Now Playing (Plain Text)
```
GET /api/nowplaying.txt
```
Returns: `Artist Name - Song Title`

### Get Status
```
GET /api/status
```
Returns system status including current track and listener count.

---

## Playback Control

### Skip Current Track
```
POST /api/skip
```
Skips the currently playing track.

**Response:**
```json
{
  "success": true
}
```

### Queue Track
```
POST /api/queue
Content-Type: application/json

{
  "file_id": 123
}
```
Adds a track to the playback queue.

### Clear Queue
```
POST /api/queue/clear
```
Clears all queued tracks.

### Get Queue Status
```
GET /api/queue/status
```
Returns current queue with metadata.

**Response:**
```json
{
  "queue": [
    {
      "filename": "song.mp3",
      "title": "Song Title",
      "artist": "Artist",
      "duration": 180
    }
  ],
  "count": 1,
  "time_until_next": 45.2,
  "now_playing": {...}
}
```

### Remove Queue Item
```
DELETE /api/queue/remove/<index>
```
Removes item at specified index (0-based).

### Reorder Queue
```
POST /api/queue/reorder
Content-Type: application/json

{
  "order": [2, 0, 1, 3]
}
```
Reorders queue items by original indices.

### Insert Random from Category
```
POST /api/insert/<category>
```
Categories: `music`, `jingles`, `promos`, `ads`, `random-moderation`, `planned-moderation`

---

## Files

### Get Files by Category
```
GET /api/files/<category>
```

### Get All Files
```
GET /api/files/all
```
Returns all files grouped by category.

### Get Single File
```
GET /api/files/<file_id>
```

### Stream Audio File
```
GET /api/audio/<category>/<filename>
```
Streams the audio file for playback.

---

## Play History

### Get History
```
GET /api/history?limit=50
```

---

## Shows

### List Shows
```
GET /api/shows
```

### Get Show Details
```
GET /api/shows/<show_id>
```

### Play Show
```
POST /api/shows/<show_id>/play
```
Queues all items from the show.

### Stop Show
```
POST /api/shows/stop
```
Returns to automation mode.

---

## Rotation Rules & Schedules

### Get Rules
```
GET /api/rules
```

### Get Schedules
```
GET /api/schedules
```

---

## Settings

### Get Stream Settings
```
GET /api/stream-settings
```

### Update Stream Settings
```
POST /api/stream-settings
Content-Type: application/json

{
  "station_name": "My Radio",
  "crossfade_music_fade_in": 0.5,
  "crossfade_music_fade_out": 0.5
}
```

---

## Moderation Panel

### Get Status
```
GET /api/moderation/status
```

### Toggle Music Bed
```
POST /api/moderation/bed/toggle
Content-Type: application/json

{
  "enabled": true
}
```

### Set Bed Volume
```
POST /api/moderation/bed/volume
Content-Type: application/json

{
  "volume": 0.3
}
```
Volume: 0.0 - 1.0

### Toggle Ducking
```
POST /api/moderation/ducking/toggle
Content-Type: application/json

{
  "active": true
}
```

### Set Ducking Level
```
POST /api/moderation/ducking/level
Content-Type: application/json

{
  "level": 0.15
}
```

### Get Instant Jingles
```
GET /api/moderation/jingles
```

### Play Jingle
```
POST /api/moderation/jingles/<slot>/play
```
Slot: 1-9

### Configure Jingle Slot
```
POST /api/moderation/jingles/<slot>
Content-Type: application/json

{
  "audio_file_id": 123,
  "label": "Station ID",
  "color": "#ff0000"
}
```

### Set Jingle Volume
```
POST /api/moderation/jingle/volume
Content-Type: application/json

{
  "volume": 1.0
}
```

---

## Microphone

### Toggle Mic
```
POST /api/moderation/mic/toggle
Content-Type: application/json

{
  "enabled": true
}
```

### Set Mic Volume
```
POST /api/moderation/mic/volume
Content-Type: application/json

{
  "volume": 1.0
}
```

### Set Auto-Duck
```
POST /api/moderation/mic/auto-duck
Content-Type: application/json

{
  "enabled": true
}
```
When enabled, automatically starts music bed and ducking when mic is active.

### Get Mic Status
```
GET /api/moderation/mic/status
```

---

## Recorded Moderations

### Upload Recording
```
POST /api/moderation/recording/upload
Content-Type: multipart/form-data

audio: <file>
with_bed: true|false
```

### Queue Recording
```
POST /api/moderation/recording/queue
Content-Type: application/json

{
  "filepath": "/media/Live-Mods/moderation_20240115_103000.mp3"
}
```

---

## Listener Statistics

### Get Current Listeners
```
GET /api/listeners/current
```

**Response:**
```json
{
  "listeners": 42
}
```

### Get Statistics
```
GET /api/listeners/stats?hours=24
```

### Get History
```
GET /api/listeners/history?hours=24&limit=100
```

---

## TTS (Text-to-Speech)

### Generate TTS
```
POST /api/tts/generate
Content-Type: application/json

{
  "text": "Hello, this is a test moderation",
  "target_folder": "random-moderation",
  "filename": "custom_name",
  "queue_immediately": true
}
```

**Response:**
```json
{
  "success": true,
  "filename": "custom_name.mp3",
  "path": "/media/random-moderation/custom_name.mp3",
  "duration": 5.2,
  "queued": true
}
```

### Get Available Voices
```
GET /api/tts/voices
```

### Get TTS Settings
```
GET /api/tts/settings
```

### Update TTS Settings
```
POST /api/tts/settings
Content-Type: application/json

{
  "minimax_voice_id": "German_PlayfulMan",
  "minimax_emotion": "happy",
  "tts_musicbed_volume": 0.15
}
```

---

## Internal Files (Intro/Outro/Musicbed)

### List Files
```
GET /api/internal-files
```

### Upload File
```
POST /api/internal-files/upload
Content-Type: multipart/form-data

file: <audio file>
```

### Delete File
```
DELETE /api/internal-files/<filename>
```

### Stream File
```
GET /api/internal-files/stream/<filename>
```

---

## Error Responses

All endpoints return consistent error responses:

```json
{
  "success": false,
  "error": "Error message here"
}
```

**HTTP Status Codes:**
- `200` - Success
- `400` - Bad Request (invalid parameters)
- `401` - Unauthorized (authentication required)
- `403` - Forbidden (access denied)
- `404` - Not Found
- `500` - Server Error

---

## Rate Limiting

Currently no rate limiting is implemented. Please be reasonable with API calls.

---

## WebSocket Events

The server broadcasts real-time updates via Socket.IO:

### now_playing
Emitted when track changes:
```json
{
  "title": "Song Title",
  "artist": "Artist",
  "filename": "song.mp3",
  "duration": 180,
  "show": "Morning Show",
  "station": "My Radio"
}
```

Connect to: `ws://your-server:8080/socket.io/`
