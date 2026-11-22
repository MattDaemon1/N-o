"""Persistent JSON configuration manager for NÉO."""

from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .defaults import NeoConfig


class ConfigManager:
    """Loads, validates, persists, and recovers dashboard_config.json safely."""

    def __init__(self, config_path: Path | str = "dashboard_config.json") -> None:
        self.config_path = Path(config_path)
        self._lock = threading.RLock()
        self.last_warning: str | None = None
        self._config: NeoConfig = self.load()

    @property
    def config(self) -> NeoConfig:
        with self._lock:
            return self._config

    def load(self) -> NeoConfig:
        with self._lock:
            self.last_warning = None
            if not self.config_path.exists():
                default_cfg = NeoConfig()
                self.save(default_cfg)
                return default_cfg

            try:
                raw_text = self.config_path.read_text(encoding="utf-8")
                data = json.loads(raw_text)
                cfg = NeoConfig.model_validate(data)
                self._config = cfg
                return cfg
            except (OSError, json.JSONDecodeError, ValidationError) as exc:
                backup_path = self.config_path.with_suffix(".corrupted.bak")
                try:
                    if self.config_path.exists():
                        shutil.copy2(self.config_path, backup_path)
                except OSError:
                    pass
                self.last_warning = (
                    f"Fichier de configuration corrompu ({exc}). "
                    "Configuration par défaut restaurée."
                )
                return self._write_validated(NeoConfig())

    def _write_validated(self, validated: NeoConfig) -> NeoConfig:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(validated.model_dump(), indent=2, ensure_ascii=False) + "\n"
        tmp_path = self.config_path.with_name(f".{self.config_path.name}.tmp")
        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(tmp_path, self.config_path)
        self._config = validated
        return self._config

    def save(self, config: NeoConfig) -> NeoConfig:
        with self._lock:
            validated = NeoConfig.model_validate(config.model_dump())
            return self._write_validated(validated)

    def update(self, patch: dict[str, Any]) -> NeoConfig:
        with self._lock:
            current = self._config.model_dump()
            merged = _deep_merge(current, patch)
            updated = NeoConfig.model_validate(merged)
            return self._write_validated(updated)

    def reset_defaults(self) -> NeoConfig:
        with self._lock:
            self.last_warning = None
            return self._write_validated(NeoConfig())


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
