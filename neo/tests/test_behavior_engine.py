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
