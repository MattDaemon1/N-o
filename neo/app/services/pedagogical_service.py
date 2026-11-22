"""Pedagogical analysis, Ollama orchestration, and demonstration scenarios."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from app.ai.model_manager import ModelManager
from app.ai.ollama_client import OllamaClient
from app.ai.prompt_manager import SYSTEM_PROMPT, PromptManager
from app.ai.response_parser import ParsedPedagogicalResponse, ResponseParser
from app.config.config_manager import ConfigManager
from app.core.behavior_engine import BehaviorEngine
from app.core.event_manager import EventManager
from app.core.session_controller import SessionController
from app.core.state_manager import BehaviorMode, NeoState, ProposalRecord, StateManager

SIMULATION_SCENARIOS: dict[str, dict[str, Any]] = {
    "question_pertinente": {
        "label": "1. Question pertinente",
        "speaker": "Apprenant",
        "transcript": "Pourquoi utilise-t-on le code HTTP 422 plutôt que 400 quand un format d'email est invalide ?",
        "explicit": False,
        "force_uncertain": False,
        "force_mode_off": False,
    },
    "incomprehension": {
        "label": "2. Incompréhension",
        "speaker": "Apprenant",
        "transcript": "Je suis désolé, je ne comprends pas du tout ce que signifie l'idempotence dans une API.",
        "explicit": False,
        "force_uncertain": False,
        "force_mode_off": False,
    },
    "confusion": {
        "label": "3. Confusion entre deux notions",
        "speaker": "Apprenant",
        "transcript": "Donc PUT et PATCH font exactement la même chose pour modifier un seul champ ?",
        "explicit": False,
        "force_uncertain": False,
        "force_mode_off": False,
    },
    "question_repetee": {
        "label": "4. Question répétée",
        "speaker": "Apprenant",
        "transcript": "Mais concrètement, pour l'idempotence, est-ce que POST est idempotent ou pas ?",
        "explicit": False,
        "force_uncertain": False,
        "force_mode_off": False,
        "seed_repeated": True,
    },
    "hors_sujet": {
        "label": "5. Conversation hors sujet",
        "speaker": "Apprenant",
        "transcript": "Au fait, vous savez à quelle heure ferme la cafétéria cet après-midi ?",
        "explicit": False,
        "force_uncertain": False,
        "force_mode_off": False,
    },
    "demande_formateur": {
        "label": "6. Demande explicite du formateur",
        "speaker": "Formateur",
        "transcript": "Néo, donne-nous un exemple concret et très simple pour illustrer la différence entre PUT et PATCH.",
        "explicit": True,
        "force_uncertain": False,
        "force_mode_off": False,
    },
    "reponse_deja_apportee": {
        "label": "7. Réponse déjà apportée",
        "speaker": "Apprenant",
        "transcript": "Pourquoi utilise-t-on le code HTTP 422 plutôt que 400 quand un format d'email est invalide ?",
        "explicit": False,
        "force_uncertain": False,
        "force_mode_off": False,
        "seed_already_answered": True,
    },
    "transcription_vide": {
        "label": "8. Transcription vide",
        "speaker": "Apprenant",
        "transcript": "   ",
        "explicit": False,
        "force_uncertain": False,
        "force_mode_off": False,
    },
    "reponse_incertaine": {
        "label": "9. Réponse LLM incertaine",
        "speaker": "Apprenant",
        "transcript": "Euh... oui voilà c'est le truc avec la chose qui bloque parfois quand on lance.",
        "explicit": False,
        "force_uncertain": True,
        "force_mode_off": False,
    },
    "mode_off": {
        "label": "10. Mode OFF",
        "speaker": "Apprenant",
        "transcript": "Je ne comprends pas comment fonctionne la validation des données.",
        "explicit": False,
        "force_uncertain": False,
        "force_mode_off": True,
    },
}


class PedagogicalService:
    """Runs transcript evaluation through BehaviorEngine and local Ollama LLM."""

    def __init__(
        self,
        *,
        config_manager: ConfigManager,
        state_manager: StateManager,
        event_manager: EventManager,
        behavior_engine: BehaviorEngine | None = None,
        decision_engine: BehaviorEngine | None = None,
        session_controller: SessionController,
        ollama_client: OllamaClient,
        model_manager: ModelManager,
        tts_service: Any | None = None,
    ) -> None:
        self.config_manager = config_manager
        self.state_manager = state_manager
        self.event_manager = event_manager
        self.behavior_engine = behavior_engine or decision_engine or BehaviorEngine()
        self.session_controller = session_controller
        self.ollama = ollama_client
        self.model_manager = model_manager
        self.tts_service = tts_service
        self._proposal_counter = 0

    def _settle_state(self) -> None:
        self.state_manager.settle_state(mode=self.config_manager.config.mode)

    async def process_transcript(
        self,
        *,
        transcript: str,
        speaker: str = "Apprenant",
        stt_uncertain: bool = False,
        explicit_trainer_request: bool = False,
        intervention_hint: str | None = None,
        transcription_ms: int = 0,
        is_simulated: bool = False,
        force_uncertain: bool = False,
    ) -> dict[str, Any]:
        cfg = self.config_manager.config
        epoch_before = self.state_manager.current_interruption_epoch()

        if not is_simulated and not explicit_trainer_request and self.state_manager.is_probable_tts_echo(transcript):
            reason = "Écho acoustique de NÉO détecté : segment ignoré."
            self.state_manager.last_silence_reason = reason
            self.event_manager.add(
                kind="decision",
                transcript=transcript.strip(),
                event_type="ECHO_IGNORE",
                decision=reason,
                transcription_ms=transcription_ms,
                is_simulated=False,
            )
            self._settle_state()
            return {"intervened": False, "decision": reason, "proposal": None}

        pre = self.behavior_engine.pre_check(
            config=cfg,
            state=self.state_manager,
            transcript=transcript,
            stt_uncertain=stt_uncertain,
            explicit_trainer_request=explicit_trainer_request,
        )

        if not pre.allow_llm:
            self.state_manager.last_silence_reason = pre.reason
            self.event_manager.add(
                kind="decision",
                transcript=transcript.strip(),
                event_type="VIDE" if pre.is_empty else "SILENCE",
                decision=pre.reason,
                transcription_ms=transcription_ms,
                is_simulated=is_simulated,
            )
            self._settle_state()
            return {"intervened": False, "decision": pre.reason, "proposal": None}

        is_explicit = self.behavior_engine.is_explicit_trainer_solicitation(
            transcript, explicit_trainer_request
        )
        self.state_manager.set_state(NeoState.ANALYSE)

        parsed, llm_ms, llm_error = await self._infer_with_single_repair(
            transcript=transcript,
            intervention_hint=intervention_hint,
            explicit_request=is_explicit,
            is_repeated=pre.is_repeated_question,
            force_uncertain=force_uncertain,
        )

        if llm_error:
            self.event_manager.add(
                kind="error",
                transcript=transcript,
                event_type="LLM_FALLBACK",
                error=llm_error,
                llm_ms=llm_ms,
                is_simulated=is_simulated,
            )

        self.state_manager.metrics.last_llm_ms = llm_ms

        # Guard if pre_check already saw identical question & answer
        if pre.is_already_answered and not is_explicit:
            parsed.should_intervene = False

        post = self.behavior_engine.post_check(
            config=cfg,
            state=self.state_manager,
            explicit_trainer_request=is_explicit,
            should_intervene=parsed.should_intervene,
            event_type=parsed.event_type,
            is_off_topic=parsed.is_off_topic,
            is_uncertain=parsed.is_uncertain or force_uncertain,
            confidence=parsed.confidence,
            learner_response=parsed.learner_response,
            private_trainer_note=parsed.private_trainer_note,
            epoch_before=epoch_before,
        )

        self.state_manager.record_transcript_memory(speaker, transcript, parsed.event_type)
        if parsed.event_type in ("QUESTION", "INCOMPREHENSION", "CONFUSION", "REPETITION"):
            self.state_manager.record_question(transcript)

        if not post.allow_proposal:
            self.state_manager.last_silence_reason = post.decision_reason
            self.event_manager.add(
                kind="analysis",
                transcript=transcript,
                event_type=parsed.event_type,
                analysis=parsed.analysis,
                decision=post.decision_reason,
                transcription_ms=transcription_ms,
                llm_ms=llm_ms,
                is_simulated=is_simulated,
            )
            self._settle_state()
            return {"intervened": False, "decision": post.decision_reason, "proposal": None}

        self._proposal_counter += 1
        proposal = ProposalRecord(
            id=f"prop-{self._proposal_counter}",
            created_at=datetime.now().strftime("%H:%M:%S"),
            transcript=transcript,
            event_type=parsed.event_type,
            analysis=parsed.analysis,
            decision=post.decision_reason,
            intervention_type=parsed.intervention_type,
            private_trainer_note=post.clamped_private_note,
            learner_response=post.clamped_response,
            confidence=parsed.confidence,
            processing_ms=transcription_ms + llm_ms,
            status="pending",
            is_simulated=is_simulated,
        )
        self.state_manager.active_proposal = proposal
        self.state_manager.last_silence_reason = None
        self.state_manager.metrics.interventions_count += 1
        if not is_explicit:
            self.state_manager.mark_intervention_now()
        if post.clamped_response:
            self.state_manager.record_answer(post.clamped_response)

        self.event_manager.add(
            kind="proposal",
            transcript=transcript,
            event_type=parsed.event_type,
            analysis=parsed.analysis,
            decision=post.decision_reason,
            proposal=post.clamped_response or post.clamped_private_note,
            transcription_ms=transcription_ms,
            llm_ms=llm_ms,
            is_simulated=is_simulated,
        )
        self.state_manager.set_state(NeoState.PROPOSITION)

        tts_result: dict[str, Any] | None = None
        if self.tts_service is not None and not is_simulated:
            spoken_candidate = post.clamped_response or (
                post.clamped_private_note if is_explicit else ""
            )
            if spoken_candidate:
                tts_result = self.tts_service.speak_autonomous(
                    text=spoken_candidate,
                    behavior_allowed=post.allow_proposal,
                    explicit_trainer_request=is_explicit,
                    epoch_before=epoch_before,
                )

        return {
            "intervened": True,
            "decision": post.decision_reason,
            "proposal": proposal.to_dict(),
            "tts": tts_result,
        }

    async def _infer_with_single_repair(
        self,
        *,
        transcript: str,
        intervention_hint: str | None,
        explicit_request: bool,
        is_repeated: bool,
        force_uncertain: bool,
    ) -> tuple[ParsedPedagogicalResponse, int, str | None]:
        cfg = self.config_manager.config
        if force_uncertain:
            return (
                ParsedPedagogicalResponse(
                    event_type="ECHANGE_NORMAL",
                    analysis="Énoncé ambigu ou incomplet.",
                    should_intervene=False,
                    is_uncertain=True,
                    confidence=0.25,
                    private_trainer_note="Incertitude détectée : énoncé insuffisamment clair.",
                    learner_response="",
                ),
                0,
                None,
            )

        if not cfg.ai_enabled:
            return (
                ResponseParser.deterministic_fallback(
                    transcript,
                    explicit_request=explicit_request,
                    reason="IA désactivée : évaluation déterministe locale.",
                ),
                0,
                None,
            )

        if not cfg.ollama_model:
            return (
                ResponseParser.deterministic_fallback(
                    transcript,
                    explicit_request=explicit_request,
                    reason="Aucun modèle Ollama sélectionné : mode déterministe actif.",
                ),
                0,
                "Aucun modèle Ollama sélectionné.",
            )

        self.ollama.set_base_url(cfg.ollama_url)
        user_prompt = PromptManager.build_analysis_prompt(
            config=cfg,
            transcript=transcript,
            recent_history=self.state_manager.get_recent_transcripts(),
            intervention_hint=intervention_hint,
            explicit_request=explicit_request,
            is_repeated=is_repeated,
        )

        total_ms = 0
        try:
            task = asyncio.create_task(
                self.ollama.generate_json(
                    model=cfg.ollama_model,
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    temperature=cfg.llm_temperature,
                    max_tokens=260,
                    timeout=cfg.llm_timeout_seconds,
                )
            )
            self.session_controller.register_active_llm_task(task)
            raw_text, ms1 = await task
            total_ms += ms1

            parsed, err = ResponseParser.parse(raw_text)
            if parsed is not None:
                return parsed, total_ms, None

            # Maximum ONE repair attempt (Section 11)
            repair_task = asyncio.create_task(
                self.ollama.generate_json(
                    model=cfg.ollama_model,
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=PromptManager.build_json_repair_prompt(raw_text),
                    temperature=0.0,
                    max_tokens=240,
                    timeout=cfg.llm_timeout_seconds,
                )
            )
            self.session_controller.register_active_llm_task(repair_task)
            repaired_raw, ms2 = await repair_task
            total_ms += ms2

            repaired, err2 = ResponseParser.parse(repaired_raw)
            if repaired is not None:
                return repaired, total_ms, None

            return (
                ResponseParser.deterministic_fallback(
                    transcript,
                    explicit_request=explicit_request,
                    reason=f"Fallback déterministe ({err2 or err}).",
                ),
                total_ms,
                err2 or err,
            )
        except asyncio.CancelledError:
            return (
                ParsedPedagogicalResponse(
                    event_type="ECHANGE_NORMAL",
                    analysis="Inférence annulée suite à une interruption.",
                    should_intervene=False,
                    confidence=0.0,
                ),
                total_ms,
                "Inférence interrompue par le formateur.",
            )
        except Exception as exc:
            return (
                ResponseParser.deterministic_fallback(
                    transcript,
                    explicit_request=explicit_request,
                    reason=f"Ollama indisponible ({exc}).",
                ),
                total_ms,
                str(exc),
            )
        finally:
            self.session_controller.register_active_llm_task(None)

    async def handle_proposal_action(self, proposal_id: str, action: str) -> dict[str, Any]:
        prop = self.state_manager.active_proposal
        if prop is None or prop.id != proposal_id:
            return {"ok": False, "error": "Proposition introuvable ou déjà traitée."}

        if action == "accept":
            prop.status = "accepted"
            self.state_manager.metrics.accepted_count += 1
            self.state_manager.active_proposal = None
            self.event_manager.add(
                kind="decision",
                event_type=prop.event_type,
                decision=f"Proposition {prop.id} acceptée par le formateur.",
                proposal=prop.learner_response or prop.private_trainer_note,
                is_simulated=prop.is_simulated,
            )
            self._settle_state()
            return {"ok": True, "action": "accept"}

        if action == "ignore":
            prop.status = "ignored"
            self.state_manager.metrics.ignored_count += 1
            self.state_manager.mark_intervention_now()
            self.state_manager.active_proposal = None
            self.state_manager.last_silence_reason = "Proposition ignorée : cooldown activé."
            self.event_manager.add(
                kind="decision",
                event_type=prop.event_type,
                decision=f"Proposition {prop.id} ignorée par le formateur.",
                is_simulated=prop.is_simulated,
            )
            self._settle_state()
            return {"ok": True, "action": "ignore"}

        if action == "publish":
            prop.status = "published"
            self.state_manager.metrics.accepted_count += 1
            if prop.learner_response:
                self.state_manager.published_to_learners.insert(
                    0,
                    {
                        "id": prop.id,
                        "time": prop.created_at,
                        "type": prop.intervention_type,
                        "text": prop.learner_response,
                        "is_simulated": prop.is_simulated,
                    },
                )
            self.state_manager.active_proposal = None
            self.event_manager.add(
                kind="decision",
                event_type=prop.event_type,
                decision=f"Réponse apprenants {prop.id} diffusée.",
                proposal=prop.learner_response,
                is_simulated=prop.is_simulated,
            )
            self._settle_state()
            return {"ok": True, "action": "publish"}

        if action in ("reformulate", "develop"):
            hint = (
                "Reformulation plus simple et différente de la précédente"
                if action == "reformulate"
                else "Explication complémentaire avec un exemple concret supplémentaire"
            )
            return await self.process_transcript(
                transcript=f"Néo, {hint} pour : {prop.transcript}",
                speaker="Formateur",
                explicit_trainer_request=True,
                intervention_hint=hint,
                is_simulated=prop.is_simulated,
            )

        return {"ok": False, "error": f"Action non reconnue : {action}"}

    async def run_simulation_scenario(self, scenario_id: str) -> dict[str, Any]:
        scenario = SIMULATION_SCENARIOS.get(scenario_id)
        if scenario is None:
            return {"ok": False, "error": f"Scénario inconnu : {scenario_id}"}

        prev_mode = self.config_manager.config.mode
        if scenario.get("force_mode_off"):
            self.config_manager.update({"mode": BehaviorMode.OFF.value})

        if scenario.get("seed_repeated") and scenario["transcript"] not in self.state_manager.asked_questions:
            self.state_manager.asked_questions.append(
                "Que veut dire l'idempotence dans une API et est-ce que POST est concerné ?"
            )
        if scenario.get("seed_already_answered"):
            if scenario["transcript"] not in self.state_manager.asked_questions:
                self.state_manager.asked_questions.append(scenario["transcript"])
            self.state_manager.recent_answers.append(
                "Le code 422 signale une erreur de validation métier sur un email ou un champ."
            )

        try:
            result = await self.process_transcript(
                transcript=scenario["transcript"],
                speaker=scenario["speaker"],
                explicit_trainer_request=bool(scenario.get("explicit")),
                is_simulated=True,
                force_uncertain=bool(scenario.get("force_uncertain")),
            )
            return {"ok": True, "scenario": scenario["label"], **result}
        finally:
            if scenario.get("force_mode_off"):
                self.config_manager.update({"mode": prev_mode})
                self._settle_state()
