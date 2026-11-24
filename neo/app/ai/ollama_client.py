"""Local HTTP client for Ollama (http://127.0.0.1:11434) with zero cloud calls."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class OllamaModelInfo:
    name: str
    size_bytes: int
    size_label: str
    family: str
    parameter_size: str
    quantization: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "size_bytes": self.size_bytes,
            "size_label": self.size_label,
            "family": self.family,
            "parameter_size": self.parameter_size,
            "quantization": self.quantization,
        }


def _format_size(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "Inconnue"
    gb = size_bytes / (1024**3)
    if gb >= 1.0:
        return f"{gb:.1f} Go"
    mb = size_bytes / (1024**2)
    return f"{mb:.0f} Mo"


class OllamaClient:
    """Async REST client communicating exclusively with a local Ollama instance."""

    def __init__(self, base_url: str = "http://127.0.0.1:11434") -> None:
        self.base_url = base_url.rstrip("/")

    def set_base_url(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def list_models(self, timeout: float = 4.0) -> tuple[bool, list[OllamaModelInfo], str | None]:
        """Queries GET /api/tags. Never fabricates models if Ollama is offline."""
        url = f"{self.base_url}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                payload = resp.json()
        except httpx.ConnectError:
            return False, [], f"Ollama inaccessible sur {self.base_url}. Vérifiez que le service local est démarré."
        except httpx.TimeoutException:
            return False, [], f"Délai dépassé lors de la connexion à Ollama ({self.base_url})."
        except Exception as exc:
            return False, [], f"Erreur Ollama : {exc}"

        models: list[OllamaModelInfo] = []
        for raw in payload.get("models", []):
            details = raw.get("details", {}) or {}
            size_b = int(raw.get("size") or 0)
            models.append(
                OllamaModelInfo(
                    name=str(raw.get("name", "")),
                    size_bytes=size_b,
                    size_label=_format_size(size_b),
                    family=str(details.get("family") or ""),
                    parameter_size=str(details.get("parameter_size") or ""),
                    quantization=str(details.get("quantization_level") or ""),
                )
            )
        return True, models, None

    async def generate_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 260,
        timeout: float = 20.0,
    ) -> tuple[str, int]:
        """Calls POST /api/chat with strict JSON mode and non-streaming bounded output."""
        if not model:
            raise ValueError("Aucun modèle Ollama sélectionné.")

        url = f"{self.base_url}/api/chat"
        body = {
            "model": model,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        content = (data.get("message") or {}).get("content")
        if content is None:
            content = data.get("response", "")
        text = str(content).strip()
        if len(text) > 12000:
            text = text[:12000]
        return text, elapsed_ms

    async def generate_text(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 300,
        timeout: float = 20.0,
    ) -> tuple[str, int]:
        """Calls POST /api/chat for plain-text direct responses (no JSON format constraint)."""
        if not model:
            raise ValueError("Aucun modèle Ollama sélectionné.")

        url = f"{self.base_url}/api/chat"
        body = {
            "model": model,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        content = (data.get("message") or {}).get("content")
        if content is None:
            content = data.get("response", "")
        text = str(content).strip()
        if len(text) > 12000:
            text = text[:12000]
        return text, elapsed_ms

    async def test_model(self, model: str, timeout: float = 15.0) -> dict[str, Any]:
        """Runs a lightweight single-sentence ping test to measure response latency."""
        if not model:
            return {"ok": False, "error": "Aucun modèle sélectionné.", "latency_ms": 0}
        url = f"{self.base_url}/api/chat"
        body = {
            "model": model,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 40},
            "messages": [
                {
                    "role": "user",
                    "content": "Réponds uniquement par : NÉO prêt pour la session.",
                }
            ],
        }
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=body)
                resp.raise_for_status()
                data = resp.json()
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            reply = str((data.get("message") or {}).get("content") or "").strip()
            return {"ok": True, "reply": reply, "latency_ms": elapsed_ms}
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return {"ok": False, "error": str(exc), "latency_ms": elapsed_ms}
