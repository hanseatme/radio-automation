#!/usr/bin/env python3
"""
RadioPro MCP Server (stdio transport)

A standalone MCP server that communicates with RadioPro via HTTP API.
Designed to be launched by Claude Desktop.

Configuration via environment variables:
- RADIOPRO_URL: Base URL of RadioPro (default: http://localhost:8080)
- RADIOPRO_API_KEY: API key for authentication (optional)
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
    List audio files in a category folder.

    Args:
        category: Category folder name. One of: music, promos, jingles, ads,
                  random-moderation, planned-moderation, musicbeds, misc

    Returns:
        JSON list of audio files with id, filename, title, artist, duration
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

    Args:
        query: Search query for title or artist
        limit: Maximum number of results (default: 20)

    Returns:
        JSON list of matching songs
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
    Add an audio file to the playback queue.

    Args:
        file_id: Database ID of the audio file (preferred)
        filepath: Full file path (alternative to file_id)

    Returns:
        Success or error message
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
    Get the current playback queue contents.

    Returns:
        JSON with current track, queue items, and queue length
    """
    result = api_request("GET", "/status")
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def get_now_playing() -> str:
    """
    Get information about the currently playing track.

    Returns:
        JSON with title, artist, filename, duration, and progress
    """
    result = api_request("GET", "/nowplaying")
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def skip_track() -> str:
    """
    Skip the currently playing track.

    Returns:
        Success or error message
    """
    result = api_request("POST", "/skip")
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def generate_moderation(text: str, target_folder: str = "random-moderation", filename: str = None, queue_immediately: bool = False) -> str:
    """
    Generate AI voice moderation using text-to-speech.

    Args:
        text: Text to convert to speech
        target_folder: Target folder (random-moderation, planned-moderation, or misc)
        filename: Optional custom filename (without extension)
        queue_immediately: If true, add to normal queue for playback.
                          The moderation will play after the current track,
                          interleaved with regular music rotation.

    Returns:
        JSON with generated file info, including 'queued' status if queue_immediately was true
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
    Add a moderation file to the PRIORITY moderation queue.
    WARNING: All items in the priority queue play consecutively before music resumes.
    Use generate_moderation with queue_immediately=true for normal interleaved playback.

    Args:
        filepath: Full path to the moderation audio file

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
    List all rotation rules configured in the system.

    Args:
        active_only: Only return active rules (default: False)

    Returns:
        JSON list of rotation rules
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
    Toggle a rotation rule on/off by ID or name.

    Args:
        rule_id: ID of the rotation rule
        rule_name: Name of the rotation rule (alternative to rule_id)

    Returns:
        Success message with new active state
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
    Clear the playback queue (removes all queued tracks except the currently playing one).

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

    Returns:
        JSON list of shows with id, name, and item count
    """
    result = api_request("GET", "/shows")
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def play_show(show_id: int) -> str:
    """
    Start playing a show (pre-programmed playlist).

    Args:
        show_id: ID of the show to play

    Returns:
        Success or error message
    """
    result = api_request("POST", f"/shows/{show_id}/play")
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def stop_show() -> str:
    """
    Stop the currently playing show and return to normal rotation.

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
