import os
import subprocess
import json
from flask import current_app
from mutagen import File as MutagenFile
from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE
from mutagen.mp4 import MP4
from mutagen.easyid3 import EasyID3
from app import db
from app.models import AudioFile

# Supported audio formats
SUPPORTED_FORMATS = ('.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.wma', '.opus')


def get_audio_metadata(filepath):
    """Extract metadata from any supported audio file"""
    metadata = {
        'duration': 0,
        'title': None,
        'artist': None,
        'bitrate': 0,
        'format': None,
        'samplerate': 0
    }

    try:
        # Try mutagen first for common formats
        audio = MutagenFile(filepath)
        if audio is not None:
            # Get duration
            if hasattr(audio, 'info') and hasattr(audio.info, 'length'):
                metadata['duration'] = audio.info.length

            # Get bitrate if available
            if hasattr(audio, 'info') and hasattr(audio.info, 'bitrate'):
                metadata['bitrate'] = audio.info.bitrate

            # Get sample rate if available
            if hasattr(audio, 'info') and hasattr(audio.info, 'sample_rate'):
                metadata['samplerate'] = audio.info.sample_rate

            # Get format
            ext = os.path.splitext(filepath)[1].lower()
            metadata['format'] = ext[1:] if ext else 'unknown'

            # Extract tags based on file type
            if isinstance(audio, MP3):
                try:
                    tags = EasyID3(filepath)
                    metadata['title'] = tags.get('title', [None])[0]
                    metadata['artist'] = tags.get('artist', [None])[0]
                except Exception:
                    pass
            elif isinstance(audio, FLAC):
                metadata['title'] = audio.get('title', [None])[0] if audio.get('title') else None
                metadata['artist'] = audio.get('artist', [None])[0] if audio.get('artist') else None
            elif isinstance(audio, OggVorbis):
                metadata['title'] = audio.get('title', [None])[0] if audio.get('title') else None
                metadata['artist'] = audio.get('artist', [None])[0] if audio.get('artist') else None
            elif isinstance(audio, MP4):
                metadata['title'] = audio.get('\xa9nam', [None])[0] if audio.get('\xa9nam') else None
                metadata['artist'] = audio.get('\xa9ART', [None])[0] if audio.get('\xa9ART') else None
            elif hasattr(audio, 'tags') and audio.tags:
                # Generic tag extraction
                tags = audio.tags
                if hasattr(tags, 'get'):
                    metadata['title'] = tags.get('title', [None])[0] if tags.get('title') else None
                    metadata['artist'] = tags.get('artist', [None])[0] if tags.get('artist') else None

        # Fallback to ffprobe for unsupported formats or if mutagen fails
        if metadata['duration'] == 0:
            metadata = get_metadata_ffprobe(filepath, metadata)

    except Exception as e:
        print(f"Error reading metadata from {filepath}: {e}")
        # Try ffprobe as fallback
        metadata = get_metadata_ffprobe(filepath, metadata)

    return metadata


def get_metadata_ffprobe(filepath, metadata=None):
    """Use ffprobe to extract metadata from any audio file"""
    if metadata is None:
        metadata = {
            'duration': 0,
            'title': None,
            'artist': None,
            'bitrate': 0,
            'format': None,
            'samplerate': 0
        }

    try:
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_format', '-show_streams', filepath
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            data = json.loads(result.stdout)

            # Get format info
            if 'format' in data:
                fmt = data['format']
                if 'duration' in fmt:
                    metadata['duration'] = float(fmt['duration'])
                if 'bit_rate' in fmt:
                    metadata['bitrate'] = int(fmt['bit_rate']) // 1000
                if 'format_name' in fmt:
                    metadata['format'] = fmt['format_name'].split(',')[0]

                # Get tags
                if 'tags' in fmt:
                    tags = fmt['tags']
                    # Tags might be in different cases
                    for key in ['title', 'TITLE', 'Title']:
                        if key in tags:
                            metadata['title'] = tags[key]
                            break
                    for key in ['artist', 'ARTIST', 'Artist']:
                        if key in tags:
                            metadata['artist'] = tags[key]
                            break

            # Get audio stream info
            if 'streams' in data:
                for stream in data['streams']:
                    if stream.get('codec_type') == 'audio':
                        if 'sample_rate' in stream:
                            metadata['samplerate'] = int(stream['sample_rate'])
                        break

    except Exception as e:
        print(f"ffprobe error for {filepath}: {e}")

    return metadata


def is_supported_audio_file(filename):
    """Check if a file is a supported audio format"""
    return filename.lower().endswith(SUPPORTED_FORMATS)


def scan_media_files(category=None):
    """Scan media directories and sync with database"""
    media_path = current_app.config['MEDIA_PATH']
    categories = [category] if category else current_app.config['CATEGORIES']

    for cat in categories:
        category_path = os.path.join(media_path, cat)

        if not os.path.exists(category_path):
            os.makedirs(category_path)
            continue

        # Get existing files from database
        existing_files = {f.filename: f for f in AudioFile.query.filter_by(category=cat).all()}

        # Scan directory
        found_files = set()
        for filename in os.listdir(category_path):
            # Support all audio formats
            if not is_supported_audio_file(filename):
                continue

            found_files.add(filename)
            filepath = os.path.join(category_path, filename)

            if filename not in existing_files:
                # New file, add to database
                metadata = get_audio_metadata(filepath)
                audio_file = AudioFile(
                    filename=filename,
                    category=cat,
                    path=filepath,
                    duration=metadata.get('duration', 0),
                    title=metadata.get('title'),
                    artist=metadata.get('artist')
                )
                db.session.add(audio_file)
            else:
                # Update path if needed
                existing = existing_files[filename]
                if existing.path != filepath:
                    existing.path = filepath

        # Remove database entries for files that no longer exist
        for filename, audio_file in existing_files.items():
            if filename not in found_files:
                db.session.delete(audio_file)

        db.session.commit()


def format_duration(seconds):
    """Format duration in seconds to MM:SS or HH:MM:SS"""
    if not seconds:
        return '0:00'

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f'{hours}:{minutes:02d}:{secs:02d}'
    return f'{minutes}:{secs:02d}'


def get_random_file_from_category(category, exclude_recent_hours=None):
    """Get a random active file from a category, excluding recently played tracks.

    Args:
        category: The category to select from
        exclude_recent_hours: Exclude tracks played within this many hours.
                              Default: 1 hour for 'music', 0 (disabled) for other categories.
                              Set to 0 to disable the filter explicitly.

    Returns:
        A random AudioFile that hasn't been played recently, or any random file
        if all have been played recently
    """
    from sqlalchemy.sql.expression import func
    from datetime import datetime, timedelta

    # Only apply the repeat blocker for music category by default
    if exclude_recent_hours is None:
        exclude_recent_hours = 1 if category == 'music' else 0

    # Base query for active files in category
    base_query = AudioFile.query.filter_by(
        category=category,
        is_active=True
    )

    # If exclusion is enabled, try to find files not recently played
    if exclude_recent_hours > 0:
        cutoff_time = datetime.now() - timedelta(hours=exclude_recent_hours)

        # First try: files that were never played OR played before cutoff
        audio_file = base_query.filter(
            (AudioFile.last_played == None) | (AudioFile.last_played < cutoff_time)
        ).order_by(func.random()).first()

        if audio_file:
            return audio_file

    # Fallback: if all files have been played recently, just pick any random one
    return base_query.order_by(func.random()).first()
