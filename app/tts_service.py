"""
TTS Service - Text-to-Speech with Minimax API and Audio Processing
"""
import os
import io
import math
import logging
import tempfile
import requests
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Helper to run requests in subprocess (bypasses eventlet DNS issues)
def _make_request_via_subprocess(method, url, **kwargs):
    """Execute a request in a subprocess to bypass eventlet monkey-patching DNS issues"""
    import subprocess
    import json

    # Build the Python code to execute in subprocess
    headers = kwargs.get('headers', {})
    json_data = kwargs.get('json', None)
    timeout = kwargs.get('timeout', 60)

    # Escape strings for Python code - use repr() to get valid Python string literals
    headers_str = repr(json.dumps(headers))
    json_data_str = repr(json.dumps(json_data)) if json_data else 'None'
    has_json_data = 'True' if json_data else 'False'

    code = f'''
import requests
import json
import sys

try:
    headers = json.loads({headers_str})
    json_data = json.loads({json_data_str}) if {has_json_data} else None
    response = requests.{method}("{url}", headers=headers, json=json_data, timeout={timeout})
    result = {{
        "status_code": response.status_code,
        "content": response.content.hex(),
        "headers": dict(response.headers)
    }}
    print(json.dumps(result))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
    sys.exit(1)
'''

    try:
        result = subprocess.run(
            ['python3', '-c', code],
            capture_output=True,
            text=True,
            timeout=timeout + 10  # Add buffer for subprocess overhead
        )

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown subprocess error"
            raise requests.exceptions.RequestException(f"Subprocess request failed: {error_msg}")

        response_data = json.loads(result.stdout)

        if "error" in response_data:
            raise requests.exceptions.RequestException(response_data["error"])

        # Create a response-like object
        class SubprocessResponse:
            def __init__(self, data):
                self.status_code = data["status_code"]
                self._content = bytes.fromhex(data["content"])
                self.headers = data["headers"]

            @property
            def content(self):
                return self._content

            def json(self):
                return json.loads(self._content.decode('utf-8'))

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")

        return SubprocessResponse(response_data)

    except subprocess.TimeoutExpired:
        raise requests.exceptions.Timeout(f"Request to {url} timed out")
    except json.JSONDecodeError as e:
        raise requests.exceptions.RequestException(f"Failed to parse subprocess response: {e}")

# Audio processing imports - optional, may not be installed
try:
    from pydub import AudioSegment
    import numpy as np
    from scipy import signal
    AUDIO_PROCESSING_AVAILABLE = True
except ImportError:
    AUDIO_PROCESSING_AVAILABLE = False
    logger.warning("Audio processing libraries not available. Install pydub, numpy, scipy for full functionality.")


class MinimaxTTS:
    """
    Minimax TTS API Integration
    Converts text to speech using Minimax's speech-2.6-turbo model
    """

    API_BASE = "https://api.minimaxi.chat"  # Note: minimaxi with 'i'
    API_URL = f"{API_BASE}/v1/t2a_v2"
    VOICE_LIST_URL = f"{API_BASE}/v1/get_voice"

    # Default system voices
    SYSTEM_VOICES = [
        {"id": "male-qn-qingse", "name": "Qingse (Männlich)", "gender": "male"},
        {"id": "male-qn-jingying", "name": "Jingying (Männlich)", "gender": "male"},
        {"id": "male-qn-badao", "name": "Badao (Männlich)", "gender": "male"},
        {"id": "male-qn-daxuesheng", "name": "Daxuesheng (Männlich)", "gender": "male"},
        {"id": "female-shaonv", "name": "Shaonv (Weiblich)", "gender": "female"},
        {"id": "female-yujie", "name": "Yujie (Weiblich)", "gender": "female"},
        {"id": "female-chengshu", "name": "Chengshu (Weiblich)", "gender": "female"},
        {"id": "female-tianmei", "name": "Tianmei (Weiblich)", "gender": "female"},
        {"id": "presenter_male", "name": "Presenter (Männlich)", "gender": "male"},
        {"id": "presenter_female", "name": "Presenter (Weiblich)", "gender": "female"},
        {"id": "audiobook_male_1", "name": "Audiobook 1 (Männlich)", "gender": "male"},
        {"id": "audiobook_male_2", "name": "Audiobook 2 (Männlich)", "gender": "male"},
        {"id": "audiobook_female_1", "name": "Audiobook 1 (Weiblich)", "gender": "female"},
        {"id": "audiobook_female_2", "name": "Audiobook 2 (Weiblich)", "gender": "female"},
    ]

    def __init__(self, api_key: str, group_id: str = None):
        """Initialize with API key and optional Group ID"""
        self.api_key = api_key
        self.group_id = group_id

    def _get_url(self, base_url: str) -> str:
        """Add GroupId to URL if available"""
        if self.group_id:
            return f"{base_url}?GroupId={self.group_id}"
        return base_url

    def generate_speech(self, text: str, voice_id: str = "German_PlayfulMan",
                       model: str = "speech-2.6-turbo",
                       speed: float = 1.0, volume: float = 1.0, pitch: int = 0,
                       emotion: str = "happy", language_boost: str = "German") -> bytes:
        """
        Generate speech from text using Minimax API

        Args:
            text: The text to convert to speech
            voice_id: Voice identifier (default: German_PlayfulMan)
            model: Model to use (default: speech-2.6-turbo)
            speed: Speech speed (0.5-2.0, default: 1.0)
            volume: Volume level (0.1-10.0, default: 1.0)
            pitch: Pitch adjustment (-12 to 12, default: 0)
            emotion: Emotion for speech (default: happy)
            language_boost: Language optimization (default: German)

        Returns:
            bytes: MP3 audio data

        Raises:
            Exception: If API call fails
        """
        if not self.api_key:
            raise ValueError("Minimax API key not configured")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": model,
            "text": text,
            "stream": False,
            "subtitle_enable": False,
            "emotion": emotion,
            "language_boost": language_boost,
            "voice_setting": {
                "voice_id": voice_id,
                "speed": speed,
                "vol": volume,
                "pitch": pitch
            },
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
                "channel": 1
            }
        }

        logger.info(f"Generating TTS with model: {model}, voice: {voice_id}, emotion: {emotion}, language: {language_boost}")

        try:
            response = _make_request_via_subprocess(
                'post',
                self._get_url(self.API_URL),
                headers=headers,
                json=payload,
                timeout=60
            )
            response.raise_for_status()

            data = response.json()

            # Check for API errors
            if "base_resp" in data:
                status_code = data["base_resp"].get("status_code", 0)
                if status_code != 0:
                    error_msg = data["base_resp"].get("status_msg", "Unknown error")
                    raise Exception(f"Minimax API error: {error_msg}")

            # Get audio data (hex encoded)
            if "data" not in data or "audio" not in data["data"]:
                raise Exception("No audio data in response")

            audio_hex = data["data"]["audio"]
            audio_bytes = bytes.fromhex(audio_hex)

            logger.info(f"TTS generation successful, audio size: {len(audio_bytes)} bytes")
            return audio_bytes

        except requests.exceptions.RequestException as e:
            logger.error(f"Minimax API request failed: {e}")
            raise Exception(f"TTS API request failed: {str(e)}")

    def list_voices(self) -> dict:
        """
        Get list of available voices from Minimax API

        Returns:
            dict with 'system_voices' and 'cloned_voices' lists
        """
        if not self.api_key:
            # Return default voices if no API key
            return {
                "system_voices": self.SYSTEM_VOICES,
                "cloned_voices": []
            }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        try:
            response = _make_request_via_subprocess(
                'post',
                self._get_url(self.VOICE_LIST_URL),
                headers=headers,
                json={"voice_type": "all"},
                timeout=30
            )
            response.raise_for_status()

            data = response.json()

            system_voices = []
            cloned_voices = []

            # Parse system voices
            if "system_voice" in data:
                for voice in data["system_voice"]:
                    system_voices.append({
                        "id": voice.get("voice_id", ""),
                        "name": voice.get("name", voice.get("voice_id", "")),
                        "gender": voice.get("gender", "unknown")
                    })

            # Parse cloned voices
            if "cloned_voice" in data:
                for voice in data["cloned_voice"]:
                    cloned_voices.append({
                        "id": voice.get("voice_id", ""),
                        "name": voice.get("name", voice.get("voice_id", "")),
                        "gender": "cloned"
                    })

            # Use defaults if no system voices returned
            if not system_voices:
                system_voices = self.SYSTEM_VOICES

            return {
                "system_voices": system_voices,
                "cloned_voices": cloned_voices
            }

        except Exception as e:
            logger.warning(f"Failed to fetch voices from API: {e}")
            return {
                "system_voices": self.SYSTEM_VOICES,
                "cloned_voices": []
            }


class AudioProcessor:
    """
    Audio processing for TTS output
    Applies voice processing, intro, outro, and music bed
    """

    def __init__(self, intro_path: str = None, outro_path: str = None,
                 musicbed_path: str = None, crossfade_ms: int = 500,
                 musicbed_volume: float = 0.25, target_dbfs: float = -3.0,
                 highpass_hz: int = 80):
        """
        Initialize audio processor

        Args:
            intro_path: Path to intro audio file
            outro_path: Path to outro audio file
            musicbed_path: Path to music bed audio file
            crossfade_ms: Crossfade duration in milliseconds
            musicbed_volume: Music bed volume (0.0-1.0)
            target_dbfs: Target peak loudness in dBFS
            highpass_hz: Highpass filter cutoff frequency
        """
        if not AUDIO_PROCESSING_AVAILABLE:
            raise RuntimeError("Audio processing libraries not available. Install pydub, numpy, scipy.")

        self.intro = None
        self.outro = None
        self.musicbed = None
        self.crossfade_ms = crossfade_ms
        self.musicbed_volume = musicbed_volume
        self.target_dbfs = target_dbfs
        self.highpass_hz = highpass_hz

        # Load audio files if paths provided
        if intro_path and os.path.exists(intro_path):
            self.intro = AudioSegment.from_file(intro_path)
            logger.info(f"Loaded intro: {intro_path} ({len(self.intro)/1000:.1f}s)")

        if outro_path and os.path.exists(outro_path):
            self.outro = AudioSegment.from_file(outro_path)
            logger.info(f"Loaded outro: {outro_path} ({len(self.outro)/1000:.1f}s)")

        if musicbed_path and os.path.exists(musicbed_path):
            self.musicbed = AudioSegment.from_file(musicbed_path)
            logger.info(f"Loaded musicbed: {musicbed_path} ({len(self.musicbed)/1000:.1f}s)")

    @staticmethod
    def _db_from_ratio(ratio: float) -> float:
        """Convert volume ratio (0-1) to dB"""
        if ratio <= 0:
            return -120
        return 20 * math.log10(ratio)

    @staticmethod
    def _audio_to_numpy(audio_segment) -> np.ndarray:
        """Convert AudioSegment to numpy array"""
        samples = np.array(audio_segment.get_array_of_samples())
        if audio_segment.channels == 2:
            samples = samples.reshape((-1, 2))
        return samples.astype(np.float64) / (2**15)

    @staticmethod
    def _numpy_to_audio(samples: np.ndarray, sample_rate: int, channels: int):
        """Convert numpy array back to AudioSegment"""
        samples = np.clip(samples, -1.0, 1.0)
        samples_int = (samples * (2**15 - 1)).astype(np.int16)

        if channels == 2:
            samples_int = samples_int.flatten()

        return AudioSegment(
            samples_int.tobytes(),
            frame_rate=sample_rate,
            sample_width=2,
            channels=channels
        )

    def _normalize_audio(self, audio_segment, target_dbfs: float = None):
        """Normalize audio to target peak level"""
        if target_dbfs is None:
            target_dbfs = self.target_dbfs

        peak_dbfs = audio_segment.max_dBFS
        change_in_db = target_dbfs - peak_dbfs
        return audio_segment.apply_gain(change_in_db)

    def _apply_highpass_filter(self, audio_segment, cutoff_hz: int = None):
        """Apply highpass filter to remove low frequency rumble"""
        if cutoff_hz is None:
            cutoff_hz = self.highpass_hz

        sample_rate = audio_segment.frame_rate
        channels = audio_segment.channels

        samples = self._audio_to_numpy(audio_segment)

        # Design Butterworth highpass filter
        nyquist = sample_rate / 2
        normalized_cutoff = cutoff_hz / nyquist

        # Ensure cutoff is valid
        if normalized_cutoff >= 1:
            normalized_cutoff = 0.99

        b, a = signal.butter(2, normalized_cutoff, btype='high')

        # Apply filter
        if channels == 1:
            filtered = signal.filtfilt(b, a, samples)
        else:
            filtered = np.zeros_like(samples)
            for ch in range(channels):
                filtered[:, ch] = signal.filtfilt(b, a, samples[:, ch])

        return self._numpy_to_audio(filtered, sample_rate, channels)

    def _process_voice(self, audio_segment):
        """Apply voice processing: highpass filter + normalization"""
        logger.info(f"Processing voice: highpass={self.highpass_hz}Hz, target={self.target_dbfs}dBFS")

        # Apply highpass filter
        processed = self._apply_highpass_filter(audio_segment)

        # Normalize
        processed = self._normalize_audio(processed)

        return processed

    def _loop_audio_to_length(self, loop_segment, target_length_ms: int):
        """Loop audio to match target length"""
        if len(loop_segment) == 0:
            raise ValueError("Loop segment is empty")

        repetitions = math.ceil(target_length_ms / len(loop_segment))
        extended_loop = loop_segment * repetitions
        return extended_loop[:target_length_ms]

    def process_audio(self, speech_bytes: bytes) -> bytes:
        """
        Process speech audio with intro, outro, and music bed

        Args:
            speech_bytes: Raw audio bytes (MP3 format)

        Returns:
            bytes: Processed MP3 audio
        """
        logger.info("Starting audio processing...")

        # Load speech audio
        speech = AudioSegment.from_file(io.BytesIO(speech_bytes), format="mp3")
        logger.info(f"Loaded speech: {len(speech)/1000:.1f}s, {speech.dBFS:.1f}dBFS")

        # Apply voice processing
        speech = self._process_voice(speech)
        logger.info(f"After voice processing: {speech.dBFS:.1f}dBFS")

        result = speech

        # Add music bed if available
        if self.musicbed is not None:
            # Loop music bed to match speech length
            musicbed_looped = self._loop_audio_to_length(self.musicbed, len(speech))

            # Reduce music bed volume
            musicbed_adjusted = musicbed_looped + self._db_from_ratio(self.musicbed_volume)

            # Overlay speech on music bed
            result = speech.overlay(musicbed_adjusted)
            logger.info(f"Added music bed at {self.musicbed_volume*100:.0f}% volume")

        # Add intro with crossfade if available
        if self.intro is not None:
            result = self.intro.append(result, crossfade=self.crossfade_ms)
            logger.info(f"Added intro with {self.crossfade_ms}ms crossfade")

        # Add outro with crossfade if available
        if self.outro is not None:
            result = result.append(self.outro, crossfade=self.crossfade_ms)
            logger.info(f"Added outro with {self.crossfade_ms}ms crossfade")

        # Export to MP3
        output_buffer = io.BytesIO()
        result.export(output_buffer, format="mp3", bitrate="192k")
        output_bytes = output_buffer.getvalue()

        logger.info(f"Processing complete: {len(result)/1000:.1f}s, {len(output_bytes)} bytes")

        return output_bytes

    def process_audio_simple(self, speech_bytes: bytes) -> bytes:
        """
        Simple processing: just voice processing without intro/outro/musicbed

        Args:
            speech_bytes: Raw audio bytes (MP3 format)

        Returns:
            bytes: Processed MP3 audio
        """
        # Load speech audio
        speech = AudioSegment.from_file(io.BytesIO(speech_bytes), format="mp3")

        # Apply voice processing
        speech = self._process_voice(speech)

        # Export to MP3
        output_buffer = io.BytesIO()
        speech.export(output_buffer, format="mp3", bitrate="192k")

        return output_buffer.getvalue()


def generate_tts_with_processing(text: str, settings, target_folder: str,
                                  filename: str = None) -> dict:
    """
    Complete TTS generation with audio processing

    Args:
        text: Text to convert to speech
        settings: StreamSettings object with TTS configuration
        target_folder: Target folder category (e.g., 'random-moderation')
        filename: Optional custom filename (without extension)

    Returns:
        dict with 'success', 'filename', 'path', 'duration', 'error'
    """
    try:
        # Check if API key is configured
        if not settings.minimax_api_key:
            return {
                "success": False,
                "error": "Minimax API key not configured"
            }

        # Initialize TTS
        tts = MinimaxTTS(settings.minimax_api_key, settings.minimax_group_id)

        # Generate speech
        speech_bytes = tts.generate_speech(
            text=text,
            voice_id=settings.minimax_voice_id or "German_PlayfulMan",
            model=settings.minimax_model or "speech-2.6-turbo",
            emotion=getattr(settings, 'minimax_emotion', None) or "happy",
            language_boost=getattr(settings, 'minimax_language_boost', None) or "German"
        )

        # Check if audio processing is available and configured
        has_processing_files = (
            settings.tts_intro_file or
            settings.tts_outro_file or
            settings.tts_musicbed_file
        )

        if AUDIO_PROCESSING_AVAILABLE and has_processing_files:
            # Build paths to internal files
            media_path = os.environ.get('MEDIA_PATH', '/media')
            internal_path = os.path.join(media_path, 'internal')

            intro_path = os.path.join(internal_path, settings.tts_intro_file) if settings.tts_intro_file else None
            outro_path = os.path.join(internal_path, settings.tts_outro_file) if settings.tts_outro_file else None
            musicbed_path = os.path.join(internal_path, settings.tts_musicbed_file) if settings.tts_musicbed_file else None

            # Initialize processor
            processor = AudioProcessor(
                intro_path=intro_path,
                outro_path=outro_path,
                musicbed_path=musicbed_path,
                crossfade_ms=settings.tts_crossfade_ms or 500,
                musicbed_volume=settings.tts_musicbed_volume or 0.25,
                target_dbfs=settings.tts_target_dbfs or -3.0,
                highpass_hz=settings.tts_highpass_hz or 80
            )

            # Process audio
            output_bytes = processor.process_audio(speech_bytes)
        elif AUDIO_PROCESSING_AVAILABLE:
            # Just apply voice processing without intro/outro/musicbed
            processor = AudioProcessor(
                crossfade_ms=settings.tts_crossfade_ms or 500,
                musicbed_volume=settings.tts_musicbed_volume or 0.25,
                target_dbfs=settings.tts_target_dbfs or -3.0,
                highpass_hz=settings.tts_highpass_hz or 80
            )
            output_bytes = processor.process_audio_simple(speech_bytes)
        else:
            # No audio processing available, use raw TTS output
            output_bytes = speech_bytes

        # Generate filename if not provided
        if not filename:
            # Create filename from first 20 chars of text
            safe_text = "".join(c if c.isalnum() else "_" for c in text[:20])
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"tts_{safe_text}_{timestamp}"

        # Ensure .mp3 extension
        if not filename.endswith('.mp3'):
            filename = f"{filename}.mp3"

        # Save to target folder
        media_path = os.environ.get('MEDIA_PATH', '/media')
        target_path = os.path.join(media_path, target_folder, filename)

        # Ensure directory exists
        os.makedirs(os.path.dirname(target_path), exist_ok=True)

        # Write file
        with open(target_path, 'wb') as f:
            f.write(output_bytes)

        logger.info(f"TTS file saved: {target_path}")

        # Get duration for response
        duration = 0
        if AUDIO_PROCESSING_AVAILABLE:
            try:
                audio = AudioSegment.from_file(io.BytesIO(output_bytes), format="mp3")
                duration = len(audio) / 1000.0
            except:
                pass

        return {
            "success": True,
            "filename": filename,
            "path": target_path,
            "duration": duration
        }

    except Exception as e:
        logger.error(f"TTS generation failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }
