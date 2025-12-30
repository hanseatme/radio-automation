#!/bin/bash
set -e

# Initialize database if not exists
if [ ! -f /data/streamserver.db ]; then
    echo "Initializing database..."
    cd /app && python -c "from app import create_app, db; app = create_app(); app.app_context().push(); db.create_all()"
fi

# Create default admin user if not exists and run migrations
cd /app && python -c "
from app import create_app, db
from app.models import User
import sqlite3
import os

app = create_app()
with app.app_context():
    db.create_all()

    # Run migrations for crossfade columns
    try:
        conn = sqlite3.connect('/data/streamserver.db')
        c = conn.cursor()
        columns_to_add = [
            ('crossfade_music_fade_in', 'REAL', '0.5'),
            ('crossfade_music_fade_out', 'REAL', '0.5'),
            ('crossfade_jingle_fade_in', 'REAL', '0.0'),
            ('crossfade_jingle_fade_out', 'REAL', '0.0'),
            ('crossfade_moderation_fade_in', 'REAL', '0.0'),
            ('crossfade_moderation_fade_out', 'REAL', '0.0'),
        ]
        for col, typ, default in columns_to_add:
            try:
                c.execute(f'ALTER TABLE stream_settings ADD COLUMN {col} {typ} DEFAULT {default}')
            except:
                pass
        conn.commit()
        conn.close()
    except Exception as e:
        print(f'Migration note: {e}')

    if not User.query.filter_by(username='${ADMIN_USERNAME:-admin}').first():
        user = User(username='${ADMIN_USERNAME:-admin}', is_admin=True)
        user.set_password('${ADMIN_PASSWORD:-admin}')
        db.session.add(user)
        db.session.commit()
        print('Default admin user created')
    else:
        print('Admin user already exists')
"

# Start supervisor (manages all services)
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
