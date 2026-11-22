"""Unit tests for Ollama client errors, invalid JSON repair, response clamping, and fallback."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from app.ai.model_manager import ModelManager
from app.ai.ollama_client import OllamaClient
from app.ai.response_parser import ResponseParser
from app.config.config_manager import ConfigManager
from app.core.decision_engine import DecisionEngine
from app.core.event_manager import EventManager
from app.core.session_controller import SessionController
from app.core.state_manager import StateManager
from app.services.pedagogical_service import PedagogicalService


def test_response_parser_rejects_invalid_json_and_provides_fallback():
    parsed, err = ResponseParser.parse("Ceci n'est pas du JSON")
    assert parsed is None
    assert err is not None

    fb = ResponseParser.deterministic_fallback(
        "Je ne comprends pas du tout cette notion.",
        explicit_request=False,
    )
    assert fb.event_type == "INCOMPREHENSION"
    assert fb.should_intervene is True


def test_pedagogical_service_handles_ollama_unavailable_and_invalid_json(tmp_path: Path):
    cfg_mgr = ConfigManager(config_path=tmp_path / "cfg.json")
    cfg_mgr.update({"ollama_model": "llama3.2:1b", "ai_enabled": True, "mode": "ACTIF"})

    state = StateManager()
    events = EventManager()
    decision = DecisionEngine()
    ctrl = SessionController(cfg_mgr, state, events)
    ollama = OllamaClient("http://127.0.0.1:11434")
    model_mgr = ModelManager(cfg_mgr, ollama)

    # 1. Invalid JSON -> single repair -> deterministic fallback (no retry loop!)
    ollama.generate_json = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            ("pas json du tout", 25),
            ("toujours pas json", 30),
        ]
    )

    svc = PedagogicalService(
        config_manager=cfg_mgr,
        state_manager=state,
        event_manager=events,
        decision_engine=decision,
        session_controller=ctrl,
        ollama_client=ollama,
        model_manager=model_mgr,
    )

    res = asyncio.run(
        svc.process_transcript(
            transcript="Je ne comprends pas la différence entre ces deux concepts.",
            speaker="Apprenant",
        )
    )
    assert ollama.generate_json.call_count == 2  # initial + max 1 repair
    assert res["intervened"] is True

    # 2. Ollama timeout / unavailable -> clean fallback without crash
    state.reset_session_memory()
    ollama.generate_json = AsyncMock(side_effect=TimeoutError("Timeout Ollama"))  # type: ignore[method-assign]
    res2 = asyncio.run(
        svc.process_transcript(
            transcript="Pourquoi cette erreur survient-elle ?",
            speaker="Apprenant",
            explicit_trainer_request=True,
        )
    )
    assert res2["intervened"] is True
    assert state.active_proposal is not None


def test_ollama_overlong_response_is_clamped(tmp_path: Path):
    cfg_mgr = ConfigManager(config_path=tmp_path / "cfg.json")
    cfg_mgr.update({"ollama_model": "qwen2.5:1.5b", "max_response_sentences": 2, "max_response_chars": 160})

    state = StateManager()
    events = EventManager()
    decision = DecisionEngine()
    ctrl = SessionController(cfg_mgr, state, events)
    ollama = OllamaClient()
    model_mgr = ModelManager(cfg_mgr, ollama)

    long_json = (
        '{"event_type":"QUESTION","analysis":"Question sur HTTP.","should_intervene":true,'
        '"intervention_type":"Reformulation","is_off_topic":false,"is_uncertain":false,'
        '"confidence":0.9,"private_trainer_note":"Note courte.",'
        '"learner_response":"Première phrase claire. Deuxième phrase concise. Troisième phrase à couper. Quatrième phrase à couper."}'
    )
    ollama.generate_json = AsyncMock(return_value=(long_json, 45))  # type: ignore[method-assign]

    svc = PedagogicalService(
        config_manager=cfg_mgr,
        state_manager=state,
        event_manager=events,
        decision_engine=decision,
        session_controller=ctrl,
        ollama_client=ollama,
        model_manager=model_mgr,
    )
    res = asyncio.run(svc.process_transcript(transcript="À quoi sert le code 422 ?"))
    assert res["intervened"] is True
    assert "Troisième phrase" not in res["proposal"]["learner_response"]
