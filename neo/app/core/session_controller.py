"""Session lifecycle controller enforcing privacy and audio state invariants."""

from __future__ import annotations

import asyncio
import time
from typing import Callable

from app.config.config_manager import ConfigManager
from app.core.event_manager import EventManager
from app.core.state_manager import BehaviorMode, NeoState, StateManager


class SessionController:
    """Controls start, pause, resume, stop, listening toggle, and immediate interruption."""

    def __init__(
        self,
        config_manager: ConfigManager,
        state_manager: StateManager,
        event_manager: EventManager,
    ) -> None:
        self.config_manager = config_manager
        self.state_manager = state_manager
        self.event_manager = event_manager
        self._start_audio_cb: Callable[[], None] | None = None
        self._stop_audio_cb: Callable[[], None] | None = None
        self._stop_tts_cb: Callable[[str], None] | None = None
        self._unload_resources_cb: Callable[[], None] | None = None
        self._active_llm_task: asyncio.Task | None = None

    def register_audio_hooks(
        self,
        start_audio_cb: Callable[[], None],
        stop_audio_cb: Callable[[], None],
    ) -> None:
        self._start_audio_cb = start_audio_cb
        self._stop_audio_cb = stop_audio_cb

    def register_tts_hook(self, stop_tts_cb: Callable[[str], None]) -> None:
        self._stop_tts_cb = stop_tts_cb

    def register_unload_hook(self, unload_resources_cb: Callable[[], None]) -> None:
        self._unload_resources_cb = unload_resources_cb

    def register_active_llm_task(self, task: asyncio.Task | None) -> None:
        self._active_llm_task = task

    def _stop_tts(self, reason: str) -> None:
        if self._stop_tts_cb is not None:
            try:
                self._stop_tts_cb(reason)
            except Exception:
                pass

    def _settle_non_off_state(self) -> NeoState:
        if self.state_manager.active_proposal is not None:
            self.state_manager.set_state(NeoState.PROPOSITION)
            return NeoState.PROPOSITION
        if (
            self.state_manager.listening_enabled
            and self.state_manager.session_active
            and not self.state_manager.session_paused
        ):
            self.state_manager.set_state(NeoState.ECOUTE)
            return NeoState.ECOUTE
        self.state_manager.set_state(NeoState.EN_VEILLE)
        return NeoState.EN_VEILLE

    def start_session(self, enable_listening: bool = True) -> NeoState:
        cfg = self.config_manager.config
        if cfg.mode == BehaviorMode.OFF.value:
            self.config_manager.update({"mode": BehaviorMode.ACTIF.value})

        self.state_manager.session_active = True
        self.state_manager.session_paused = False
        self.state_manager.session_started_at = time.monotonic()

        if enable_listening:
            self.enable_listening()
        else:
            self.state_manager.listening_enabled = False
            self.state_manager.set_state(NeoState.EN_VEILLE)

        self.event_manager.add(
            kind="system",
            event_type="SESSION_START",
            decision="Session démarrée.",
        )
        return self.state_manager.state

    def pause_session(self) -> NeoState:
        self._stop_tts("Session mise en pause.")
        self.state_manager.session_paused = True
        self.disable_listening()
        if self.config_manager.config.mode != BehaviorMode.OFF.value:
            self.state_manager.set_state(NeoState.EN_VEILLE)
        self.event_manager.add(
            kind="system",
            event_type="SESSION_PAUSE",
            decision="Session mise en pause (microphone coupé).",
        )
        return self.state_manager.state

    def resume_session(self) -> NeoState:
        if not self.state_manager.session_active:
            return self.start_session(enable_listening=True)
        if self.config_manager.config.mode == BehaviorMode.OFF.value:
            self.state_manager.set_state(NeoState.OFF)
            return NeoState.OFF
        self.state_manager.session_paused = False
        self.enable_listening()
        self.event_manager.add(
            kind="system",
            event_type="SESSION_RESUME",
            decision="Session reprise.",
        )
        return self.state_manager.state

    def stop_session(self) -> NeoState:
        self._stop_tts("Arrêt de session demandé par le formateur.")
        self.interrupt(reason="Arrêt de session demandé par le formateur.")
        self.state_manager.session_active = False
        self.state_manager.session_paused = False
        self.state_manager.session_started_at = None
        self.disable_listening()
        if self._unload_resources_cb is not None:
            try:
                self._unload_resources_cb()
            except Exception:
                pass

        if self.config_manager.config.mode == BehaviorMode.OFF.value:
            self.state_manager.set_state(NeoState.OFF)
        else:
            self.state_manager.set_state(NeoState.EN_VEILLE)

        self.event_manager.add(
            kind="system",
            event_type="SESSION_STOP",
            decision="Session arrêtée et microphone désactivé.",
        )
        return self.state_manager.state

    def on_behavior_mode_changed(self, new_mode: str) -> NeoState:
        if new_mode == BehaviorMode.OFF.value:
            return self.set_neo_enabled(False)
        was_off = self.config_manager.config.mode == BehaviorMode.OFF.value
        self.config_manager.update({"mode": new_mode})
        if was_off or self.state_manager.state == NeoState.OFF:
            if (
                self.state_manager.session_active
                and not self.state_manager.session_paused
                and self.state_manager.listening_enabled
                and self._start_audio_cb is not None
            ):
                self._start_audio_cb()
            return self._settle_non_off_state()
        return self.state_manager.state

    def set_neo_enabled(self, enabled: bool) -> NeoState:
        if not enabled:
            self._stop_tts("NÉO désactivé (mode OFF).")
            self.interrupt(reason="NÉO désactivé (mode OFF).")
            self.config_manager.update({"mode": BehaviorMode.OFF.value})
            self.disable_listening()
            if self._unload_resources_cb is not None:
                try:
                    self._unload_resources_cb()
                except Exception:
                    pass
            self.state_manager.set_state(NeoState.OFF)
        else:
            if self.config_manager.config.mode == BehaviorMode.OFF.value:
                self.config_manager.update({"mode": BehaviorMode.ACTIF.value})
            if (
                self.state_manager.session_active
                and not self.state_manager.session_paused
                and self.state_manager.listening_enabled
                and self._start_audio_cb is not None
            ):
                self._start_audio_cb()
            self._settle_non_off_state()
        return self.state_manager.state

    def enable_listening(self) -> bool:
        if self.config_manager.config.mode == BehaviorMode.OFF.value:
            self.state_manager.set_state(NeoState.OFF)
            return False
        if not self.state_manager.session_active:
            self.state_manager.session_active = True
            self.state_manager.session_paused = False
            if self.state_manager.session_started_at is None:
                self.state_manager.session_started_at = time.monotonic()

        self.state_manager.listening_enabled = True
        if self._start_audio_cb is not None:
            self._start_audio_cb()
        if self.state_manager.state not in (NeoState.ERREUR, NeoState.PROPOSITION, NeoState.INTERVENTION):
            self.state_manager.set_state(NeoState.ECOUTE)
        return True

    def disable_listening(self) -> None:
        self.state_manager.listening_enabled = False
        self.state_manager.mic_active = False
        self.state_manager.audio_level = 0.0
        if self._stop_audio_cb is not None:
            self._stop_audio_cb()
        if self.config_manager.config.mode == BehaviorMode.OFF.value:
            self.state_manager.set_state(NeoState.OFF)
        elif self.state_manager.state not in (NeoState.ERREUR, NeoState.PROPOSITION):
            self.state_manager.set_state(NeoState.EN_VEILLE)

    def interrupt(self, reason: str = "Interruption immédiate par le formateur.") -> NeoState:
        self._stop_tts(reason)
        self.state_manager.bump_interruption()
        if self._active_llm_task is not None and not self._active_llm_task.done():
            self._active_llm_task.cancel()
        self._active_llm_task = None

        mode = self.config_manager.config.mode
        if mode == BehaviorMode.OFF.value:
            self.state_manager.set_state(NeoState.OFF)
        elif self.state_manager.listening_enabled and self.state_manager.session_active:
            self.state_manager.set_state(NeoState.ECOUTE)
        else:
            self.state_manager.set_state(NeoState.EN_VEILLE)

        self.event_manager.add(
            kind="system",
            event_type="INTERRUPTION",
            decision=reason,
        )
        return self.state_manager.state
