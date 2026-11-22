"""Automated unit & integration tests for local Piper TTS, vocal modes, and interruption priority."""

from __future__ import annotations

import asyncio
import json
import struct
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from app.audio.capture import AudioCapture
from app.audio.pipeline import AudioPipeline
from app.audio.segmentation import SegmentQueueManager
from app.config.config_manager import ConfigManager
from app.core.decision_engine import DecisionEngine
from app.core.event_manager import EventManager
from app.core.session_controller import SessionController
from app.core.state_manager import NeoState, StateManager, VocalMode
from app.services.pedagogical_service import PedagogicalService
from app.services.tts_service import TTSService
from app.tts.engine import PiperTTSEngine, SynthesizedAudio
from app.tts.speaker_worker import SpeakerWorker
from app.tts.text_limiter import SpeechTextSanitizer
from app.tts.voice_manager import VoiceManager


def _create_dummy_voice(voices_dir: Path, voice_id: str = "fr_FR-siwis-medium", sample_rate: int = 22050) -> None:
    voices_dir.mkdir(parents=True, exist_ok=True)
    (voices_dir / f"{voice_id}.onnx").write_bytes(b"ONNX" * 256)  # >= 1024 bytes valid dummy
    (voices_dir / f"{voice_id}.onnx.json").write_text(
        json.dumps({"audio": {"sample_rate": sample_rate}}),
        encoding="utf-8",
    )


def _make_tts_service(
    tmp_path: Path,
    *,
    with_valid_voice: bool = True,
    backend_available: bool = True,
) -> tuple[ConfigManager, StateManager, EventManager, VoiceManager, PiperTTSEngine, TTSService]:
    cfg_mgr = ConfigManager(config_path=tmp_path / "cfg.json")
    cfg_mgr.update({"tts_enabled": True, "vocal_mode": "AUTONOME", "tts_delay_ms": 0})
    state = StateManager()
    events = EventManager()
    voices_dir = tmp_path / "voices"
    if with_valid_voice:
        _create_dummy_voice(voices_dir, "fr_FR-siwis-medium")
    vm = VoiceManager(voices_dir=voices_dir)
    engine = PiperTTSEngine(voice_manager=vm, tools_dir=tmp_path / "tools")
    if backend_available:
        engine.get_backend_info = lambda: {  # type: ignore[method-assign]
            "available": True,
            "backend": "mock_piper",
            "python_piper_installed": True,
            "piper_binary_path": "",
            "model_loaded": False,
            "loaded_voice": "",
        }
    svc = TTSService(
        config_manager=cfg_mgr,
        state_manager=state,
        event_manager=events,
        voice_manager=vm,
        engine=engine,
    )
    return cfg_mgr, state, events, vm, engine, svc


def test_speech_text_sanitizer_empty_and_overlong():
    assert SpeechTextSanitizer.sanitize("") == ""
    assert SpeechTextSanitizer.sanitize("   ... --- *** ") == ""

    md = "## Titre\n- **Point un** : explication avec `code`.\n- Point deux. Point trois. Point quatre."
    clean = SpeechTextSanitizer.sanitize(md, max_chars=120, max_sentences=2)
    assert "**" not in clean
    assert "`" not in clean
    assert len(clean) <= 120
    assert "Point quatre" not in clean


def test_missing_and_invalid_voice_model_handled_cleanly(tmp_path: Path):
    cfg_mgr, state, events, vm, engine, svc = _make_tts_service(tmp_path, with_valid_voice=False)
    try:
        res_missing = svc.test_voice("Bonjour")
        assert res_missing["spoken"] is False
        assert "absent" in (res_missing.get("error") or "").lower()

        # Corrupted / truncated .onnx file + bad JSON
        bad_dir = tmp_path / "voices"
        bad_dir.mkdir(parents=True, exist_ok=True)
        (bad_dir / "fr_FR-siwis-medium.onnx").write_bytes(b"corrupt")
        (bad_dir / "fr_FR-siwis-medium.onnx.json").write_text("{bad json", encoding="utf-8")

        res_bad = svc.test_voice("Bonjour")
        assert res_bad["spoken"] is False
        assert res_bad.get("error") is not None
        assert state.tts_state == "ERREUR"
    finally:
        svc.worker.stop_worker()


def test_empty_text_is_ignored_without_synthesis(tmp_path: Path):
    cfg_mgr, state, events, vm, engine, svc = _make_tts_service(tmp_path)
    try:
        res = svc.speak_on_trainer_request("   \n\t  ")
        assert res["spoken"] is False
        assert state.tts_speaking is False
    finally:
        svc.worker.stop_worker()


def test_voice_generation_and_error_policies(tmp_path: Path):
    cfg_mgr, state, events, vm, engine, svc = _make_tts_service(tmp_path)
    try:
        pcm = struct.pack("<800h", *([500] * 800))
        engine.synthesize_pcm = lambda **_kw: SynthesizedAudio(pcm_int16=pcm, sample_rate=16000, duration_ms=12)  # type: ignore[method-assign]
        svc.worker._play_pcm_chunked = lambda _p, _sr: (False, None)  # type: ignore[method-assign]

        res = svc.test_voice("Bonjour, voici un exemple simple.")
        assert res["spoken"] is True
        deadline = time.monotonic() + 2.0
        while svc.worker.is_busy() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert state.metrics.tts_spoken_count == 1
        assert state.tts_state == "PRET"

        # Synthesis error with silent_fallback -> last_error stays None
        cfg_mgr.update({"tts_error_policy": "silent_fallback"})
        state.last_error = None
        engine.synthesize_pcm = lambda **_kw: SynthesizedAudio(  # type: ignore[method-assign]
            pcm_int16=b"", sample_rate=16000, duration_ms=5, error="Erreur ONNX simulée"
        )
        svc.test_voice("Test erreur silencieuse")
        deadline = time.monotonic() + 2.0
        while svc.worker.is_busy() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert state.tts_last_error == "Erreur ONNX simulée"
        assert state.last_error is None

        # Synthesis error with notify_error -> last_error populated without crashing
        cfg_mgr.update({"tts_error_policy": "notify_error"})
        svc.test_voice("Test erreur visible")
        deadline = time.monotonic() + 2.0
        while svc.worker.is_busy() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert state.last_error is not None and "Erreur ONNX simulée" in state.last_error
    finally:
        svc.worker.stop_worker()


def test_interruption_mid_playback_and_clean_restart(tmp_path: Path):
    cfg_mgr, state, events, vm, engine, svc = _make_tts_service(tmp_path)
    try:
        pcm = struct.pack("<1600h", *([400] * 1600))
        engine.synthesize_pcm = lambda **_kw: SynthesizedAudio(pcm_int16=pcm, sample_rate=16000, duration_ms=5)  # type: ignore[method-assign]

        playback_started = False

        def slow_play(_pcm: bytes, _sr: int):
            nonlocal playback_started
            playback_started = True
            for _ in range(40):
                if svc.worker._cancel_event.is_set():
                    return True, None
                time.sleep(0.02)
            return False, None

        svc.worker._play_pcm_chunked = slow_play  # type: ignore[method-assign]
        svc.speak_on_trainer_request("Première explication longue pour tester l'arrêt immédiat.")

        deadline = time.monotonic() + 2.0
        while not playback_started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert playback_started is True

        interrupted = svc.interrupt("STOP VOIX")
        assert interrupted is True

        deadline = time.monotonic() + 1.5
        while svc.worker.is_busy() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert svc.worker.is_busy() is False
        assert state.metrics.tts_interrupted_count >= 1

        # Clean restart after interruption
        svc.worker._play_pcm_chunked = lambda _p, _sr: (False, None)  # type: ignore[method-assign]
        res2 = svc.speak_on_trainer_request("Deuxième explication après redémarrage.")
        assert res2["spoken"] is True
        deadline = time.monotonic() + 1.5
        while svc.worker.is_busy() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert state.tts_state == "PRET"
    finally:
        svc.worker.stop_worker()


def test_no_uncontrolled_voice_queue_single_slot_replaces_pending(tmp_path: Path):
    cfg_mgr, state, events, vm, engine, svc = _make_tts_service(tmp_path)
    try:
        spoken_order: list[str] = []
        pcm = struct.pack("<400h", *([300] * 400))
        engine.synthesize_pcm = lambda **kw: SynthesizedAudio(pcm_int16=pcm, sample_rate=16000, duration_ms=5)  # type: ignore[method-assign]
        svc.worker._play_pcm_chunked = lambda _p, _sr: (False, None)  # type: ignore[method-assign]

        # Delay first message and enqueue second quickly: only the latest replacement runs (no backlog!)
        cfg_mgr.update({"tts_delay_ms": 200})
        svc.speak_autonomous(text="Ancien message obsolète.", behavior_allowed=True)
        svc.speak_on_trainer_request("Nouveau message prioritaire.")

        deadline = time.monotonic() + 2.0
        while svc.worker.is_busy() and time.monotonic() < deadline:
            time.sleep(0.02)

        assert state.tts_last_spoken_text == "Nouveau message prioritaire."
        assert state.metrics.tts_spoken_count == 1
    finally:
        svc.worker.stop_worker()


def test_vocal_mode_transitions_and_disabling_tts(tmp_path: Path):
    cfg_mgr, state, events, vm, engine, svc = _make_tts_service(tmp_path)
    try:
        pcm = struct.pack("<400h", *([300] * 400))
        engine.synthesize_pcm = lambda **_kw: SynthesizedAudio(pcm_int16=pcm, sample_rate=16000, duration_ms=5)  # type: ignore[method-assign]
        svc.worker._play_pcm_chunked = lambda _p, _sr: (False, None)  # type: ignore[method-assign]

        # SILENCIEUX blocks both autonomous and trainer button
        cfg_mgr.update({"vocal_mode": VocalMode.SILENCIEUX.value})
        assert svc.speak_autonomous(text="Auto", behavior_allowed=True)["spoken"] is False
        assert svc.speak_on_trainer_request("Bouton")["spoken"] is False

        # SILENCIEUX -> ASSISTANT: trainer button works, autonomous stays silent
        cfg_mgr.update({"vocal_mode": VocalMode.ASSISTANT.value})
        assert svc.speak_autonomous(text="Auto", behavior_allowed=True)["spoken"] is False
        assert svc.speak_on_trainer_request("Bouton validé")["spoken"] is True

        deadline = time.monotonic() + 2.0
        while svc.worker.is_busy() and time.monotonic() < deadline:
            time.sleep(0.02)

        # ASSISTANT -> AUTONOME: autonomous allowed when behavior engine approves
        cfg_mgr.update({"vocal_mode": VocalMode.AUTONOME.value})
        assert svc.speak_autonomous(text="Intervention refusée", behavior_allowed=False)["spoken"] is False
        assert svc.speak_autonomous(text="Intervention validée.", behavior_allowed=True)["spoken"] is True

        deadline = time.monotonic() + 2.0
        while svc.worker.is_busy() and time.monotonic() < deadline:
            time.sleep(0.02)

        # Disabling TTS blocks speech and unloads resources cleanly
        cfg_mgr.update({"tts_enabled": False})
        svc.unload_resources()
        assert svc.speak_autonomous(text="Ne doit pas parler", behavior_allowed=True)["spoken"] is False
        assert engine.is_loaded() is False
    finally:
        svc.worker.stop_worker()


def test_trainer_and_vad_speech_interrupt_tts_without_stopping_mic_pipeline(tmp_path: Path):
    cfg_mgr, state, events, vm, engine, svc = _make_tts_service(tmp_path)
    ctrl = SessionController(cfg_mgr, state, events)
    ctrl.register_tts_hook(svc.interrupt)

    pcm = struct.pack("<1600h", *([400] * 1600))
    engine.synthesize_pcm = lambda **_kw: SynthesizedAudio(pcm_int16=pcm, sample_rate=16000, duration_ms=5)  # type: ignore[method-assign]

    def slow_play(_pcm: bytes, _sr: int):
        for _ in range(50):
            if svc.worker._cancel_event.is_set():
                return True, None
            time.sleep(0.02)
        return False, None

    svc.worker._play_pcm_chunked = slow_play  # type: ignore[method-assign]

    cap = AudioCapture()
    sqm = SegmentQueueManager(max_pending=2, temp_dir=tmp_path / "wavs")
    pipeline = AudioPipeline(cfg_mgr, state, cap, sqm)

    # Simulate active mic listening + VAD speech_started hook
    state.session_active = True
    state.listening_enabled = True
    state.mic_active = True
    state.set_state(NeoState.ECOUTE)
    pipeline.bind_speech_started_hook(lambda: svc.interrupt("Apprenant détecté au micro"))

    try:
        # 1. Start speaking, then trainer calls session_controller.interrupt()
        svc.speak_on_trainer_request("NÉO commence une explication.")
        time.sleep(0.08)
        ctrl.interrupt("Formateur reprend la parole")
        deadline = time.monotonic() + 1.5
        while svc.worker.is_busy() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert state.mic_active is True
        assert state.listening_enabled is True
        assert state.state == NeoState.ECOUTE

        # 2. Start speaking again, then simulated VAD speech_started fires -> TTS stops, mic stays active!
        svc.speak_on_trainer_request("NÉO reprend une autre explication.")
        time.sleep(0.08)
        assert pipeline._speech_started_cb is not None
        pipeline._speech_started_cb()
        deadline = time.monotonic() + 1.5
        while svc.worker.is_busy() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert state.mic_active is True
        assert state.listening_enabled is True
        assert state.metrics.tts_interrupted_count >= 2
    finally:
        pipeline.stop()
        svc.worker.stop_worker()


def test_self_echo_filter_ignores_neos_own_voice(tmp_path: Path):
    cfg_mgr = ConfigManager(config_path=tmp_path / "cfg.json")
    state = StateManager()
    events = EventManager()
    decision = DecisionEngine()
    ctrl = SessionController(cfg_mgr, state, events)

    from app.ai.model_manager import ModelManager
    from app.ai.ollama_client import OllamaClient

    ollama = OllamaClient()
    mm = ModelManager(cfg_mgr, ollama)
    ped = PedagogicalService(
        config_manager=cfg_mgr,
        state_manager=state,
        event_manager=events,
        decision_engine=decision,
        session_controller=ctrl,
        ollama_client=ollama,
        model_manager=mm,
    )

    state.record_tts_spoken("PUT remplace toute la ressource tandis que PATCH modifie un seul champ.")
    res = asyncio.run(
        ped.process_transcript(
            transcript="PUT remplace toute la ressource tandis que PATCH modifie un seul champ",
            speaker="Apprenant",
            is_simulated=False,
        )
    )
    assert res["intervened"] is False
    assert "Écho acoustique" in res["decision"]


@pytest.mark.real_hardware
def test_real_piper_tts_if_installed():
    """Optional real-hardware check: runs only when Piper and a French voice exist locally."""
    vm = VoiceManager()
    engine = PiperTTSEngine(voice_manager=vm)
    info = engine.get_backend_info()
    installed = vm.list_installed_voice_ids()
    if not info["available"] or not installed:
        pytest.skip("Piper TTS ou modèle vocal français non installé sur cette machine.")
    audio = engine.synthesize_pcm(
        text="Bonjour, test matériel réel de la voix française de NÉO.",
        voice_id=installed[0],
    )
    assert audio.error is None
    assert len(audio.pcm_int16) > 1000
