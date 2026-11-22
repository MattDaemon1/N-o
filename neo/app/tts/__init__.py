"""Independent local CPU Text-to-Speech (Piper TTS) subsystem for NÉO."""

from .engine import PiperTTSEngine, SynthesizedAudio
from .speaker_worker import SpeakerWorker
from .text_limiter import SpeechTextSanitizer
from .voice_manager import FrenchVoiceInfo, VoiceManager

__all__ = [
    "FrenchVoiceInfo",
    "PiperTTSEngine",
    "SpeakerWorker",
    "SpeechTextSanitizer",
    "SynthesizedAudio",
    "VoiceManager",
]
