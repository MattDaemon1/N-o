"""Compact prompt builder for local lightweight SLMs (1B–3B quantized)."""

from __future__ import annotations

from app.config.defaults import NeoConfig

SYSTEM_PROMPT = """Tu es NÉO (Nouvel Équipier Opérationnel), un assistant pédagogique discret pour un formateur.
Règles impératives :
- Réponds uniquement en JSON strict valide, sans texte autour.
- Réponds toujours en français clair, sobre et pragmatique.
- Tes réponses pédagogiques doivent être courtes (2 à 6 phrases max), directement exploitables.
- Si l'échange est hors sujet ou normal sans difficulté, mets should_intervene à false.
- Si la situation est trop floue pour conclure, mets is_uncertain à true sans inventer de difficulté.
- Respecte ce schéma JSON exact :
{
  "event_type": "QUESTION | INCOMPREHENSION | CONFUSION | REPETITION | HORS_SUJET | ECHANGE_NORMAL | DEMANDE_FORMATEUR",
  "analysis": "1 phrase courte décrivant la situation détectée",
  "should_intervene": true,
  "intervention_type": "Reformulation | Exemple concret | Analogie | Explication simplifiée | Explication complémentaire | Synthèse | Détection de confusion | Aide au formateur",
  "is_off_topic": false,
  "is_uncertain": false,
  "confidence": 0.85,
  "private_trainer_note": "Conseil privé très court pour le formateur",
  "learner_response": "Explication courte (2 à 6 phrases) prête pour les apprenants"
}"""

DIRECT_RESPONSE_SYSTEM_PROMPT = (
    "Tu es un assistant vocal. Réponds directement à la question de l'utilisateur "
    "de manière claire, naturelle et concise. Ne produis que la réponse destinée à "
    "l'utilisateur. Ne fais pas d'analyse, ne présente pas ton raisonnement, ne produis "
    "pas de classification, de note, de commentaire pédagogique ou de structure JSON. "
    "Adapte la longueur à la question. Si tu ne sais pas, indique-le clairement."
)


class PromptManager:
    """Builds minimal context-bounded prompts to save CPU and RAM."""

    @staticmethod
    def build_analysis_prompt(
        *,
        config: NeoConfig,
        transcript: str,
        recent_history: list[dict],
        intervention_hint: str | None = None,
        explicit_request: bool = False,
        is_repeated: bool = False,
    ) -> str:
        ctx = config.training_context
        history_lines = [
            f"- [{item.get('time', '')}] {item.get('speaker', 'Apprenant')}: {item.get('text', '')}"
            for item in recent_history[-5:]
        ]
        history_block = "\n".join(history_lines) if history_lines else "Aucun échange précédent."

        parts = [
            f"Formation : {ctx.title}",
            f"Sujet : {ctx.subject or 'Non précisé'}",
            f"Niveau des apprenants : {ctx.learner_level}",
        ]
        if ctx.objectives:
            parts.append(f"Objectifs : {ctx.objectives}")
        if ctx.custom_instructions:
            parts.append(f"Instructions du formateur : {ctx.custom_instructions}")

        parts.append(f"Historique récent :\n{history_block}")
        parts.append(f"Dernier énoncé capté : « {transcript} »")

        if is_repeated:
            parts.append("Note contexte : Cette question ressemble à une interrogation déjà posée.")
        if explicit_request:
            parts.append("Priorité : Le formateur sollicite explicitement NÉO.")
        if intervention_hint:
            parts.append(f"Type d'aide demandé : {intervention_hint}")

        parts.append(
            f"Limite stricte : learner_response en {config.max_response_sentences} phrases maximum."
        )
        return "\n".join(parts)

    @staticmethod
    def build_json_repair_prompt(raw_output: str) -> str:
        return (
            "Ta réponse précédente n'était pas un JSON valide. "
            "Corrige-la immédiatement en retournant UNIQUEMENT un objet JSON conforme au schéma demandé.\n\n"
            f"Sortie brute à corriger :\n{raw_output[:800]}"
        )

    @staticmethod
    def build_direct_response_prompt(question: str) -> str:
        return " ".join(question.strip().split())
