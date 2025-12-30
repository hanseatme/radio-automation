from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import current_app

scheduler = BackgroundScheduler()
song_counter = 0


def init_scheduler(app):
    """Initialize the scheduler with the Flask app"""
    global scheduler

    with app.app_context():
        # Add jobs
        scheduler.add_job(
            func=check_rotation_rules,
            trigger='interval',
            seconds=30,
            id='rotation_check',
            replace_existing=True,
            kwargs={'app': app}
        )

        scheduler.add_job(
            func=check_scheduled_shows,
            trigger='interval',
            seconds=60,
            id='schedule_check',
            replace_existing=True,
            kwargs={'app': app}
        )

        scheduler.add_job(
            func=scan_all_media,
            trigger='interval',
            minutes=5,
            id='media_scan',
            replace_existing=True,
            kwargs={'app': app}
        )

        # Poll Liquidsoap for current track metadata
        scheduler.add_job(
            func=poll_current_track,
            trigger='interval',
            seconds=5,
            id='track_poll',
            replace_existing=True,
            kwargs={'app': app}
        )

        # Regenerate playlists periodically to reflect active/inactive changes
        # and to update play history sorting (avoid song repetition)
        scheduler.add_job(
            func=regenerate_playlists_task,
            trigger='interval',
            minutes=5,
            id='playlist_regeneration',
            replace_existing=True,
            kwargs={'app': app}
        )

        # Generate playlists immediately on startup
        regenerate_playlists_task(app)

        scheduler.start()


def check_rotation_rules(app):
    """Check and execute rotation rules"""
    global song_counter

    with app.app_context():
        from app.models import RotationRule, SystemState
        from app.audio_engine import insert_from_category
        from app.utils import get_random_file_from_category

        now = datetime.now()
        current_minute = now.minute
        current_hour = now.hour
        current_day = now.weekday()

        # Get all active rules sorted by priority
        rules = RotationRule.query.filter_by(is_active=True).order_by(
            RotationRule.priority.desc()
        ).all()

        for rule in rules:
            # Check if rule applies to current day
            days = [int(d) for d in rule.days_of_week.split(',') if d]
            if current_day not in days:
                continue

            # Check time range if specified
            if rule.time_start and rule.time_end:
                current_time = now.time()
                if not (rule.time_start <= current_time <= rule.time_end):
                    continue

            should_trigger = False

            if rule.rule_type == 'at_minute':
                # Trigger at specific minute of each hour
                if rule.minute_of_hour is not None:
                    last_trigger_key = f'rule_{rule.id}_last_trigger'
                    last_trigger = SystemState.get(last_trigger_key)

                    if current_minute == rule.minute_of_hour:
                        if not last_trigger or last_trigger != now.strftime('%Y-%m-%d %H'):
                            should_trigger = True
                            SystemState.set(last_trigger_key, now.strftime('%Y-%m-%d %H'))

            elif rule.rule_type == 'interval':
                # Trigger every X minutes
                if rule.interval_value > 0:
                    last_trigger_key = f'rule_{rule.id}_last_trigger'
                    last_trigger_str = SystemState.get(last_trigger_key)

                    if last_trigger_str:
                        try:
                            last_trigger = datetime.fromisoformat(last_trigger_str)
                            if (now - last_trigger).total_seconds() >= rule.interval_value * 60:
                                should_trigger = True
                        except ValueError:
                            should_trigger = True
                    else:
                        should_trigger = True

                    if should_trigger:
                        SystemState.set(last_trigger_key, now.isoformat())

            elif rule.rule_type == 'after_songs':
                # This is now handled directly in increment_song_counter()
                # which is called immediately when a song changes
                # Skip processing here to avoid double triggering
                continue

            if should_trigger:
                # Insert content from the rule's category
                insert_from_category(rule.category)


def increment_song_counter():
    """Increment song counters for 'after_songs' rules and trigger if threshold reached"""
    from flask import current_app
    from app.models import RotationRule, SystemState
    from app.audio_engine import insert_from_category
    from datetime import datetime

    now = datetime.now()
    current_day = now.weekday()

    rules = RotationRule.query.filter_by(
        rule_type='after_songs',
        is_active=True
    ).all()

    for rule in rules:
        # Check if rule applies to current day
        days = [int(d) for d in rule.days_of_week.split(',') if d]
        if current_day not in days:
            continue

        # Check time range if specified
        if rule.time_start and rule.time_end:
            current_time = now.time()
            if not (rule.time_start <= current_time <= rule.time_end):
                continue

        counter_key = f'rule_{rule.id}_song_counter'
        counter = int(SystemState.get(counter_key, '0')) + 1

        if counter >= rule.interval_value:
            # Threshold reached - insert content and reset counter
            print(f"[Rotation] Rule '{rule.name}' triggered: inserting {rule.category} after {counter} songs")
            insert_from_category(rule.category)
            SystemState.set(counter_key, '0')
        else:
            # Just increment counter
            SystemState.set(counter_key, str(counter))
            print(f"[Rotation] Rule '{rule.name}': {counter}/{rule.interval_value} songs")


def check_scheduled_shows(app):
    """Check and start scheduled shows"""
    with app.app_context():
        from app.models import Schedule, db
        from app.audio_engine import queue_track

        now = datetime.now()
        window_start = now - timedelta(minutes=1)
        window_end = now + timedelta(minutes=1)

        # Find schedules that should start now
        schedules = Schedule.query.filter(
            Schedule.is_active == True,
            Schedule.scheduled_time >= window_start,
            Schedule.scheduled_time <= window_end
        ).all()

        for schedule in schedules:
            # Check if already run recently
            if schedule.last_run:
                if (now - schedule.last_run).total_seconds() < 120:
                    continue

            # Check day of week for weekly repeats
            if schedule.repeat_type == 'weekly':
                if schedule.days_of_week:
                    days = [int(d) for d in schedule.days_of_week.split(',') if d]
                    if now.weekday() not in days:
                        continue

            # Queue all show items
            if schedule.show:
                for item in schedule.show.items.order_by('position').all():
                    if item.audio_file:
                        queue_track(item.audio_file.path)

            schedule.last_run = now

            # Handle repeat scheduling
            if schedule.repeat_type == 'daily':
                schedule.scheduled_time = schedule.scheduled_time + timedelta(days=1)
            elif schedule.repeat_type == 'weekly':
                schedule.scheduled_time = schedule.scheduled_time + timedelta(weeks=1)
            elif schedule.repeat_type == 'once':
                schedule.is_active = False

            db.session.commit()


def scan_all_media(app):
    """Periodically scan all media directories"""
    with app.app_context():
        from app.utils import scan_media_files
        for category in app.config['CATEGORIES']:
            scan_media_files(category)


def regenerate_playlists_task(app):
    """Regenerate all playlist files with active tracks only"""
    with app.app_context():
        from app.utils import regenerate_all_playlists
        try:
            regenerate_all_playlists()
        except Exception as e:
            print(f'Error regenerating playlists: {e}', flush=True)


def poll_current_track(app):
    """Poll Liquidsoap for current track and update NowPlaying/PlayHistory"""
    with app.app_context():
        from app.models import AudioFile, NowPlaying, PlayHistory, SystemState, StreamSettings, db
        from app.audio_engine import send_liquidsoap_command
        from app import socketio

        # Get currently playing metadata from Radio_Automation source
        response = send_liquidsoap_command('Radio_Automation.metadata')
        if not response or 'ERROR' in response:
            return

        # Parse metadata from response - find the MOST RECENT entry
        # Response format (sections numbered in descending order, lowest = most recent):
        # --- 5 ---
        # (empty or older metadata)
        # --- 4 ---
        # filename="..."
        # ...
        # --- 1 ---
        # (most recent metadata)
        metadata = {'title': '', 'artist': '', 'filename': '', 'rid': '', 'source': '', 'on_air': ''}

        import re
        # Find all sections with their numbers
        # Pattern captures the section number and content after it
        sections = re.findall(r'---\s*(\d+)\s*---\s*(.*?)(?=---\s*\d+\s*---|END|$)', response, re.DOTALL)

        # Find the section with the lowest number that has actual filename content
        best_section = None
        best_num = float('inf')

        for num_str, content in sections:
            num = int(num_str)
            # Check if this section has a filename
            if 'filename=' in content and num < best_num:
                best_num = num
                best_section = content

        if not best_section:
            # Fallback: take any section with content
            for num_str, content in sections:
                if content.strip():
                    best_section = content
                    break

        if not best_section:
            return

        # Parse key=value pairs from the best block
        for line in best_section.split('\n'):
            line = line.strip()
            if '=' in line:
                # Handle key="value" format
                eq_pos = line.index('=')
                key = line[:eq_pos].strip()
                value = line[eq_pos+1:].strip().strip('"')
                if key == 'title':
                    metadata['title'] = value
                elif key == 'artist':
                    metadata['artist'] = value
                elif key == 'filename':
                    metadata['filename'] = value
                elif key == 'rid':
                    metadata['rid'] = value
                elif key == 'source':
                    metadata['source'] = value
                elif key == 'on_air':
                    metadata['on_air'] = value

        # Use filename + on_air as unique identifier (RID can be unreliable with crossfade)
        current_filename = metadata.get('filename', '')
        current_on_air = metadata.get('on_air', '')
        if not current_filename:
            print(f"[Track Poll] No filename in metadata, skipping")
            return

        # Create a unique track identifier
        track_id = f"{current_filename}_{current_on_air}"

        # Check if this is a new track
        last_track_id = SystemState.get('last_track_id', '')
        if track_id == last_track_id:
            return  # Same track, no update needed

        # New track detected - update state
        print(f"[Track Poll] NEW TRACK DETECTED: {current_filename}")
        SystemState.set('last_track_id', track_id)

        full_path = metadata['filename']
        filename = full_path
        if '/' in filename:
            filename = filename.split('/')[-1]

        # Determine category from path if not in database
        # Path format: /media/<category>/filename.mp3
        path_category = ''
        if full_path.startswith('/media/'):
            parts = full_path.split('/')
            if len(parts) >= 3:
                path_category = parts[2]  # e.g., 'music', 'jingles', 'promos'

        # Try to find the file in database
        audio_file = AudioFile.query.filter_by(filename=filename).first()

        title = metadata['title']
        artist = metadata['artist']
        duration = 0
        category = path_category  # Use path-based category as default
        audio_file_id = None

        if audio_file:
            title = audio_file.title or title or filename
            artist = audio_file.artist or artist
            duration = audio_file.duration or 0
            category = audio_file.category  # Override with database category if available
            audio_file_id = audio_file.id

            # Update play count
            audio_file.play_count += 1
            audio_file.last_played = datetime.now()

        if not title:
            title = filename

        # Update NowPlaying
        NowPlaying.update(
            title=title,
            artist=artist,
            filename=filename,
            category=category,
            duration=duration,
            audio_file_id=audio_file_id
        )

        # Log to play history
        history = PlayHistory(
            audio_file_id=audio_file_id,
            filename=filename,
            title=title,
            artist=artist,
            category=category,
            triggered_by='rotation'
        )
        db.session.add(history)
        db.session.commit()

        # Increment song counter for 'after_songs' rules
        # Only count music tracks, not jingles/promos/ads/moderations
        if category == 'music' or category == '':
            increment_song_counter()

        # Broadcast via WebSocket
        settings = StreamSettings.get_settings()
        show_name = settings.current_show.name if settings.current_show else settings.default_show_name

        socketio.emit('now_playing', {
            'title': title,
            'artist': artist,
            'filename': filename,
            'duration': duration,
            'show': show_name,
            'station': settings.station_name,
            'started_at': datetime.now().isoformat()
        })
