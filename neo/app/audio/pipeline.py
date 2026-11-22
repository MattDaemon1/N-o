"""Async audio pipeline: Capture -> VAD -> Bounded Segment Queue -> STT -> Pedagogical Service."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
import threading
import time
from typing import Awaitable, Callable

from app.audio.capture import AudioCapture
from app.audio.segmentation import AudioSegment, SegmentQueueManager
from app.audio.vad import VoiceActivityDetector
from app.config.config_manager import ConfigManager
from app.core.state_manager import BehaviorMode, NeoState, StateManager


class AudioPipeline:
    """Runs capture/VAD in lightweight background threads and dispatches 1 segment at a time."""

    def __init__(
        self,
        config_manager: ConfigManager,
        state_manager: StateManager,
        capture: AudioCapture,
        segment_queue: SegmentQueueManager,
    ) -> None:
        self.config_manager = config_manager
        self.state_manager = state_manager
        self.capture = capture
        self.segment_queue = segment_queue

        self._loop: asyncio.AbstractEventLoop | None = None
        self._segment_callback: Callable[[AudioSegment], Awaitable[None]] | None = None
        self._speech_started_cb: Callable[[], None] | None = None
        self._stop_event = threading.Event()
        self._vad_thread: threading.Thread | None = None
        self._worker_thread: threading.Thread | None = None
        self._process_lock = asyncio.Semaphore(1)
        self._active_future: Future[None] | None = None
        self._future_lock = threading.Lock()

    def bind_async_handler(
        self,
        loop: asyncio.AbstractEventLoop,
        callback: Callable[[AudioSegment], Awaitable[None]],
    ) -> None:
        self._loop = loop
        self._segment_callback = callback

    def bind_speech_started_hook(self, callback: Callable[[], None]) -> None:
        """Called immediately when VAD detects human speech start (trainer/learner priority)."""
        self._speech_started_cb = callback

    def start(self) -> bool:
        cfg = self.config_manager.config
        if cfg.mode == BehaviorMode.OFF.value:
            self.stop()
            self.state_manager.set_state(NeoState.OFF)
            return False

        self.stop()
        self.segment_queue.set_max_pending(cfg.max_pending_segments)
        self._stop_event.clear()

        def _on_audio_err(err_msg: str) -> None:
            self.state_manager.mic_active = False
            self.state_manager.set_state(NeoState.ERREUR, error=err_msg)

        started = self.capture.start(
            device_index=cfg.mic_device_index,
            sample_rate=cfg.sample_rate,
            channels=cfg.channels,
            block_size=cfg.block_size,
            on_error=_on_audio_err,
        )
        if not started:
            self.state_manager.mic_active = False
            return False

        self.state_manager.mic_active = True
        if self.state_manager.state != NeoState.PROPOSITION:
            self.state_manager.set_state(NeoState.ECOUTE)

        self._vad_thread = threading.Thread(
            target=self._vad_loop, name="neo-vad-thread", daemon=True
        )
        self._worker_thread = threading.Thread(
            target=self._segment_dispatch_loop, name="neo-seg-worker", daemon=True
        )
        self._vad_thread.start()
        self._worker_thread.start()
        return True

    def _vad_loop(self) -> None:
        cfg = self.config_manager.config
        vad = VoiceActivityDetector(
            sample_rate=cfg.sample_rate,
            energy_threshold=cfg.vad_energy_threshold,
            min_speech_seconds=cfg.vad_min_speech_seconds,
            silence_duration_seconds=cfg.vad_silence_duration_seconds,
            max_segment_seconds=cfg.vad_max_segment_seconds,
        )
        last_reported_error: str | None = None

        while not self._stop_event.is_set() and self.capture.is_running:
            frame = self.capture.read_frame(timeout=0.15)
            self.state_manager.audio_level = self.capture.current_level
            cap_err = self.capture.last_error
            if frame is None:
                if cap_err:
                    if cap_err != last_reported_error:
                        last_reported_error = cap_err
                        self.state_manager.set_state(NeoState.ERREUR, error=cap_err)
                    if "débranché" in cap_err.lower() or "indisponible" in cap_err.lower():
                        self.state_manager.mic_active = False
                        break
                continue

            if last_reported_error is not None:
                last_reported_error = None
                if self.state_manager.state == NeoState.ERREUR and self.state_manager.listening_enabled:
                    self.state_manager.set_state(NeoState.ECOUTE)

            live_cfg = self.config_manager.config
            vad.energy_threshold = live_cfg.vad_energy_threshold
            vad.min_speech_seconds = live_cfg.vad_min_speech_seconds
            vad.silence_duration_seconds = live_cfg.vad_silence_duration_seconds
            vad.max_segment_seconds = live_cfg.vad_max_segment_seconds

            ev = vad.process_frame(frame)
            if ev.speech_started:
                if self._speech_started_cb is not None:
                    try:
                        self._speech_started_cb()
                    except Exception:
                        pass
                if self.state_manager.state in (NeoState.ECOUTE, NeoState.INTERVENTION):
                    self.state_manager.set_state(NeoState.PAROLE_DETECTEE)

            if ev.speech_ended:
                if ev.segment_pcm:
                    self.segment_queue.enqueue(
                        AudioSegment(
                            pcm_bytes=ev.segment_pcm,
                            sample_rate=live_cfg.sample_rate,
                            channels=live_cfg.channels,
                            duration_seconds=ev.duration_seconds,
                        )
                    )
                elif self.state_manager.state == NeoState.PAROLE_DETECTEE:
                    self.state_manager.set_state(
                        NeoState.ECOUTE if self.state_manager.listening_enabled else NeoState.EN_VEILLE
                    )

    def _segment_dispatch_loop(self) -> None:
        while not self._stop_event.is_set():
            segment = self.segment_queue.dequeue(timeout=0.2)
            if segment is None:
                continue
            if self._stop_event.is_set() or self._loop is None or self._segment_callback is None:
                continue

            async def _run_serialized(seg: AudioSegment = segment) -> None:
                async with self._process_lock:
                    if self._segment_callback is not None:
                        await self._segment_callback(seg)

            cfg = self.config_manager.config
            dispatch_timeout = float(cfg.stt_timeout_seconds) + float(cfg.llm_timeout_seconds) + 10.0
            fut = asyncio.run_coroutine_threadsafe(_run_serialized(), self._loop)
            with self._future_lock:
                self._active_future = fut
            try:
                fut.result(timeout=dispatch_timeout)
            except FutureTimeoutError:
                fut.cancel()
            except Exception:
                # Error logging handled cleanly by TranscriptionService / PedagogicalService
                pass
            finally:
                with self._future_lock:
                    self._active_future = None
                if (
                    not self._stop_event.is_set()
                    and self.state_manager.state
                    in (NeoState.TRANSCRIPTION, NeoState.ANALYSE, NeoState.PAROLE_DETECTEE)
                ):
                    self.state_manager.set_state(
                        NeoState.ECOUTE if self.state_manager.listening_enabled else NeoState.EN_VEILLE
                    )
                time.sleep(0.05)

    def stop(self) -> None:
        self._stop_event.set()
        with self._future_lock:
            if self._active_future is not None and not self._active_future.done():
                self._active_future.cancel()
            self._active_future = None
        self.capture.stop()
        self.segment_queue.clear()
        self.state_manager.mic_active = False
        self.state_manager.audio_level = 0.0
        if self.state_manager.state == NeoState.PAROLE_DETECTEE:
            self.state_manager.set_state(NeoState.EN_VEILLE)
        if self._vad_thread and self._vad_thread.is_alive():
            self._vad_thread.join(timeout=1.5)
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.5)
        self._vad_thread = None
        self._worker_thread = None
