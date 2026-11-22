"""Minimal shared text normalization helper for lexical matching."""

from __future__ import annotations

import re

_NON_ALNUM_FR_RE = re.compile(r"[^\w\sàâäéèêëîïôöùûüç]")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Lowercase, strip punctuation (preserving French accents), and collapse spaces."""
    cleaned = _NON_ALNUM_FR_RE.sub(" ", text.lower())
    return _WHITESPACE_RE.sub(" ", cleaned).strip()
