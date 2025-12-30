from datetime import datetime
from flask import Blueprint, request, jsonify, current_app, Response
from app import db, socketio
from app.models import AudioFile, PlayHistory, SystemState, StreamSettings, NowPlaying, InstantJingle, ModerationSettings

api_bp = Blueprint('api', __name__)


@api_bp.route('/now-playing', methods=['POST'])
def update_now_playing():
    """Called by Liquidsoap when a new track starts playing"""
    title = request.form.get('title', '')
    artist = request.form.get('artist', '')
    filename = request.form.get('filename', '')
    duration = request.form.get('duration', 0, type=float)

    # Get settings for custom texts
    settings = StreamSettings.get_settings()

    # Find audio file in database
    audio_file = AudioFile.query.filter_by(filename=filename).first()

    # Update play count and last played
    if audio_file:
        audio_file.play_count += 1
        audio_file.last_played = datetime.utcnow()
        title = audio_file.title or title or filename
        artist = audio_file.artist or artist
        duration = audio_file.duration or duration
        category = audio_file.category

        # Use custom text for jingles and moderations
        if category == 'jingles':
            title = settings.jingle_nowplaying_text
            artist = ''
        elif category == 'promos':
            title = settings.promo_nowplaying_text
            artist = ''
        elif category == 'ads':
            title = settings.ad_nowplaying_text
            artist = ''
        elif category in ['random-moderation', 'planned-moderation']:
            title = settings.moderation_nowplaying_text
            artist = ''

        # Log to history
        history = PlayHistory(
            audio_file_id=audio_file.id,
            filename=filename,
            title=title,
            artist=artist,
            category=category,
            triggered_by='rotation'
        )
        db.session.add(history)
    else:
        category = ''

    # Update NowPlaying singleton
    NowPlaying.update(
        title=title or filename,
        artist=artist,
        filename=filename,
        category=category,
        duration=duration,
        audio_file_id=audio_file.id if audio_file else None
    )

    db.session.commit()

    # Get current show info
    show_name = settings.current_show.name if settings.current_show else settings.default_show_name

    # Broadcast to all connected clients
    socketio.emit('now_playing', {
        'title': title or filename,
        'artist': artist,
        'filename': filename,
        'duration': duration,
        'show': show_name,
        'station': settings.station_name,
        'started_at': datetime.utcnow().isoformat()
    })

    return jsonify({'success': True})


@api_bp.route('/nowplaying')
@api_bp.route('/nowplaying.json')
def get_nowplaying_json():
    """Public JSON API for current track info - no auth required"""
    np = NowPlaying.get_current()
    response = jsonify(np.to_dict())

    # Add CORS headers to allow external access (e.g., from JavaScript on other websites)
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'

    return response


@api_bp.route('/nowplaying', methods=['OPTIONS'])
@api_bp.route('/nowplaying.json', methods=['OPTIONS'])
def nowplaying_options():
    """Handle CORS preflight requests for nowplaying endpoint"""
    response = Response()
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


@api_bp.route('/nowplaying.txt')
def get_nowplaying_text():
    """Plain text format for simple integrations"""
    np = NowPlaying.get_current()
    settings = StreamSettings.get_settings()
    show = settings.current_show.name if settings.current_show else settings.default_show_name

    text = f"{np.artist} - {np.title}" if np.artist else np.title
    return Response(text, mimetype='text/plain')


@api_bp.route('/status')
def get_status():
    """Get current playback status"""
    from app.audio_engine import get_queue_status, get_listener_count

    np = NowPlaying.get_current()
    settings = StreamSettings.get_settings()

    return jsonify({
        'current_track': np.to_dict(),
        'queue': get_queue_status(),
        'listeners': get_listener_count(),
        'stream_settings': settings.to_dict()
    })


@api_bp.route('/stream-settings', methods=['GET'])
def get_stream_settings():
    """Get stream output settings"""
    settings = StreamSettings.get_settings()
    return jsonify(settings.to_dict())


@api_bp.route('/stream-settings', methods=['POST'])
def update_stream_settings():
    """Update stream output settings"""
    data = request.json
    settings = StreamSettings.get_settings()

    if 'output_format' in data:
        settings.output_format = data['output_format']
    if 'output_bitrate' in data:
        settings.output_bitrate = int(data['output_bitrate'])
    if 'output_samplerate' in data:
        settings.output_samplerate = int(data['output_samplerate'])
    if 'output_channels' in data:
        settings.output_channels = int(data['output_channels'])
    if 'normalize_enabled' in data:
        settings.normalize_enabled = bool(data['normalize_enabled'])
    if 'target_lufs' in data:
        settings.target_lufs = float(data['target_lufs'])
    if 'station_name' in data:
        settings.station_name = data['station_name']
    if 'default_show_name' in data:
        settings.default_show_name = data['default_show_name']
    if 'current_show_id' in data:
        settings.current_show_id = data['current_show_id'] if data['current_show_id'] else None

    # Crossfade settings
    if 'crossfade_music_fade_in' in data:
        settings.crossfade_music_fade_in = max(0.0, min(5.0, float(data['crossfade_music_fade_in'])))
    if 'crossfade_music_fade_out' in data:
        settings.crossfade_music_fade_out = max(0.0, min(5.0, float(data['crossfade_music_fade_out'])))
    if 'crossfade_jingle_fade_in' in data:
        settings.crossfade_jingle_fade_in = max(0.0, min(5.0, float(data['crossfade_jingle_fade_in'])))
    if 'crossfade_jingle_fade_out' in data:
        settings.crossfade_jingle_fade_out = max(0.0, min(5.0, float(data['crossfade_jingle_fade_out'])))
    if 'crossfade_moderation_fade_in' in data:
        settings.crossfade_moderation_fade_in = max(0.0, min(5.0, float(data['crossfade_moderation_fade_in'])))
    if 'crossfade_moderation_fade_out' in data:
        settings.crossfade_moderation_fade_out = max(0.0, min(5.0, float(data['crossfade_moderation_fade_out'])))

    # Now Playing custom texts
    if 'jingle_nowplaying_text' in data:
        settings.jingle_nowplaying_text = data['jingle_nowplaying_text']
    if 'promo_nowplaying_text' in data:
        settings.promo_nowplaying_text = data['promo_nowplaying_text']
    if 'ad_nowplaying_text' in data:
        settings.ad_nowplaying_text = data['ad_nowplaying_text']
    if 'moderation_nowplaying_text' in data:
        settings.moderation_nowplaying_text = data['moderation_nowplaying_text']

    db.session.commit()

    # Write settings to file for Liquidsoap to read
    write_liquidsoap_settings(settings)

    # Update crossfade settings in Liquidsoap via telnet
    from app.audio_engine import update_crossfade_settings
    update_crossfade_settings(settings)

    return jsonify({'success': True, 'settings': settings.to_dict()})


def write_liquidsoap_settings(settings):
    """Write settings to a file that Liquidsoap can read"""
    import json
    settings_file = '/data/stream_settings.json'
    with open(settings_file, 'w') as f:
        json.dump(settings.to_dict(), f)


@api_bp.route('/skip', methods=['POST'])
def skip_track():
    """Skip current track"""
    from app.audio_engine import skip_current_track
    result = skip_current_track()
    return jsonify({'success': result})


@api_bp.route('/queue', methods=['POST'])
def queue_track():
    """Add a track to the queue"""
    from app.audio_engine import send_liquidsoap_command

    data = request.json
    file_id = data.get('file_id')

    audio_file = AudioFile.query.get(file_id)
    if not audio_file:
        return jsonify({'error': 'File not found'}), 404

    # Determine which queue to use based on category
    # Moderation goes to moderation_queue (higher priority, plays after current track)
    # Everything else goes to normal queue
    if audio_file.category in ['random-moderation', 'planned-moderation']:
        response = send_liquidsoap_command(f'moderation_queue.push {audio_file.path}')
    else:
        response = send_liquidsoap_command(f'queue.push {audio_file.path}')

    result = response is not None and 'ERROR' not in str(response)
    return jsonify({'success': result})


@api_bp.route('/queue/clear', methods=['POST'])
def clear_queue():
    """Clear the entire queue"""
    from app.audio_engine import clear_queue as do_clear_queue
    result = do_clear_queue()
    return jsonify({'success': result})


@api_bp.route('/insert/<category>', methods=['POST'])
def insert_category(category):
    """Insert a random file from a category"""
    from app.audio_engine import insert_from_category

    valid_categories = current_app.config['CATEGORIES']
    if category not in valid_categories:
        return jsonify({'error': 'Invalid category'}), 400

    result = insert_from_category(category)
    return jsonify({'success': result})


@api_bp.route('/files/<category>')
def get_files(category):
    """Get all files for a category"""
    valid_categories = current_app.config['CATEGORIES']
    if category not in valid_categories:
        return jsonify({'error': 'Invalid category'}), 400

    files = AudioFile.query.filter_by(category=category).order_by(AudioFile.filename).all()
    return jsonify([f.to_dict() for f in files])


@api_bp.route('/files/all')
def get_all_files():
    """Get all files grouped by category"""
    categories = current_app.config['CATEGORIES']
    result = {}

    for category in categories:
        files = AudioFile.query.filter_by(category=category).order_by(AudioFile.filename).all()
        result[category] = [f.to_dict() for f in files]

    return jsonify(result)


@api_bp.route('/files/<int:file_id>')
def get_file(file_id):
    """Get details for a single file"""
    audio_file = AudioFile.query.get_or_404(file_id)
    return jsonify(audio_file.to_dict())


@api_bp.route('/history')
def get_history():
    """Get play history"""
    limit = request.args.get('limit', 50, type=int)
    history = PlayHistory.query.order_by(PlayHistory.played_at.desc()).limit(limit).all()
    return jsonify([h.to_dict() for h in history])


@api_bp.route('/shows')
def get_shows():
    """Get all shows"""
    from app.models import Show
    shows = Show.query.order_by(Show.name).all()
    return jsonify([s.to_dict() for s in shows])


@api_bp.route('/shows/<int:show_id>')
def get_show(show_id):
    """Get a specific show with items"""
    from app.models import Show
    show = Show.query.get_or_404(show_id)
    return jsonify(show.to_dict(include_items=True))


@api_bp.route('/shows/<int:show_id>/play', methods=['POST'])
def play_show(show_id):
    """Queue all items from a show and set as current show"""
    from app.models import Show
    from app.audio_engine import queue_track

    show = Show.query.get_or_404(show_id)

    # Set as current show
    settings = StreamSettings.get_settings()
    settings.current_show_id = show_id
    db.session.commit()

    for item in show.items.order_by('position').all():
        if item.audio_file:
            queue_track(item.audio_file.path)

    return jsonify({'success': True, 'items_queued': show.items.count()})


@api_bp.route('/shows/stop', methods=['POST'])
def stop_show():
    """Clear current show (back to automation mode)"""
    settings = StreamSettings.get_settings()
    settings.current_show_id = None
    db.session.commit()
    return jsonify({'success': True})


@api_bp.route('/internal/track-change', methods=['POST'])
def internal_track_change():
    """Internal endpoint called by Liquidsoap when track changes"""
    title = request.form.get('title', '')
    artist = request.form.get('artist', '')
    filename = request.form.get('filename', '')

    # Extract just the filename if full path provided
    if '/' in filename:
        filename = filename.split('/')[-1]

    # Get settings for custom texts
    settings = StreamSettings.get_settings()

    # Try to find the file in database
    audio_file = AudioFile.query.filter_by(filename=filename).first()

    if audio_file:
        title = audio_file.title or title or filename
        artist = audio_file.artist or artist
        duration = audio_file.duration or 0
        category = audio_file.category

        # Use custom text for jingles and moderations
        if category == 'jingles':
            title = settings.jingle_nowplaying_text
            artist = ''
        elif category == 'promos':
            title = settings.promo_nowplaying_text
            artist = ''
        elif category == 'ads':
            title = settings.ad_nowplaying_text
            artist = ''
        elif category in ['random-moderation', 'planned-moderation']:
            title = settings.moderation_nowplaying_text
            artist = ''

        # Update play count
        audio_file.play_count += 1
        audio_file.last_played = datetime.utcnow()

        # Update NowPlaying
        NowPlaying.update(
            title=title,
            artist=artist,
            filename=filename,
            category=category,
            duration=duration,
            audio_file_id=audio_file.id
        )

        # Log to history
        history = PlayHistory(
            audio_file_id=audio_file.id,
            filename=filename,
            title=title,
            artist=artist,
            category=category,
            triggered_by='rotation'
        )
        db.session.add(history)
        db.session.commit()
    else:
        # Unknown file, still update NowPlaying
        NowPlaying.update(
            title=title or filename,
            artist=artist,
            filename=filename,
            category='',
            duration=0
        )

    # Broadcast via WebSocket
    show_name = settings.current_show.name if settings.current_show else settings.default_show_name

    socketio.emit('now_playing', {
        'title': title or filename,
        'artist': artist,
        'show': show_name,
        'station': settings.station_name
    })

    return 'OK', 200


@api_bp.route('/rules')
def get_rules():
    """Get all rotation rules"""
    from app.models import RotationRule
    rules = RotationRule.query.order_by(RotationRule.priority.desc()).all()
    return jsonify([r.to_dict() for r in rules])


@api_bp.route('/schedules')
def get_schedules():
    """Get all schedules"""
    from app.models import Schedule
    schedules = Schedule.query.order_by(Schedule.scheduled_time).all()
    return jsonify([s.to_dict() for s in schedules])


# ========== MODERATION PANEL API ==========

@api_bp.route('/moderation/status')
def get_moderation_status():
    """Get current moderation panel status from Liquidsoap"""
    from app.audio_engine import get_moderation_status
    status = get_moderation_status()
    settings = ModerationSettings.get_settings()
    return jsonify({
        'liquidsoap': status,
        'settings': settings.to_dict()
    })


@api_bp.route('/moderation/settings', methods=['GET'])
def get_moderation_settings():
    """Get moderation panel settings"""
    settings = ModerationSettings.get_settings()
    return jsonify(settings.to_dict())


@api_bp.route('/moderation/settings', methods=['POST'])
def update_moderation_settings():
    """Update moderation panel settings"""
    data = request.json
    settings = ModerationSettings.get_settings()

    if 'mic_enabled' in data:
        settings.mic_enabled = bool(data['mic_enabled'])
    if 'mic_auto_start_bed' in data:
        settings.mic_auto_start_bed = bool(data['mic_auto_start_bed'])
    if 'bed_enabled' in data:
        settings.bed_enabled = bool(data['bed_enabled'])
    if 'bed_volume' in data:
        settings.bed_volume = float(data['bed_volume'])
    if 'bed_ducking_level' in data:
        settings.bed_ducking_level = float(data['bed_ducking_level'])
    if 'bed_loop' in data:
        settings.bed_loop = bool(data['bed_loop'])
    if 'bed_audio_file_id' in data:
        settings.bed_audio_file_id = data['bed_audio_file_id'] if data['bed_audio_file_id'] else None
    if 'ducking_enabled' in data:
        settings.ducking_enabled = bool(data['ducking_enabled'])
    if 'ducking_attack_ms' in data:
        settings.ducking_attack_ms = int(data['ducking_attack_ms'])
    if 'ducking_release_ms' in data:
        settings.ducking_release_ms = int(data['ducking_release_ms'])
    if 'jingle_volume' in data:
        settings.jingle_volume = float(data['jingle_volume'])
    if 'jingle_duck_music' in data:
        settings.jingle_duck_music = bool(data['jingle_duck_music'])

    db.session.commit()
    return jsonify({'success': True, 'settings': settings.to_dict()})


@api_bp.route('/moderation/bed/toggle', methods=['POST'])
def toggle_music_bed():
    """Toggle music bed on/off"""
    from app.audio_engine import set_bed_enabled, get_bed_status

    data = request.json or {}
    enabled = data.get('enabled')

    if enabled is None:
        # Toggle current state
        status = get_bed_status()
        enabled = not status.get('enabled', False)

    result = set_bed_enabled(enabled)

    # Update settings in DB
    settings = ModerationSettings.get_settings()
    settings.bed_enabled = enabled
    db.session.commit()

    return jsonify({'success': result, 'enabled': enabled})


@api_bp.route('/moderation/bed/volume', methods=['POST'])
def set_music_bed_volume():
    """Set music bed volume"""
    from app.audio_engine import set_bed_volume

    data = request.json
    volume = float(data.get('volume', 0.3))

    result = set_bed_volume(volume)

    # Update settings in DB
    settings = ModerationSettings.get_settings()
    settings.bed_volume = volume
    db.session.commit()

    return jsonify({'success': result, 'volume': volume})


@api_bp.route('/moderation/ducking/toggle', methods=['POST'])
def toggle_ducking():
    """Toggle ducking on/off"""
    from app.audio_engine import set_ducking_active, get_ducking_status

    data = request.json or {}
    active = data.get('active')

    if active is None:
        # Toggle current state
        active = not get_ducking_status()

    result = set_ducking_active(active)
    return jsonify({'success': result, 'active': active})


@api_bp.route('/moderation/ducking/level', methods=['POST'])
def set_ducking_level():
    """Set ducking level"""
    from app.audio_engine import set_bed_ducking_level

    data = request.json
    level = float(data.get('level', 0.15))

    result = set_bed_ducking_level(level)

    # Update settings in DB
    settings = ModerationSettings.get_settings()
    settings.bed_ducking_level = level
    db.session.commit()

    return jsonify({'success': result, 'level': level})


@api_bp.route('/moderation/jingles', methods=['GET'])
def get_instant_jingles():
    """Get all 9 instant jingle slots"""
    InstantJingle.ensure_slots_exist()
    jingles = InstantJingle.query.order_by(InstantJingle.slot_number).all()
    return jsonify([j.to_dict() for j in jingles])


@api_bp.route('/moderation/jingles/<int:slot>', methods=['GET'])
def get_instant_jingle(slot):
    """Get a specific jingle slot"""
    if slot < 1 or slot > 9:
        return jsonify({'error': 'Invalid slot number (1-9)'}), 400

    jingle = InstantJingle.query.filter_by(slot_number=slot).first()
    if not jingle:
        return jsonify({'error': 'Slot not found'}), 404

    return jsonify(jingle.to_dict())


@api_bp.route('/moderation/jingles/<int:slot>', methods=['POST'])
def update_instant_jingle(slot):
    """Configure a jingle slot"""
    if slot < 1 or slot > 9:
        return jsonify({'error': 'Invalid slot number (1-9)'}), 400

    InstantJingle.ensure_slots_exist()
    jingle = InstantJingle.query.filter_by(slot_number=slot).first()

    data = request.json
    if 'audio_file_id' in data:
        jingle.audio_file_id = data['audio_file_id'] if data['audio_file_id'] else None
    if 'label' in data:
        jingle.label = data['label']
    if 'color' in data:
        jingle.color = data['color']

    db.session.commit()
    return jsonify({'success': True, 'jingle': jingle.to_dict()})


@api_bp.route('/moderation/jingles/<int:slot>/play', methods=['POST'])
def play_instant_jingle(slot):
    """Play a jingle from a specific slot"""
    from app.audio_engine import play_instant_jingle as do_play_jingle

    if slot < 1 or slot > 9:
        return jsonify({'error': 'Invalid slot number (1-9)'}), 400

    jingle = InstantJingle.query.filter_by(slot_number=slot).first()
    if not jingle or not jingle.audio_file:
        return jsonify({'error': 'No jingle configured for this slot'}), 404

    result = do_play_jingle(jingle.audio_file.path)
    return jsonify({'success': result, 'played': jingle.audio_file.filename})


@api_bp.route('/moderation/jingle/volume', methods=['POST'])
def set_jingle_volume_api():
    """Set instant jingle volume"""
    from app.audio_engine import set_jingle_volume

    data = request.json
    volume = float(data.get('volume', 1.0))

    result = set_jingle_volume(volume)

    # Update settings in DB
    settings = ModerationSettings.get_settings()
    settings.jingle_volume = volume
    db.session.commit()

    return jsonify({'success': result, 'volume': volume})


@api_bp.route('/moderation/beds', methods=['GET'])
def get_music_beds():
    """Get all available music bed files"""
    beds = AudioFile.query.filter_by(category='musicbeds', is_active=True).order_by(AudioFile.filename).all()
    return jsonify([b.to_dict() for b in beds])


@api_bp.route('/moderation/bed/current', methods=['GET'])
def get_current_music_bed():
    """Get the current/first available music bed file for recording"""
    import os

    # First check if there's a specific bed configured in settings
    settings = ModerationSettings.get_settings()
    if settings.bed_audio_file_id:
        bed = AudioFile.query.get(settings.bed_audio_file_id)
        if bed and bed.is_active:
            # Return web-accessible URL
            return jsonify({
                'file': f'/api/moderation/bed/stream/{bed.filename}',
                'filename': bed.filename
            })

    # Otherwise get first available bed from the directory
    beds_dir = '/media/musicbeds'
    if os.path.exists(beds_dir):
        for f in os.listdir(beds_dir):
            if f.lower().endswith(('.mp3', '.ogg', '.wav', '.flac')):
                # Return web-accessible URL
                return jsonify({
                    'file': f'/api/moderation/bed/stream/{f}',
                    'filename': f
                })

    return jsonify({'file': None, 'filename': None})


@api_bp.route('/moderation/bed/stream/<filename>')
def stream_music_bed(filename):
    """Stream a music bed file for browser playback"""
    import os
    from flask import send_file

    # Sanitize filename
    filename = os.path.basename(filename)
    filepath = os.path.join('/media/musicbeds', filename)

    if os.path.exists(filepath):
        return send_file(filepath, mimetype='audio/mpeg')
    else:
        return jsonify({'error': 'File not found'}), 404


# ========== MICROPHONE API ==========

@api_bp.route('/moderation/mic/toggle', methods=['POST'])
def toggle_mic():
    """Toggle microphone on/off"""
    from app.audio_engine import set_mic_enabled, get_mic_status

    data = request.json or {}
    enabled = data.get('enabled')

    if enabled is None:
        # Toggle current state
        status = get_mic_status()
        enabled = not status.get('enabled', False)

    result = set_mic_enabled(enabled)

    # Update settings in DB
    settings = ModerationSettings.get_settings()
    settings.mic_enabled = enabled
    db.session.commit()

    return jsonify({'success': result, 'enabled': enabled})


@api_bp.route('/moderation/mic/volume', methods=['POST'])
def set_mic_volume_api():
    """Set microphone volume"""
    from app.audio_engine import set_mic_volume

    data = request.json
    volume = float(data.get('volume', 1.0))

    result = set_mic_volume(volume)
    return jsonify({'success': result, 'volume': volume})


@api_bp.route('/moderation/mic/auto-duck', methods=['POST'])
def set_mic_auto_duck_api():
    """Set microphone auto-duck setting"""
    from app.audio_engine import set_mic_auto_duck

    data = request.json
    enabled = bool(data.get('enabled', True))

    result = set_mic_auto_duck(enabled)

    # Update settings in DB
    settings = ModerationSettings.get_settings()
    settings.mic_auto_start_bed = enabled
    db.session.commit()

    return jsonify({'success': result, 'enabled': enabled})


@api_bp.route('/moderation/mic/status', methods=['GET'])
def get_mic_status_api():
    """Get microphone status"""
    from app.audio_engine import get_mic_status
    status = get_mic_status()
    return jsonify(status)


# ========== RECORDED MODERATION API ==========

@api_bp.route('/moderation/recording/upload', methods=['POST'])
def upload_recorded_moderation():
    """Upload a recorded moderation and queue it for playback"""
    import os
    import subprocess
    from werkzeug.utils import secure_filename

    if 'audio' not in request.files:
        return jsonify({'error': 'No audio file provided'}), 400

    audio_file = request.files['audio']
    with_bed = request.form.get('with_bed', 'false').lower() == 'true'

    if audio_file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    # Create Live-Mods directory if it doesn't exist
    recordings_dir = '/media/Live-Mods'
    os.makedirs(recordings_dir, exist_ok=True)

    # Generate unique filename
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    base_name = f'moderation_{timestamp}'

    # Save the uploaded webm file temporarily
    temp_webm = os.path.join(recordings_dir, f'{base_name}.webm')
    audio_file.save(temp_webm)

    # Convert to MP3 using ffmpeg for Liquidsoap compatibility
    output_mp3 = os.path.join(recordings_dir, f'{base_name}.mp3')
    try:
        result = subprocess.run([
            'ffmpeg', '-y', '-i', temp_webm,
            '-acodec', 'libmp3lame', '-ab', '192k', '-ar', '44100', '-ac', '2',
            output_mp3
        ], capture_output=True, timeout=60)

        if result.returncode != 0:
            return jsonify({'error': 'Audio conversion failed'}), 500

        # Get duration using ffprobe
        duration_result = subprocess.run([
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', output_mp3
        ], capture_output=True, text=True, timeout=30)

        duration = float(duration_result.stdout.strip()) if duration_result.stdout.strip() else 0

        # Remove temp webm file
        os.remove(temp_webm)

        # Queue in Liquidsoap
        from app.audio_engine import queue_recorded_moderation
        queue_result = queue_recorded_moderation(output_mp3)

        return jsonify({
            'success': True,
            'filename': f'{base_name}.mp3',
            'path': output_mp3,
            'duration': duration,
            'queued': queue_result
        })

    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Conversion timeout'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/moderation/recording/queue', methods=['GET'])
def get_recording_queue():
    """Get list of queued recorded moderations"""
    from app.audio_engine import get_moderation_queue
    queue = get_moderation_queue()
    return jsonify(queue)


# ==================== LISTENER STATISTICS ====================

@api_bp.route('/listeners/current', methods=['GET'])
def get_current_listeners():
    """Get current listener count"""
    from app.listener_tracking import get_icecast_listeners
    count = get_icecast_listeners()
    return jsonify({'listeners': count})


@api_bp.route('/listeners/stats', methods=['GET'])
def get_listener_stats():
    """
    Get listener statistics for a given time period
    Query params:
    - hours: Number of hours to look back (default: 24)
    """
    from app.listener_tracking import get_listener_statistics

    hours = request.args.get('hours', 24, type=int)

    # Limit to reasonable range
    hours = max(1, min(hours, 720))  # 1 hour to 30 days

    stats = get_listener_statistics(hours=hours)
    return jsonify(stats)


@api_bp.route('/listeners/history', methods=['GET'])
def get_listener_history():
    """
    Get detailed listener history
    Query params:
    - hours: Number of hours to look back (default: 24)
    - limit: Maximum number of data points to return (default: unlimited)
    """
    from app.models import ListenerStats

    hours = request.args.get('hours', 24, type=int)
    limit = request.args.get('limit', 0, type=int)

    # Get stats
    stats = ListenerStats.get_stats(hours=hours)

    # Apply limit if specified
    if limit > 0:
        stats = stats[-limit:]

    return jsonify({
        'data': [s.to_dict() for s in stats],
        'count': len(stats)
    })
