"""Application runtime wiring connecting config, core, audio, AI, and services."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from app.ai.model_manager import ModelManager
from app.ai.ollama_client import OllamaClient
from app.audio.capture import AudioCapture
from app.audio.pipeline import AudioPipeline
from app.audio.segmentation import AudioSegment, SegmentQueueManager
from app.audio.stt import FasterWhisperSTT
from app.config.config_manager import ConfigManager
from app.config.defaults import NeoConfig
from app.core.behavior_engine import BehaviorEngine
from app.core.event_manager import EventManager
from app.core.session_controller import SessionController
from app.core.state_manager import NeoState, StateManager
from app.services.diagnostics_service import DiagnosticsService
from app.services.pedagogical_service import PedagogicalService
from app.services.transcription_service import TranscriptionService
from app.services.tts_service import TTSService


class NeoRuntime:
    """Single clean dependency container for the NÉO local server."""

    def __init__(self, config_path: Path | str = "dashboard_config.json") -> None:
        self.config_manager = ConfigManager(config_path=config_path)
        self.state_manager = StateManager()
        self.event_manager = EventManager(max_events=250)
        self.behavior_engine = BehaviorEngine()
        self.session_controller = SessionController(
            self.config_manager,
            self.state_manager,
            self.event_manager,
        )

        self.ollama_client = OllamaClient(self.config_manager.config.ollama_url)
        self.model_manager = ModelManager(self.config_manager, self.ollama_client)

        self.audio_capture = AudioCapture()
        self.segment_queue = SegmentQueueManager(
            max_pending=self.config_manager.config.max_pending_segments
        )
        self.stt = FasterWhisperSTT()
        self.audio_pipeline = AudioPipeline(
            self.config_manager,
            self.state_manager,
            self.audio_capture,
            self.segment_queue,
        )

        self.tts_service = TTSService(
            config_manager=self.config_manager,
            state_manager=self.state_manager,
            event_manager=self.event_manager,
        )

        self.transcription_service = TranscriptionService(
            self.config_manager,
            self.state_manager,
            self.event_manager,
            self.segment_queue,
            self.stt,
        )
        self.pedagogical_service = PedagogicalService(
            config_manager=self.config_manager,
            state_manager=self.state_manager,
            event_manager=self.event_manager,
            behavior_engine=self.behavior_engine,
            session_controller=self.session_controller,
            ollama_client=self.ollama_client,
            model_manager=self.model_manager,
            tts_service=self.tts_service,
        )
        self.diagnostics_service = DiagnosticsService(
            config_manager=self.config_manager,
            state_manager=self.state_manager,
            model_manager=self.model_manager,
            audio_capture=self.audio_capture,
            segment_queue=self.segment_queue,
            stt=self.stt,
            tts_service=self.tts_service,
        )

        self.session_controller.register_audio_hooks(
            start_audio_cb=self.audio_pipeline.start,
            stop_audio_cb=self.audio_pipeline.stop,
        )
        self.session_controller.register_tts_hook(self.tts_service.interrupt)
        self.session_controller.register_unload_hook(self.unload_heavy_models)

        # Absolute priority: Formateur > Apprenants > NÉO
        # Any human speech start detected by VAD immediately interrupts NÉO's voice
        # without ever stopping the microphone, VAD, or STT.
        self.audio_pipeline.bind_speech_started_hook(
            lambda: self.tts_service.interrupt("Parole détectée : priorité au formateur et aux apprenants.")
        )

        if self.config_manager.config.mode == "OFF":
            self.state_manager.set_state(NeoState.OFF)

    def unload_heavy_models(self) -> None:
        self.tts_service.unload_resources()
        self.stt.unload_model()

    def _apply_runtime_config_effects(
        self,
        prev_cfg: NeoConfig,
        new_cfg: NeoConfig,
        *,
        mode_changed: bool = False,
        already_unloaded_tts: bool = False,
    ) -> None:
        self.ollama_client.set_base_url(new_cfg.ollama_url)
        self.segment_queue.set_max_pending(new_cfg.max_pending_segments)
        self.tts_service.worker.set_auto_unload_seconds(new_cfg.tts_auto_unload_seconds)

        if mode_changed:
            self.session_controller.on_behavior_mode_changed(new_cfg.mode)
        if not new_cfg.tts_enabled:
            if not already_unloaded_tts:
                self.tts_service.unload_resources()
        elif new_cfg.vocal_mode == "SILENCIEUX":
            self.tts_service.interrupt("Mode vocal SILENCIEUX sélectionné.")
        self.diagnostics_service.invalidate_inventory_cache()

    def apply_config_update(self, patch: dict[str, Any]) -> NeoConfig:
        prev_cfg = self.config_manager.config
        updated = self.config_manager.update(patch)
        self._apply_runtime_config_effects(
            prev_cfg,
            updated,
            mode_changed=("mode" in patch and updated.mode != prev_cfg.mode),
        )
        return updated

    def reset_config_defaults(self) -> NeoConfig:
        prev_cfg = self.config_manager.config
        self.tts_service.unload_resources()
        reset_cfg = self.config_manager.reset_defaults()
        self._apply_runtime_config_effects(
            prev_cfg,
            reset_cfg,
            mode_changed=(reset_cfg.mode != prev_cfg.mode),
            already_unloaded_tts=True,
        )
        return reset_cfg

    async def startup(self) -> None:
        loop = asyncio.get_running_loop()
        self.audio_pipeline.bind_async_handler(loop, self._handle_audio_segment)
        await self.model_manager.refresh()

    async def shutdown(self) -> None:
        self.session_controller.stop_session()
        self.audio_pipeline.stop()
        self.tts_service.worker.stop_worker()
        self.stt.unload_model()

    async def _handle_audio_segment(self, segment: AudioSegment) -> None:
        result = await self.transcription_service.transcribe_segment(segment)
        if result.error and not result.text:
            self.state_manager.set_state(NeoState.ERREUR, error=result.error)
            return
        await self.pedagogical_service.process_transcript(
            transcript=result.text,
            speaker="Apprenant",
            stt_uncertain=result.is_uncertain,
            transcription_ms=result.duration_ms,
            is_simulated=False,
        )
