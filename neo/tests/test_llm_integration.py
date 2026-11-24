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


def test_parse_valid_analysis_and_overlong_analysis_preserves_learner_response():
    import json

    # A. Valid analysis <= 320 characters is preserved verbatim
    short_analysis = "L'apprenant demande la différence entre HTTP 400 et HTTP 422."
    learner_text = (
        "Le code 400 signale une syntaxe JSON cassée, alors que le code 422 "
        "indique un JSON bien formé mais invalide sur le plan métier."
    )
    raw_ok = json.dumps(
        {
            "event_type": "QUESTION",
            "analysis": short_analysis,
            "should_intervene": True,
            "intervention_type": "Explication simplifiée",
            "is_off_topic": False,
            "is_uncertain": False,
            "confidence": 0.91,
            "private_trainer_note": "Rappeler l'exemple email.",
            "learner_response": learner_text,
        }
    )
    parsed_ok, err_ok = ResponseParser.parse(raw_ok)
    assert err_ok is None
    assert parsed_ok is not None
    assert parsed_ok.analysis == short_analysis
    assert parsed_ok.learner_response == learner_text

    # B & H. Overlong internal analysis (> 320 chars) is deterministically bounded without altering learner_response
    long_analysis = " ".join(["Analyse pédagogique détaillée très longue sur le contexte technique"] * 10)
    assert len(long_analysis) > 400
    raw_long_analysis = json.dumps(
        {
            "event_type": "QUESTION",
            "analysis": long_analysis,
            "should_intervene": True,
            "intervention_type": "Analogie",
            "is_off_topic": False,
            "is_uncertain": False,
            "confidence": 0.88,
            "private_trainer_note": "Note formateur intacte.",
            "learner_response": learner_text,
        }
    )
    parsed_bounded, err_bounded = ResponseParser.parse(raw_long_analysis)
    assert err_bounded is None
    assert parsed_bounded is not None
    assert len(parsed_bounded.analysis) <= 320
    assert parsed_bounded.analysis.endswith("…")
    assert parsed_bounded.learner_response == learner_text
    assert parsed_bounded.private_trainer_note == "Note formateur intacte."


def test_deterministic_fallback_with_huge_reason_and_schema_rejection():
    import json

    # C. deterministic_fallback must stay valid even with multi-thousand-character reason across all branches
    huge_reason = "Erreur détaillée très verbeuse " * 150  # ~4500 chars
    for sample_transcript in (
        "Je ne comprends pas du tout cet exercice.",
        "Pourquoi cette route renvoie 422 ?",
        "D'accord, on continue sur le module suivant.",
    ):
        fb = ResponseParser.deterministic_fallback(
            sample_transcript,
            explicit_request=True,
            reason=huge_reason,
        )
        assert len(fb.analysis) <= 320
        assert fb.analysis.endswith("…")

    # D. Invalid intervention_type or out-of-range confidence is strictly rejected (never silently fixed)
    bad_schema = json.dumps(
        {
            "event_type": "QUESTION",
            "analysis": "Analyse courte.",
            "should_intervene": True,
            "intervention_type": "TypeInexistant",
            "confidence": 0.8,
            "learner_response": "Texte",
        }
    )
    parsed_bad, err_bad = ResponseParser.parse(bad_schema)
    assert parsed_bad is None
    assert err_bad is not None
    assert err_bad.startswith("Validation schéma LLM")


def test_repair_double_failure_ollama_error_distinction_and_full_log_error(tmp_path: Path):
    import json

    cfg_mgr = ConfigManager(config_path=tmp_path / "cfg.json")
    cfg_mgr.update({"ollama_model": "llama3.2:1b", "ai_enabled": True, "mode": "ACTIF"})

    state = StateManager()
    events = EventManager()
    decision = DecisionEngine()
    ctrl = SessionController(cfg_mgr, state, events)
    ollama = OllamaClient("http://127.0.0.1:11434")
    model_mgr = ModelManager(cfg_mgr, ollama)

    svc = PedagogicalService(
        config_manager=cfg_mgr,
        state_manager=state,
        event_manager=events,
        decision_engine=decision,
        session_controller=ctrl,
        ollama_client=ollama,
        model_manager=model_mgr,
    )

    # E & G. Double schema failure produces verbose error (> 320 chars): fallback succeeds cleanly,
    # analysis is <= 320, LLM_FALLBACK.error keeps full diagnostic, and NOT mislabeled as Ollama indisponible.
    invalid_schema_json = json.dumps(
        {
            "event_type": "QUESTION",
            "analysis": "Analyse courte.",
            "should_intervene": True,
            "intervention_type": "InvalidePourProvoquerValidationError_" + ("X" * 120),
            "confidence": 0.9,
            "learner_response": "Texte test",
        }
    )
    ollama.generate_json = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            ("Pas du json valide", 20),
            (invalid_schema_json, 25),
        ]
    )
    res_schema = asyncio.run(
        svc.process_transcript(
            transcript="Pourquoi la validation échoue ici ?",
            speaker="Formateur",
            explicit_trainer_request=True,
        )
    )
    assert res_schema["intervened"] is True
    assert len(res_schema["proposal"]["analysis"]) <= 320
    assert "Ollama indisponible" not in res_schema["proposal"]["analysis"]

    fallback_events = [e for e in events.list_events(limit=10) if e["event_type"] == "LLM_FALLBACK"]
    assert len(fallback_events) == 1
    logged_err = fallback_events[0]["error"]
    assert "Échec après réparation LLM" in logged_err
    assert "JSON invalide" in logged_err
    assert "Validation schéma LLM" in logged_err
    assert "Ollama indisponible" not in logged_err
    assert "string_too_long" not in logged_err

    # F. Real Ollama network/timeout exception is classified as Ollama indisponible (not parsing error)
    events.clear()
    state.reset_session_memory()
    long_network_exc = RuntimeError("Connexion refusée vers 127.0.0.1:11434 : " + ("détail réseau " * 30))
    ollama.generate_json = AsyncMock(side_effect=long_network_exc)  # type: ignore[method-assign]
    res_net = asyncio.run(
        svc.process_transcript(
            transcript="Pourquoi Ollama ne répond pas ?",
            speaker="Formateur",
            explicit_trainer_request=True,
        )
    )
    assert res_net["intervened"] is True
    assert len(res_net["proposal"]["analysis"]) <= 320
    assert res_net["proposal"]["analysis"].startswith("Ollama indisponible")
    net_events = [e for e in events.list_events(limit=10) if e["event_type"] == "LLM_FALLBACK"]
    assert len(net_events) == 1
    assert net_events[0]["error"].startswith("Ollama indisponible")
    assert len(net_events[0]["error"]) > 320  # Full untruncated error preserved in log

    # H. Full E2E through PedagogicalService with overlong analysis keeps exact learner_response
    events.clear()
    state.reset_session_memory()
    exact_learner_reply = "Une API REST utilise POST pour créer et PUT pour remplacer une ressource entière."
    valid_with_long_analysis = json.dumps(
        {
            "event_type": "DEMANDE_FORMATEUR",
            "analysis": "Analyse interne verbeuse " * 25,
            "should_intervene": True,
            "intervention_type": "Exemple concret",
            "is_off_topic": False,
            "is_uncertain": False,
            "confidence": 0.95,
            "private_trainer_note": "Clarification directe.",
            "learner_response": exact_learner_reply,
        }
    )
    ollama.generate_json = AsyncMock(return_value=(valid_with_long_analysis, 18))  # type: ignore[method-assign]
    res_e2e = asyncio.run(
        svc.process_transcript(
            transcript="Néo, résume POST vs PUT en une phrase.",
            speaker="Formateur",
            explicit_trainer_request=True,
        )
    )
    assert res_e2e["intervened"] is True
    assert len(res_e2e["proposal"]["analysis"]) <= 320
    assert res_e2e["proposal"]["learner_response"] == exact_learner_reply
    assert [e for e in events.list_events(limit=10) if e["event_type"] == "LLM_FALLBACK"] == []

