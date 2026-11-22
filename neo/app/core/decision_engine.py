"""Decision coordinator connecting transcripts, BehaviorEngine, and StateManager."""

from __future__ import annotations

from app.config.defaults import NeoConfig
from app.core.behavior_engine import BehaviorEngine, PostCheckResult, PreCheckResult
from app.core.state_manager import BehaviorMode, StateManager


class DecisionEngine:
    """Orchestrates pre-LLM and post-LLM deterministic checks."""

    def __init__(self, behavior_engine: BehaviorEngine | None = None) -> None:
        self.behavior = behavior_engine or BehaviorEngine()

    @staticmethod
    def resolve_mode(config: NeoConfig) -> BehaviorMode:
        return BehaviorMode(config.mode)

    def pre_check(
        self,
        *,
        config: NeoConfig,
        state: StateManager,
        transcript: str,
        stt_uncertain: bool = False,
        explicit_trainer_request: bool = False,
    ) -> PreCheckResult:
        mode = self.resolve_mode(config)
        cooldown = state.cooldown_remaining(config.cooldown_seconds)
        return self.behavior.evaluate_pre_llm(
            mode=mode,
            transcript=transcript,
            stt_uncertain=stt_uncertain,
            explicit_trainer_request=explicit_trainer_request,
            cooldown_remaining=cooldown,
            asked_questions=state.asked_questions,
            recent_answers=state.recent_answers,
        )

    def post_check(
        self,
        *,
        config: NeoConfig,
        state: StateManager,
        explicit_trainer_request: bool,
        should_intervene: bool,
        event_type: str,
        is_off_topic: bool,
        is_uncertain: bool,
        confidence: float,
        learner_response: str,
        private_trainer_note: str,
        epoch_before: int,
    ) -> PostCheckResult:
        mode = self.resolve_mode(config)
        cooldown = state.cooldown_remaining(config.cooldown_seconds)
        return self.behavior.evaluate_post_llm(
            mode=mode,
            explicit_trainer_request=explicit_trainer_request,
            cooldown_remaining=cooldown,
            should_intervene=should_intervene,
            event_type=event_type,
            is_off_topic=is_off_topic,
            is_uncertain=is_uncertain,
            confidence=confidence,
            learner_response=learner_response,
            private_trainer_note=private_trainer_note,
            recent_answers=state.recent_answers,
            max_sentences=config.max_response_sentences,
            max_chars=config.max_response_chars,
            epoch_before=epoch_before,
            epoch_after=state.current_interruption_epoch(),
        )
