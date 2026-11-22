"""Speech text sanitization and strict length guard for concise spoken output."""

from __future__ import annotations

import re


class SpeechTextSanitizer:
    """Cleans markdown/symbols and limits spoken text to preserve calm 5–20s interventions."""

    _MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
    _MD_CODE_RE = re.compile(r"`([^`]+)`")
    _MD_STYLE_RE = re.compile(r"(\*\*|__|\*|~~)")
    _MD_HEADING_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s+")
    _MD_BULLET_RE = re.compile(r"(?m)^\s*[-*•]\s+")
    _SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

    @classmethod
    def sanitize(
        cls,
        text: str,
        *,
        max_chars: int = 380,
        max_sentences: int = 3,
    ) -> str:
        if not text or not isinstance(text, str):
            return ""

        cleaned = text.strip()
        cleaned = cls._MD_LINK_RE.sub(r"\1", cleaned)
        cleaned = cls._MD_CODE_RE.sub(r"\1", cleaned)
        cleaned = cls._MD_HEADING_RE.sub("", cleaned)
        cleaned = cls._MD_BULLET_RE.sub("", cleaned)
        cleaned = cls._MD_STYLE_RE.sub("", cleaned)
        cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
        cleaned = re.sub(r"\n+", ". ", cleaned)
        cleaned = re.sub(r"\.\s*\.", ".", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        # Reject strings containing only punctuation or whitespace
        if not re.search(r"[A-Za-zÀ-ÿ0-9]", cleaned):
            return ""

        sentences = [s.strip() for s in cls._SENTENCE_SPLIT_RE.split(cleaned) if s.strip()]
        limited = " ".join(sentences[: max(1, int(max_sentences))]).strip()

        safe_max_chars = max(40, int(max_chars))
        if len(limited) > safe_max_chars:
            cut = limited[: safe_max_chars - 1].rsplit(" ", 1)[0].rstrip(".,;: ")
            if not cut:
                cut = limited[: safe_max_chars - 1].rstrip(".,;: ")
            limited = f"{cut}."
        return limited
