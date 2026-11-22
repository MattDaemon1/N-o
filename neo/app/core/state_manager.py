"""State, proposal, and metrics management for NÉO."""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal


class NeoState(str, Enum):
    OFF = "OFF"
    EN_VEILLE = "EN VEILLE"
    ECOUTE = "ÉCOUTE"
    PAROLE_DETECTEE = "PAROLE DÉTECTÉE"
    TRANSCRIPTION = "TRANSCRIPTION"
    ANALYSE = "ANALYSE"
    PROPOSITION = "PROPOSITION"
    INTERVENTION = "INTERVENTION"
    ERREUR = "ERREUR"


class BehaviorMode(str, Enum):
    OFF = "OFF"
    PASSIF = "PASSIF"
    SUR_DEMANDE = "SUR_DEMANDE"
    ACTIF = "ACTIF"


class VocalMode(str, Enum):
    SILENCIEUX = "SILENCIEUX"
    ASSISTANT = "ASSISTANT"
    AUTONOME = "AUTONOME"


ProposalAction = Literal["accept", "ignore", "reformulate", "develop", "publish"]


@dataclass
class ProposalRecord:
    id: str
    created_at: str
    transcript: str
    event_type: str
    analysis: str
    decision: str
    intervention_type: str
    private_trainer_note: str
    learner_response: str
    confidence: float
    processing_ms: int
    status: str = "pending"  # pending | accepted | ignored | published
    is_simulated: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "transcript": self.transcript,
            "event_type": self.event_type,
            "analysis": self.analysis,
            "decision": self.decision,
            "intervention_type": self.intervention_type,
            "private_trainer_note": self.private_trainer_note,
            "learner_response": self.learner_response,
            "confidence": round(self.confidence, 2),
            "processing_ms": self.processing_ms,
            "status": self.status,
            "is_simulated": self.is_simulated,
        }


@dataclass
class SessionMetrics:
    segments_processed: int = 0
    errors_count: int = 0
    interventions_count: int = 0
    accepted_count: int = 0
    ignored_count: int = 0
    tts_spoken_count: int = 0
    tts_interrupted_count: int = 0
    tts_errors_count: int = 0
    last_transcription_ms: int = 0
    last_llm_ms: int = 0
    last_tts_ms: int = 0


class StateManager:
    """Thread-safe state container for the active training session."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.state: NeoState = NeoState.EN_VEILLE
        self.session_active: bool = False
        self.session_paused: bool = False
        self.listening_enabled: bool = False
        self.mic_active: bool = False
        self.audio_level: float = 0.0
        self.last_error: str | None = None
        self.last_silence_reason: str | None = None
        self.last_intervention_monotonic: float = 0.0
        self.interruption_epoch: int = 0
        self.session_started_at: float | None = None

        # TTS observability & acoustic echo suppression memory
        self.tts_state: str = "INACTIF"  # INACTIF | PRET | EN_ATTENTE | SYNTHESE | LECTURE | INTERROMPU | ERREUR
        self.tts_speaking: bool = False
        self.tts_last_error: str | None = None
        self.tts_last_spoken_text: str = ""
        self.tts_last_spoken_at: float = 0.0
        self.recent_spoken_phrases: list[tuple[float, str]] = []

        self.active_proposal: ProposalRecord | None = None
        self.published_to_learners: list[dict] = []
        self.metrics: SessionMetrics = SessionMetrics()

        # Lightweight anti-repetition session memory
        self.asked_questions: list[str] = []
        self.recent_answers: list[str] = []
        self.recent_transcripts: list[dict] = []

    def set_state(self, state: NeoState, error: str | None = None) -> None:
        with self._lock:
            self.state = state
            if error is not None:
                self.last_error = error
                self.metrics.errors_count += 1
            elif state != NeoState.ERREUR:
                self.last_error = None

    def set_tts_status(
        self,
        *,
        tts_state: str,
        speaking: bool,
        error: str | None = None,
        clear_error: bool = False,
    ) -> None:
        with self._lock:
            self.tts_state = tts_state
            self.tts_speaking = speaking
            if error is not None:
                self.tts_last_error = error
                self.metrics.tts_errors_count += 1
            elif clear_error:
                self.tts_last_error = None

    def record_tts_spoken(self, text: str) -> None:
        norm = re.sub(r"[^\w\sàâäéèêëîïôöùûüç]", " ", text.lower())
        norm = re.sub(r"\s+", " ", norm).strip()
        now = time.monotonic()
        with self._lock:
            self.tts_last_spoken_text = text
            self.tts_last_spoken_at = now
            self.metrics.tts_spoken_count += 1
            if norm:
                self.recent_spoken_phrases.append((now, norm))
                self.recent_spoken_phrases = [
                    (ts, phr) for ts, phr in self.recent_spoken_phrases[-6:] if now - ts <= 15.0
                ]

    def is_probable_tts_echo(self, transcript: str, window_seconds: float = 9.0) -> bool:
        """Detects when the microphone accidentally recaptured NÉO's own speaker output."""
        norm = re.sub(r"[^\w\sàâäéèêëîïôöùûüç]", " ", transcript.lower())
        norm = re.sub(r"\s+", " ", norm).strip()
        if len(norm) < 8:
            return False
        now = time.monotonic()
        with self._lock:
            for ts, phr in self.recent_spoken_phrases:
                if now - ts > window_seconds:
                    continue
                if norm in phr or phr in norm:
                    return True
                t_words = {w for w in norm.split() if len(w) >= 4}
                p_words = {w for w in phr.split() if len(w) >= 4}
                if len(t_words) >= 3 and len(t_words & p_words) / len(t_words) >= 0.72:
                    return True
        return False

    def bump_interruption(self) -> int:
        with self._lock:
            self.interruption_epoch += 1
            self.active_proposal = None
            return self.interruption_epoch

    def current_interruption_epoch(self) -> int:
        with self._lock:
            return self.interruption_epoch

    def cooldown_remaining(self, cooldown_seconds: int) -> int:
        with self._lock:
            if cooldown_seconds <= 0 or self.last_intervention_monotonic == 0.0:
                return 0
            elapsed = time.monotonic() - self.last_intervention_monotonic
            remaining = int(max(0.0, cooldown_seconds - elapsed))
            return remaining

    def mark_intervention_now(self) -> None:
        with self._lock:
            self.last_intervention_monotonic = time.monotonic()

    def record_transcript_memory(self, speaker: str, text: str, event_type: str) -> None:
        with self._lock:
            self.recent_transcripts.append(
                {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "speaker": speaker,
                    "text": text,
                    "event_type": event_type,
                }
            )
            if len(self.recent_transcripts) > 12:
                self.recent_transcripts = self.recent_transcripts[-12:]

    def reset_session_memory(self) -> None:
        with self._lock:
            self.active_proposal = None
            self.published_to_learners.clear()
            self.asked_questions.clear()
            self.recent_answers.clear()
            self.recent_transcripts.clear()
            self.recent_spoken_phrases.clear()
            self.last_silence_reason = None
            self.last_intervention_monotonic = 0.0
            self.metrics = SessionMetrics()
