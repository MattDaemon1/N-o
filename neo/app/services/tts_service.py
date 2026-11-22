"""Local TTS service coordinating vocal modes, behavior protections, interruption, and errors."""

from __future__ import annotations

import threading
import time
from typing import Any

from app.config.config_manager import ConfigManager
from app.core.event_manager import EventManager
from app.core.state_manager import BehaviorMode, NeoState, StateManager, VocalMode
from app.tts.engine import PiperTTSEngine
from app.tts.speaker_worker import SpeakerWorker
from app.tts.text_limiter import SpeechTextSanitizer
from app.tts.voice_manager import VoiceManager


DEFAULT_DEMO_TEXT = "Bonjour, je suis NÉO, votre assistant pédagogique local."


class TTSService:
    """High-level orchestration for local Piper TTS with strict interruption priority."""

    def __init__(
        self,
        *,
        config_manager: ConfigManager,
        state_manager: StateManager,
        event_manager: EventManager,
        voice_manager: VoiceManager | None = None,
        engine: PiperTTSEngine | None = None,
        worker: SpeakerWorker | None = None,
    ) -> None:
        self.config_manager = config_manager
        self.state_manager = state_manager
        self.event_manager = event_manager
        self.voice_manager = voice_manager or VoiceManager()
        self.engine = engine or PiperTTSEngine(voice_manager=self.voice_manager)
        self.worker = worker or SpeakerWorker(self.engine)
        self.worker.set_auto_unload_seconds(self.config_manager.config.tts_auto_unload_seconds)
        self._inventory_lock = threading.RLock()
        self._inventory_ttl_seconds = 12.0
        self._inventory_cached_at = 0.0
        self._cached_voice_key = ""
        self._cached_backend: dict[str, Any] = {}
        self._cached_voices: list[Any] = []
        self._cached_selected_ok = False
        self._cached_selected_err: str | None = None
        self._cached_installed_ids: list[str] = []

    def invalidate_inventory_cache(self) -> None:
        with self._inventory_lock:
            self._inventory_cached_at = 0.0

    def _settle_after_speech(self) -> None:
        self.state_manager.settle_state(
            mode=self.config_manager.config.mode,
            preserve_states=(NeoState.PAROLE_DETECTEE,),
        )

    def get_status(self, refresh_inventory: bool = True) -> dict[str, Any]:
        cfg = self.config_manager.config
        now = time.monotonic()
        with self._inventory_lock:
            cache_expired = (
                self._inventory_cached_at == 0.0
                or (now - self._inventory_cached_at) >= self._inventory_ttl_seconds
                or self._cached_voice_key != cfg.tts_voice
            )
            if refresh_inventory or cache_expired:
                backend = self.engine.get_backend_info()
                voices = self.voice_manager.list_voices()
                selected_ok, selected_err, _ = self.voice_manager.validate_voice(cfg.tts_voice)
                installed_ids = [v.voice_id for v in voices if v.valid]

                self._cached_backend = backend
                self._cached_voices = voices
                self._cached_selected_ok = selected_ok
                self._cached_selected_err = selected_err
                self._cached_installed_ids = installed_ids
                self._cached_voice_key = cfg.tts_voice
                self._inventory_cached_at = now
            else:
                backend = {
                    **self._cached_backend,
                    "model_loaded": self.engine.is_loaded(),
                }
                voices = self._cached_voices
                selected_ok = self._cached_selected_ok
                selected_err = self._cached_selected_err
                installed_ids = self._cached_installed_ids

        if not cfg.tts_enabled:
            effective_state = "INACTIF"
        elif self.state_manager.tts_state in ("EN_ATTENTE", "SYNTHESE", "LECTURE", "ERREUR", "INTERROMPU"):
            effective_state = self.state_manager.tts_state
        else:
            effective_state = "PRET" if (backend["available"] and selected_ok) else "INDISPONIBLE"

        return {
            "tts_enabled": cfg.tts_enabled,
            "vocal_mode": cfg.vocal_mode,
            "tts_state": effective_state,
            "speaking": self.state_manager.tts_speaking or self.worker.is_busy(),
            "selected_voice": cfg.tts_voice,
            "selected_voice_installed": selected_ok,
            "selected_voice_error": selected_err,
            "installed_voices": installed_ids,
            "voices": [v.to_dict() for v in voices],
            "speed": cfg.tts_speed,
            "volume": cfg.tts_volume,
            "delay_ms": cfg.tts_delay_ms,
            "error_policy": cfg.tts_error_policy,
            "max_spoken_chars": cfg.tts_max_spoken_chars,
            "last_error": self.state_manager.tts_last_error,
            "last_tts_ms": self.state_manager.metrics.last_tts_ms,
            "backend": backend,
        }

    def speak_autonomous(
        self,
        *,
        text: str,
        behavior_allowed: bool,
        explicit_trainer_request: bool = False,
        epoch_before: int | None = None,
    ) -> dict[str, Any]:
        """Speaks proactively ONLY in AUTONOME mode when all behavioral rules approve."""
        cfg = self.config_manager.config
        if cfg.mode == BehaviorMode.OFF.value:
            return {"spoken": False, "reason": "Mode OFF : voix bloquée."}
        if not cfg.tts_enabled:
            return {"spoken": False, "reason": "Voix de NÉO désactivée."}
        if cfg.vocal_mode != VocalMode.AUTONOME.value:
            return {
                "spoken": False,
                "reason": f"Mode vocal '{cfg.vocal_mode}' : pas de prise de parole autonome.",
            }
        if not behavior_allowed:
            return {"spoken": False, "reason": "Moteur comportemental : silence maintenu."}
        if cfg.mode == BehaviorMode.PASSIF.value and not explicit_trainer_request:
            return {"spoken": False, "reason": "Mode PASSIF : pas de prise de parole autonome."}
        if cfg.mode == BehaviorMode.SUR_DEMANDE.value and not explicit_trainer_request:
            return {"spoken": False, "reason": "Mode SUR_DEMANDE : attente sollicitation formateur."}
        if (
            epoch_before is not None
            and epoch_before != self.state_manager.current_interruption_epoch()
        ):
            return {"spoken": False, "reason": "Interruption active : parole annulée."}

        return self._schedule_speech(
            raw_text=text,
            delay_ms=cfg.tts_delay_ms,
            origin="AUTONOME",
        )

    def speak_on_trainer_request(self, text: str) -> dict[str, Any]:
        """Speaks text explicitly triggered by the trainer (ASSISTANT or AUTONOME mode)."""
        cfg = self.config_manager.config
        if cfg.mode == BehaviorMode.OFF.value:
            return {"spoken": False, "reason": "NÉO est désactivé (mode OFF)."}
        if not cfg.tts_enabled:
            return {"spoken": False, "reason": "Activez la voix de NÉO dans le panneau « Voix de NÉO »."}
        if cfg.vocal_mode == VocalMode.SILENCIEUX.value:
            return {
                "spoken": False,
                "reason": "Mode vocal SILENCIEUX actif : passez en mode ASSISTANT ou AUTONOME pour prononcer la réponse.",
            }
        return self._schedule_speech(raw_text=text, delay_ms=0, origin="ASSISTANT")

    def test_voice(self, text: str | None = None) -> dict[str, Any]:
        """Standalone voice test from the dashboard panel (bypasses listening/LLM pipeline)."""
        cfg = self.config_manager.config
        sample = (text or "").strip() or DEFAULT_DEMO_TEXT
        return self._schedule_speech(
            raw_text=sample,
            delay_ms=0,
            origin="TEST_VOIX",
            update_neo_state=False,
        )

    def _schedule_speech(
        self,
        *,
        raw_text: str,
        delay_ms: int,
        origin: str,
        update_neo_state: bool = True,
    ) -> dict[str, Any]:
        cfg = self.config_manager.config
        clean_text = SpeechTextSanitizer.sanitize(
            raw_text,
            max_chars=cfg.tts_max_spoken_chars,
            max_sentences=cfg.tts_max_spoken_sentences,
        )
        if not clean_text:
            return {"spoken": False, "reason": "Texte vide ou non oralisable ignoré."}

        # Pre-flight validation so missing/corrupted voice or absent Piper fails cleanly
        backend = self.engine.get_backend_info()
        if not backend["available"]:
            err = (
                "Moteur Piper TTS absent. Installez 'piper-tts' ou placez piper.exe dans neo/tools/piper/."
            )
            self._handle_tts_error(err)
            return {"spoken": False, "reason": err, "error": err}

        valid, v_err, _ = self.voice_manager.validate_voice(cfg.tts_voice)
        if not valid:
            err = v_err or f"Modèle vocal '{cfg.tts_voice}' indisponible."
            self._handle_tts_error(err)
            return {"spoken": False, "reason": err, "error": err}

        self.worker.set_auto_unload_seconds(cfg.tts_auto_unload_seconds)
        self.state_manager.set_tts_status(
            tts_state="EN_ATTENTE" if delay_ms > 0 else "SYNTHESE",
            speaking=True,
            clear_error=True,
        )

        def _on_start(job_id: int, spoken_text: str) -> None:
            if job_id != self.worker.current_job_id():
                return
            self.state_manager.set_tts_status(tts_state="SYNTHESE", speaking=True)
            if update_neo_state and self.config_manager.config.mode != BehaviorMode.OFF.value:
                self.state_manager.set_state(NeoState.INTERVENTION)

        def _on_playback(job_id: int, spoken_text: str) -> None:
            if job_id != self.worker.current_job_id():
                return
            self.state_manager.set_tts_status(tts_state="LECTURE", speaking=True)
            self.state_manager.record_tts_spoken(spoken_text)

        def _on_finish(job_id: int, interrupted: bool, duration_ms: int, error: str | None) -> None:
            self.state_manager.mark_tts_playback_ended()
            if job_id != self.worker.current_job_id():
                return
            self.state_manager.metrics.last_tts_ms = duration_ms
            if interrupted:
                self.state_manager.set_tts_status(tts_state="INTERROMPU", speaking=False)
            elif error:
                self._handle_tts_error(error)
            else:
                ready_state = "PRET" if self.config_manager.config.tts_enabled else "INACTIF"
                self.state_manager.set_tts_status(tts_state=ready_state, speaking=False)

            if update_neo_state:
                self._settle_after_speech()

        self.worker.enqueue(
            text=clean_text,
            voice_id=cfg.tts_voice,
            speed=cfg.tts_speed,
            volume=cfg.tts_volume,
            delay_ms=delay_ms,
            on_start=_on_start,
            on_playback=_on_playback,
            on_finish=_on_finish,
        )
        self.event_manager.add(
            kind="system",
            event_type=f"TTS_{origin}",
            decision=f"Parole planifiée ({cfg.tts_voice})",
            proposal=clean_text,
        )
        return {"spoken": True, "text": clean_text, "voice": cfg.tts_voice}

    def _handle_tts_error(self, error_msg: str) -> None:
        cfg = self.config_manager.config
        self.state_manager.set_tts_status(tts_state="ERREUR", speaking=False, error=error_msg)
        self.event_manager.add(kind="error", event_type="TTS_ERROR", error=error_msg)
        if cfg.tts_error_policy == "notify_error":
            self.state_manager.last_error = f"Voix (TTS) : {error_msg}"

    def interrupt(self, reason: str = "Voix interrompue.") -> bool:
        """Immediately stops TTS synthesis & playback WITHOUT touching microphone/VAD/STT."""
        was_busy = self.worker.interrupt()
        if was_busy or self.state_manager.tts_speaking:
            self.state_manager.mark_tts_playback_ended()
            self.state_manager.metrics.tts_interrupted_count += 1
            self.state_manager.set_tts_status(tts_state="INTERROMPU", speaking=False)
            self.event_manager.add(kind="system", event_type="TTS_INTERRUPTION", decision=reason)
            if self.state_manager.state == NeoState.INTERVENTION:
                self._settle_after_speech()
            return True
        return False

    def unload_resources(self) -> None:
        self.interrupt("Libération ressources TTS.")
        self.engine.unload()
        ready_state = "PRET" if self.config_manager.config.tts_enabled else "INACTIF"
        self.state_manager.set_tts_status(tts_state=ready_state, speaking=False)
