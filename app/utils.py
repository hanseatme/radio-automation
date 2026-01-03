import os
import subprocess
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import current_app
from mutagen import File as MutagenFile
from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE
from mutagen.mp4 import MP4
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, TIT2, TPE1, ID3NoHeaderError
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


def write_audio_metadata(filepath, title=None, artist=None):
    """Write metadata (title, artist) to an audio file's tags.

    Supports MP3 (ID3), FLAC, OGG Vorbis, and M4A/AAC (MP4) formats.

    Args:
        filepath: Path to the audio file
        title: New title to set (None to skip)
        artist: New artist to set (None to skip)

    Returns:
        tuple: (success: bool, message: str)
    """
    if title is None and artist is None:
        return True, "Keine Änderungen"

    ext = os.path.splitext(filepath)[1].lower()

    try:
        if ext == '.mp3':
            # Handle MP3 files with ID3 tags
            try:
                tags = ID3(filepath)
            except ID3NoHeaderError:
                # No ID3 tag exists, create one
                tags = ID3()

            if title is not None:
                tags['TIT2'] = TIT2(encoding=3, text=title)
            if artist is not None:
                tags['TPE1'] = TPE1(encoding=3, text=artist)

            tags.save(filepath)
            return True, "ID3-Tags aktualisiert"

        elif ext == '.flac':
            audio = FLAC(filepath)
            if title is not None:
                audio['title'] = title
            if artist is not None:
                audio['artist'] = artist
            audio.save()
            return True, "FLAC-Tags aktualisiert"

        elif ext == '.ogg':
            audio = OggVorbis(filepath)
            if title is not None:
                audio['title'] = [title]
            if artist is not None:
                audio['artist'] = [artist]
            audio.save()
            return True, "Vorbis-Tags aktualisiert"

        elif ext in ['.m4a', '.aac', '.mp4']:
            audio = MP4(filepath)
            if title is not None:
                audio['\xa9nam'] = [title]
            if artist is not None:
                audio['\xa9ART'] = [artist]
            audio.save()
            return True, "MP4-Tags aktualisiert"

        elif ext == '.wav':
            # WAV files typically don't support metadata well
            return False, "WAV-Dateien unterstützen keine Metadaten-Tags"

        else:
            return False, f"Format {ext} wird nicht zum Schreiben unterstützt"

    except Exception as e:
        return False, f"Fehler beim Schreiben der Tags: {str(e)}"


# Preview folder path
PREVIEW_FOLDER = '/media/previews'


def get_preview_path(file_id):
    """Get the path where a preview file should be stored"""
    return os.path.join(PREVIEW_FOLDER, f'preview_{file_id}.mp3')


def generate_preview(audio_file_id, source_path, duration):
    """Generate a 30-second preview from the middle of an audio file.

    Args:
        audio_file_id: The database ID of the audio file
        source_path: Path to the source audio file
        duration: Duration of the source file in seconds

    Returns:
        tuple: (success: bool, preview_path_or_error: str)
    """
    # Ensure preview folder exists
    os.makedirs(PREVIEW_FOLDER, exist_ok=True)

    preview_path = get_preview_path(audio_file_id)
    preview_duration = 30  # seconds

    # Calculate start time (middle of song minus half preview duration)
    if duration <= preview_duration:
        # Song is shorter than preview, use the whole song
        start_time = 0
        actual_duration = duration
    else:
        # Start from middle minus half of preview duration
        start_time = (duration / 2) - (preview_duration / 2)
        actual_duration = preview_duration

    try:
        # Use ffmpeg to extract and encode the preview
        cmd = [
            'ffmpeg', '-y',  # Overwrite output file
            '-ss', str(start_time),  # Start time
            '-i', source_path,  # Input file
            '-t', str(actual_duration),  # Duration
            '-c:a', 'libmp3lame',  # MP3 codec
            '-b:a', '128k',  # Bitrate
            '-ar', '44100',  # Sample rate
            '-ac', '2',  # Stereo
            '-map_metadata', '-1',  # Strip metadata
            preview_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            return False, f"FFmpeg error: {result.stderr}"

        if os.path.exists(preview_path):
            return True, preview_path
        else:
            return False, "Preview file was not created"

    except subprocess.TimeoutExpired:
        return False, "Preview generation timed out"
    except Exception as e:
        return False, f"Error generating preview: {str(e)}"


def delete_preview(audio_file_id):
    """Delete the preview file for an audio file.

    Args:
        audio_file_id: The database ID of the audio file

    Returns:
        bool: True if deleted or didn't exist, False on error
    """
    preview_path = get_preview_path(audio_file_id)
    try:
        if os.path.exists(preview_path):
            os.remove(preview_path)
        return True
    except Exception as e:
        print(f"Error deleting preview {preview_path}: {e}")
        return False


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


def generate_playlist_file(category):
    """Generate a playlist file containing only active tracks from a category.

    This creates a .m3u playlist file that Liquidsoap can use instead of
    scanning the entire directory. Only active files are included.

    For music category: Songs are sorted to avoid repetition:
    - Never played songs first
    - Then sorted by last_played (oldest first)
    - Then by play_count (least played first)

    Args:
        category: The category to generate a playlist for

    Returns:
        Path to the generated playlist file, or None on error
    """
    try:
        # Get all active files for this category
        query = AudioFile.query.filter_by(
            category=category,
            is_active=True
        )

        # For music category: sort to avoid repetition
        # Songs that were played recently should appear later in the playlist
        if category == 'music':
            # Sort by last_played (NULL first = never played), then by play_count
            query = query.order_by(
                AudioFile.last_played.asc().nullsfirst(),
                AudioFile.play_count.asc()
            )

        active_files = query.all()

        # Generate playlist path
        playlist_path = f'/data/playlists/{category}.m3u'

        # Ensure playlist directory exists
        os.makedirs('/data/playlists', exist_ok=True)

        # Write playlist file
        with open(playlist_path, 'w', encoding='utf-8') as f:
            f.write('#EXTM3U\n')
            for file in active_files:
                # Write metadata line
                duration = int(file.duration) if file.duration else 0
                artist = file.artist or 'Unknown Artist'
                title = file.title or file.filename
                f.write(f'#EXTINF:{duration},{artist} - {title}\n')
                # Write file path
                f.write(f'{file.path}\n')

        print(f'Generated playlist for {category}: {len(active_files)} active tracks', flush=True)
        return playlist_path

    except Exception as e:
        print(f'Error generating playlist for {category}: {e}', flush=True)
        return None


def regenerate_all_playlists():
    """Regenerate playlist files for all categories.

    This should be called:
    - On startup
    - When a file's active status changes
    - Periodically (every few minutes) to stay in sync
    """
    categories = ['music', 'promos', 'jingles', 'ads', 'random-moderation',
                  'planned-moderation', 'musicbeds']

    for category in categories:
        generate_playlist_file(category)

    print('All playlists regenerated', flush=True)


def get_local_now():
    """Get current datetime in the configured timezone.

    Returns a timezone-aware datetime object in the configured timezone.
    Falls back to Europe/Berlin if no timezone is configured.
    """
    try:
        from app.models import StreamSettings
        settings = StreamSettings.get_settings()
        tz_name = settings.timezone or 'Europe/Berlin'
    except Exception:
        tz_name = 'Europe/Berlin'

    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        # Fallback to UTC if timezone is invalid
        tz = ZoneInfo('UTC')

    return datetime.now(tz)


def get_timezone():
    """Get the configured timezone as a ZoneInfo object.

    Returns ZoneInfo for the configured timezone or Europe/Berlin as fallback.
    """
    try:
        from app.models import StreamSettings
        settings = StreamSettings.get_settings()
        tz_name = settings.timezone or 'Europe/Berlin'
    except Exception:
        tz_name = 'Europe/Berlin'

    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo('UTC')
