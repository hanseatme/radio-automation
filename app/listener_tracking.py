"""
Listener Tracking System
Tracks listener count statistics from Icecast in 5-minute intervals
"""
import logging
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from app import db
from app.models import ListenerStats, StreamSettings

logger = logging.getLogger(__name__)


def get_icecast_listeners(mountpoint='/stream'):
    """
    Fetch current listener count from Icecast server
    Returns the number of listeners or 0 if unable to fetch
    """
    try:
        # Icecast stats endpoint (XML format)
        url = 'http://localhost:8000/admin/stats'

        # Get password from database settings
        settings = StreamSettings.get_settings()
        password = settings.icecast_password or 'hackme'
        auth = ('admin', password)

        response = requests.get(url, auth=auth, timeout=5)
        response.raise_for_status()

        # Parse XML response
        root = ET.fromstring(response.content)

        # Find the mountpoint we're interested in
        for source in root.findall('.//source'):
            mount = source.get('mount')
            if mount == mountpoint:
                listeners_elem = source.find('listeners')
                if listeners_elem is not None:
                    return int(listeners_elem.text)

        # If mountpoint not found, return 0
        logger.warning(f"Mountpoint {mountpoint} not found in Icecast stats")
        return 0

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch Icecast stats: {e}")
        return 0
    except ET.ParseError as e:
        logger.error(f"Failed to parse Icecast XML: {e}")
        return 0
    except Exception as e:
        logger.error(f"Unexpected error getting Icecast listeners: {e}")
        return 0


def record_listener_stats(mountpoint='/stream'):
    """
    Record current listener count to database
    Called every 5 minutes by the scheduler
    """
    try:
        listener_count = get_icecast_listeners(mountpoint)

        # Create new stats entry
        stat = ListenerStats(
            timestamp=datetime.utcnow(),
            listener_count=listener_count,
            peak_listeners=listener_count,  # Can be enhanced to track peak within interval
            mountpoint=mountpoint
        )

        db.session.add(stat)
        db.session.commit()

        logger.info(f"Recorded listener stats: {listener_count} listeners on {mountpoint}")

        # Cleanup old stats (keep last 30 days)
        cleanup_old_stats(days=30)

        return listener_count

    except Exception as e:
        logger.error(f"Failed to record listener stats: {e}")
        db.session.rollback()
        return 0


def cleanup_old_stats(days=30):
    """
    Delete listener statistics older than N days
    Keeps database size manageable
    """
    try:
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(days=days)

        deleted = ListenerStats.query.filter(ListenerStats.timestamp < cutoff).delete()

        if deleted > 0:
            db.session.commit()
            logger.info(f"Cleaned up {deleted} old listener stats entries")

    except Exception as e:
        logger.error(f"Failed to cleanup old listener stats: {e}")
        db.session.rollback()


def get_listener_statistics(hours=24):
    """
    Get aggregated listener statistics for the last N hours
    Returns dict with current, peak, average, and historical data
    """
    try:
        stats = ListenerStats.get_stats(hours=hours)
        current = ListenerStats.get_current_listeners()
        peak = ListenerStats.get_peak_listeners(hours=hours)
        average = ListenerStats.get_average_listeners(hours=hours)

        return {
            'current': current,
            'peak': peak,
            'average': average,
            'history': [s.to_dict() for s in stats]
        }

    except Exception as e:
        logger.error(f"Failed to get listener statistics: {e}")
        return {
            'current': 0,
            'peak': 0,
            'average': 0,
            'history': []
        }
