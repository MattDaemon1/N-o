"""Lightweight bounded session event log manager."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime


@dataclass
class SessionEvent:
    id: str
    timestamp: str
    kind: str  # transcription | analysis | decision | proposal | error | system
    transcript: str
    event_type: str
    analysis: str
    decision: str
    proposal: str
    error: str
    transcription_ms: int
    llm_ms: int
    is_simulated: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "kind": self.kind,
            "transcript": self.transcript,
            "event_type": self.event_type,
            "analysis": self.analysis,
            "decision": self.decision,
            "proposal": self.proposal,
            "error": self.error,
            "transcription_ms": self.transcription_ms,
            "llm_ms": self.llm_ms,
            "is_simulated": self.is_simulated,
        }


class EventManager:
    """Stores a bounded ring buffer of session events in memory (zero disk storage by default)."""

    def __init__(self, max_events: int = 250) -> None:
        self._lock = threading.RLock()
        self._events: deque[SessionEvent] = deque(maxlen=max_events)
        self._counter = 0

    def add(
        self,
        *,
        kind: str,
        transcript: str = "",
        event_type: str = "",
        analysis: str = "",
        decision: str = "",
        proposal: str = "",
        error: str = "",
        transcription_ms: int = 0,
        llm_ms: int = 0,
        is_simulated: bool = False,
    ) -> SessionEvent:
        with self._lock:
            self._counter += 1
            ev = SessionEvent(
                id=f"evt-{self._counter}",
                timestamp=datetime.now().strftime("%H:%M:%S"),
                kind=kind,
                transcript=transcript,
                event_type=event_type,
                analysis=analysis,
                decision=decision,
                proposal=proposal,
                error=error,
                transcription_ms=transcription_ms,
                llm_ms=llm_ms,
                is_simulated=is_simulated,
            )
            self._events.appendleft(ev)
            return ev

    def list_events(self, limit: int = 100) -> list[dict]:
        with self._lock:
            return [e.to_dict() for e in list(self._events)[:limit]]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
