#!/usr/bin/env python3
"""
RadioPro MCP Server (stdio transport)

A standalone MCP server that communicates with RadioPro via HTTP API.
Designed to be launched by Claude Desktop.

Configuration via environment variables:
- RADIOPRO_URL: Base URL of RadioPro (default: http://localhost:8080)
- RADIOPRO_API_KEY: API key for authentication (optional)

=== QUICK REFERENCE: COMMON WORKFLOWS ===

1. PLAY A SONG FROM LIBRARY:
   search_song("Artist Name") -> get file_id -> add_to_queue(file_id=123)

2. GENERATE AND PLAY MODERATION (ONE STEP):
   generate_moderation("Your text here", queue_immediately=true)
   -> DONE! Do NOT call any queue function afterwards!
   -> File is saved to "planned-moderation" folder by default

3. GENERATE MODERATION FOR LATER:
   generate_moderation("Your text", queue_immediately=false)
   -> File saved to "planned-moderation", not queued. Queue manually later if needed.

4. GENERATE MODERATION FOR RANDOM ROTATION:
   generate_moderation("Jingle text", target_folder="random-moderation")
   -> File saved to "random-moderation" for automatic rotation rules

5. INSERT RANDOM JINGLE/PROMO:
   list_files("jingles") -> pick one -> add_to_queue(file_id=...)

=== IMPORTANT: AVOID DUPLICATE QUEUEING ===

The most common mistake is queueing content twice:
- generate_moderation(..., queue_immediately=true) ALREADY queues the file
- Do NOT then call add_to_queue() or queue_moderation_priority() on the same file
- Check the "queued" field in the response - if true, no further action needed
"""
import os
import json
import requests
from datetime import datetime
from mcp.server.fastmcp import FastMCP

# Configuration
RADIOPRO_URL = os.environ.get("RADIOPRO_URL", "http://localhost:8080")
RADIOPRO_API_KEY = os.environ.get("RADIOPRO_API_KEY", "")

# Create MCP server
mcp = FastMCP("RadioPro")


def api_request(method: str, endpoint: str, data: dict = None) -> dict:
    """Make an API request to RadioPro"""
    url = f"{RADIOPRO_URL}/api{endpoint}"
    headers = {"Content-Type": "application/json"}

    if RADIOPRO_API_KEY:
        headers["Authorization"] = f"Bearer {RADIOPRO_API_KEY}"

    try:
        if method.upper() == "GET":
            response = requests.get(url, headers=headers, timeout=30)
        elif method.upper() == "POST":
            response = requests.post(url, headers=headers, json=data, timeout=30)
        else:
            return {"error": f"Unsupported method: {method}"}

        if response.status_code == 200:
            return response.json()
        else:
            return {"error": f"API error {response.status_code}: {response.text}"}
    except requests.exceptions.RequestException as e:
        return {"error": f"Connection error: {str(e)}"}


# ============================================================================
# MCP Tools
# ============================================================================

@mcp.tool()
def list_files(category: str) -> str:
    """
    List all audio files in a specific category folder.

    WORKFLOW: List files -> Get file_id -> Use add_to_queue(file_id=...) to play

    Args:
        category: One of:
                  - "music": Main music library
                  - "jingles": Station jingles
                  - "promos": Promotional announcements
                  - "ads": Advertisements
                  - "random-moderation": AI-generated moderations for random rotation
                  - "planned-moderation": AI-generated moderations for scheduled use
                  - "musicbeds": Background music for live moderation
                  - "misc": Other audio files

    Returns:
        JSON list of audio files with id, filename, title, artist, duration, path

    IMPORTANT: Use the "id" field from results when calling add_to_queue()
    """
    valid_categories = ["music", "promos", "jingles", "ads",
                       "random-moderation", "planned-moderation", "musicbeds", "misc"]

    if category not in valid_categories:
        return json.dumps({"error": f"Invalid category. Must be one of: {', '.join(valid_categories)}"})

    result = api_request("GET", f"/files/{category}")
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def search_song(query: str, limit: int = 20) -> str:
    """
    Search for songs by title or artist name.

    WORKFLOW: Search -> Get file_id -> Use add_to_queue(file_id=...) to play

    Args:
        query: Search query (matches title, artist, or filename)
        limit: Maximum number of results (default: 20)

    Returns:
        JSON with:
        - results: List of matching files with id, title, artist, path, duration
        - count: Number of matches

    IMPORTANT: Use the "id" field from results when calling add_to_queue()
    """
    # Get all files and filter
    result = api_request("GET", "/files/all")

    if "error" in result:
        return json.dumps(result)

    files = result.get("files", [])
    query_lower = query.lower()

    matches = []
    for f in files:
        title = (f.get("title") or "").lower()
        artist = (f.get("artist") or "").lower()
        filename = (f.get("filename") or "").lower()

        if query_lower in title or query_lower in artist or query_lower in filename:
            matches.append({
                "id": f.get("id"),
                "filename": f.get("filename"),
                "title": f.get("title"),
                "artist": f.get("artist"),
                "category": f.get("category"),
                "duration": f.get("duration"),
                "path": f.get("path")
            })

            if len(matches) >= limit:
                break

    return json.dumps({
        "query": query,
        "count": len(matches),
        "results": matches
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def add_to_queue(file_id: int = None, filepath: str = None) -> str:
    """
    Add an EXISTING audio file to the playback queue.

    USE THIS FOR:
    - Adding existing music files from the library (use file_id from search_song results)
    - Adding existing jingles, promos, or ads
    - Re-queuing previously generated moderations that were saved but not queued

    DO NOT USE THIS FOR:
    - Newly generated moderations with queue_immediately=true (already queued!)
    - Files that don't exist yet

    Files play in queue order, interleaved with regular music rotation.

    Args:
        file_id: Database ID of the audio file (preferred - get from search_song or list_files)
        filepath: Full file path as alternative (e.g., "/media/music/song.mp3")

    Returns:
        Success message with queued filename, or error
    """
    if not file_id and not filepath:
        return json.dumps({"error": "Either file_id or filepath is required"})

    data = {}
    if file_id:
        data["file_id"] = file_id
    if filepath:
        data["path"] = filepath

    result = api_request("POST", "/queue", data)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def get_queue() -> str:
    """
    Get the current playback queue contents and status.

    USE THIS TO:
    - Check what's currently playing and what's queued next
    - Verify if a file was successfully queued
    - See how many items are waiting in the queue

    Returns:
        JSON with:
        - current: Currently playing track info
        - queue: List of upcoming queued items
        - queue_length: Number of items in queue
    """
    result = api_request("GET", "/status")
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def get_now_playing() -> str:
    """
    Get detailed information about the currently playing track.

    USE THIS TO:
    - Check what song is currently on air
    - Get remaining time of current track
    - Provide context for moderations (e.g., "You just heard...")

    Returns:
        JSON with:
        - title: Track title
        - artist: Artist name
        - filename: Audio file name
        - duration: Total duration in seconds
        - elapsed: Time played so far
        - remaining: Time remaining
    """
    result = api_request("GET", "/nowplaying")
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def skip_track() -> str:
    """
    Skip the currently playing track and play the next item.

    BEHAVIOR:
    - Immediately stops current track
    - If queue has items: plays next queued item
    - If queue empty: plays next from music rotation

    USE WITH CAUTION: This interrupts playback mid-song.

    Returns:
        Success or error message
    """
    result = api_request("POST", "/skip")
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def generate_moderation(text: str, target_folder: str = "planned-moderation", filename: str = None, queue_immediately: bool = False) -> str:
    """
    Generate AI voice moderation using text-to-speech.

    IMPORTANT WORKFLOW DECISION:
    - To generate AND play immediately: Set queue_immediately=true. Done! Do NOT call any other queue function.
    - To only save for later use: Set queue_immediately=false (default). File is saved but NOT queued.

    WARNING: If queue_immediately=true, the file is ALREADY queued. Do NOT additionally call
    add_to_queue() or queue_moderation_priority() - this would cause DUPLICATE playback!

    Args:
        text: The text to convert to speech (German or English)
        target_folder: Where to save the file (default: "planned-moderation"):
                      - "planned-moderation": For manually created/scheduled moderations (DEFAULT)
                      - "random-moderation": For automatic random rotation by rotation rules
                      - "misc": For other audio files
        filename: Optional custom filename (without .mp3 extension)
        queue_immediately: CRITICAL PARAMETER:
                          - true = Generate AND add to queue in one step. Plays after current track.
                          - false = Only generate and save. Must manually queue later if needed.

    Returns:
        JSON with:
        - filepath: Path to the generated file
        - queued: true/false - whether the file was added to queue
        - filename: Name of the generated file

    Example usage:
        # Generate and play immediately (ONE step, no further action needed):
        generate_moderation("Willkommen bei Radio XY!", queue_immediately=true)

        # Only save for later (default folder is planned-moderation):
        generate_moderation("Ankündigung für morgen", queue_immediately=false)

        # Save for random rotation:
        generate_moderation("Zufälliger Jingle", target_folder="random-moderation")
    """
    data = {
        "text": text,
        "target_folder": target_folder,
        "queue_immediately": queue_immediately
    }
    if filename:
        data["filename"] = filename

    result = api_request("POST", "/tts/generate", data)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def queue_moderation_priority(filepath: str) -> str:
    """
    Add an EXISTING moderation file to the PRIORITY queue.

    WHEN TO USE THIS:
    - Only for files that ALREADY EXIST and were NOT queued during generation
    - For urgent announcements that must play before all other queued content

    WHEN NOT TO USE THIS:
    - Do NOT use after generate_moderation(..., queue_immediately=true) - file is already queued!
    - Do NOT use for normal moderation playback - use generate_moderation with queue_immediately=true instead

    BEHAVIOR: All items in the priority queue play CONSECUTIVELY before any regular queue
    items or music rotation. Use sparingly!

    Args:
        filepath: Full path to an existing audio file (e.g., "/media/random-moderation/file.mp3")

    Returns:
        Success or error message
    """
    data = {"filepath": filepath}
    result = api_request("POST", "/moderation/recording/queue", data)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def get_upcoming_shows(limit: int = 5) -> str:
    """
    Get the next scheduled shows.

    Args:
        limit: Number of upcoming shows to return (default: 5)

    Returns:
        JSON list of upcoming scheduled shows
    """
    result = api_request("GET", "/schedules")

    if "error" in result:
        return json.dumps(result)

    schedules = result.get("schedules", [])

    # Filter to active and future schedules
    now = datetime.now()
    upcoming = []

    for s in schedules:
        if s.get("is_active"):
            scheduled_time = s.get("scheduled_time")
            if scheduled_time:
                upcoming.append({
                    "id": s.get("id"),
                    "show_name": s.get("show_name"),
                    "scheduled_time": scheduled_time,
                    "repeat_type": s.get("repeat_type"),
                    "days_of_week": s.get("days_of_week")
                })

    # Sort by scheduled time and limit
    upcoming.sort(key=lambda x: x.get("scheduled_time", ""))
    upcoming = upcoming[:limit]

    return json.dumps({
        "count": len(upcoming),
        "shows": upcoming
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def get_current_time() -> str:
    """
    Get the current time in the configured station timezone.

    Returns:
        JSON with current time, date, day of week, and timezone
    """
    result = api_request("GET", "/stream-settings")

    if "error" in result:
        return json.dumps(result)

    timezone = result.get("timezone", "Europe/Berlin")

    # Get current time
    from zoneinfo import ZoneInfo
    try:
        tz = ZoneInfo(timezone)
        now = datetime.now(tz)
    except Exception:
        now = datetime.now()
        timezone = "local"

    days = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

    return json.dumps({
        "time": now.strftime("%H:%M:%S"),
        "date": now.strftime("%Y-%m-%d"),
        "day_of_week": days[now.weekday()],
        "day_number": now.weekday(),
        "timezone": timezone,
        "iso": now.isoformat()
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def list_rotation_rules(active_only: bool = False) -> str:
    """
    List all automatic rotation rules.

    Rotation rules automatically insert content (jingles, promos, ads) at configured intervals.
    Rules are PAUSED when manual queue items are present - they resume when queue is empty.

    RULE TYPES:
    - "after_songs": Insert after X songs played (e.g., jingle every 3 songs)
    - "interval": Insert every X minutes
    - "at_minute": Insert at specific minute of each hour

    Args:
        active_only: If true, only show enabled rules (default: false = show all)

    Returns:
        JSON list of rules with id, name, category, rule_type, is_active, etc.
    """
    result = api_request("GET", "/rules")

    if "error" in result:
        return json.dumps(result)

    rules = result.get("rules", [])

    if active_only:
        rules = [r for r in rules if r.get("is_active")]

    return json.dumps({
        "count": len(rules),
        "rules": rules
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def toggle_rotation_rule(rule_id: int = None, rule_name: str = None) -> str:
    """
    Enable or disable a rotation rule.

    WORKFLOW: list_rotation_rules() -> get rule_id or name -> toggle_rotation_rule(...)

    USE THIS TO:
    - Temporarily disable jingles during a special show
    - Enable/disable ad rotation
    - Control which content types are automatically inserted

    Args:
        rule_id: ID of the rule (from list_rotation_rules)
        rule_name: Name of the rule (alternative - case insensitive)

    Returns:
        JSON with success status and new is_active state
    """
    if not rule_id and not rule_name:
        return json.dumps({"error": "Either rule_id or rule_name is required"})

    # If rule_name provided, find the rule_id first
    if not rule_id and rule_name:
        result = api_request("GET", "/rules")
        if "error" in result:
            return json.dumps(result)

        rules = result.get("rules", [])
        for r in rules:
            if r.get("name", "").lower() == rule_name.lower():
                rule_id = r.get("id")
                break

        if not rule_id:
            return json.dumps({"error": f"Rule not found: {rule_name}"})

    # Toggle the rule (uses main blueprint, not API)
    url = f"{RADIOPRO_URL}/rotation/toggle/{rule_id}"
    headers = {"Content-Type": "application/json"}

    if RADIOPRO_API_KEY:
        headers["Authorization"] = f"Bearer {RADIOPRO_API_KEY}"

    try:
        response = requests.post(url, headers=headers, timeout=30)
        if response.status_code == 200:
            result = response.json()
            return json.dumps({
                "success": True,
                "rule_id": rule_id,
                "is_active": result.get("is_active"),
                "message": f"Rule {'activated' if result.get('is_active') else 'deactivated'}"
            }, ensure_ascii=False, indent=2)
        else:
            return json.dumps({"error": f"API error {response.status_code}: {response.text}"})
    except requests.exceptions.RequestException as e:
        return json.dumps({"error": f"Connection error: {str(e)}"})


@mcp.tool()
def get_listener_stats() -> str:
    """
    Get current listener statistics.

    Returns:
        JSON with current listener count and recent stats
    """
    current = api_request("GET", "/listeners/current")
    stats = api_request("GET", "/listeners/stats")

    return json.dumps({
        "current": current,
        "stats": stats
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def clear_queue() -> str:
    """
    Clear the entire playback queue.

    BEHAVIOR:
    - Removes ALL queued tracks (both regular queue and priority queue)
    - The currently playing track continues to play
    - After queue is cleared, normal music rotation resumes

    USE THIS WHEN:
    - User wants to cancel all planned content
    - Starting fresh with a new programming block
    - Fixing mistakes (e.g., accidentally queued wrong content)

    Returns:
        Success or error message
    """
    result = api_request("POST", "/queue/clear")
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def get_playback_history(limit: int = 20) -> str:
    """
    Get recent playback history.

    Args:
        limit: Maximum number of entries to return (default: 20)

    Returns:
        JSON list of recently played tracks with timestamps
    """
    result = api_request("GET", "/history")

    if "error" in result:
        return json.dumps(result)

    history = result.get("history", result) if isinstance(result, dict) else result

    # Limit results
    if isinstance(history, list) and len(history) > limit:
        history = history[:limit]

    return json.dumps({
        "count": len(history) if isinstance(history, list) else 0,
        "history": history
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def list_shows() -> str:
    """
    List all available shows (pre-programmed playlists).

    Shows are curated playlists that can be played as a block,
    overriding normal rotation until complete or stopped.

    WORKFLOW: list_shows() -> get show_id -> play_show(show_id=...)

    Returns:
        JSON list of shows with id, name, and item count
    """
    result = api_request("GET", "/shows")
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def play_show(show_id: int) -> str:
    """
    Start playing a show (pre-programmed playlist).

    BEHAVIOR:
    - Show items are added to the queue in order
    - Overrides normal music rotation
    - Continues until all show items played or stop_show() called

    WORKFLOW: list_shows() -> get show_id -> play_show(show_id=...)

    Args:
        show_id: ID of the show (from list_shows)

    Returns:
        Success or error message
    """
    result = api_request("POST", f"/shows/{show_id}/play")
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def stop_show() -> str:
    """
    Stop the currently playing show and return to normal rotation.

    BEHAVIOR:
    - Clears remaining show items from queue
    - Current track continues playing
    - Normal music rotation resumes after current track

    USE THIS WHEN:
    - Show needs to end early
    - Switching to different programming

    Returns:
        Success or error message
    """
    result = api_request("POST", "/shows/stop")
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def get_stream_settings() -> str:
    """
    Get current stream settings (station name, timezone, etc.).

    Returns:
        JSON with stream settings
    """
    result = api_request("GET", "/stream-settings")
    return json.dumps(result, ensure_ascii=False, indent=2)


# ============================================================================
# Run Server
# ============================================================================

if __name__ == "__main__":
    # Run with stdio transport for Claude Desktop
    mcp.run(transport="stdio")
