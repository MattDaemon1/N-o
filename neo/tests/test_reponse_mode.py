"""Targeted tests (A-I) for REPONSE direct voice-assistant mode."""

from __future__ import annotations

import asyncio
import json
import struct
import time
from pathlib import Path
from unittest.mock import AsyncMock

from app.ai.model_manager import ModelManager
from app.ai.ollama_client import OllamaClient
from app.ai.response_parser import ResponseParser
from app.config.config_manager import ConfigManager
from app.core.behavior_engine import BehaviorEngine
from app.core.event_manager import EventManager
from app.core.session_controller import SessionController
from app.core.state_manager import NeoState, StateManager
from app.runtime import NeoRuntime
from app.services.pedagogical_service import PedagogicalService
from app.services.tts_service import TTSService
from app.tts.engine import PiperTTSEngine, SynthesizedAudio
from app.tts.voice_manager import VoiceManager


def _pcm(amplitude: int = 300, samples: int = 400) -> bytes:
    return struct.pack(f"<{samples}h", *([amplitude] * samples))


def _build_reponse_stack(tmp_path: Path, *, tts_enabled: bool = True, vocal_mode: str = "ASSISTANT"):
    cfg_mgr = ConfigManager(config_path=tmp_path / "dashboard_config.json")
    cfg_mgr.update(
        {
            "mode": "REPONSE",
            "ai_enabled": True,
            "ollama_model": "gemma3:1b",
            "tts_enabled": tts_enabled,
            "vocal_mode": vocal_mode,
            "tts_delay_ms": 0,
        }
    )
    state = StateManager()
    events = EventManager(max_events=100)
    behavior = BehaviorEngine()
    ctrl = SessionController(cfg_mgr, state, events)
    ollama = OllamaClient("http://127.0.0.1:11434")
    mm = ModelManager(cfg_mgr, ollama)

    voices_dir = tmp_path / "voices"
    voices_dir.mkdir(parents=True, exist_ok=True)
    (voices_dir / "fr_FR-siwis-medium.onnx").write_bytes(b"ONNX" * 128)
    (voices_dir / "fr_FR-siwis-medium.onnx.json").write_text(
        json.dumps({"audio": {"sample_rate": 22050}}),
        encoding="utf-8",
    )
    vm = VoiceManager(voices_dir=voices_dir)
    engine = PiperTTSEngine(voice_manager=vm, tools_dir=tmp_path / "tools")
    engine.get_backend_info = lambda: {  # type: ignore[method-assign]
        "available": True,
        "backend": "mock_piper",
        "python_piper_installed": True,
        "piper_binary_path": "",
        "model_loaded": False,
        "loaded_voice": "",
    }
    engine.synthesize_pcm = lambda **_kw: SynthesizedAudio(  # type: ignore[method-assign]
        pcm_int16=_pcm(), sample_rate=16000, duration_ms=5
    )
    tts = TTSService(
        config_manager=cfg_mgr,
        state_manager=state,
        event_manager=events,
        voice_manager=vm,
        engine=engine,
    )
    tts.worker._play_pcm_chunked = lambda _p, _sr: (False, None)  # type: ignore[method-assign]
    ctrl.register_tts_hook(tts.interrupt)

    ped = PedagogicalService(
        config_manager=cfg_mgr,
        state_manager=state,
        event_manager=events,
        behavior_engine=behavior,
        session_controller=ctrl,
        ollama_client=ollama,
        model_manager=mm,
        tts_service=tts,
    )
    return cfg_mgr, state, events, ctrl, ollama, tts, ped


def test_reponse_simple_question_no_transcript_no_analysis_and_tts(tmp_path: Path, monkeypatch):
    """Covers tests A, B, and C: direct question -> LLM -> display/TTS, zero transcript/analysis/proposal."""
    _, state, events, _, ollama, tts, ped = _build_reponse_stack(tmp_path, tts_enabled=True, vocal_mode="ASSISTANT")
    try:
        # Ensure pedagogical parser/fallback are NEVER invoked in REPONSE mode
        monkeypatch.setattr(
            ResponseParser,
            "parse",
            staticmethod(lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("ResponseParser.parse called"))),
        )
        monkeypatch.setattr(
            ResponseParser,
            "deterministic_fallback",
            staticmethod(lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("deterministic_fallback called"))),
        )

        expected_answer = "La capitale de l'Italie est Rome."
        ollama.generate_json = AsyncMock(side_effect=AssertionError("generate_json must not be called"))  # type: ignore[method-assign]
        ollama.generate_text = AsyncMock(return_value=(expected_answer, 22))  # type: ignore[method-assign]

        question = "Quelle est la capitale de l'Italie ?"
        res = asyncio.run(
            ped.process_transcript(
                transcript=question,
                speaker="Apprenant",
                is_simulated=False,
            )
        )

        # Wait briefly for TTS worker to finish mock playback
        deadline = time.monotonic() + 1.0
        while tts.worker.is_busy() and time.monotonic() < deadline:
            time.sleep(0.005)

        # A. Simple question answered & spoken via TTS without ParsedPedagogicalResponse
        assert ollama.generate_text.call_count == 1
        assert res["intervened"] is True
        assert res["response"] == expected_answer
        assert res["proposal"] is None
        assert res["tts"] is not None and res["tts"]["spoken"] is True
        assert state.last_direct_response is not None
        assert state.last_direct_response["text"] == expected_answer
        assert state.last_direct_response["is_error"] is False

        # B. STT transcript NOT exposed in visible session history or memory
        assert state.get_recent_transcripts() == []
        assert state.get_asked_questions() == []
        evts = events.list_events(limit=20)
        assert all(e["transcript"] == "" for e in evts)
        assert all(question not in (e["proposal"] or "") for e in evts)

        # C. Zero pedagogical analysis, private note, classification, or proposal
        assert state.active_proposal is None
        assert state.state != NeoState.PROPOSITION
        assert all(e["analysis"] == "" for e in evts)
        assert all(
            e["event_type"] not in (
                "QUESTION",
                "INCOMPREHENSION",
                "CONFUSION",
                "REPETITION",
                "ECHANGE_NORMAL",
                "DEMANDE_FORMATEUR",
                "HORS_SUJET",
            )
            for e in evts
        )
        assert any(e["kind"] == "response" and e["event_type"] == "REPONSE" and e["proposal"] == expected_answer for e in evts)
    finally:
        tts.worker.stop_worker()


def test_reponse_empty_noise_and_echo_ignored(tmp_path: Path):
    """Covers tests D and E: empty/noise/too-short transcripts and TTS self-echo never call LLM."""
    _, state, events, _, ollama, tts, ped = _build_reponse_stack(tmp_path)
    try:
        ollama.generate_text = AsyncMock(return_value=("Ne devrait pas être appelé.", 10))  # type: ignore[method-assign]

        # D. Empty, noise, and overly short/incomplete fragments
        for empty_or_short in ("   ", "", "Merci d'avoir regardé", "Euh...", "Oui voilà", "Explique-moi"):
            res = asyncio.run(ped.process_transcript(transcript=empty_or_short, is_simulated=False))
            assert res["intervened"] is False
        assert ollama.generate_text.call_count == 0

        # E. Probable TTS echo ignored silently
        spoken = "Un modèle open source publie ses poids pour une exécution locale."
        state.set_tts_status(tts_state="LECTURE", speaking=True)
        state.record_tts_spoken(spoken)
        res_echo = asyncio.run(ped.process_transcript(transcript=spoken, is_simulated=False))
        assert res_echo["intervened"] is False
        assert ollama.generate_text.call_count == 0
        assert all(e["transcript"] == "" for e in events.list_events(limit=10))
    finally:
        tts.worker.stop_worker()


def test_reponse_successive_vad_segments_avoid_duplicate_answers(tmp_path: Path):
    """Covers test F: VAD-split continuation segments only produce one answer per question, while distinct questions still work."""
    _, _, _, _, ollama, tts, ped = _build_reponse_stack(tmp_path, tts_enabled=False)
    try:
        ollama.generate_text = AsyncMock(  # type: ignore[method-assign]
            side_effect=[
                ("La capitale de l'Italie est Rome.", 15),
                ("Un RAG combine recherche documentaire et génération de texte.", 18),
            ]
        )

        # Split question 1 across two VAD segments
        r1 = asyncio.run(ped.process_transcript(transcript="Quelle est la capitale", is_simulated=False))
        r2 = asyncio.run(ped.process_transcript(transcript="de l'Italie ?", is_simulated=False))
        assert r1["intervened"] is True
        assert r2["intervened"] is False
        assert ollama.generate_text.call_count == 1

        # High-overlap repeat right after is also ignored
        r_dup = asyncio.run(ped.process_transcript(transcript="la capitale de l'Italie", is_simulated=False))
        assert r_dup["intervened"] is False
        assert ollama.generate_text.call_count == 1

        # A genuinely new complete question IS answered
        r3 = asyncio.run(
            ped.process_transcript(
                transcript="Explique-moi le fonctionnement d'un RAG.",
                is_simulated=False,
            )
        )
        assert r3["intervened"] is True
        assert ollama.generate_text.call_count == 2
    finally:
        tts.worker.stop_worker()


def test_reponse_llm_error_graceful_without_pedagogical_fallback(tmp_path: Path, monkeypatch):
    """Covers test G: Ollama error shows simple unavailable message, logs technical error, and never falls back to pedagogical mode."""
    _, state, events, _, ollama, tts, ped = _build_reponse_stack(tmp_path, tts_enabled=False)
    try:
        monkeypatch.setattr(
            ResponseParser,
            "deterministic_fallback",
            staticmethod(lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("deterministic_fallback called"))),
        )
        ollama.generate_text = AsyncMock(side_effect=TimeoutError("Connexion http://127.0.0.1:11434 expirée"))  # type: ignore[method-assign]

        res = asyncio.run(
            ped.process_transcript(
                transcript="Comment fonctionne le référencement naturel ?",
                is_simulated=False,
            )
        )
        assert res["intervened"] is False
        assert state.active_proposal is None
        assert state.last_direct_response is not None
        assert state.last_direct_response["is_error"] is True
        assert "127.0.0.1" not in state.last_direct_response["text"]
        assert "TimeoutError" not in state.last_direct_response["text"]

        err_events = [e for e in events.list_events(limit=10) if e["event_type"] == "REPONSE_ERREUR"]
        assert len(err_events) == 1
        assert err_events[0]["transcript"] == ""
        assert "Erreur Ollama en mode REPONSE" in err_events[0]["error"]
    finally:
        tts.worker.stop_worker()


def test_reponse_interruption_tts_and_inflight_llm(tmp_path: Path):
    """Covers test H: STOP VOIX / vocal interruption and mid-LLM cancellation work cleanly in REPONSE mode."""
    _, state, _, ctrl, ollama, tts, ped = _build_reponse_stack(tmp_path, tts_enabled=True, vocal_mode="AUTONOME")
    try:
        # 1. Mid-playback TTS interruption
        tts.worker._play_pcm_chunked = lambda _p, _sr: (  # type: ignore[method-assign]
            time.sleep(0.06) or (tts.worker._cancel_event.is_set(), None)
        )
        ollama.generate_text = AsyncMock(return_value=("Voici trois exemples concrets en entreprise.", 12))  # type: ignore[method-assign]
        res = asyncio.run(
            ped.process_transcript(
                transcript="Donne-moi trois exemples d'utilisation de l'IA en entreprise.",
                is_simulated=False,
            )
        )
        assert res["tts"]["spoken"] is True
        time.sleep(0.02)
        assert tts.interrupt("STOP VOIX") is True
        deadline = time.monotonic() + 1.0
        while tts.worker.is_busy() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert tts.worker.is_busy() is False

        # 2. Mid-LLM interruption cancels pending direct response cleanly
        state.last_direct_response = None

        async def _slow_llm(**_kw):
            await asyncio.sleep(0.5)
            return ("Réponse tardive", 500)

        ollama.generate_text = _slow_llm  # type: ignore[method-assign]

        async def _run_and_interrupt():
            task = asyncio.create_task(
                ped.process_transcript(
                    transcript="Peux-tu reformuler cette phrase ?",
                    is_simulated=False,
                )
            )
            await asyncio.sleep(0.03)
            ctrl.interrupt("Interruption test")
            return await task

        res_int = asyncio.run(_run_and_interrupt())
        assert res_int["intervened"] is False
        assert state.last_direct_response is None
    finally:
        tts.worker.stop_worker()


def test_reponse_mode_persistence_across_restart(tmp_path: Path):
    """Covers test I: REPONSE mode is persisted to dashboard_config.json and restored cleanly."""
    cfg_path = tmp_path / "dashboard_config.json"
    rt1 = NeoRuntime(config_path=cfg_path)
    try:
        updated = rt1.apply_config_update({"mode": "REPONSE"})
        assert updated.mode == "REPONSE"
        assert rt1.state_manager.state == NeoState.EN_VEILLE
    finally:
        rt1.tts_service.worker.stop_worker()

    rt2 = NeoRuntime(config_path=cfg_path)
    try:
        assert rt2.config_manager.config.mode == "REPONSE"
        assert rt2.state_manager.state == NeoState.EN_VEILLE
    finally:
        rt2.tts_service.worker.stop_worker()
