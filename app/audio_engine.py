import socket
import urllib.request
import xml.etree.ElementTree as ET
from app.models import SystemState


LIQUIDSOAP_HOST = '127.0.0.1'
LIQUIDSOAP_PORT = 1234
ICECAST_HOST = 'localhost'
ICECAST_PORT = 8000


def send_liquidsoap_command(command):
    """Send a command to Liquidsoap via telnet"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((LIQUIDSOAP_HOST, LIQUIDSOAP_PORT))

        sock.sendall((command + '\n').encode())

        response = b''
        while True:
            try:
                data = sock.recv(4096)
                if not data:
                    break
                response += data
                # Only stop when we see 'END' which marks the end of Liquidsoap response
                # Don't stop on newlines since metadata responses have multiple lines
                if b'END' in response:
                    break
            except socket.timeout:
                break

        sock.close()
        return response.decode().strip()
    except Exception as e:
        print(f"Liquidsoap command error: {e}")
        return None


def get_current_track():
    """Get currently playing track info"""
    title = SystemState.get('current_title', 'Nichts abgespielt')
    artist = SystemState.get('current_artist', '')
    filename = SystemState.get('current_filename', '')
    started = SystemState.get('current_started', '')

    return {
        'title': title,
        'artist': artist,
        'filename': filename,
        'started_at': started
    }


def get_queue_status():
    """Get current queue from Liquidsoap with metadata - includes both normal queue and moderation queue"""
    all_items = []

    # Get normal queue (jingles, promos, ads, etc.)
    response = send_liquidsoap_command('queue.queue')
    if response and 'ERROR' not in response:
        lines = response.strip().split('\n')
        request_ids = [line.strip() for line in lines if line.strip() and line.strip() != 'END' and line.strip().isdigit()]

        for rid in request_ids:
            metadata = get_request_metadata(rid)
            if metadata:
                metadata['queue_type'] = 'normal'
                all_items.append(metadata)
            else:
                all_items.append({'rid': rid, 'title': f'Request #{rid}', 'artist': '', 'filename': '', 'queue_type': 'normal'})

    # Get moderation queue (random-moderation, planned-moderation)
    mod_response = send_liquidsoap_command('moderation_queue.queue')
    if mod_response and 'ERROR' not in mod_response:
        lines = mod_response.strip().split('\n')
        request_ids = [line.strip() for line in lines if line.strip() and line.strip() != 'END' and line.strip().isdigit()]

        for rid in request_ids:
            metadata = get_request_metadata(rid)
            if metadata:
                metadata['queue_type'] = 'moderation'
                all_items.append(metadata)
            else:
                all_items.append({'rid': rid, 'title': f'Moderation #{rid}', 'artist': '', 'filename': '', 'queue_type': 'moderation'})

    return all_items


def get_request_metadata(rid):
    """Get metadata for a specific request ID"""
    response = send_liquidsoap_command(f'request.metadata {rid}')
    if response and 'ERROR' not in response:
        metadata = {'rid': rid, 'title': '', 'artist': '', 'filename': ''}
        for line in response.strip().split('\n'):
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip().strip('"')
                value = value.strip().strip('"')
                if key == 'title':
                    metadata['title'] = value
                elif key == 'artist':
                    metadata['artist'] = value
                elif key == 'filename':
                    metadata['filename'] = value
        # If no title, use filename
        if not metadata['title'] and metadata['filename']:
            metadata['title'] = metadata['filename'].split('/')[-1]
        return metadata
    return None


def remove_from_queue(rid):
    """Remove a specific request from the queue"""
    # Liquidsoap doesn't have a direct remove command for single items
    # We can skip the queue item if it's currently playing from queue
    response = send_liquidsoap_command('queue.skip')
    return response is not None and 'ERROR' not in str(response)


def clear_queue():
    """Clear the entire queue"""
    response = send_liquidsoap_command('queue.flush_and_skip')
    return response is not None and 'ERROR' not in str(response)


def get_listener_count():
    """Get listener count from Icecast"""
    try:
        url = f'http://{ICECAST_HOST}:{ICECAST_PORT}/status-json.xsl'
        with urllib.request.urlopen(url, timeout=5) as response:
            import json
            data = json.loads(response.read().decode())
            icestats = data.get('icestats', {})
            sources = icestats.get('source')

            # Handle different cases: no source, single source (dict), multiple sources (list)
            if sources is None:
                return 0
            if isinstance(sources, dict):
                sources = [sources]
            if not isinstance(sources, list):
                return 0

            total = sum(s.get('listeners', 0) for s in sources if isinstance(s, dict))
            return total
    except Exception as e:
        print(f"Error getting listener count: {e}")
        return 0


def skip_current_track():
    """Skip the currently playing track"""
    response = send_liquidsoap_command('skip')
    return response is not None


def queue_track(filepath):
    """Add a track to the queue"""
    response = send_liquidsoap_command(f'push {filepath}')
    return response is not None


def insert_from_category(category):
    """Insert a random file from a category into the queue"""
    from app.utils import get_random_file_from_category

    # Get a random file from the database
    audio_file = get_random_file_from_category(category)

    if audio_file and audio_file.path:
        # Determine which queue to use based on category
        # Moderation goes to moderation_queue (higher priority, plays after current track)
        # Everything else goes to normal queue
        if category in ['random-moderation', 'planned-moderation']:
            queue_command = f'moderation_queue.push {audio_file.path}'
        else:
            queue_command = f'queue.push {audio_file.path}'

        response = send_liquidsoap_command(queue_command)
        if response is not None and 'ERROR' not in str(response):
            print(f"[Rotation] Queued {category}: {audio_file.filename}")
            return True
        else:
            print(f"[Rotation] Failed to queue {category}: {response}")

    # Fallback to Liquidsoap's directory-based approach
    command_map = {
        'jingles': 'jingle',
        'promos': 'promo',
        'ads': 'ad',
        'random-moderation': 'random_mod',
        'planned-moderation': 'planned_mod'
    }

    command = command_map.get(category)
    if command:
        response = send_liquidsoap_command(command)
        return response is not None
    return False


def clear_queue():
    """Clear the current queue"""
    # Liquidsoap doesn't have a direct clear command,
    # we'd need to skip until empty
    while get_queue_status():
        skip_current_track()
    return True


def update_output_settings(settings):
    """Update Liquidsoap output settings

    Note: Most output settings require Liquidsoap restart.
    This function updates the configuration file and signals
    for a restart if needed.
    """
    import os

    # Build output encoder string based on format
    if settings.output_format == 'mp3':
        encoder = f'%mp3(bitrate={settings.output_bitrate}, samplerate={settings.output_samplerate}, stereo={"true" if settings.output_channels == 2 else "false"})'
    elif settings.output_format == 'aac':
        encoder = f'%fdkaac(bitrate={settings.output_bitrate}, samplerate={settings.output_samplerate}, channels={settings.output_channels})'
    elif settings.output_format == 'ogg':
        # Vorbis uses quality instead of bitrate, approximate mapping
        quality = min(10, max(0, (settings.output_bitrate - 64) // 25))
        encoder = f'%vorbis(quality={quality}, samplerate={settings.output_samplerate}, channels={settings.output_channels})'
    else:
        encoder = f'%mp3(bitrate={settings.output_bitrate})'

    # Write settings to a file that Liquidsoap can read
    config_path = '/app/config/output_settings.liq'
    try:
        with open(config_path, 'w') as f:
            f.write(f'# Auto-generated output settings\n')
            f.write(f'output_encoder = {encoder}\n')
            f.write(f'normalize_enabled = {"true" if settings.normalize_enabled else "false"}\n')
            f.write(f'target_lufs = {settings.target_lufs}\n')
            f.write(f'station_name = "{settings.station_name}"\n')

        # Signal Liquidsoap to reload if possible
        send_liquidsoap_command('reload')
        return True
    except Exception as e:
        print(f"Error updating output settings: {e}")
        return False


def update_now_playing(title, artist, filename, category, duration, audio_file_id=None):
    """Update the now playing information in the database"""
    from app.models import NowPlaying, PlayHistory
    from app import db
    from app.utils import get_local_now

    # Update NowPlaying
    NowPlaying.update(
        title=title,
        artist=artist,
        filename=filename,
        category=category,
        duration=duration,
        audio_file_id=audio_file_id
    )

    # Also update SystemState for backwards compatibility
    now = get_local_now()
    SystemState.set('current_title', title)
    SystemState.set('current_artist', artist)
    SystemState.set('current_filename', filename)
    SystemState.set('current_started', now.isoformat())

    # Log to play history
    history = PlayHistory(
        audio_file_id=audio_file_id,
        filename=filename,
        title=title,
        artist=artist,
        category=category,
        triggered_by='rotation',
        played_at=now.replace(tzinfo=None)
    )
    db.session.add(history)
    db.session.commit()


# ========== MODERATION PANEL CONTROLS ==========

def set_bed_enabled(enabled):
    """Enable or disable the music bed"""
    command = 'bed.on' if enabled else 'bed.off'
    response = send_liquidsoap_command(command)
    return response is not None and 'ERROR' not in str(response)


def set_bed_volume(volume):
    """Set music bed volume (0.0 - 1.0)"""
    volume = max(0.0, min(1.0, float(volume)))
    response = send_liquidsoap_command(f'bed.volume {volume}')
    return response is not None and 'ERROR' not in str(response)


def set_bed_ducking_level(level):
    """Set music bed ducking level (0.0 - 1.0)"""
    level = max(0.0, min(1.0, float(level)))
    response = send_liquidsoap_command(f'bed.duck_level {level}')
    return response is not None and 'ERROR' not in str(response)


def get_bed_status():
    """Get current music bed status"""
    response = send_liquidsoap_command('bed.status')
    if response and 'ERROR' not in response:
        # Clean up response
        response = response.replace('END', '').replace('\r', '').replace('\n', '').strip()

        # Parse: enabled=true, volume=0.3, duck_level=0.15
        status = {'enabled': False, 'volume': 0.3, 'duck_level': 0.15}
        for part in response.split(','):
            if '=' in part:
                key, value = part.strip().split('=', 1)
                value = value.strip()
                try:
                    if key == 'enabled':
                        status['enabled'] = value.lower() == 'true'
                    elif key == 'volume':
                        status['volume'] = float(value)
                    elif key == 'duck_level':
                        status['duck_level'] = float(value)
                except ValueError:
                    pass
        return status
    return {'enabled': False, 'volume': 0.3, 'duck_level': 0.15}


def set_ducking_active(active):
    """Activate or deactivate ducking (lowers music bed volume)"""
    command = 'duck.on' if active else 'duck.off'
    response = send_liquidsoap_command(command)
    return response is not None and 'ERROR' not in str(response)


def get_ducking_status():
    """Get ducking status"""
    response = send_liquidsoap_command('duck.status')
    if response and 'ERROR' not in response:
        # Clean up response
        response = response.replace('END', '').replace('\r', '').replace('\n', '').strip().lower()
        # Parse: active=true
        return 'active=true' in response
    return False


def play_instant_jingle(filepath):
    """Play an instant jingle immediately"""
    response = send_liquidsoap_command(f'jingle.play {filepath}')
    return response is not None and 'ERROR' not in str(response)


def set_jingle_volume(volume):
    """Set instant jingle volume (0.0 - 1.0)"""
    volume = max(0.0, min(1.0, float(volume)))
    response = send_liquidsoap_command(f'jingle.volume {volume}')
    return response is not None and 'ERROR' not in str(response)


def get_moderation_status():
    """Get complete moderation panel status"""
    response = send_liquidsoap_command('moderation.status')
    if response and 'ERROR' not in response:
        # Clean up response - remove END marker and extra whitespace
        response = response.replace('END', '').replace('\r', '').replace('\n', '').strip()

        # Parse: bed_enabled=true, ducking=false, bed_vol=0.3, duck_level=0.15, jingle_vol=1.0, mic_enabled=false, mic_vol=1.0, mic_auto_duck=true
        status = {
            'bed_enabled': False,
            'ducking_active': False,
            'bed_volume': 0.3,
            'ducking_level': 0.15,
            'jingle_volume': 1.0,
            'mic_enabled': False,
            'mic_volume': 1.0,
            'mic_auto_duck': True
        }
        for part in response.split(','):
            if '=' in part:
                key, value = part.strip().split('=', 1)
                value = value.strip()
                try:
                    if key == 'bed_enabled':
                        status['bed_enabled'] = value.lower() == 'true'
                    elif key == 'ducking':
                        status['ducking_active'] = value.lower() == 'true'
                    elif key == 'bed_vol':
                        status['bed_volume'] = float(value)
                    elif key == 'duck_level':
                        status['ducking_level'] = float(value)
                    elif key == 'jingle_vol':
                        status['jingle_volume'] = float(value)
                    elif key == 'mic_enabled':
                        status['mic_enabled'] = value.lower() == 'true'
                    elif key == 'mic_vol':
                        status['mic_volume'] = float(value)
                    elif key == 'mic_auto_duck':
                        status['mic_auto_duck'] = value.lower() == 'true'
                except ValueError:
                    pass  # Skip malformed values
        return status
    return {
        'bed_enabled': False,
        'ducking_active': False,
        'bed_volume': 0.3,
        'ducking_level': 0.15,
        'jingle_volume': 1.0,
        'mic_enabled': False,
        'mic_volume': 1.0,
        'mic_auto_duck': True
    }


# ========== MICROPHONE CONTROLS ==========

def set_mic_enabled(enabled):
    """Enable or disable the microphone input"""
    command = 'mic.on' if enabled else 'mic.off'
    response = send_liquidsoap_command(command)
    return response is not None and 'ERROR' not in str(response)


def set_mic_volume(volume):
    """Set microphone volume (0.0 - 1.0)"""
    volume = max(0.0, min(1.0, float(volume)))
    response = send_liquidsoap_command(f'mic.volume {volume}')
    return response is not None and 'ERROR' not in str(response)


def set_mic_auto_duck(enabled):
    """Enable or disable auto-ducking when mic is active"""
    value = 'true' if enabled else 'false'
    response = send_liquidsoap_command(f'mic.auto_duck {value}')
    return response is not None and 'ERROR' not in str(response)


def get_mic_status():
    """Get current microphone status"""
    response = send_liquidsoap_command('mic.status')
    if response and 'ERROR' not in response:
        # Clean up response
        response = response.replace('END', '').replace('\r', '').replace('\n', '').strip()

        # Parse: enabled=true, volume=1.0, auto_duck=true
        status = {'enabled': False, 'volume': 1.0, 'auto_duck': True}
        for part in response.split(','):
            if '=' in part:
                key, value = part.strip().split('=', 1)
                value = value.strip()
                try:
                    if key == 'enabled':
                        status['enabled'] = value.lower() == 'true'
                    elif key == 'volume':
                        status['volume'] = float(value)
                    elif key == 'auto_duck':
                        status['auto_duck'] = value.lower() == 'true'
                except ValueError:
                    pass
        return status
    return {'enabled': False, 'volume': 1.0, 'auto_duck': True}


# ========== RECORDED MODERATION CONTROLS ==========

def queue_recorded_moderation(filepath):
    """Queue a recorded moderation to play after current track"""
    # Use the moderation queue in Liquidsoap
    response = send_liquidsoap_command(f'moderation_queue.push {filepath}')
    return response is not None and 'ERROR' not in str(response)


def get_moderation_queue():
    """Get list of queued moderations"""
    response = send_liquidsoap_command('moderation_queue.queue')
    if response and 'ERROR' not in response:
        lines = response.strip().split('\n')
        items = [line.strip() for line in lines if line.strip() and line.strip() != 'END']
        return items
    return []


def clear_moderation_queue():
    """Clear all queued moderations"""
    response = send_liquidsoap_command('moderation_queue.flush_and_skip')
    return response is not None and 'ERROR' not in str(response)


# ========== CROSSFADE CONTROLS ==========

def update_crossfade_settings(settings):
    """Update crossfade settings in Liquidsoap"""
    results = []

    # Update music fade settings
    if hasattr(settings, 'crossfade_music_fade_in'):
        response = send_liquidsoap_command(f'crossfade.music_fade_in {settings.crossfade_music_fade_in}')
        results.append(response is not None)

    if hasattr(settings, 'crossfade_music_fade_out'):
        response = send_liquidsoap_command(f'crossfade.music_fade_out {settings.crossfade_music_fade_out}')
        results.append(response is not None)

    # Update jingle fade settings
    if hasattr(settings, 'crossfade_jingle_fade_in'):
        response = send_liquidsoap_command(f'crossfade.jingle_fade_in {settings.crossfade_jingle_fade_in}')
        results.append(response is not None)

    if hasattr(settings, 'crossfade_jingle_fade_out'):
        response = send_liquidsoap_command(f'crossfade.jingle_fade_out {settings.crossfade_jingle_fade_out}')
        results.append(response is not None)

    # Update moderation fade settings
    if hasattr(settings, 'crossfade_moderation_fade_in'):
        response = send_liquidsoap_command(f'crossfade.moderation_fade_in {settings.crossfade_moderation_fade_in}')
        results.append(response is not None)

    if hasattr(settings, 'crossfade_moderation_fade_out'):
        response = send_liquidsoap_command(f'crossfade.moderation_fade_out {settings.crossfade_moderation_fade_out}')
        results.append(response is not None)

    return all(results) if results else True


def reload_crossfade_settings():
    """Reload crossfade settings from JSON file"""
    response = send_liquidsoap_command('crossfade.reload')
    return response is not None and 'ERROR' not in str(response)


def get_crossfade_status():
    """Get current crossfade settings from Liquidsoap"""
    response = send_liquidsoap_command('crossfade.status')
    if response and 'ERROR' not in response:
        # Clean up response
        response = response.replace('END', '').replace('\r', '').replace('\n', '').strip()

        # Parse: music_in=0.5, music_out=0.5, jingle_in=0.0, jingle_out=0.0, mod_in=0.0, mod_out=0.0
        status = {
            'music_fade_in': 0.5,
            'music_fade_out': 0.5,
            'jingle_fade_in': 0.0,
            'jingle_fade_out': 0.0,
            'moderation_fade_in': 0.0,
            'moderation_fade_out': 0.0
        }
        for part in response.split(','):
            if '=' in part:
                key, value = part.strip().split('=', 1)
                value = value.strip()
                try:
                    if key == 'music_in':
                        status['music_fade_in'] = float(value)
                    elif key == 'music_out':
                        status['music_fade_out'] = float(value)
                    elif key == 'jingle_in':
                        status['jingle_fade_in'] = float(value)
                    elif key == 'jingle_out':
                        status['jingle_fade_out'] = float(value)
                    elif key == 'mod_in':
                        status['moderation_fade_in'] = float(value)
                    elif key == 'mod_out':
                        status['moderation_fade_out'] = float(value)
                except ValueError:
                    pass
        return status
    return {
        'music_fade_in': 0.5,
        'music_fade_out': 0.5,
        'jingle_fade_in': 0.0,
        'jingle_fade_out': 0.0,
        'moderation_fade_in': 0.0,
        'moderation_fade_out': 0.0
    }
