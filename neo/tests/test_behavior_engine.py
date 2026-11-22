"""Unit tests for the deterministic BehaviorEngine."""

from app.core.behavior_engine import BehaviorEngine
from app.core.state_manager import BehaviorMode


def test_mode_off_blocks_everything():
    eng = BehaviorEngine()
    pre = eng.evaluate_pre_llm(
        mode=BehaviorMode.OFF,
        transcript="Néo, explique-nous ce concept.",
        stt_uncertain=False,
        explicit_trainer_request=True,
        cooldown_remaining=0,
        asked_questions=[],
        recent_answers=[],
    )
    assert pre.allow_llm is False

    post = eng.evaluate_post_llm(
        mode=BehaviorMode.OFF,
        explicit_trainer_request=True,
        cooldown_remaining=0,
        should_intervene=True,
        event_type="DEMANDE_FORMATEUR",
        is_off_topic=False,
        is_uncertain=False,
        confidence=0.95,
        learner_response="Réponse test.",
        private_trainer_note="Note test.",
        recent_answers=[],
        max_sentences=4,
        max_chars=500,
        epoch_before=1,
        epoch_after=1,
    )
    assert post.allow_proposal is False


def test_mode_passif_logs_but_blocks_spontaneous_proposal():
    eng = BehaviorEngine()
    pre = eng.evaluate_pre_llm(
        mode=BehaviorMode.PASSIF,
        transcript="Je ne comprends pas la différence entre PUT et PATCH.",
        stt_uncertain=False,
        explicit_trainer_request=False,
        cooldown_remaining=0,
        asked_questions=[],
        recent_answers=[],
    )
    assert pre.allow_llm is True

    post = eng.evaluate_post_llm(
        mode=BehaviorMode.PASSIF,
        explicit_trainer_request=False,
        cooldown_remaining=0,
        should_intervene=True,
        event_type="INCOMPREHENSION",
        is_off_topic=False,
        is_uncertain=False,
        confidence=0.9,
        learner_response="PUT remplace tout, PATCH modifie un champ.",
        private_trainer_note="",
        recent_answers=[],
        max_sentences=4,
        max_chars=500,
        epoch_before=0,
        epoch_after=0,
    )
    assert post.allow_proposal is False


def test_mode_sur_demande_requires_explicit_request():
    eng = BehaviorEngine()
    pre_spontaneous = eng.evaluate_pre_llm(
        mode=BehaviorMode.SUR_DEMANDE,
        transcript="C'est quoi une API REST ?",
        stt_uncertain=False,
        explicit_trainer_request=False,
        cooldown_remaining=0,
        asked_questions=[],
        recent_answers=[],
    )
    assert pre_spontaneous.allow_llm is False

    pre_explicit = eng.evaluate_pre_llm(
        mode=BehaviorMode.SUR_DEMANDE,
        transcript="Néo, donne un exemple.",
        stt_uncertain=False,
        explicit_trainer_request=True,
        cooldown_remaining=0,
        asked_questions=[],
        recent_answers=[],
    )
    assert pre_explicit.allow_llm is True


def test_mode_actif_respects_cooldown_unless_explicit():
    eng = BehaviorEngine()
    pre_blocked = eng.evaluate_pre_llm(
        mode=BehaviorMode.ACTIF,
        transcript="Pourquoi le code 422 ?",
        stt_uncertain=False,
        explicit_trainer_request=False,
        cooldown_remaining=12,
        asked_questions=[],
        recent_answers=[],
    )
    assert pre_blocked.allow_llm is False

    pre_bypass = eng.evaluate_pre_llm(
        mode=BehaviorMode.ACTIF,
        transcript="Néo, réponds maintenant.",
        stt_uncertain=False,
        explicit_trainer_request=True,
        cooldown_remaining=12,
        asked_questions=[],
        recent_answers=[],
    )
    assert pre_bypass.allow_llm is True


def test_interruption_cancels_post_llm_proposal():
    eng = BehaviorEngine()
    post = eng.evaluate_post_llm(
        mode=BehaviorMode.ACTIF,
        explicit_trainer_request=True,
        cooldown_remaining=0,
        should_intervene=True,
        event_type="DEMANDE_FORMATEUR",
        is_off_topic=False,
        is_uncertain=False,
        confidence=0.95,
        learner_response="Voici un exemple.",
        private_trainer_note="",
        recent_answers=[],
        max_sentences=4,
        max_chars=500,
        epoch_before=2,
        epoch_after=3,
    )
    assert post.allow_proposal is False
    assert "Interruption" in post.decision_reason


def test_off_topic_and_uncertainty_stay_silent():
    eng = BehaviorEngine()
    off_topic = eng.evaluate_post_llm(
        mode=BehaviorMode.ACTIF,
        explicit_trainer_request=False,
        cooldown_remaining=0,
        should_intervene=True,
        event_type="HORS_SUJET",
        is_off_topic=True,
        is_uncertain=False,
        confidence=0.9,
        learner_response="La cafétéria ferme à 17h.",
        private_trainer_note="",
        recent_answers=[],
        max_sentences=4,
        max_chars=500,
        epoch_before=0,
        epoch_after=0,
    )
    assert off_topic.allow_proposal is False

    uncertain = eng.evaluate_post_llm(
        mode=BehaviorMode.ACTIF,
        explicit_trainer_request=False,
        cooldown_remaining=0,
        should_intervene=True,
        event_type="QUESTION",
        is_off_topic=False,
        is_uncertain=True,
        confidence=0.3,
        learner_response="Peut-être ceci.",
        private_trainer_note="",
        recent_answers=[],
        max_sentences=4,
        max_chars=500,
        epoch_before=0,
        epoch_after=0,
    )
    assert uncertain.allow_proposal is False


def test_repeated_question_and_deduplication():
    eng = BehaviorEngine()
    asked = ["Quelle est la différence entre PUT et PATCH dans une API ?"]
    answers = ["PUT remplace toute la ressource tandis que PATCH modifie un champ."]

    is_rep, already = eng.detect_repetition(
        "Du coup quelle différence entre PUT et PATCH pour une API ?",
        asked,
        answers,
    )
    assert is_rep is True
    assert already is True

    dup = eng.evaluate_post_llm(
        mode=BehaviorMode.ACTIF,
        explicit_trainer_request=False,
        cooldown_remaining=0,
        should_intervene=True,
        event_type="REPETITION",
        is_off_topic=False,
        is_uncertain=False,
        confidence=0.88,
        learner_response="PUT remplace toute la ressource tandis que PATCH modifie un champ.",
        private_trainer_note="",
        recent_answers=answers,
        max_sentences=4,
        max_chars=500,
        epoch_before=0,
        epoch_after=0,
    )
    assert dup.allow_proposal is False


def test_sentence_and_char_clamping():
    eng = BehaviorEngine()
    long_text = "Phrase une. Phrase deux. Phrase trois. Phrase quatre. Phrase cinq. Phrase six."
    clamped = eng.clamp_sentences_and_chars(long_text, max_sentences=3, max_chars=200)
    assert "Phrase quatre" not in clamped
    assert "Phrase trois." in clamped


def test_behavior_engine_pre_post_check_and_decision_engine_alias():
    from app.config.defaults import NeoConfig
    from app.core.decision_engine import DecisionEngine
    from app.core.state_manager import StateManager

    assert DecisionEngine is BehaviorEngine
    eng = DecisionEngine()
    cfg = NeoConfig()
    state = StateManager()
    assert eng.behavior is eng

    pre = eng.pre_check(
        config=cfg,
        state=state,
        transcript="Pourquoi utiliser le code 422 ici ?",
    )
    assert pre.allow_llm is True

    post = eng.post_check(
        config=cfg,
        state=state,
        explicit_trainer_request=False,
        should_intervene=True,
        event_type="QUESTION",
        is_off_topic=False,
        is_uncertain=False,
        confidence=0.9,
        learner_response="Le code 422 signale une erreur de validation métier.",
        private_trainer_note="Nuance syntaxe vs métier.",
        epoch_before=state.current_interruption_epoch(),
    )
    assert post.allow_proposal is True


def test_state_manager_settle_state_and_session_transitions(tmp_path):
    from app.config.config_manager import ConfigManager
    from app.core.event_manager import EventManager
    from app.core.session_controller import SessionController
    from app.core.state_manager import NeoState, ProposalRecord, StateManager

    state = StateManager()
    proposal = ProposalRecord(
        id="prop-1",
        created_at="10:00:00",
        transcript="Question ?",
        event_type="QUESTION",
        analysis="Analyse",
        decision="OK",
        intervention_type="Reformulation",
        private_trainer_note="Note",
        learner_response="Réponse",
        confidence=0.9,
        processing_ms=20,
    )

    # 1. OFF always takes priority even with active_proposal or PAROLE_DETECTEE
    state.session_active = True
    state.listening_enabled = True
    state.active_proposal = proposal
    state.set_state(NeoState.PAROLE_DETECTEE)
    assert (
        state.settle_state(
            mode=BehaviorMode.OFF.value,
            preserve_states=(NeoState.PAROLE_DETECTEE,),
        )
        == NeoState.OFF
    )

    # 2. PAROLE_DETECTEE preserved when explicitly requested (e.g. TTS interrupted by VAD)
    state.set_state(NeoState.PAROLE_DETECTEE)
    assert (
        state.settle_state(
            mode=BehaviorMode.ACTIF.value,
            preserve_states=(NeoState.PAROLE_DETECTEE,),
        )
        == NeoState.PAROLE_DETECTEE
    )

    # 3. ERREUR preserved when requested (e.g. disable_listening) and error message kept
    state.set_state(NeoState.ERREUR, error="Micro débranché")
    assert (
        state.settle_state(
            mode=BehaviorMode.ACTIF.value,
            preserve_states=(NeoState.ERREUR, NeoState.PROPOSITION),
        )
        == NeoState.ERREUR
    )
    assert state.last_error == "Micro débranché"

    # 4. active_proposal takes priority over ECOUTE
    state.set_state(NeoState.ANALYSE)
    state.active_proposal = proposal
    state.session_active = True
    state.listening_enabled = True
    state.session_paused = False
    assert state.settle_state(mode=BehaviorMode.ACTIF.value) == NeoState.PROPOSITION

    # 5. session_paused blocks ECOUTE and never reactivates listening
    state.active_proposal = None
    state.session_paused = True
    assert state.settle_state(mode=BehaviorMode.ACTIF.value) == NeoState.EN_VEILLE
    assert state.listening_enabled is True  # settle_state does not mutate listening/session flags

    # 6. ECOUTE only when listening_enabled + session_active + not session_paused
    state.session_paused = False
    assert state.settle_state(mode=BehaviorMode.ACTIF.value) == NeoState.ECOUTE

    # 7. SessionController pause, resume, interrupt, stop invariants
    cfg_mgr = ConfigManager(config_path=tmp_path / "cfg.json")
    events = EventManager()
    ctrl = SessionController(cfg_mgr, state, events)
    audio_events: list[str] = []
    ctrl.register_audio_hooks(
        lambda: audio_events.append("start"),
        lambda: audio_events.append("stop"),
    )

    assert ctrl.start_session(enable_listening=True) == NeoState.ECOUTE
    assert ctrl.pause_session() == NeoState.EN_VEILLE
    assert state.session_paused is True
    assert state.listening_enabled is False
    assert audio_events[-1] == "stop"

    # Interrupt during active listening returns to ECOUTE and clears active_proposal
    assert ctrl.resume_session() == NeoState.ECOUTE
    state.active_proposal = proposal
    assert ctrl.interrupt("Stop formateur") == NeoState.ECOUTE
    assert state.active_proposal is None
    assert ctrl.stop_session() == NeoState.EN_VEILLE
    assert state.session_active is False


def test_shared_text_normalization_and_distinct_context_rules():
    from app.core.state_manager import StateManager
    from app.core.text_utils import normalize_text
    from app.tts.text_limiter import SpeechTextSanitizer

    samples = [
        ("C'est quoi l'API REST ? — NÉO !", "c est quoi l api rest néo"),
        ("  PUT, PATCH : différence à connaître... ", "put patch différence à connaître"),
        ("Évaluation\t\nà   l’oral ?", "évaluation à l oral"),
        ("Àâäéèêëîïôöùûüç !?", "àâäéèêëîïôöùûüç"),
    ]
    for raw, expected in samples:
        assert normalize_text(raw) == expected
        assert BehaviorEngine.normalize_text(raw) == expected

    # StateManager record_tts_spoken & echo detection use exact same normalization
    state = StateManager()
    spoken = "L'idempotence garantit qu'un appel répété produit le même effet !"
    state.record_tts_spoken(spoken)
    assert state.recent_spoken_phrases[-1][1] == normalize_text(spoken)
    assert state.is_probable_tts_echo("l idempotence garantit qu un appel répété produit le même effet") is True

    # Display clamping vs TTS sanitization remain strictly distinct
    eng = BehaviorEngine()
    md_text = "**PUT** remplace toute la ressource tandis que `PATCH` modifie uniquement un champ précis dans l'objet."
    display_clamped = eng.clamp_sentences_and_chars(md_text, max_sentences=2, max_chars=55)
    tts_sanitized = SpeechTextSanitizer.sanitize(md_text, max_chars=55, max_sentences=2)
    assert "**PUT**" in display_clamped and display_clamped.endswith("…")
    assert "**" not in tts_sanitized and "`" not in tts_sanitized and tts_sanitized.endswith(".")


def test_runtime_config_centralization_update_reset_and_recovery(tmp_path):
    from app.config.config_manager import ConfigManager
    from app.core.state_manager import NeoState
    from app.runtime import NeoRuntime

    cfg_path = tmp_path / "dashboard_config.json"

    # 1. Corrupted JSON recovery & startup coherence
    cfg_path.write_text("{json_corrompu!!!", encoding="utf-8")
    rt = NeoRuntime(config_path=cfg_path)
    assert rt.config_manager.last_warning is not None
    assert (tmp_path / "dashboard_config.corrupted.bak").exists()
    assert rt.config_manager.config.mode == "ACTIF"
    assert rt.state_manager.state == NeoState.EN_VEILLE

    # 2. Hot config update applies all runtime side effects
    updated = rt.apply_config_update(
        {
            "ollama_url": "http://127.0.0.1:11555",
            "max_pending_segments": 6,
            "tts_auto_unload_seconds": 45,
            "tts_enabled": True,
            "vocal_mode": "AUTONOME",
            "mode": "OFF",
        }
    )
    assert updated.mode == "OFF"
    assert rt.state_manager.state == NeoState.OFF
    assert rt.ollama_client.base_url == "http://127.0.0.1:11555"
    assert rt.segment_queue.max_pending == 6
    assert rt.tts_service.worker._auto_unload_seconds == 45

    # 3. Reset restores defaults, syncs _auto_unload_seconds, and exits OFF cleanly
    reset_cfg = rt.reset_config_defaults()
    assert reset_cfg.mode == "ACTIF"
    assert reset_cfg.ollama_url == "http://127.0.0.1:11434"
    assert reset_cfg.max_pending_segments == 3
    assert rt.ollama_client.base_url == "http://127.0.0.1:11434"
    assert rt.segment_queue.max_pending == 3
    assert rt.tts_service.worker._auto_unload_seconds == 120
    assert rt.state_manager.state == NeoState.EN_VEILLE

    # 4. Vocal mode SILENCIEUX interrupts TTS; tts_enabled=False unloads TTS resources
    interrupted_reasons: list[str] = []
    unloaded: list[bool] = []
    orig_interrupt = rt.tts_service.interrupt
    orig_unload = rt.tts_service.unload_resources
    rt.tts_service.interrupt = lambda reason="": (interrupted_reasons.append(reason) or True)  # type: ignore[assignment]
    rt.tts_service.unload_resources = lambda: unloaded.append(True)  # type: ignore[assignment]
    try:
        rt.apply_config_update({"tts_enabled": True, "vocal_mode": "SILENCIEUX"})
        assert len(interrupted_reasons) == 1
        rt.apply_config_update({"tts_enabled": False})
        assert len(unloaded) == 1
    finally:
        rt.tts_service.interrupt = orig_interrupt  # type: ignore[assignment]
        rt.tts_service.unload_resources = orig_unload  # type: ignore[assignment]

    # 5. Reloading from saved file preserves updated values
    reloaded = ConfigManager(config_path=cfg_path)
    assert reloaded.config.vocal_mode == "SILENCIEUX"

