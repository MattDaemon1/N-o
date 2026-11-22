"""Local model availability manager for Ollama (no implicit downloads)."""

from __future__ import annotations

from typing import Any

from app.ai.ollama_client import OllamaClient, OllamaModelInfo
from app.config.config_manager import ConfigManager


class ModelManager:
    """Queries installed Ollama models and manages active model selection."""

    def __init__(self, config_manager: ConfigManager, client: OllamaClient) -> None:
        self.config_manager = config_manager
        self.client = client
        self.connected: bool = False
        self.last_error: str | None = None
        self.installed_models: list[OllamaModelInfo] = []

    async def refresh(self) -> dict[str, Any]:
        cfg = self.config_manager.config
        self.client.set_base_url(cfg.ollama_url)
        ok, models, err = await self.client.list_models()
        self.connected = ok
        self.installed_models = models
        self.last_error = err

        selected = cfg.ollama_model
        selected_available = any(m.name == selected for m in models) if selected else False

        return {
            "connected": self.connected,
            "ollama_url": cfg.ollama_url,
            "ai_enabled": cfg.ai_enabled,
            "selected_model": selected,
            "selected_available": selected_available,
            "models": [m.to_dict() for m in models],
            "error": self.last_error,
        }

    def select_model(self, model_name: str) -> dict[str, Any]:
        self.config_manager.update({"ollama_model": model_name})
        available = any(m.name == model_name for m in self.installed_models)
        return {"selected_model": model_name, "available": available}

    async def test_selected_model(self, model_name: str | None = None) -> dict[str, Any]:
        target = model_name or self.config_manager.config.ollama_model
        self.client.set_base_url(self.config_manager.config.ollama_url)
        return await self.client.test_model(target, timeout=self.config_manager.config.llm_timeout_seconds)
