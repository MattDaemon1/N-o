"""Transcription service managing STT timeout, error handling, and WAV cleanup."""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.audio.segmentation import AudioSegment, SegmentQueueManager
from app.audio.stt import FasterWhisperSTT, TranscriptionResult
from app.config.config_manager import ConfigManager
from app.core.event_manager import EventManager
from app.core.state_manager import NeoState, StateManager


class TranscriptionService:
    """Runs Faster-Whisper transcription on a single audio segment and deletes temp WAV."""

    def __init__(
        self,
        config_manager: ConfigManager,
        state_manager: StateManager,
        event_manager: EventManager,
        segment_queue: SegmentQueueManager,
        stt: FasterWhisperSTT,
    ) -> None:
        self.config_manager = config_manager
        self.state_manager = state_manager
        self.event_manager = event_manager
        self.segment_queue = segment_queue
        self.stt = stt

    async def transcribe_segment(self, segment: AudioSegment) -> TranscriptionResult:
        cfg = self.config_manager.config
        self.state_manager.set_state(NeoState.TRANSCRIPTION)
        wav_path: Path | None = None

        try:
            wav_path = self.segment_queue.write_temp_wav(segment)
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    self.stt.transcribe_wav,
                    wav_path,
                    model_name=cfg.stt_model,
                    compute_type=cfg.stt_compute_type,
                    language=cfg.stt_language,
                ),
                timeout=cfg.stt_timeout_seconds,
            )
            self.state_manager.metrics.segments_processed += 1
            self.state_manager.metrics.last_transcription_ms = result.duration_ms
            if result.error:
                self.event_manager.add(
                    kind="error",
                    event_type="STT_ERROR",
                    error=result.error,
                    transcription_ms=result.duration_ms,
                )
            return result
        except asyncio.TimeoutError:
            err = f"Timeout STT dépassé ({cfg.stt_timeout_seconds} s)."
            self.state_manager.metrics.errors_count += 1
            self.event_manager.add(kind="error", event_type="STT_TIMEOUT", error=err)
            return TranscriptionResult(
                text="",
                is_empty=True,
                is_uncertain=True,
                avg_logprob=-99.0,
                duration_ms=int(cfg.stt_timeout_seconds * 1000),
                error=err,
            )
        except Exception as exc:
            err = f"Erreur de transcription : {exc}"
            self.state_manager.metrics.errors_count += 1
            self.event_manager.add(kind="error", event_type="STT_EXCEPTION", error=err)
            return TranscriptionResult(
                text="",
                is_empty=True,
                is_uncertain=True,
                avg_logprob=-99.0,
                duration_ms=0,
                error=err,
            )
        finally:
            self.segment_queue.delete_temp_wav(
                wav_path,
                keep_diagnostic=cfg.privacy.keep_audio_diagnostic,
            )
