import os
from datetime import datetime, time
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, send_file
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.models import User, AudioFile, RotationRule, Show, ShowItem, Schedule, PlayHistory, StreamSettings, InstantJingle, ModerationSettings
from app.utils import scan_media_files, get_audio_metadata, is_supported_audio_file, SUPPORTED_FORMATS

main_bp = Blueprint('main', __name__)


@main_bp.route('/health')
def health():
    return jsonify({'status': 'ok'}), 200


@main_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('main.dashboard'))
        else:
            flash('Ungültiger Benutzername oder Passwort', 'error')

    return render_template('login.html')


@main_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.login'))


@main_bp.route('/')
@login_required
def dashboard():
    # Get current playing info from NowPlaying model
    from app.models import NowPlaying
    from app.audio_engine import get_queue_status

    np = NowPlaying.get_current()
    current_track = {
        'title': np.title or 'Nichts abgespielt',
        'artist': np.artist or '',
        'filename': np.filename or '',
        'started_at': np.started_at.isoformat() if np.started_at else ''
    }

    # Get queue status (may be empty if Liquidsoap doesn't support the command)
    queue_status = get_queue_status()

    # Get recent play history
    recent_plays = PlayHistory.query.order_by(PlayHistory.played_at.desc()).limit(10).all()

    # Get file counts per category
    file_counts = {}
    for category in current_app.config['CATEGORIES']:
        file_counts[category] = AudioFile.query.filter_by(category=category, is_active=True).count()

    # Get active rules count
    active_rules = RotationRule.query.filter_by(is_active=True).count()

    # Get upcoming schedules
    upcoming = Schedule.query.filter(
        Schedule.is_active == True,
        Schedule.scheduled_time >= datetime.now()
    ).order_by(Schedule.scheduled_time).limit(5).all()

    return render_template('dashboard.html',
                           current_track=current_track,
                           queue_status=queue_status,
                           recent_plays=recent_plays,
                           file_counts=file_counts,
                           active_rules=active_rules,
                           upcoming=upcoming)


@main_bp.route('/files')
@main_bp.route('/files/<category>')
@login_required
def files(category=None):
    categories = current_app.config['CATEGORIES']
    if category and category not in categories:
        category = categories[0]

    if not category:
        category = categories[0]

    # Scan for new files
    scan_media_files(category)

    files = AudioFile.query.filter_by(category=category).order_by(AudioFile.filename).all()
    return render_template('files.html',
                           files=files,
                           current_category=category,
                           categories=categories)


@main_bp.route('/files/toggle/<int:file_id>', methods=['POST'])
@login_required
def toggle_file(file_id):
    audio_file = AudioFile.query.get_or_404(file_id)
    audio_file.is_active = not audio_file.is_active
    db.session.commit()

    # Immediately regenerate the playlist for this category
    from app.utils import generate_playlist_file
    try:
        generate_playlist_file(audio_file.category)
        print(f'Regenerated playlist for {audio_file.category} after toggling {audio_file.filename}', flush=True)
    except Exception as e:
        print(f'Error regenerating playlist: {e}', flush=True)

    return jsonify({'success': True, 'is_active': audio_file.is_active})


@main_bp.route('/files/upload/<category>', methods=['POST'])
@login_required
def upload_file(category):
    if category not in current_app.config['CATEGORIES']:
        return jsonify({'error': 'Invalid category'}), 400

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not is_supported_audio_file(file.filename):
        return jsonify({'error': f'Unterstützte Formate: {", ".join(SUPPORTED_FORMATS)}'}), 400

    filename = secure_filename(file.filename)
    category_path = os.path.join(current_app.config['MEDIA_PATH'], category)
    filepath = os.path.join(category_path, filename)

    file.save(filepath)

    # Get metadata and create database entry
    metadata = get_audio_metadata(filepath)
    audio_file = AudioFile(
        filename=filename,
        category=category,
        path=filepath,
        duration=metadata.get('duration', 0),
        title=metadata.get('title', filename),
        artist=metadata.get('artist', 'Unknown')
    )
    db.session.add(audio_file)
    db.session.commit()

    # Immediately regenerate the playlist to include new file
    from app.utils import generate_playlist_file
    try:
        generate_playlist_file(category)
        print(f'Regenerated playlist for {category} after uploading {filename}', flush=True)
    except Exception as e:
        print(f'Error regenerating playlist: {e}', flush=True)

    return jsonify({'success': True, 'file': audio_file.to_dict()})


@main_bp.route('/files/delete/<int:file_id>', methods=['POST'])
@login_required
def delete_file(file_id):
    from app.models import ShowItem, InstantJingle, ModerationSettings, PlayHistory, NowPlaying

    try:
        audio_file = AudioFile.query.get_or_404(file_id)

        # Save file path and category before deleting from DB (needed after commit)
        file_path = audio_file.path
        category = audio_file.category

        # Remove references from related tables before deleting
        # Delete ShowItems that reference this file
        ShowItem.query.filter_by(audio_file_id=file_id).delete(synchronize_session=False)

        # Clear InstantJingles that reference this file
        InstantJingle.query.filter_by(audio_file_id=file_id).update({'audio_file_id': None}, synchronize_session=False)

        # Clear ModerationSettings bed reference if it points to this file
        ModerationSettings.query.filter_by(bed_audio_file_id=file_id).update({'bed_audio_file_id': None}, synchronize_session=False)

        # Clear PlayHistory references (set to NULL)
        PlayHistory.query.filter_by(audio_file_id=file_id).update({'audio_file_id': None}, synchronize_session=False)

        # Clear NowPlaying reference if it points to this file
        NowPlaying.query.filter_by(audio_file_id=file_id).update({'audio_file_id': None}, synchronize_session=False)

        # Delete from database
        db.session.delete(audio_file)
        db.session.commit()

        # Delete physical file after successful DB deletion
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                # Log but don't fail if file removal fails
                print(f"Warning: Could not delete physical file {file_path}: {e}")

        # Immediately regenerate the playlist to exclude deleted file
        from app.utils import generate_playlist_file
        try:
            generate_playlist_file(category)
            print(f'Regenerated playlist for {category} after deleting file', flush=True)
        except Exception as e:
            print(f'Error regenerating playlist: {e}', flush=True)

        return jsonify({'success': True})

    except Exception as e:
        db.session.rollback()
        import traceback
        error_msg = f"Error deleting file {file_id}: {str(e)}\n{traceback.format_exc()}"
        print(error_msg, flush=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@main_bp.route('/files/stream/<int:file_id>')
@login_required
def stream_file(file_id):
    """Stream an audio file for preview playback"""
    audio_file = AudioFile.query.get_or_404(file_id)

    # Check if file exists
    if not os.path.exists(audio_file.path):
        return jsonify({'error': 'File not found'}), 404

    return send_file(
        audio_file.path,
        mimetype='audio/mpeg',
        as_attachment=False,
        download_name=audio_file.filename
    )


@main_bp.route('/rotation')
@login_required
def rotation():
    rules = RotationRule.query.order_by(RotationRule.priority.desc()).all()
    categories = current_app.config['CATEGORIES']
    return render_template('rotation.html', rules=rules, categories=categories)


@main_bp.route('/rotation/save', methods=['POST'])
@login_required
def save_rotation_rule():
    data = request.json

    if data.get('id'):
        rule = RotationRule.query.get_or_404(data['id'])
    else:
        rule = RotationRule()

    rule.name = data['name']
    rule.rule_type = data['rule_type']
    rule.category = data['category']
    rule.interval_value = data.get('interval_value', 0)
    rule.priority = data.get('priority', 0)
    rule.is_active = data.get('is_active', True)
    rule.days_of_week = data.get('days_of_week', '0,1,2,3,4,5,6')

    if data.get('time_start'):
        parts = data['time_start'].split(':')
        rule.time_start = time(int(parts[0]), int(parts[1]))
    if data.get('time_end'):
        parts = data['time_end'].split(':')
        rule.time_end = time(int(parts[0]), int(parts[1]))
    if data.get('minute_of_hour') is not None:
        rule.minute_of_hour = int(data['minute_of_hour'])

    if not rule.id:
        db.session.add(rule)

    db.session.commit()
    return jsonify({'success': True, 'rule': rule.to_dict()})


@main_bp.route('/rotation/delete/<int:rule_id>', methods=['POST'])
@login_required
def delete_rotation_rule(rule_id):
    rule = RotationRule.query.get_or_404(rule_id)
    db.session.delete(rule)
    db.session.commit()
    return jsonify({'success': True})


@main_bp.route('/rotation/toggle/<int:rule_id>', methods=['POST'])
@login_required
def toggle_rotation_rule(rule_id):
    rule = RotationRule.query.get_or_404(rule_id)
    rule.is_active = not rule.is_active
    db.session.commit()
    return jsonify({'success': True, 'is_active': rule.is_active})


@main_bp.route('/shows')
@login_required
def shows():
    shows = Show.query.order_by(Show.updated_at.desc()).all()
    return render_template('shows.html', shows=shows)


@main_bp.route('/shows/new')
@main_bp.route('/shows/edit/<int:show_id>')
@login_required
def edit_show(show_id=None):
    show = None
    if show_id:
        show = Show.query.get_or_404(show_id)

    categories = current_app.config['CATEGORIES']
    return render_template('show_editor.html', show=show, categories=categories)


@main_bp.route('/shows/save', methods=['POST'])
@login_required
def save_show():
    data = request.json

    if data.get('id'):
        show = Show.query.get_or_404(data['id'])
        # Clear existing items
        ShowItem.query.filter_by(show_id=show.id).delete()
    else:
        show = Show()

    show.name = data['name']
    show.description = data.get('description', '')

    if not show.id:
        db.session.add(show)
        db.session.flush()

    # Add items
    for i, item_data in enumerate(data.get('items', [])):
        item = ShowItem(
            show_id=show.id,
            audio_file_id=item_data['audio_file_id'],
            position=i
        )
        db.session.add(item)

    show.recalculate_duration()
    db.session.commit()

    return jsonify({'success': True, 'show': show.to_dict()})


@main_bp.route('/shows/delete/<int:show_id>', methods=['POST'])
@login_required
def delete_show(show_id):
    show = Show.query.get_or_404(show_id)

    # Delete related items and schedules
    ShowItem.query.filter_by(show_id=show_id).delete()
    Schedule.query.filter_by(show_id=show_id).delete()

    db.session.delete(show)
    db.session.commit()

    return jsonify({'success': True})


@main_bp.route('/schedule')
@login_required
def schedule():
    schedules = Schedule.query.order_by(Schedule.scheduled_time).all()
    shows = Show.query.all()
    return render_template('schedule.html', schedules=schedules, shows=shows)


@main_bp.route('/schedule/save', methods=['POST'])
@login_required
def save_schedule():
    data = request.json

    if data.get('id'):
        schedule = Schedule.query.get_or_404(data['id'])
    else:
        schedule = Schedule()

    schedule.show_id = data['show_id']
    schedule.scheduled_time = datetime.fromisoformat(data['scheduled_time'])
    schedule.repeat_type = data.get('repeat_type', 'once')
    schedule.days_of_week = data.get('days_of_week')
    schedule.is_active = data.get('is_active', True)

    if not schedule.id:
        db.session.add(schedule)

    db.session.commit()
    return jsonify({'success': True, 'schedule': schedule.to_dict()})


@main_bp.route('/schedule/delete/<int:schedule_id>', methods=['POST'])
@login_required
def delete_schedule(schedule_id):
    schedule = Schedule.query.get_or_404(schedule_id)
    db.session.delete(schedule)
    db.session.commit()
    return jsonify({'success': True})


@main_bp.route('/schedule/toggle/<int:schedule_id>', methods=['POST'])
@login_required
def toggle_schedule(schedule_id):
    schedule = Schedule.query.get_or_404(schedule_id)
    schedule.is_active = not schedule.is_active
    db.session.commit()
    return jsonify({'success': True, 'is_active': schedule.is_active})


@main_bp.route('/settings')
@login_required
def settings():
    stream_settings = StreamSettings.get_settings()
    shows = Show.query.all()
    return render_template('settings.html', stream_settings=stream_settings, shows=shows)


@main_bp.route('/settings/stream', methods=['POST'])
@login_required
def save_stream_settings():
    data = request.json
    settings = StreamSettings.get_settings()

    # Output format settings
    if 'output_format' in data:
        settings.output_format = data['output_format']
    if 'output_bitrate' in data:
        settings.output_bitrate = int(data['output_bitrate'])
    if 'output_samplerate' in data:
        settings.output_samplerate = int(data['output_samplerate'])
    if 'output_channels' in data:
        settings.output_channels = int(data['output_channels'])

    # Normalization settings
    if 'normalize_enabled' in data:
        settings.normalize_enabled = bool(data['normalize_enabled'])
    if 'target_lufs' in data:
        settings.target_lufs = float(data['target_lufs'])

    # Station info
    if 'station_name' in data:
        settings.station_name = data['station_name']
    if 'default_show_name' in data:
        settings.default_show_name = data['default_show_name']

    # Current show
    if 'current_show_id' in data:
        settings.current_show_id = int(data['current_show_id']) if data['current_show_id'] else None

    # Timezone
    if 'timezone' in data:
        settings.timezone = data['timezone']

    # Crossfade settings
    if 'crossfade_music_fade_in' in data:
        settings.crossfade_music_fade_in = float(data['crossfade_music_fade_in'])
    if 'crossfade_music_fade_out' in data:
        settings.crossfade_music_fade_out = float(data['crossfade_music_fade_out'])
    if 'crossfade_jingle_fade_in' in data:
        settings.crossfade_jingle_fade_in = float(data['crossfade_jingle_fade_in'])
    if 'crossfade_jingle_fade_out' in data:
        settings.crossfade_jingle_fade_out = float(data['crossfade_jingle_fade_out'])
    if 'crossfade_moderation_fade_in' in data:
        settings.crossfade_moderation_fade_in = float(data['crossfade_moderation_fade_in'])
    if 'crossfade_moderation_fade_out' in data:
        settings.crossfade_moderation_fade_out = float(data['crossfade_moderation_fade_out'])

    db.session.commit()

    # Trigger Liquidsoap config update
    try:
        from app.audio_engine import update_output_settings, update_crossfade_settings
        import json
        import subprocess

        update_output_settings(settings)

        # Write crossfade settings to JSON file that Liquidsoap reads on startup
        settings_file = '/data/stream_settings.json'
        crossfade_data = {
            'crossfade_music_fade_in': settings.crossfade_music_fade_in,
            'crossfade_music_fade_out': settings.crossfade_music_fade_out,
            'crossfade_jingle_fade_in': settings.crossfade_jingle_fade_in,
            'crossfade_jingle_fade_out': settings.crossfade_jingle_fade_out,
            'crossfade_moderation_fade_in': settings.crossfade_moderation_fade_in,
            'crossfade_moderation_fade_out': settings.crossfade_moderation_fade_out
        }

        try:
            with open(settings_file, 'w') as f:
                json.dump(crossfade_data, f, indent=2)
            print(f"Wrote crossfade settings to {settings_file}: {crossfade_data}", flush=True)
        except Exception as e:
            print(f"Warning: Could not write crossfade settings to file: {e}", flush=True)

        # Apply crossfade settings to Liquidsoap (for immediate effect via telnet)
        update_crossfade_settings(settings)

        # Restart Liquidsoap to load new crossfade values from JSON
        # Note: This requires supervisor to restart the liquidsoap process
        try:
            subprocess.run(['supervisorctl', 'restart', 'liquidsoap'], timeout=10)
            print("Restarted Liquidsoap to apply new crossfade settings", flush=True)
        except Exception as e:
            print(f"Warning: Could not restart Liquidsoap: {e}", flush=True)

    except Exception as e:
        print(f"Warning: Could not update Liquidsoap settings: {e}", flush=True)

    return jsonify({'success': True, 'settings': settings.to_dict()})


@main_bp.route('/settings/password', methods=['POST'])
@login_required
def change_password():
    data = request.json
    current_password = data.get('current_password')
    new_password = data.get('new_password')

    if not current_user.check_password(current_password):
        return jsonify({'error': 'Aktuelles Passwort ist falsch'}), 400

    if len(new_password) < 4:
        return jsonify({'error': 'Neues Passwort muss mindestens 4 Zeichen haben'}), 400

    current_user.set_password(new_password)
    db.session.commit()

    return jsonify({'success': True})


@main_bp.route('/history')
@login_required
def history():
    page = request.args.get('page', 1, type=int)
    per_page = 50
    history = PlayHistory.query.order_by(PlayHistory.played_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return render_template('history.html', history=history)


@main_bp.route('/moderation')
@login_required
def moderation():
    """Moderation panel for live broadcasting"""
    # Ensure jingle slots exist
    InstantJingle.ensure_slots_exist()

    # Get all jingle slots
    jingles = InstantJingle.query.order_by(InstantJingle.slot_number).all()

    # Get moderation settings
    settings = ModerationSettings.get_settings()

    # Get available music beds
    beds = AudioFile.query.filter_by(category='musicbeds', is_active=True).order_by(AudioFile.filename).all()

    # Get all audio files for jingle configuration
    all_files = AudioFile.query.filter_by(is_active=True).order_by(AudioFile.category, AudioFile.filename).all()

    return render_template('moderation.html',
                           jingles=jingles,
                           settings=settings,
                           beds=beds,
                           all_files=all_files)


@main_bp.route('/statistics')
@login_required
def statistics():
    """Statistics page showing listener counts and trends"""
    return render_template('statistics.html')


@main_bp.route('/tts-generator')
@login_required
def tts_generator():
    """KI Moderation page for creating AI voice moderations"""
    # Get current settings
    settings = StreamSettings.get_settings()

    # Get internal files for intro/outro/musicbed selection
    import os
    media_path = os.environ.get('MEDIA_PATH', '/media')
    internal_path = os.path.join(media_path, 'internal')

    internal_files = []
    if os.path.exists(internal_path):
        for filename in os.listdir(internal_path):
            if filename.lower().endswith(('.mp3', '.wav', '.ogg', '.flac')):
                internal_files.append(filename)
    internal_files.sort()

    return render_template('tts_generator.html',
                           settings=settings,
                           internal_files=internal_files)
