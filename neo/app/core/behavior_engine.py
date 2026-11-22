"""Deterministic behavioral rules engine independent of any LLM."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.state_manager import BehaviorMode

# Common Whisper noise artifacts on silence/ambient sound
NOISE_ARTIFACTS = {
    "sous-titrage",
    "sous-titrage st' 501",
    "merci d'avoir regardé",
    "merci d'avoir regardé cette vidéo",
    "amara.org",
}


@dataclass
class PreCheckResult:
    allow_llm: bool
    reason: str
    is_empty: bool = False
    is_repeated_question: bool = False
    is_already_answered: bool = False
    is_off_topic_heuristic: bool = False


@dataclass
class PostCheckResult:
    allow_proposal: bool
    decision_reason: str
    clamped_response: str
    clamped_private_note: str


class BehaviorEngine:
    """Enforces deterministic rules before and after any LLM inference."""

    @staticmethod
    def normalize_text(text: str) -> str:
        cleaned = re.sub(r"[^\w\sàâäéèêëîïôöùûüç]", " ", text.lower())
        return re.sub(r"\s+", " ", cleaned).strip()

    def is_empty_or_noise(self, transcript: str, stt_uncertain: bool = False) -> bool:
        norm = self.normalize_text(transcript)
        if not norm or len(norm) < 3:
            return True
        if norm in NOISE_ARTIFACTS:
            return True
        if stt_uncertain and len(norm.split()) <= 2:
            return True
        return False

    _STOPWORDS = {
        "les", "des", "une", "est", "sont", "pas", "que", "qui", "sur", "par",
        "dans", "avec", "pour", "entre", "mon", "ton", "son", "nos", "vos",
        "ces", "cet", "cette", "mais", "donc", "car", "aux", "oui", "non",
        "moi", "toi", "lui", "eux", "ici", "ont", "fait", "plus", "moins",
        "tout", "tous", "toute", "coup", "quelle", "quel", "quels", "quelles",
        "quoi", "comment", "pourquoi", "quand", "sans", "sous", "chez", "vers",
        "aussi", "très", "bien", "alors", "tandis", "encore",
    }

    @classmethod
    def _meaningful_tokens(cls, text: str) -> set[str]:
        norm = cls.normalize_text(text)
        return {
            w for w in norm.split()
            if len(w) >= 3 and w not in cls._STOPWORDS
        }

    def detect_repetition(
        self,
        transcript: str,
        asked_questions: list[str],
        recent_answers: list[str],
    ) -> tuple[bool, bool]:
        """Returns (is_repeated_question, is_already_answered)."""
        tokens = self._meaningful_tokens(transcript)
        if not tokens:
            return False, False

        is_repeated = False
        for prev_q in asked_questions:
            prev_tokens = self._meaningful_tokens(prev_q)
            if not prev_tokens:
                continue
            overlap = len(tokens & prev_tokens)
            ratio = overlap / max(1, min(len(tokens), len(prev_tokens)))
            if overlap >= 3 or ratio >= 0.65:
                is_repeated = True
                break

        already_answered = False
        if is_repeated and recent_answers:
            for ans in recent_answers:
                ans_tokens = self._meaningful_tokens(ans)
                if len(tokens & ans_tokens) >= 2:
                    already_answered = True
                    break

        return is_repeated, already_answered

    @staticmethod
    def is_explicit_trainer_solicitation(transcript: str, explicit_flag: bool = False) -> bool:
        if explicit_flag:
            return True
        lower = transcript.strip().lower()
        return lower.startswith(("néo", "neo", "dis néo", "ok néo"))

    def evaluate_pre_llm(
        self,
        *,
        mode: BehaviorMode,
        transcript: str,
        stt_uncertain: bool,
        explicit_trainer_request: bool,
        cooldown_remaining: int,
        asked_questions: list[str],
        recent_answers: list[str],
    ) -> PreCheckResult:
        if mode == BehaviorMode.OFF:
            return PreCheckResult(allow_llm=False, reason="Mode OFF actif : analyse désactivée.")

        if self.is_empty_or_noise(transcript, stt_uncertain=stt_uncertain):
            return PreCheckResult(
                allow_llm=False,
                reason="Transcription vide ou bruit non exploitable ignoré.",
                is_empty=True,
            )

        is_explicit = self.is_explicit_trainer_solicitation(transcript, explicit_trainer_request)

        if mode == BehaviorMode.SUR_DEMANDE and not is_explicit:
            return PreCheckResult(
                allow_llm=False,
                reason="Mode SUR_DEMANDE : NÉO reste silencieux sans sollicitation du formateur.",
            )

        if mode == BehaviorMode.ACTIF and cooldown_remaining > 0 and not is_explicit:
            return PreCheckResult(
                allow_llm=False,
                reason=f"Cooldown actif ({cooldown_remaining} s) : segmentation ignorée pour éviter la surcharge.",
            )

        is_repeated, is_already_answered = self.detect_repetition(
            transcript, asked_questions, recent_answers
        )

        # Avoid wasting CPU/RAM re-calling LLM on an identical question already answered unless trainer insists
        if is_already_answered and not is_explicit and mode == BehaviorMode.ACTIF:
            return PreCheckResult(
                allow_llm=True,  # still log/analyze or flag repetition if PASSIF/ACTIF, or handle cleanly
                reason="Question déjà traitée détectée — analyse contextuelle prudente.",
                is_repeated_question=is_repeated,
                is_already_answered=True,
            )

        return PreCheckResult(
            allow_llm=True,
            reason="Éligible pour analyse pédagogique.",
            is_repeated_question=is_repeated,
            is_already_answered=is_already_answered,
        )

    @staticmethod
    def clamp_sentences_and_chars(text: str, max_sentences: int, max_chars: int) -> str:
        clean = " ".join(text.strip().split())
        if not clean:
            return ""
        parts = re.split(r"(?<=[.!?])\s+", clean)
        limited = " ".join(parts[:max(1, max_sentences)]).strip()
        if len(limited) > max_chars:
            truncated = limited[: max_chars - 1].rsplit(" ", 1)[0].rstrip(".,;:")
            limited = f"{truncated}…"
        return limited

    def evaluate_post_llm(
        self,
        *,
        mode: BehaviorMode,
        explicit_trainer_request: bool,
        cooldown_remaining: int,
        should_intervene: bool,
        event_type: str,
        is_off_topic: bool,
        is_uncertain: bool,
        confidence: float,
        learner_response: str,
        private_trainer_note: str,
        recent_answers: list[str],
        max_sentences: int,
        max_chars: int,
        epoch_before: int,
        epoch_after: int,
    ) -> PostCheckResult:
        if mode == BehaviorMode.OFF:
            return PostCheckResult(False, "Mode OFF prioritaire : aucune restitution.", "", "")

        if epoch_before != epoch_after:
            return PostCheckResult(
                False,
                "Interruption du formateur : réponse annulée et non reprise.",
                "",
                "",
            )

        clamped_resp = self.clamp_sentences_and_chars(learner_response, max_sentences, max_chars)
        clamped_note = self.clamp_sentences_and_chars(private_trainer_note, 2, 280)

        if mode == BehaviorMode.PASSIF and not explicit_trainer_request:
            return PostCheckResult(
                False,
                "Mode PASSIF : analyse enregistrée en silence sans proposition spontanée.",
                clamped_resp,
                clamped_note,
            )

        if mode == BehaviorMode.SUR_DEMANDE and not explicit_trainer_request:
            return PostCheckResult(
                False,
                "Mode SUR_DEMANDE : en attente d'une sollicitation explicite.",
                clamped_resp,
                clamped_note,
            )

        if is_off_topic or event_type == "HORS_SUJET":
            return PostCheckResult(
                False,
                "Hors sujet détecté : NÉO reste silencieux pour ne pas perturber la session.",
                "",
                "",
            )

        if is_uncertain or confidence < 0.45:
            if explicit_trainer_request:
                return PostCheckResult(
                    True,
                    "Incertitude signalée au formateur suite à sa demande explicite.",
                    "",
                    clamped_note
                    or "Situation peu claire : je préfère ne pas extrapoler sans précision supplémentaire.",
                )
            return PostCheckResult(
                False,
                "Incertitude détectée : NÉO privilégie le silence plutôt que d'inventer.",
                "",
                clamped_note,
            )

        if not should_intervene and not explicit_trainer_request:
            return PostCheckResult(
                False,
                "Silence pertinent : aucune difficulté pédagogique nécessitant une aide.",
                "",
                "",
            )

        if cooldown_remaining > 0 and not explicit_trainer_request:
            return PostCheckResult(
                False,
                f"Cooldown actif ({cooldown_remaining} s) : proposition retenue.",
                "",
                "",
            )

        # Deduplicate identical response
        if clamped_resp and not explicit_trainer_request:
            norm_resp = self.normalize_text(clamped_resp)[:90]
            if any(norm_resp and norm_resp in self.normalize_text(a) for a in recent_answers):
                return PostCheckResult(
                    False,
                    "Réponse déjà apportée précédemment : silence pour éviter la répétition.",
                    "",
                    "Ce point a déjà été expliqué récemment ; signalez si une reformulation différente est nécessaire.",
                )

        if not clamped_resp and not clamped_note:
            return PostCheckResult(
                False,
                "Aucun contenu exploitable généré : silence maintenu.",
                "",
                "",
            )

        return PostCheckResult(
            True,
            "Proposition pédagogique validée par le moteur comportemental.",
            clamped_resp,
            clamped_note,
        )
