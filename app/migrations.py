"""
Database Migrations System
Automatically applies schema changes without data loss
"""
import logging
from sqlalchemy import text, inspect
from app import db

logger = logging.getLogger(__name__)

# Current schema version
SCHEMA_VERSION = 2  # Increment this when adding new migrations


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


# Registry of all migrations in order
MIGRATIONS = {
    1: None,  # Base version (no migration needed)
    2: migration_v1_to_v2,
    # Add future migrations here:
    # 3: migration_v2_to_v3,
    # 4: migration_v3_to_v4,
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
