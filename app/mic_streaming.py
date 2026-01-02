"""
Browser Microphone Streaming Module

Handles WebSocket audio streaming from browser to Liquidsoap.
Uses raw PCM audio -> direct HTTP PUT to Harbor (low latency)
"""

import subprocess
import threading
import queue
import time
import sys
import logging
import socket
import base64
from flask_socketio import emit
from app import socketio

def get_icecast_password():
    """Get the Icecast password from database settings"""
    try:
        from app.models import StreamSettings
        settings = StreamSettings.get_settings()
        return settings.icecast_password or 'hackme'
    except Exception:
        return 'hackme'

# Setup logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('mic_streaming')
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stderr)
handler.setLevel(logging.DEBUG)
logger.addHandler(handler)

# Global state for mic streaming
mic_state = {
    'active': False,
    'http_socket': None,
    'audio_queue': None,
    'thread': None
}


def start_harbor_connection():
    """Start direct HTTP connection to Liquidsoap Harbor (low latency)"""
    try:
        # Create TCP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(('127.0.0.1', 9998))

        # Send HTTP PUT request with chunked transfer encoding for streaming
        password = get_icecast_password()
        auth = base64.b64encode(f'source:{password}'.encode()).decode()
        http_header = (
            "PUT /mic HTTP/1.1\r\n"
            "Host: 127.0.0.1:9998\r\n"
            f"Authorization: Basic {auth}\r\n"
            "Content-Type: audio/x-raw\r\n"
            "Transfer-Encoding: chunked\r\n"
            "Connection: keep-alive\r\n"
            "\r\n"
        )
        sock.sendall(http_header.encode())

        # Read response header
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(1024)
            if not chunk:
                break
            response += chunk

        if b"200" in response or b"OK" in response:
            logger.info("Harbor connection established successfully")
            sock.setblocking(False)
            sock.settimeout(0.1)
            return sock
        else:
            logger.error(f"Harbor rejected connection: {response.decode()}")
            sock.close()
            return None

    except Exception as e:
        logger.error(f"Failed to connect to Harbor: {e}")
        return None


def audio_writer_thread():
    """Thread that writes audio data directly to Harbor via HTTP chunked encoding"""
    global mic_state

    logger.info("Audio writer thread started (direct HTTP)")
    bytes_written = 0
    last_log_time = time.time()

    while mic_state['active'] and mic_state['http_socket']:
        try:
            # Get audio data from queue with short timeout for responsiveness
            data = mic_state['audio_queue'].get(timeout=0.05)
            if data and mic_state['http_socket']:
                # Send as HTTP chunked data
                chunk_header = f"{len(data):x}\r\n".encode()
                chunk_footer = b"\r\n"
                mic_state['http_socket'].sendall(chunk_header + data + chunk_footer)
                bytes_written += len(data)

                # Log periodically
                if time.time() - last_log_time > 2.0:
                    logger.info(f"Audio writer: {bytes_written} bytes streamed")
                    last_log_time = time.time()

        except queue.Empty:
            continue
        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            logger.error(f"Harbor connection lost: {e}")
            break
        except Exception as e:
            logger.error(f"Audio writer error: {e}")
            break

    logger.info(f"Audio writer thread ended. Total bytes written: {bytes_written}")
    stop_mic_stream_internal()


def stop_mic_stream_internal():
    """Internal cleanup of mic streaming"""
    global mic_state

    if mic_state.get('ffmpeg_process'):
        try:
            mic_state['ffmpeg_process'].stdin.close()
            mic_state['ffmpeg_process'].terminate()
            mic_state['ffmpeg_process'].wait(timeout=2)
        except:
            try:
                mic_state['ffmpeg_process'].kill()
            except:
                pass
        mic_state['ffmpeg_process'] = None

    mic_state['active'] = False


def audio_streaming_thread():
    """Thread that streams audio directly to Harbor via HTTP PUT (low latency)"""
    global mic_state

    logger.info("Audio streaming thread started (direct HTTP)")

    # Connect directly to Liquidsoap Harbor via HTTP PUT
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(('127.0.0.1', 9998))

        # Send HTTP PUT request with WAV content type
        # Liquidsoap accepts WAV streams which include format info
        password = get_icecast_password()
        auth = base64.b64encode(f'source:{password}'.encode()).decode()
        http_header = (
            "SOURCE /mic ICE/1.0\r\n"
            f"Authorization: Basic {auth}\r\n"
            "Content-Type: audio/x-wav\r\n"
            "ice-name: Browser Microphone\r\n"
            "\r\n"
        )
        sock.sendall(http_header.encode())

        # Read response
        response = b""
        sock.settimeout(2)
        try:
            while b"\r\n" not in response:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                response += chunk
        except socket.timeout:
            pass

        logger.info(f"Harbor response: {response.decode(errors='ignore').strip()}")

        if b"OK" not in response and b"200" not in response:
            logger.error(f"Harbor rejected connection: {response}")
            sock.close()
            mic_state['active'] = False
            return

        # Send WAV header (44 bytes) - tells Liquidsoap the format
        # 44100 Hz, 16-bit, mono
        wav_header = create_wav_header(44100, 1, 16)
        sock.sendall(wav_header)
        logger.info("Sent WAV header, streaming audio...")

        mic_state['http_socket'] = sock
        sock.setblocking(True)
        sock.settimeout(0.5)

    except Exception as e:
        logger.error(f"Failed to connect to Harbor: {e}")
        mic_state['active'] = False
        return

    bytes_written = 0
    last_log_time = time.time()

    while mic_state['active']:
        try:
            # Get audio data with short timeout
            data = mic_state['audio_queue'].get(timeout=0.02)
            if data and mic_state['http_socket']:
                mic_state['http_socket'].sendall(data)
                bytes_written += len(data)

                if time.time() - last_log_time > 3.0:
                    logger.info(f"Streamed {bytes_written} bytes directly to Harbor")
                    last_log_time = time.time()

        except queue.Empty:
            continue
        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            logger.error(f"Harbor connection error: {e}")
            break
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            break

    logger.info(f"Streaming thread ended. Total: {bytes_written} bytes")

    # Cleanup socket
    if mic_state.get('http_socket'):
        try:
            mic_state['http_socket'].close()
        except:
            pass
        mic_state['http_socket'] = None

    stop_mic_stream_internal()


def create_wav_header(sample_rate, channels, bits_per_sample):
    """Create a WAV header for streaming (infinite length)"""
    import struct

    # Use max size to indicate streaming
    data_size = 0xFFFFFFFF - 36
    file_size = 0xFFFFFFFF

    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8

    header = struct.pack('<4sI4s', b'RIFF', file_size, b'WAVE')
    header += struct.pack('<4sIHHIIHH', b'fmt ', 16, 1, channels,
                          sample_rate, byte_rate, block_align, bits_per_sample)
    header += struct.pack('<4sI', b'data', data_size)

    return header


@socketio.on('mic_start')
def handle_mic_start():
    """Handle mic stream start request from browser"""
    global mic_state

    logger.info("=== MIC START REQUEST RECEIVED ===")

    if mic_state['active']:
        logger.info("Mic already active")
        emit('mic_status', {'status': 'already_active'})
        return

    # Enable mic and ducking in Liquidsoap FIRST (before audio arrives)
    logger.info("Enabling mic and ducking in Liquidsoap...")
    from app.audio_engine import set_mic_enabled, set_ducking_active, set_bed_enabled
    set_mic_enabled(True)

    # Auto-enable ducking and bed if configured
    from app.models import ModerationSettings
    settings = ModerationSettings.get_settings()
    if settings.mic_auto_start_bed:
        logger.info("Auto-enabling ducking and bed")
        set_ducking_active(True)
        set_bed_enabled(True)

    # Initialize audio queue (small size for low latency)
    logger.info("Initializing audio queue...")
    mic_state['audio_queue'] = queue.Queue(maxsize=50)

    # Mark as active immediately so audio can be queued
    mic_state['active'] = True

    # Start writer thread (will connect to Harbor)
    logger.info("Starting audio writer thread...")
    mic_state['thread'] = threading.Thread(target=audio_streaming_thread, daemon=True)
    mic_state['thread'].start()

    emit('mic_status', {'status': 'started'})
    logger.info("=== MIC START COMPLETE ===")


@socketio.on('mic_stop')
def handle_mic_stop():
    """Handle mic stream stop request from browser"""
    global mic_state

    logger.info("Mic stop requested")
    mic_state['active'] = False

    # Disable mic in Liquidsoap
    from app.audio_engine import set_mic_enabled, set_ducking_active, set_bed_enabled
    set_mic_enabled(False)

    # Auto-disable ducking and bed if they were auto-started
    from app.models import ModerationSettings
    settings = ModerationSettings.get_settings()
    if settings.mic_auto_start_bed:
        logger.info("Auto-disabling ducking and bed")
        set_ducking_active(False)
        set_bed_enabled(False)

    stop_mic_stream_internal()

    emit('mic_status', {'status': 'stopped'})
    logger.info("Browser mic stream stopped")


@socketio.on('mic_audio')
def handle_mic_audio(data):
    """Handle incoming audio data from browser"""
    global mic_state

    if not mic_state['active'] or not mic_state['audio_queue']:
        logger.warning(f"Mic audio received but not active or no queue")
        return

    try:
        # Convert various data types to bytes
        audio_bytes = None
        if isinstance(data, bytes):
            audio_bytes = data
        elif isinstance(data, (bytearray, memoryview)):
            audio_bytes = bytes(data)
        elif isinstance(data, list):
            # Socket.IO might send Uint8Array as list of integers
            audio_bytes = bytes(data)
        elif isinstance(data, dict):
            # Could be {_placeholder: true, num: 0} for binary
            if '_placeholder' in data:
                logger.debug("Received placeholder, binary will follow")
                return
            elif 'audio' in data:
                audio_bytes = bytes(data['audio']) if isinstance(data['audio'], (list, bytearray)) else data['audio']
        else:
            logger.warning(f"Received unknown data type: {type(data)} - {repr(data)[:100]}")
            return

        if audio_bytes:
            logger.debug(f"Received {len(audio_bytes)} bytes of audio data")
            mic_state['audio_queue'].put_nowait(audio_bytes)
    except queue.Full:
        # Drop frames if queue is full (buffer overflow protection)
        logger.warning("Audio queue full, dropping frame")
    except Exception as e:
        logger.error(f"Error handling mic audio: {e}")


@socketio.on('mic_status_request')
def handle_mic_status_request():
    """Return current mic streaming status"""
    global mic_state
    emit('mic_status', {
        'status': 'active' if mic_state['active'] else 'inactive',
        'streaming': mic_state['process'] is not None
    })
