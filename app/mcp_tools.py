"""
MCP Tool Implementations for Radio Automation
Contains the actual logic for each MCP tool
"""
import os
import base64
import logging
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)

# Supported audio formats
SUPPORTED_FORMATS = ('.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.wma', '.opus')


def execute_tool(tool_name, arguments):
    """Execute a tool by name with the given arguments"""
    tools = {
        'list_files': tool_list_files,
        'search_song': tool_search_song,
        'add_to_queue': tool_add_to_queue,
        'get_queue': tool_get_queue,
        'upload_file': tool_upload_file,
        'generate_moderation': tool_generate_moderation,
        'queue_moderation': tool_queue_moderation,
        'get_upcoming_shows': tool_get_upcoming_shows,
        'get_current_time': tool_get_current_time,
        'list_rotation_rules': tool_list_rotation_rules,
        'toggle_rotation_rule': tool_toggle_rotation_rule
    }

    tool_func = tools.get(tool_name)
    if not tool_func:
        return {"error": f"Unknown tool: {tool_name}"}

    try:
        return tool_func(arguments)
    except Exception as e:
        logger.error(f"Tool {tool_name} failed: {e}")
        return {"error": str(e)}


def tool_list_files(args):
    """List audio files in a category folder"""
    from app.models import AudioFile

    category = args.get('category')
    if not category:
        return {"error": "category is required"}

    valid_categories = ['music', 'promos', 'jingles', 'ads', 'random-moderation',
                        'planned-moderation', 'musicbeds', 'misc']
    if category not in valid_categories:
        return {"error": f"Invalid category. Must be one of: {', '.join(valid_categories)}"}

    files = AudioFile.query.filter_by(category=category).order_by(AudioFile.title).all()

    return {
        "category": category,
        "count": len(files),
        "files": [
            {
                "id": f.id,
                "filename": f.filename,
                "title": f.title or f.filename,
                "artist": f.artist or "",
                "duration": f.duration,
                "is_active": f.is_active,
                "play_count": f.play_count
            }
            for f in files
        ]
    }


def tool_search_song(args):
    """Search for songs by title or artist"""
    from app.models import AudioFile
    from sqlalchemy import or_

    query = args.get('query')
    if not query:
        return {"error": "query is required"}

    limit = args.get('limit', 20)

    # Search in title and artist fields
    search_pattern = f"%{query}%"
    files = AudioFile.query.filter(
        AudioFile.category == 'music',
        or_(
            AudioFile.title.ilike(search_pattern),
            AudioFile.artist.ilike(search_pattern),
            AudioFile.filename.ilike(search_pattern)
        )
    ).limit(limit).all()

    return {
        "query": query,
        "count": len(files),
        "results": [
            {
                "id": f.id,
                "filename": f.filename,
                "title": f.title or f.filename,
                "artist": f.artist or "",
                "duration": f.duration,
                "category": f.category,
                "is_active": f.is_active,
                "path": f.path
            }
            for f in files
        ]
    }


def tool_add_to_queue(args):
    """Add an audio file to the playback queue"""
    from app.models import AudioFile
    from app.audio_engine import queue_track

    file_id = args.get('file_id')
    filepath = args.get('filepath')

    if not file_id and not filepath:
        return {"error": "Either file_id or filepath is required"}

    if file_id:
        audio_file = AudioFile.query.get(file_id)
        if not audio_file:
            return {"error": f"File with ID {file_id} not found"}
        filepath = audio_file.path

    if not filepath:
        return {"error": "Could not determine file path"}

    # Check if file exists
    if not os.path.exists(filepath):
        return {"error": f"File not found: {filepath}"}

    # Add to queue
    success = queue_track(filepath)

    if success:
        return {
            "success": True,
            "message": f"Added to queue: {os.path.basename(filepath)}",
            "filepath": filepath
        }
    else:
        return {"error": "Failed to add file to queue"}


def tool_get_queue(args):
    """Get the current playback queue contents"""
    from app.audio_engine import get_queue_status
    from app.models import NowPlaying

    queue = get_queue_status()
    now_playing = NowPlaying.query.first()

    current_track = None
    if now_playing:
        current_track = {
            "title": now_playing.title,
            "artist": now_playing.artist,
            "filename": now_playing.filename,
            "category": now_playing.category,
            "duration": now_playing.duration,
            "started_at": now_playing.started_at.isoformat() if now_playing.started_at else None
        }

    return {
        "current_track": current_track,
        "queue_length": len(queue),
        "queue": queue
    }


def tool_upload_file(args):
    """Upload an audio file to a category folder"""
    from flask import current_app
    from app.models import AudioFile, db
    from app.utils import get_audio_metadata

    category = args.get('category')
    filename = args.get('filename')
    content_b64 = args.get('content')

    if not category or not filename or not content_b64:
        return {"error": "category, filename, and content are required"}

    valid_categories = ['music', 'promos', 'jingles', 'ads', 'random-moderation',
                        'planned-moderation', 'musicbeds', 'misc']
    if category not in valid_categories:
        return {"error": f"Invalid category. Must be one of: {', '.join(valid_categories)}"}

    # Secure the filename
    filename = secure_filename(filename)
    if not filename:
        return {"error": "Invalid filename"}

    # Ensure file has audio extension
    ext = os.path.splitext(filename)[1].lower()
    if ext not in SUPPORTED_FORMATS:
        return {"error": f"Unsupported format. Must be one of: {', '.join(SUPPORTED_FORMATS)}"}

    # Decode base64 content
    try:
        content = base64.b64decode(content_b64)
    except Exception as e:
        return {"error": f"Invalid base64 content: {str(e)}"}

    # Save file
    media_path = current_app.config.get('MEDIA_PATH', '/media')
    category_path = os.path.join(media_path, category)
    os.makedirs(category_path, exist_ok=True)

    filepath = os.path.join(category_path, filename)

    try:
        with open(filepath, 'wb') as f:
            f.write(content)
    except Exception as e:
        return {"error": f"Failed to save file: {str(e)}"}

    # Get metadata and add to database
    try:
        metadata = get_audio_metadata(filepath)
        audio_file = AudioFile(
            filename=filename,
            category=category,
            path=filepath,
            duration=metadata.get('duration', 0),
            title=metadata.get('title'),
            artist=metadata.get('artist')
        )
        db.session.add(audio_file)
        db.session.commit()

        return {
            "success": True,
            "message": f"File uploaded successfully: {filename}",
            "file_id": audio_file.id,
            "filepath": filepath,
            "duration": audio_file.duration
        }
    except Exception as e:
        return {"error": f"Failed to add file to database: {str(e)}"}


def tool_generate_moderation(args):
    """Generate AI voice moderation using TTS"""
    from app.models import StreamSettings
    from app.tts_service import generate_tts_with_processing

    text = args.get('text')
    if not text:
        return {"error": "text is required"}

    target_folder = args.get('target_folder', 'random-moderation')
    filename = args.get('filename')

    valid_folders = ['random-moderation', 'planned-moderation', 'misc']
    if target_folder not in valid_folders:
        return {"error": f"Invalid target_folder. Must be one of: {', '.join(valid_folders)}"}

    # Get settings
    settings = StreamSettings.get_settings()

    if not settings.minimax_api_key:
        return {"error": "Minimax API key not configured. Please configure TTS settings first."}

    # Generate TTS
    result = generate_tts_with_processing(
        text=text,
        settings=settings,
        target_folder=target_folder,
        filename=filename
    )

    if result.get('success'):
        return {
            "success": True,
            "message": "Moderation generated successfully",
            "filename": result.get('filename'),
            "filepath": result.get('path'),
            "duration": result.get('duration')
        }
    else:
        return {"error": result.get('error', 'TTS generation failed')}


def tool_queue_moderation(args):
    """Add a moderation file to the priority moderation queue"""
    from app.audio_engine import queue_recorded_moderation

    filepath = args.get('filepath')
    if not filepath:
        return {"error": "filepath is required"}

    # Check if file exists
    if not os.path.exists(filepath):
        return {"error": f"File not found: {filepath}"}

    # Add to moderation queue
    success = queue_recorded_moderation(filepath)

    if success:
        return {
            "success": True,
            "message": f"Added to moderation queue: {os.path.basename(filepath)}",
            "filepath": filepath
        }
    else:
        return {"error": "Failed to add moderation to queue"}


def tool_get_upcoming_shows(args):
    """Get the next scheduled shows"""
    from app.models import Schedule
    from app.utils import get_local_now

    limit = args.get('limit', 5)

    now = get_local_now()
    now_naive = now.replace(tzinfo=None)

    schedules = Schedule.query.filter(
        Schedule.is_active == True,
        Schedule.scheduled_time >= now_naive
    ).order_by(Schedule.scheduled_time.asc()).limit(limit).all()

    return {
        "count": len(schedules),
        "shows": [
            {
                "id": s.id,
                "show_name": s.show.name if s.show else "Unknown",
                "scheduled_time": s.scheduled_time.isoformat() if s.scheduled_time else None,
                "repeat_type": s.repeat_type,
                "days_of_week": s.days_of_week
            }
            for s in schedules
        ]
    }


def tool_get_current_time(args):
    """Get the current time in the configured station timezone"""
    from app.utils import get_local_now
    from app.models import StreamSettings

    now = get_local_now()
    settings = StreamSettings.get_settings()

    return {
        "current_time": now.isoformat(),
        "timezone": settings.timezone or 'Europe/Berlin',
        "formatted": now.strftime('%A, %d. %B %Y, %H:%M:%S'),
        "day_of_week": now.weekday(),
        "hour": now.hour,
        "minute": now.minute
    }


def tool_list_rotation_rules(args):
    """List all rotation rules configured in the system"""
    from app.models import RotationRule

    active_only = args.get('active_only', False)

    query = RotationRule.query
    if active_only:
        query = query.filter_by(is_active=True)

    rules = query.order_by(RotationRule.priority.desc()).all()

    return {
        "count": len(rules),
        "rules": [
            {
                "id": r.id,
                "name": r.name,
                "rule_type": r.rule_type,
                "category": r.category,
                "is_active": r.is_active,
                "priority": r.priority,
                "interval_value": r.interval_value,
                "minute_of_hour": r.minute_of_hour,
                "time_start": r.time_start.strftime('%H:%M') if r.time_start else None,
                "time_end": r.time_end.strftime('%H:%M') if r.time_end else None,
                "days_of_week": r.days_of_week
            }
            for r in rules
        ]
    }


def tool_toggle_rotation_rule(args):
    """Enable or disable a rotation rule"""
    from app.models import RotationRule, db

    rule_id = args.get('rule_id')
    rule_name = args.get('rule_name')
    enabled = args.get('enabled')

    if enabled is None:
        return {"error": "enabled is required"}

    if not rule_id and not rule_name:
        return {"error": "Either rule_id or rule_name is required"}

    # Find the rule
    if rule_id:
        rule = RotationRule.query.get(rule_id)
    else:
        rule = RotationRule.query.filter_by(name=rule_name).first()

    if not rule:
        return {"error": f"Rotation rule not found"}

    # Update the rule
    previous_state = rule.is_active
    rule.is_active = enabled
    db.session.commit()

    return {
        "success": True,
        "rule_id": rule.id,
        "rule_name": rule.name,
        "previous_state": previous_state,
        "current_state": rule.is_active,
        "message": f"Rule '{rule.name}' {'enabled' if enabled else 'disabled'}"
    }
