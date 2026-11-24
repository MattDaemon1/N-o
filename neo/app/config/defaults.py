"""Configuration defaults and validated Pydantic schema for NÉO."""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field

BehaviorModeStr = Literal["OFF", "PASSIF", "SUR_DEMANDE", "ACTIF", "REPONSE"]
VocalModeStr = Literal["SILENCIEUX", "ASSISTANT", "AUTONOME"]
TtsErrorPolicyStr = Literal["silent_fallback", "notify_error"]
LearnerLevelStr = Literal["Débutant", "Intermédiaire", "Avancé", "Mixte"]

APP_VERSION = "0.2.0"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7860


class TrainingContextConfig(BaseModel):
    title: str = Field(default="Session de formation", max_length=160)
    subject: str = Field(default="", max_length=240)
    objectives: str = Field(default="", max_length=1000)
    learner_level: LearnerLevelStr = Field(default="Intermédiaire")
    custom_instructions: str = Field(default="", max_length=1000)


class PrivacyConfig(BaseModel):
    keep_audio_diagnostic: bool = Field(default=False)
    persist_session_history: bool = Field(default=False)
    telemetry_enabled: bool = Field(default=False)


class NeoConfig(BaseModel):
    # Local Ollama settings
    ollama_url: str = Field(default="http://127.0.0.1:11434")
    ollama_model: str = Field(default="")
    ai_enabled: bool = Field(default=True)
    llm_temperature: float = Field(default=0.2, ge=0.0, le=1.5)
    llm_timeout_seconds: float = Field(default=20.0, ge=3.0, le=120.0)
    max_response_sentences: int = Field(default=4, ge=1, le=8)
    max_response_chars: int = Field(default=600, ge=150, le=1500)

    # Behavior rules
    mode: BehaviorModeStr = Field(default="ACTIF")
    cooldown_seconds: int = Field(default=20, ge=0, le=300)

    # Local TTS & Voice settings (CPU-only Piper)
    tts_enabled: bool = Field(default=False)
    vocal_mode: VocalModeStr = Field(default="ASSISTANT")
    tts_voice: str = Field(default="fr_FR-siwis-medium")
    tts_speed: float = Field(default=1.0, ge=0.65, le=1.5)
    tts_volume: float = Field(default=0.9, ge=0.0, le=1.0)
    tts_delay_ms: int = Field(default=500, ge=0, le=5000)
    tts_max_spoken_chars: int = Field(default=380, ge=100, le=800)
    tts_max_spoken_sentences: int = Field(default=3, ge=1, le=6)
    tts_error_policy: TtsErrorPolicyStr = Field(default="silent_fallback")
    tts_auto_unload_seconds: int = Field(default=120, ge=0, le=900)

    # Audio & Microphone
    mic_device_index: int | None = Field(default=None)
    mic_device_name: str = Field(default="")
    sample_rate: int = Field(default=16000, ge=8000, le=48000)
    channels: int = Field(default=1, ge=1, le=2)
    block_size: int = Field(default=512, ge=256, le=4096)

    # VAD & Segmentation
    vad_energy_threshold: float = Field(default=0.018, ge=0.002, le=0.5)
    vad_min_speech_seconds: float = Field(default=0.6, ge=0.2, le=3.0)
    vad_silence_duration_seconds: float = Field(default=1.2, ge=0.4, le=4.0)
    vad_max_segment_seconds: float = Field(default=18.0, ge=4.0, le=45.0)
    max_pending_segments: int = Field(default=3, ge=1, le=10)

    # Faster-Whisper CPU STT
    stt_model: str = Field(default="small")
    stt_compute_type: str = Field(default="int8")
    stt_language: str = Field(default="fr")
    stt_timeout_seconds: float = Field(default=18.0, ge=3.0, le=120.0)

    # Pedagogical & Privacy
    training_context: TrainingContextConfig = Field(default_factory=TrainingContextConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    diagnostics_verbose: bool = Field(default=False)
