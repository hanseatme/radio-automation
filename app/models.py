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
            'current_show_name': self.current_show.name if self.current_show else None
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
