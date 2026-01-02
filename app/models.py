from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class AudioFile(db.Model):
    __tablename__ = 'audio_files'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    path = db.Column(db.String(512), nullable=False)
    duration = db.Column(db.Float, default=0)
    title = db.Column(db.String(255))
    artist = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True)
    play_count = db.Column(db.Integer, default=0)
    last_played = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    show_items = db.relationship('ShowItem', backref='audio_file', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'category': self.category,
            'path': self.path,
            'duration': self.duration,
            'duration_formatted': self.format_duration(),
            'title': self.title or self.filename,
            'artist': self.artist or 'Unknown',
            'is_active': self.is_active,
            'play_count': self.play_count,
            'last_played': self.last_played.isoformat() if self.last_played else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def format_duration(self):
        if not self.duration:
            return '0:00'
        minutes = int(self.duration // 60)
        seconds = int(self.duration % 60)
        return f'{minutes}:{seconds:02d}'


class RotationRule(db.Model):
    __tablename__ = 'rotation_rules'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    rule_type = db.Column(db.String(50), nullable=False)  # 'after_songs', 'at_minute', 'interval', 'time_range'
    category = db.Column(db.String(50), nullable=False)  # Which category to play
    interval_value = db.Column(db.Integer, default=0)  # Number of songs or minutes
    time_start = db.Column(db.Time)  # Start time for time-based rules
    time_end = db.Column(db.Time)  # End time for time-based rules
    minute_of_hour = db.Column(db.Integer)  # For 'at_minute' rule type
    days_of_week = db.Column(db.String(50), default='0,1,2,3,4,5,6')  # Comma-separated days
    priority = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'rule_type': self.rule_type,
            'category': self.category,
            'interval_value': self.interval_value,
            'time_start': self.time_start.strftime('%H:%M') if self.time_start else None,
            'time_end': self.time_end.strftime('%H:%M') if self.time_end else None,
            'minute_of_hour': self.minute_of_hour,
            'days_of_week': self.days_of_week,
            'priority': self.priority,
            'is_active': self.is_active
        }


class Show(db.Model):
    __tablename__ = 'shows'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    total_duration = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    items = db.relationship('ShowItem', backref='show', lazy='dynamic', order_by='ShowItem.position')
    schedules = db.relationship('Schedule', backref='show', lazy='dynamic')

    def to_dict(self, include_items=False):
        data = {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'total_duration': self.total_duration,
            'total_duration_formatted': self.format_duration(),
            'item_count': self.items.count(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
        if include_items:
            data['items'] = [item.to_dict() for item in self.items.all()]
        return data

    def format_duration(self):
        if not self.total_duration:
            return '0:00'
        hours = int(self.total_duration // 3600)
        minutes = int((self.total_duration % 3600) // 60)
        seconds = int(self.total_duration % 60)
        if hours > 0:
            return f'{hours}:{minutes:02d}:{seconds:02d}'
        return f'{minutes}:{seconds:02d}'

    def recalculate_duration(self):
        total = 0
        for item in self.items.all():
            if item.audio_file and item.audio_file.duration:
                total += item.audio_file.duration
        self.total_duration = total


class ShowItem(db.Model):
    __tablename__ = 'show_items'

    id = db.Column(db.Integer, primary_key=True)
    show_id = db.Column(db.Integer, db.ForeignKey('shows.id'), nullable=False)
    audio_file_id = db.Column(db.Integer, db.ForeignKey('audio_files.id'), nullable=False)
    position = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # audio_file relationship is defined via backref from AudioFile.show_items

    def to_dict(self):
        return {
            'id': self.id,
            'show_id': self.show_id,
            'audio_file_id': self.audio_file_id,
            'position': self.position,
            'audio_file': self.audio_file.to_dict() if self.audio_file else None
        }


class Schedule(db.Model):
    __tablename__ = 'schedules'

    id = db.Column(db.Integer, primary_key=True)
    show_id = db.Column(db.Integer, db.ForeignKey('shows.id'), nullable=False)
    scheduled_time = db.Column(db.DateTime, nullable=False)
    repeat_type = db.Column(db.String(20), default='once')  # 'once', 'daily', 'weekly'
    days_of_week = db.Column(db.String(50))  # For weekly repeats
    is_active = db.Column(db.Boolean, default=True)
    last_run = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'show_id': self.show_id,
            'show_name': self.show.name if self.show else None,
            'scheduled_time': self.scheduled_time.isoformat() if self.scheduled_time else None,
            'repeat_type': self.repeat_type,
            'days_of_week': self.days_of_week,
            'is_active': self.is_active,
            'last_run': self.last_run.isoformat() if self.last_run else None
        }


class PlayHistory(db.Model):
    __tablename__ = 'play_history'

    id = db.Column(db.Integer, primary_key=True)
    audio_file_id = db.Column(db.Integer, db.ForeignKey('audio_files.id'))
    filename = db.Column(db.String(255))
    title = db.Column(db.String(255))
    artist = db.Column(db.String(255))
    category = db.Column(db.String(50))
    played_at = db.Column(db.DateTime, default=datetime.utcnow)
    triggered_by = db.Column(db.String(50))  # 'rotation', 'schedule', 'manual'

    audio_file = db.relationship('AudioFile', backref='play_history')

    def to_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'title': self.title,
            'artist': self.artist,
            'category': self.category,
            'played_at': self.played_at.isoformat() if self.played_at else None,
            'triggered_by': self.triggered_by
        }


class SystemState(db.Model):
    __tablename__ = 'system_state'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def get(key, default=None):
        state = SystemState.query.filter_by(key=key).first()
        return state.value if state else default

    @staticmethod
    def set(key, value):
        from app import db
        state = SystemState.query.filter_by(key=key).first()
        if state:
            state.value = str(value)
        else:
            state = SystemState(key=key, value=str(value))
            db.session.add(state)
        db.session.commit()


class StreamSettings(db.Model):
    """Stream output settings - singleton table"""
    __tablename__ = 'stream_settings'

    id = db.Column(db.Integer, primary_key=True)
    # Output format
    output_format = db.Column(db.String(10), default='mp3')  # mp3, aac, ogg
    output_bitrate = db.Column(db.Integer, default=192)  # kbps
    output_samplerate = db.Column(db.Integer, default=44100)  # Hz
    output_channels = db.Column(db.Integer, default=2)  # 1=mono, 2=stereo

    # Loudness normalization
    normalize_enabled = db.Column(db.Boolean, default=True)
    target_lufs = db.Column(db.Float, default=-16.0)  # Target loudness in LUFS

    # Crossfade settings (in seconds)
    crossfade_music_fade_in = db.Column(db.Float, default=0.5)
    crossfade_music_fade_out = db.Column(db.Float, default=0.5)
    crossfade_jingle_fade_in = db.Column(db.Float, default=0.0)
    crossfade_jingle_fade_out = db.Column(db.Float, default=0.0)
    crossfade_moderation_fade_in = db.Column(db.Float, default=0.0)
    crossfade_moderation_fade_out = db.Column(db.Float, default=0.0)

    # Station info for API
    station_name = db.Column(db.String(100), default='Radio Automation')
    default_show_name = db.Column(db.String(100), default='Automatik')  # When no show is running

    # Now Playing custom texts for categories
    jingle_nowplaying_text = db.Column(db.String(100), default='Jingle')
    promo_nowplaying_text = db.Column(db.String(100), default='Promo')
    ad_nowplaying_text = db.Column(db.String(100), default='Werbung')
    moderation_nowplaying_text = db.Column(db.String(100), default='Moderation')

    # Minimax TTS Konfiguration
    minimax_api_key = db.Column(db.Text, default='')  # JWT tokens can be 800+ chars
    minimax_group_id = db.Column(db.String(50), default='')  # GroupId for API calls
    minimax_model = db.Column(db.String(100), default='speech-2.6-turbo')
    minimax_voice_id = db.Column(db.String(100), default='German_PlayfulMan')
    minimax_emotion = db.Column(db.String(50), default='happy')  # Emotion for TTS
    minimax_language_boost = db.Column(db.String(50), default='German')  # Language optimization

    # TTS Audio Processing Einstellungen
    tts_intro_file = db.Column(db.String(500), default='')
    tts_outro_file = db.Column(db.String(500), default='')
    tts_musicbed_file = db.Column(db.String(500), default='')
    tts_crossfade_ms = db.Column(db.Integer, default=500)
    tts_musicbed_volume = db.Column(db.Float, default=0.25)
    tts_target_dbfs = db.Column(db.Float, default=-3.0)
    tts_highpass_hz = db.Column(db.Integer, default=80)

    # System timezone
    timezone = db.Column(db.String(50), default='Europe/Berlin')

    # MCP API Key for external AI access
    mcp_api_key = db.Column(db.String(64), default='')

    # Icecast server password (for source, relay, and admin)
    icecast_password = db.Column(db.String(100), default='hackme')

    # Current show tracking
    current_show_id = db.Column(db.Integer, db.ForeignKey('shows.id'), nullable=True)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    current_show = db.relationship('Show', foreign_keys=[current_show_id])

    @staticmethod
    def get_settings():
        settings = StreamSettings.query.first()
        if not settings:
            settings = StreamSettings()
            db.session.add(settings)
            db.session.commit()
        return settings

    def generate_mcp_api_key(self):
        """Generate a new MCP API key and save it"""
        import secrets
        self.mcp_api_key = secrets.token_urlsafe(32)
        return self.mcp_api_key

    def validate_mcp_api_key(self, key):
        """Validate an MCP API key using constant-time comparison"""
        import secrets
        if not self.mcp_api_key or not key:
            return False
        return secrets.compare_digest(self.mcp_api_key, key)

    @property
    def mcp_api_key_set(self):
        """Check if MCP API key is configured (for template access)"""
        return bool(self.mcp_api_key)

    def to_dict(self):
        return {
            'output_format': self.output_format,
            'output_bitrate': self.output_bitrate,
            'output_samplerate': self.output_samplerate,
            'output_channels': self.output_channels,
            'normalize_enabled': self.normalize_enabled,
            'target_lufs': self.target_lufs,
            'crossfade_music_fade_in': self.crossfade_music_fade_in,
            'crossfade_music_fade_out': self.crossfade_music_fade_out,
            'crossfade_jingle_fade_in': self.crossfade_jingle_fade_in,
            'crossfade_jingle_fade_out': self.crossfade_jingle_fade_out,
            'crossfade_moderation_fade_in': self.crossfade_moderation_fade_in,
            'crossfade_moderation_fade_out': self.crossfade_moderation_fade_out,
            'station_name': self.station_name,
            'default_show_name': self.default_show_name,
            'jingle_nowplaying_text': self.jingle_nowplaying_text,
            'promo_nowplaying_text': self.promo_nowplaying_text,
            'ad_nowplaying_text': self.ad_nowplaying_text,
            'moderation_nowplaying_text': self.moderation_nowplaying_text,
            'current_show_id': self.current_show_id,
            'current_show_name': self.current_show.name if self.current_show else None,
            # TTS Settings
            'minimax_api_key': '***' if self.minimax_api_key else '',  # Mask API key
            'minimax_api_key_set': bool(self.minimax_api_key),
            'minimax_model': self.minimax_model,
            'minimax_voice_id': self.minimax_voice_id,
            'minimax_emotion': self.minimax_emotion,
            'minimax_language_boost': self.minimax_language_boost,
            'tts_intro_file': self.tts_intro_file,
            'tts_outro_file': self.tts_outro_file,
            'tts_musicbed_file': self.tts_musicbed_file,
            'tts_crossfade_ms': self.tts_crossfade_ms,
            'tts_musicbed_volume': self.tts_musicbed_volume,
            'tts_target_dbfs': self.tts_target_dbfs,
            'tts_highpass_hz': self.tts_highpass_hz,
            'timezone': self.timezone or 'Europe/Berlin',
            # MCP Settings
            'mcp_api_key_set': bool(self.mcp_api_key),
            # Icecast Settings
            'icecast_password_set': bool(self.icecast_password)
        }


class NowPlaying(db.Model):
    """Current track info - singleton table for real-time updates"""
    __tablename__ = 'now_playing'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), default='')
    artist = db.Column(db.String(255), default='')
    filename = db.Column(db.String(255), default='')
    category = db.Column(db.String(50), default='')
    duration = db.Column(db.Float, default=0)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    audio_file_id = db.Column(db.Integer, db.ForeignKey('audio_files.id'), nullable=True)

    audio_file = db.relationship('AudioFile', foreign_keys=[audio_file_id])

    @staticmethod
    def get_current():
        np = NowPlaying.query.first()
        if not np:
            np = NowPlaying()
            db.session.add(np)
            db.session.commit()
        return np

    @staticmethod
    def update(title='', artist='', filename='', category='', duration=0, audio_file_id=None):
        np = NowPlaying.get_current()
        np.title = title
        np.artist = artist
        np.filename = filename
        np.category = category
        np.duration = duration
        np.audio_file_id = audio_file_id
        np.started_at = datetime.utcnow()
        db.session.commit()
        return np

    def to_dict(self):
        settings = StreamSettings.get_settings()
        elapsed = 0
        remaining = 0
        if self.started_at and self.duration:
            elapsed = (datetime.utcnow() - self.started_at).total_seconds()
            remaining = max(0, self.duration - elapsed)

        return {
            'title': self.title or 'Unbekannt',
            'artist': self.artist or '',
            'filename': self.filename,
            'category': self.category,
            'duration': self.duration,
            'elapsed': round(elapsed, 1),
            'remaining': round(remaining, 1),
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'show': settings.current_show.name if settings.current_show else settings.default_show_name,
            'station': settings.station_name
        }


class InstantJingle(db.Model):
    """9 configurable instant jingle slots"""
    __tablename__ = 'instant_jingles'

    id = db.Column(db.Integer, primary_key=True)
    slot_number = db.Column(db.Integer, nullable=False, unique=True)  # 1-9
    audio_file_id = db.Column(db.Integer, db.ForeignKey('audio_files.id'), nullable=True)
    label = db.Column(db.String(50))
    color = db.Column(db.String(20), default='primary')  # Bootstrap color class
    hotkey = db.Column(db.String(10))  # Keyboard shortcut (1-9)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    audio_file = db.relationship('AudioFile', backref='instant_jingle_slots')

    def to_dict(self):
        return {
            'id': self.id,
            'slot_number': self.slot_number,
            'audio_file_id': self.audio_file_id,
            'audio_file': self.audio_file.to_dict() if self.audio_file else None,
            'label': self.label,
            'color': self.color,
            'hotkey': self.hotkey
        }

    @staticmethod
    def ensure_slots_exist():
        """Ensure all 9 slots exist in database"""
        existing_slots = {j.slot_number for j in InstantJingle.query.all()}
        for slot in range(1, 10):
            if slot not in existing_slots:
                jingle = InstantJingle(slot_number=slot, hotkey=str(slot), label=f'Jingle {slot}')
                db.session.add(jingle)
        db.session.commit()


class ModerationSettings(db.Model):
    """Moderation panel settings - singleton table"""
    __tablename__ = 'moderation_settings'

    id = db.Column(db.Integer, primary_key=True)

    # Microphone settings
    mic_enabled = db.Column(db.Boolean, default=False)
    mic_auto_start_bed = db.Column(db.Boolean, default=True)

    # Music bed settings
    bed_enabled = db.Column(db.Boolean, default=False)
    bed_volume = db.Column(db.Float, default=0.3)  # Normal volume (0.0-1.0)
    bed_ducking_level = db.Column(db.Float, default=0.15)  # Ducked volume when mic active
    bed_loop = db.Column(db.Boolean, default=True)
    bed_audio_file_id = db.Column(db.Integer, db.ForeignKey('audio_files.id'), nullable=True)

    # Ducking settings
    ducking_enabled = db.Column(db.Boolean, default=True)
    ducking_attack_ms = db.Column(db.Integer, default=100)
    ducking_release_ms = db.Column(db.Integer, default=500)

    # Instant jingle settings
    jingle_volume = db.Column(db.Float, default=1.0)
    jingle_duck_music = db.Column(db.Boolean, default=True)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    bed_audio_file = db.relationship('AudioFile', foreign_keys=[bed_audio_file_id])

    @staticmethod
    def get_settings():
        settings = ModerationSettings.query.first()
        if not settings:
            settings = ModerationSettings()
            db.session.add(settings)
            db.session.commit()
        return settings

    def to_dict(self):
        return {
            'mic_enabled': self.mic_enabled,
            'mic_auto_start_bed': self.mic_auto_start_bed,
            'bed_enabled': self.bed_enabled,
            'bed_volume': self.bed_volume,
            'bed_ducking_level': self.bed_ducking_level,
            'bed_loop': self.bed_loop,
            'bed_audio_file_id': self.bed_audio_file_id,
            'bed_audio_file': self.bed_audio_file.to_dict() if self.bed_audio_file else None,
            'ducking_enabled': self.ducking_enabled,
            'ducking_attack_ms': self.ducking_attack_ms,
            'ducking_release_ms': self.ducking_release_ms,
            'jingle_volume': self.jingle_volume,
            'jingle_duck_music': self.jingle_duck_music
        }


class ListenerStats(db.Model):
    """Track listener count statistics in 5-minute intervals"""
    __tablename__ = 'listener_stats'

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    listener_count = db.Column(db.Integer, default=0, nullable=False)

    # Optional: track peak listeners during this interval
    peak_listeners = db.Column(db.Integer, default=0)

    # Track which mountpoint/stream this is for (if you have multiple)
    mountpoint = db.Column(db.String(100), default='/stream', nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'listener_count': self.listener_count,
            'peak_listeners': self.peak_listeners,
            'mountpoint': self.mountpoint
        }

    @staticmethod
    def get_stats(hours=24, mountpoint='/stream'):
        """Get listener statistics for the last N hours"""
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        return ListenerStats.query.filter(
            ListenerStats.timestamp >= cutoff,
            ListenerStats.mountpoint == mountpoint
        ).order_by(ListenerStats.timestamp.asc()).all()

    @staticmethod
    def get_current_listeners():
        """Get the most recent listener count"""
        stat = ListenerStats.query.order_by(ListenerStats.timestamp.desc()).first()
        return stat.listener_count if stat else 0

    @staticmethod
    def get_peak_listeners(hours=24, mountpoint='/stream'):
        """Get peak listener count in the last N hours"""
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        result = db.session.query(db.func.max(ListenerStats.listener_count)).filter(
            ListenerStats.timestamp >= cutoff,
            ListenerStats.mountpoint == mountpoint
        ).scalar()
        return result or 0

    @staticmethod
    def get_average_listeners(hours=24, mountpoint='/stream'):
        """Get average listener count in the last N hours"""
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        result = db.session.query(db.func.avg(ListenerStats.listener_count)).filter(
            ListenerStats.timestamp >= cutoff,
            ListenerStats.mountpoint == mountpoint
        ).scalar()
        return round(result, 1) if result else 0
