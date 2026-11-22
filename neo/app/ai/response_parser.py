"""Strict JSON response parser with single repair signal and deterministic fallback."""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

EventTypeStr = Literal[
    "QUESTION",
    "INCOMPREHENSION",
    "CONFUSION",
    "REPETITION",
    "HORS_SUJET",
    "ECHANGE_NORMAL",
    "DEMANDE_FORMATEUR",
]

InterventionTypeStr = Literal[
    "Reformulation",
    "Exemple concret",
    "Analogie",
    "Explication simplifiée",
    "Explication complémentaire",
    "Synthèse",
    "Détection de confusion",
    "Aide au formateur",
]


class ParsedPedagogicalResponse(BaseModel):
    event_type: EventTypeStr = "ECHANGE_NORMAL"
    analysis: str = Field(default="Analyse pédagogique non précisée.", max_length=320)
    should_intervene: bool = False
    intervention_type: InterventionTypeStr = "Aide au formateur"
    is_off_topic: bool = False
    is_uncertain: bool = False
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    private_trainer_note: str = Field(default="", max_length=400)
    learner_response: str = Field(default="", max_length=1200)


def _extract_json_object(raw_text: str) -> str:
    stripped = raw_text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    return match.group(0) if match else stripped


class ResponseParser:
    """Validates LLM JSON output strictly and provides a deterministic fallback."""

    @staticmethod
    def parse(raw_text: str) -> tuple[ParsedPedagogicalResponse | None, str | None]:
        if not raw_text or not raw_text.strip():
            return None, "Réponse vide du modèle."
        candidate = _extract_json_object(raw_text)
        try:
            data = json.loads(candidate)
            parsed = ParsedPedagogicalResponse.model_validate(data)
            return parsed, None
        except (json.JSONDecodeError, ValidationError) as exc:
            return None, f"JSON invalide : {exc}"

    @staticmethod
    def deterministic_fallback(
        transcript: str,
        *,
        explicit_request: bool = False,
        reason: str = "Fallback déterministe suite à une réponse LLM indisponible ou invalide.",
    ) -> ParsedPedagogicalResponse:
        lower = transcript.lower()
        if any(w in lower for w in ("comprends pas", "perdu", "flou", "compliqué", "difficile")):
            return ParsedPedagogicalResponse(
                event_type="INCOMPREHENSION",
                analysis=reason,
                should_intervene=True,
                intervention_type="Détection de confusion",
                confidence=0.62,
                private_trainer_note=(
                    "Signal d'incompréhension détecté localement : envisagez une pause ou une reformulation."
                ),
                learner_response="",
            )
        if "?" in transcript or lower.startswith(("pourquoi", "comment", "est-ce que", "c'est quoi")):
            return ParsedPedagogicalResponse(
                event_type="QUESTION",
                analysis=reason,
                should_intervene=explicit_request,
                intervention_type="Aide au formateur",
                is_uncertain=not explicit_request,
                confidence=0.55 if explicit_request else 0.35,
                private_trainer_note="Question détectée ; réponse automatique indisponible (vérifiez Ollama).",
                learner_response="",
            )
        return ParsedPedagogicalResponse(
            event_type="ECHANGE_NORMAL",
            analysis=reason,
            should_intervene=False,
            is_uncertain=True,
            confidence=0.35,
            private_trainer_note="",
            learner_response="",
        )
