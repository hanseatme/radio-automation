"""
Configuration Writer for Icecast and Liquidsoap
Handles updating passwords in configuration files and restarting services
"""
import logging
import subprocess
import re
import os

logger = logging.getLogger(__name__)

# Configuration file paths
ICECAST_CONFIG_PATH = '/etc/icecast2/icecast.xml'
LIQUIDSOAP_CONFIG_PATH = '/app/config/liquidsoap.liq'


def write_icecast_config(password):
    """
    Update the Icecast configuration file with new password.
    Updates source-password, relay-password, and admin-password.

    Args:
        password: The new password to set

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Read current config
        with open(ICECAST_CONFIG_PATH, 'r', encoding='utf-8') as f:
            content = f.read()

        # Replace passwords in authentication section
        # Use regex to update each password field
        content = re.sub(
            r'<source-password>.*?</source-password>',
            f'<source-password>{password}</source-password>',
            content
        )
        content = re.sub(
            r'<relay-password>.*?</relay-password>',
            f'<relay-password>{password}</relay-password>',
            content
        )
        content = re.sub(
            r'<admin-password>.*?</admin-password>',
            f'<admin-password>{password}</admin-password>',
            content
        )

        # Write updated config
        with open(ICECAST_CONFIG_PATH, 'w', encoding='utf-8') as f:
            f.write(content)

        logger.info("Icecast configuration updated successfully")
        return True

    except Exception as e:
        logger.error(f"Failed to update Icecast config: {e}")
        return False


def write_liquidsoap_config(password):
    """
    Update the Liquidsoap configuration file with new password.
    Updates harbor input password and Icecast output password.

    Args:
        password: The new password to set

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Read current config
        with open(LIQUIDSOAP_CONFIG_PATH, 'r', encoding='utf-8') as f:
            content = f.read()

        # Replace harbor password (for mic input)
        # Pattern: password="..." in input.harbor context
        content = re.sub(
            r'(input\.harbor\([^)]*password=)"[^"]*"',
            rf'\1"{password}"',
            content
        )

        # Replace output.icecast password
        # Use [\s\S]*? to match across multiple lines (non-greedy)
        # This handles the nested %mp3(...) parentheses in the output.icecast block
        content = re.sub(
            r'(output\.icecast\([\s\S]*?password=)"[^"]*"',
            rf'\1"{password}"',
            content
        )

        # Write updated config
        with open(LIQUIDSOAP_CONFIG_PATH, 'w', encoding='utf-8') as f:
            f.write(content)

        logger.info("Liquidsoap configuration updated successfully")
        return True

    except Exception as e:
        logger.error(f"Failed to update Liquidsoap config: {e}")
        return False


def restart_services():
    """
    Restart Icecast and Liquidsoap services via supervisorctl.

    Returns:
        tuple: (success: bool, message: str)
    """
    errors = []

    try:
        # Restart Icecast
        result = subprocess.run(
            ['supervisorctl', 'restart', 'icecast'],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            errors.append(f"Icecast: {result.stderr}")
        else:
            logger.info("Icecast restarted successfully")
    except subprocess.TimeoutExpired:
        errors.append("Icecast restart timed out")
    except Exception as e:
        errors.append(f"Icecast: {str(e)}")

    try:
        # Restart Liquidsoap
        result = subprocess.run(
            ['supervisorctl', 'restart', 'liquidsoap'],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            errors.append(f"Liquidsoap: {result.stderr}")
        else:
            logger.info("Liquidsoap restarted successfully")
    except subprocess.TimeoutExpired:
        errors.append("Liquidsoap restart timed out")
    except Exception as e:
        errors.append(f"Liquidsoap: {str(e)}")

    if errors:
        return False, "; ".join(errors)

    return True, "Services restarted successfully"


def update_icecast_password(new_password):
    """
    Complete password update workflow:
    1. Update Icecast config
    2. Update Liquidsoap config
    3. Restart services

    Args:
        new_password: The new password to set

    Returns:
        tuple: (success: bool, message: str)
    """
    # Validate password
    if not new_password or len(new_password) < 8:
        return False, "Passwort muss mindestens 8 Zeichen lang sein"

    # Check for characters that could break XML/Liquidsoap parsing
    forbidden_chars = ['<', '>', '&', '"', "'", '\\']
    if any(char in new_password for char in forbidden_chars):
        return False, "Passwort darf keine Sonderzeichen wie < > & \" ' \\ enthalten"

    # Update Icecast config
    if not write_icecast_config(new_password):
        return False, "Fehler beim Aktualisieren der Icecast-Konfiguration"

    # Update Liquidsoap config
    if not write_liquidsoap_config(new_password):
        return False, "Fehler beim Aktualisieren der Liquidsoap-Konfiguration"

    # Restart services
    success, message = restart_services()
    if not success:
        return False, f"Konfiguration aktualisiert, aber Dienste konnten nicht neu gestartet werden: {message}"

    return True, "Passwort erfolgreich geändert. Dienste wurden neu gestartet."
