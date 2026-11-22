"""System, audio, STT, and Ollama diagnostics service (no implicit downloads)."""

from __future__ import annotations

import platform
import sys
import threading
import time
from typing import Any

from app.ai.model_manager import ModelManager
from app.audio.capture import AudioCapture
from app.audio.segmentation import SegmentQueueManager
from app.audio.stt import FasterWhisperSTT
from app.config.config_manager import ConfigManager
from app.config.defaults import APP_VERSION
from app.core.state_manager import StateManager

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]


class DiagnosticsService:
    """Collects non-intrusive system and pipeline telemetry."""

    def __init__(
        self,
        *,
        config_manager: ConfigManager,
        state_manager: StateManager,
        model_manager: ModelManager,
        audio_capture: AudioCapture,
        segment_queue: SegmentQueueManager,
        stt: FasterWhisperSTT,
        tts_service: Any | None = None,
        inventory_ttl_seconds: float = 12.0,
    ) -> None:
        self.config_manager = config_manager
        self.state_manager = state_manager
        self.model_manager = model_manager
        self.audio_capture = audio_capture
        self.segment_queue = segment_queue
        self.stt = stt
        self.tts_service = tts_service

        self._inventory_lock = threading.RLock()
        self._inventory_ttl_seconds = max(0.0, float(inventory_ttl_seconds))
        self._inventory_cached_at: float = 0.0
        self._cached_installed_stt: list[str] = []
        self._cached_devices: list[Any] = []
        self._cached_mic_err: str | None = None

    def invalidate_inventory_cache(self) -> None:
        with self._inventory_lock:
            self._inventory_cached_at = 0.0
        if self.tts_service is not None and hasattr(self.tts_service, "invalidate_inventory_cache"):
            self.tts_service.invalidate_inventory_cache()

    def _system_resources(self) -> dict[str, Any]:
        cpu_percent: float | None = None
        ram_available_mb: int | None = None
        ram_total_mb: int | None = None
        ram_percent: float | None = None

        if psutil is not None:
            try:
                cpu_percent = round(float(psutil.cpu_percent(interval=None)), 1)
                vm = psutil.virtual_memory()
                ram_available_mb = int(vm.available / (1024 * 1024))
                ram_total_mb = int(vm.total / (1024 * 1024))
                ram_percent = round(float(vm.percent), 1)
            except Exception:
                pass

        return {
            "os": f"{platform.system()} {platform.release()}",
            "python_version": sys.version.split()[0],
            "cpu_percent": cpu_percent,
            "ram_available_mb": ram_available_mb,
            "ram_total_mb": ram_total_mb,
            "ram_percent": ram_percent,
        }

    def _get_inventory(self, *, force_refresh: bool) -> tuple[list[str], list[Any], str | None]:
        now = time.monotonic()
        with self._inventory_lock:
            expired = (
                self._inventory_cached_at == 0.0
                or (now - self._inventory_cached_at) >= self._inventory_ttl_seconds
            )
            if force_refresh or expired:
                self._cached_installed_stt = self.stt.list_installed_models()
                self._cached_devices, self._cached_mic_err = AudioCapture.list_devices()
                self._inventory_cached_at = now
            return (
                list(self._cached_installed_stt),
                list(self._cached_devices),
                self._cached_mic_err,
            )

    async def snapshot(
        self,
        refresh_ollama: bool = False,
        refresh_inventory: bool = False,
    ) -> dict[str, Any]:
        cfg = self.config_manager.config
        if refresh_ollama:
            ollama_info = await self.model_manager.refresh()
        else:
            ollama_info = {
                "connected": self.model_manager.connected,
                "ollama_url": cfg.ollama_url,
                "selected_model": cfg.ollama_model,
                "models": [m.to_dict() for m in self.model_manager.installed_models],
                "error": self.model_manager.last_error,
            }

        installed_stt, devices, mic_err = self._get_inventory(force_refresh=refresh_inventory)
        if self.tts_service is not None:
            tts_info = self.tts_service.get_status(refresh_inventory=refresh_inventory)
        else:
            tts_info = {}

        return {
            "app_version": APP_VERSION,
            "system": self._system_resources(),
            "ollama": ollama_info,
            "audio": {
                "mic_active": self.state_manager.mic_active,
                "selected_device_index": cfg.mic_device_index,
                "selected_device_name": cfg.mic_device_name,
                "detected_devices_count": len(devices),
                "error": self.audio_capture.last_error or mic_err,
                "pending_segments": self.segment_queue.pending_count(),
                "dropped_segments": self.segment_queue.dropped_count,
            },
            "stt": {
                "selected_model": cfg.stt_model,
                "compute_type": cfg.stt_compute_type,
                "language": cfg.stt_language,
                "installed_models": installed_stt,
                "selected_installed": cfg.stt_model in installed_stt,
            },
            "tts": tts_info,
            "pipeline": {
                "neo_state": self.state_manager.state.value,
                "mode": cfg.mode,
                "vocal_mode": cfg.vocal_mode,
                "session_active": self.state_manager.session_active,
                "segments_processed": self.state_manager.metrics.segments_processed,
                "errors_count": self.state_manager.metrics.errors_count,
                "interventions_count": self.state_manager.metrics.interventions_count,
                "tts_spoken_count": self.state_manager.metrics.tts_spoken_count,
                "tts_interrupted_count": self.state_manager.metrics.tts_interrupted_count,
                "last_transcription_ms": self.state_manager.metrics.last_transcription_ms,
                "last_llm_ms": self.state_manager.metrics.last_llm_ms,
                "last_tts_ms": self.state_manager.metrics.last_tts_ms,
                "last_error": self.state_manager.last_error,
            },
        }

    async def run_global_check(self) -> dict[str, Any]:
        """Performs a read-only check across config, Ollama, microphone, local STT, and local TTS."""
        snap = await self.snapshot(refresh_ollama=True, refresh_inventory=True)
        tts_snap = snap.get("tts") or {}
        tts_backend = tts_snap.get("backend") or {}
        tts_enabled = bool(tts_snap.get("tts_enabled"))
        tts_ready = bool(tts_backend.get("available")) and bool(tts_snap.get("selected_voice_installed"))

        checks = [
            {
                "name": "Configuration locale",
                "ok": self.config_manager.last_warning is None,
                "detail": self.config_manager.last_warning or "dashboard_config.json valide.",
            },
            {
                "name": "Connexion Ollama",
                "ok": snap["ollama"]["connected"],
                "detail": (
                    f"{len(snap['ollama']['models'])} modèle(s) détecté(s)."
                    if snap["ollama"]["connected"]
                    else snap["ollama"]["error"] or "Ollama déconnecté."
                ),
            },
            {
                "name": "Modèle LLM sélectionné",
                "ok": bool(snap["ollama"]["selected_model"])
                and any(
                    m["name"] == snap["ollama"]["selected_model"]
                    for m in snap["ollama"]["models"]
                ),
                "detail": snap["ollama"]["selected_model"]
                or "Aucun modèle sélectionné dans la liste Ollama.",
            },
            {
                "name": "Périphériques microphone",
                "ok": snap["audio"]["detected_devices_count"] > 0,
                "detail": (
                    f"{snap['audio']['detected_devices_count']} entrée(s) audio détectée(s)."
                    if snap["audio"]["detected_devices_count"] > 0
                    else snap["audio"]["error"] or "Aucun microphone détecté."
                ),
            },
            {
                "name": "Modèle STT Faster-Whisper (cache local)",
                "ok": snap["stt"]["selected_installed"],
                "detail": (
                    f"Modèle '{snap['stt']['selected_model']}' présent en local."
                    if snap["stt"]["selected_installed"]
                    else f"Modèle '{snap['stt']['selected_model']}' non téléchargé en local."
                ),
            },
            {
                "name": "Synthèse vocale locale (Piper TTS)",
                "ok": (not tts_enabled) or tts_ready,
                "detail": (
                    f"Voix '{tts_snap.get('selected_voice')}' prête ({tts_backend.get('backend', 'local')})."
                    if tts_ready
                    else (
                        "Voix désactivée (mode texte uniquement)."
                        if not tts_enabled
                        else tts_snap.get("selected_voice_error")
                        or "Moteur Piper ou voix française manquante."
                    )
                ),
            },
        ]
        return {"ok": all(c["ok"] for c in checks), "checks": checks, "snapshot": snap}
