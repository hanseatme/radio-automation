"""
Database Migrations System
Automatically applies schema changes without data loss
"""
import logging
from sqlalchemy import text, inspect
from app import db

logger = logging.getLogger(__name__)

# Current schema version
SCHEMA_VERSION = 7  # Increment this when adding new migrations


def get_schema_version():
    """Get current schema version from database"""
    try:
        result = db.session.execute(text("SELECT version FROM schema_version ORDER BY id DESC LIMIT 1"))
        row = result.fetchone()
        return row[0] if row else 0
    except:
        # Table doesn't exist yet
        return 0


def set_schema_version(version):
    """Update schema version in database"""
    try:
        db.session.execute(text(f"INSERT INTO schema_version (version) VALUES ({version})"))
        db.session.commit()
    except Exception as e:
        logger.error(f"Failed to set schema version: {e}")
        db.session.rollback()


def column_exists(table_name, column_name):
    """Check if a column exists in a table"""
    inspector = inspect(db.engine)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def add_column_if_not_exists(table_name, column_name, column_definition):
    """Add a column to a table if it doesn't exist"""
    if not column_exists(table_name, column_name):
        logger.info(f"Adding column {column_name} to {table_name}")
        try:
            db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"))
            db.session.commit()
            logger.info(f"Successfully added column {column_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to add column {column_name}: {e}")
            db.session.rollback()
            return False
    return False


def migration_v1_to_v2():
    """
    Migration from v1 to v2:
    - Add custom Now Playing text fields to stream_settings
    """
    logger.info("Running migration v1 -> v2: Adding Now Playing custom text fields")

    changes_made = False

    # Add jingle_nowplaying_text column
    if add_column_if_not_exists('stream_settings', 'jingle_nowplaying_text',
                                  "VARCHAR(100) DEFAULT 'Jingle'"):
        changes_made = True

    # Add promo_nowplaying_text column
    if add_column_if_not_exists('stream_settings', 'promo_nowplaying_text',
                                  "VARCHAR(100) DEFAULT 'Promo'"):
        changes_made = True

    # Add ad_nowplaying_text column
    if add_column_if_not_exists('stream_settings', 'ad_nowplaying_text',
                                  "VARCHAR(100) DEFAULT 'Werbung'"):
        changes_made = True

    # Add moderation_nowplaying_text column
    if add_column_if_not_exists('stream_settings', 'moderation_nowplaying_text',
                                  "VARCHAR(100) DEFAULT 'Moderation'"):
        changes_made = True

    if changes_made:
        logger.info("Migration v1 -> v2 completed successfully")
    else:
        logger.info("Migration v1 -> v2: No changes needed (columns already exist)")

    return True


def migration_v2_to_v3():
    """
    Migration from v2 to v3:
    - Create listener_stats table for tracking listener counts
    """
    logger.info("Running migration v2 -> v3: Creating listener_stats table")

    try:
        # Check if table already exists
        inspector = inspect(db.engine)
        if 'listener_stats' in inspector.get_table_names():
            logger.info("Migration v2 -> v3: listener_stats table already exists")
            return True

        # Create listener_stats table
        db.session.execute(text("""
            CREATE TABLE listener_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                listener_count INTEGER NOT NULL DEFAULT 0,
                peak_listeners INTEGER DEFAULT 0,
                mountpoint VARCHAR(100) NOT NULL DEFAULT '/stream'
            )
        """))

        # Create index on timestamp for faster queries
        db.session.execute(text("""
            CREATE INDEX idx_listener_stats_timestamp
            ON listener_stats(timestamp)
        """))

        db.session.commit()
        logger.info("Migration v2 -> v3 completed successfully")
        return True

    except Exception as e:
        logger.error(f"Migration v2 -> v3 failed: {e}")
        db.session.rollback()
        return False


def migration_v3_to_v4():
    """
    Migration from v3 to v4:
    - Add TTS configuration fields to stream_settings
    """
    logger.info("Running migration v3 -> v4: Adding TTS configuration fields")

    changes_made = False

    # Minimax TTS configuration
    if add_column_if_not_exists('stream_settings', 'minimax_api_key',
                                  "VARCHAR(200) DEFAULT ''"):
        changes_made = True

    if add_column_if_not_exists('stream_settings', 'minimax_voice_id',
                                  "VARCHAR(100) DEFAULT 'male-qn-qingse'"):
        changes_made = True

    # TTS Audio Processing settings
    if add_column_if_not_exists('stream_settings', 'tts_intro_file',
                                  "VARCHAR(500) DEFAULT ''"):
        changes_made = True

    if add_column_if_not_exists('stream_settings', 'tts_outro_file',
                                  "VARCHAR(500) DEFAULT ''"):
        changes_made = True

    if add_column_if_not_exists('stream_settings', 'tts_musicbed_file',
                                  "VARCHAR(500) DEFAULT ''"):
        changes_made = True

    if add_column_if_not_exists('stream_settings', 'tts_crossfade_ms',
                                  "INTEGER DEFAULT 500"):
        changes_made = True

    if add_column_if_not_exists('stream_settings', 'tts_musicbed_volume',
                                  "FLOAT DEFAULT 0.25"):
        changes_made = True

    if add_column_if_not_exists('stream_settings', 'tts_target_dbfs',
                                  "FLOAT DEFAULT -3.0"):
        changes_made = True

    if add_column_if_not_exists('stream_settings', 'tts_highpass_hz',
                                  "INTEGER DEFAULT 80"):
        changes_made = True

    if changes_made:
        logger.info("Migration v3 -> v4 completed successfully")
    else:
        logger.info("Migration v3 -> v4: No changes needed (columns already exist)")

    return True


def migration_v4_to_v5():
    """
    Migration from v4 to v5:
    - Add minimax_model field to stream_settings
    """
    logger.info("Running migration v4 -> v5: Adding minimax_model field")

    changes_made = False

    if add_column_if_not_exists('stream_settings', 'minimax_model',
                                  "VARCHAR(100) DEFAULT 'speech-2.6-turbo'"):
        changes_made = True

    if changes_made:
        logger.info("Migration v4 -> v5 completed successfully")
    else:
        logger.info("Migration v4 -> v5: No changes needed (column already exists)")

    return True


def migration_v5_to_v6():
    """
    Migration from v5 to v6:
    - Add minimax_group_id field for Minimax API GroupId
    """
    logger.info("Running migration v5 -> v6: Adding minimax_group_id field")

    changes_made = False

    if add_column_if_not_exists('stream_settings', 'minimax_group_id',
                                  "VARCHAR(50) DEFAULT ''"):
        changes_made = True

    if changes_made:
        logger.info("Migration v5 -> v6 completed successfully")
    else:
        logger.info("Migration v5 -> v6: No changes needed (column already exists)")

    return True


def migration_v6_to_v7():
    """
    Migration from v6 to v7:
    - Add minimax_emotion field for TTS emotion
    - Add minimax_language_boost field for language optimization
    """
    logger.info("Running migration v6 -> v7: Adding emotion and language_boost fields")

    changes_made = False

    if add_column_if_not_exists('stream_settings', 'minimax_emotion',
                                  "VARCHAR(50) DEFAULT 'happy'"):
        changes_made = True

    if add_column_if_not_exists('stream_settings', 'minimax_language_boost',
                                  "VARCHAR(50) DEFAULT 'German'"):
        changes_made = True

    if changes_made:
        logger.info("Migration v6 -> v7 completed successfully")
    else:
        logger.info("Migration v6 -> v7: No changes needed (columns already exist)")

    return True


# Registry of all migrations in order
MIGRATIONS = {
    1: None,  # Base version (no migration needed)
    2: migration_v1_to_v2,
    3: migration_v2_to_v3,
    4: migration_v3_to_v4,
    5: migration_v4_to_v5,
    6: migration_v5_to_v6,
    7: migration_v6_to_v7,
}


def run_migrations():
    """
    Run all pending migrations
    Called automatically on application startup
    """
    logger.info("Checking for database migrations...")

    # Ensure schema_version table exists
    try:
        db.session.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_version (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version INTEGER NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        db.session.commit()
    except Exception as e:
        logger.error(f"Failed to create schema_version table: {e}")
        db.session.rollback()
        return

    # Get current version
    current_version = get_schema_version()
    logger.info(f"Current schema version: {current_version}")
    logger.info(f"Target schema version: {SCHEMA_VERSION}")

    if current_version >= SCHEMA_VERSION:
        logger.info("Database schema is up to date")
        return

    # Run pending migrations
    for version in range(current_version + 1, SCHEMA_VERSION + 1):
        if version in MIGRATIONS and MIGRATIONS[version] is not None:
            logger.info(f"Applying migration to version {version}...")
            try:
                success = MIGRATIONS[version]()
                if success:
                    set_schema_version(version)
                    logger.info(f"Migration to version {version} completed")
                else:
                    logger.error(f"Migration to version {version} failed")
                    break
            except Exception as e:
                logger.error(f"Error during migration to version {version}: {e}")
                break
        else:
            # No migration function for this version, just update version number
            set_schema_version(version)

    final_version = get_schema_version()
    if final_version == SCHEMA_VERSION:
        logger.info("All migrations completed successfully")
    else:
        logger.warning(f"Migrations incomplete. Current version: {final_version}, Target: {SCHEMA_VERSION}")
