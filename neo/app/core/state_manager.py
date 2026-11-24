"""State, proposal, and metrics management for NÉO."""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal

from app.core.text_utils import normalize_text


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
        self.tts_playback_ended_at: float = 0.0
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

    def settle_state(
        self,
        *,
        mode: str,
        preserve_states: tuple[NeoState, ...] = (),
    ) -> NeoState:
        """Atomically return NÉO to its canonical resting state without side effects."""
        with self._lock:
            if mode == BehaviorMode.OFF.value:
                target = NeoState.OFF
            elif preserve_states and self.state in preserve_states:
                return self.state
            elif self.active_proposal is not None:
                target = NeoState.PROPOSITION
            elif (
                self.listening_enabled
                and self.session_active
                and not self.session_paused
            ):
                target = NeoState.ECOUTE
            else:
                target = NeoState.EN_VEILLE
            self.set_state(target)
            return target

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
        norm = normalize_text(text)
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

    def mark_tts_playback_ended(self) -> None:
        with self._lock:
            self.tts_playback_ended_at = time.monotonic()

    def is_probable_tts_echo(
        self,
        transcript: str,
        post_playback_grace_seconds: float = 3.5,
    ) -> bool:
        """Detects when the microphone accidentally recaptured NÉO's own speaker output
        without blocking genuine learner questions or trainer interruptions."""
        raw = transcript.strip()
        lower_raw = raw.lower()
        norm = normalize_text(lower_raw)
        if len(norm) < 8:
            return False

        human_question_or_interrupt = (
            raw.endswith("?")
            or lower_raw.startswith(
                (
                    "pourquoi",
                    "comment",
                    "est-ce",
                    "qu'est-ce",
                    "c'est quoi",
                    "peux-tu",
                    "néo",
                    "neo",
                    "attends",
                    "stop",
                    "arrête",
                )
            )
            or any(
                cue in lower_raw
                for cue in (
                    "pas compris",
                    "mais du coup",
                    "néo ",
                    "neo ",
                    "arrête ",
                    "attends ",
                )
            )
            or bool(
                re.search(
                    r"(?:^(?:[^\w]+)*(?:(?:dis(?:-moi)?|ok(?:ay)?|h[eé]|eh|hey|bonjour|salut|alors)[,\s]+)?n[eé]o(?![\w-])|,\s*n[eé]o(?![\w-])(?:[\s.!?…»\"']*$|[,:]))",
                    lower_raw,
                )
            )
        )

        now = time.monotonic()
        with self._lock:
            in_active_window = (
                self.tts_speaking
                or (
                    self.tts_playback_ended_at > 0.0
                    and (now - self.tts_playback_ended_at) <= post_playback_grace_seconds
                )
            )
            for ts, phr in self.recent_spoken_phrases:
                within_phrase_window = in_active_window or (
                    self.tts_playback_ended_at == 0.0 and (now - ts) <= 9.0
                )
                if not within_phrase_window or (now - ts) > 15.0:
                    continue

                if norm == phr:
                    return True

                if human_question_or_interrupt:
                    continue

                if len(norm.split()) >= 3 and norm in phr:
                    return True

                t_words = {w for w in norm.split() if len(w) >= 4}
                p_words = {w for w in phr.split() if len(w) >= 4}
                if (
                    len(t_words) >= 3
                    and len(t_words & p_words) / len(t_words) >= 0.80
                    and len(t_words - p_words) <= 1
                ):
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

    def get_recent_transcripts(self) -> list[dict]:
        with self._lock:
            return list(self.recent_transcripts)

    def record_question(self, text: str) -> None:
        with self._lock:
            self.asked_questions.append(text)
            if len(self.asked_questions) > 20:
                self.asked_questions = self.asked_questions[-20:]

    def get_asked_questions(self) -> list[str]:
        with self._lock:
            return list(self.asked_questions)

    def record_answer(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            self.recent_answers.append(text)
            if len(self.recent_answers) > 15:
                self.recent_answers = self.recent_answers[-15:]

    def get_recent_answers(self) -> list[str]:
        with self._lock:
            return list(self.recent_answers)

    def reset_session_memory(self) -> None:
        with self._lock:
            self.active_proposal = None
            self.published_to_learners.clear()
            self.asked_questions.clear()
            self.recent_answers.clear()
            self.recent_transcripts.clear()
            self.recent_spoken_phrases.clear()
            self.tts_playback_ended_at = 0.0
            self.last_silence_reason = None
            self.last_intervention_monotonic = 0.0
            self.metrics = SessionMetrics()
