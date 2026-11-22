"""Unit tests for AudioCapture, VAD, Segmentation, WAV cleanup, and STT error handling."""

import asyncio
import struct
from pathlib import Path
from unittest.mock import MagicMock

from app.audio.capture import AudioCapture
from app.audio.segmentation import AudioSegment, SegmentQueueManager
from app.audio.stt import FasterWhisperSTT, TranscriptionResult
from app.audio.vad import VoiceActivityDetector
from app.config.config_manager import ConfigManager
from app.core.event_manager import EventManager
from app.core.state_manager import StateManager
from app.services.transcription_service import TranscriptionService


def _make_pcm_frame(amplitude: int, samples: int = 1600) -> bytes:
    return struct.pack(f"<{samples}h", *([amplitude] * samples))


def test_vad_ignores_silence_and_segments_speech():
    vad = VoiceActivityDetector(
        sample_rate=16000,
        energy_threshold=0.02,
        min_speech_seconds=0.3,
        silence_duration_seconds=0.4,
        max_segment_seconds=5.0,
    )
    silent = _make_pcm_frame(0, samples=1600)  # 0.1s
    speech = _make_pcm_frame(4000, samples=1600)  # 0.1s

    # Pure silence -> never triggers
    for _ in range(10):
        ev = vad.process_frame(silent)
        assert ev.speech_started is False
        assert ev.speech_ended is False

    # 0.4s speech followed by 0.5s silence -> emits segment
    started_seen = False
    ended_ev = None
    for _ in range(4):
        ev = vad.process_frame(speech)
        if ev.speech_started:
            started_seen = True
    for _ in range(5):
        ev = vad.process_frame(silent)
        if ev.speech_ended:
            ended_ev = ev
            break

    assert started_seen is True
    assert ended_ev is not None
    assert ended_ev.segment_pcm is not None
    assert len(ended_ev.segment_pcm) > 0


def test_segment_queue_bounded_and_deletes_temp_wav(tmp_path: Path):
    sqm = SegmentQueueManager(max_pending=2, temp_dir=tmp_path)
    seg = AudioSegment(pcm_bytes=_make_pcm_frame(500, 800), sample_rate=16000, channels=1, duration_seconds=0.5)

    sqm.enqueue(seg)
    sqm.enqueue(seg)
    sqm.enqueue(seg)  # drops oldest cleanly
    assert sqm.pending_count() == 2
    assert sqm.dropped_count == 1

    wav_path = sqm.write_temp_wav(seg)
    assert wav_path.exists()
    sqm.delete_temp_wav(wav_path, keep_diagnostic=False)
    assert not wav_path.exists()


def test_audio_capture_handles_missing_or_unplugged_mic(monkeypatch):
    import app.audio.capture as cap_mod

    monkeypatch.setattr(cap_mod, "sd", None)
    cap = AudioCapture()
    devices, err = cap.list_devices()
    assert devices == []
    assert err is not None

    errors: list[str] = []
    ok = cap.start(device_index=0, on_error=errors.append)
    assert ok is False
    assert len(errors) == 1


def test_transcription_service_deletes_wav_on_stt_error_and_timeout(tmp_path: Path):
    cfg_mgr = ConfigManager(config_path=tmp_path / "cfg.json")
    cfg_mgr.update({"stt_timeout_seconds": 3.0})
    state = StateManager()
    events = EventManager()
    sqm = SegmentQueueManager(max_pending=2, temp_dir=tmp_path / "wavs")

    stt = FasterWhisperSTT(cache_dir=tmp_path / "hf")
    stt.transcribe_wav = MagicMock(  # type: ignore[method-assign]
        return_value=TranscriptionResult(
            text="",
            is_empty=True,
            is_uncertain=True,
            avg_logprob=-2.5,
            duration_ms=42,
            error="Erreur STT simulée",
        )
    )

    svc = TranscriptionService(cfg_mgr, state, events, sqm, stt)
    seg = AudioSegment(pcm_bytes=_make_pcm_frame(1000, 1600), sample_rate=16000, channels=1, duration_seconds=0.1)
    res = asyncio.run(svc.transcribe_segment(seg))

    assert res.error == "Erreur STT simulée"
    assert state.metrics.segments_processed == 1
    # Temp WAV must be deleted after processing
    assert list((tmp_path / "wavs").glob("*.wav")) == []


def test_transcription_service_handles_slow_stt_timeout(tmp_path: Path, monkeypatch):
    import time

    cfg_mgr = ConfigManager(config_path=tmp_path / "cfg.json")
    state = StateManager()
    events = EventManager()
    sqm = SegmentQueueManager(max_pending=2, temp_dir=tmp_path / "wavs")
    stt = FasterWhisperSTT(cache_dir=tmp_path / "hf")

    def slow_transcribe(*_args, **_kwargs):
        time.sleep(0.25)
        return TranscriptionResult("ok", False, False, -0.2, 250)

    stt.transcribe_wav = slow_transcribe  # type: ignore[method-assign]
    svc = TranscriptionService(cfg_mgr, state, events, sqm, stt)

    # Force short timeout in test via monkeypatching config value directly
    cfg_mgr.config.stt_timeout_seconds = 0.05
    seg = AudioSegment(pcm_bytes=_make_pcm_frame(1000, 1600), sample_rate=16000, channels=1, duration_seconds=0.1)
    res = asyncio.run(svc.transcribe_segment(seg))

    assert res.error is not None
    assert "Timeout" in res.error
    assert list((tmp_path / "wavs").glob("*.wav")) == []
