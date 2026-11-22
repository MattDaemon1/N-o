"""Local CPU Speech-to-Text via Faster-Whisper (no implicit model downloads)."""

from __future__ import annotations

import gc
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from faster_whisper import WhisperModel
except ImportError:  # pragma: no cover - optional in test environments
    WhisperModel = None  # type: ignore[assignment]


SUPPORTED_WHISPER_MODELS = ["tiny", "base", "small", "medium"]


@dataclass
class TranscriptionResult:
    text: str
    is_empty: bool
    is_uncertain: bool
    avg_logprob: float
    duration_ms: int
    error: str | None = None


class FasterWhisperSTT:
    """CPU-friendly French STT wrapper with explicit model installation policy."""

    def __init__(self, cache_dir: Path | str | None = None) -> None:
        self._model: Any = None
        self._loaded_model_name: str = ""
        self._loaded_compute_type: str = ""
        self.cache_dir = Path(cache_dir) if cache_dir else self._default_hf_cache_dir()

    @staticmethod
    def _default_hf_cache_dir() -> Path:
        hf_home = os.environ.get("HF_HOME")
        if hf_home:
            return Path(hf_home) / "hub"
        return Path.home() / ".cache" / "huggingface" / "hub"

    def list_installed_models(self) -> list[str]:
        """Inspects local HuggingFace cache for already-installed Systran faster-whisper models."""
        installed: list[str] = []
        if not self.cache_dir.exists():
            return installed
        for name in SUPPORTED_WHISPER_MODELS:
            folder = self.cache_dir / f"models--Systran--faster-whisper-{name}"
            if folder.exists():
                installed.append(name)
        return installed

    def is_model_installed(self, model_name: str) -> bool:
        return model_name in self.list_installed_models()

    def unload_model(self) -> None:
        """Releases Faster-Whisper model weights from RAM when idle or stopped."""
        if self._model is not None:
            self._model = None
            self._loaded_model_name = ""
            self._loaded_compute_type = ""
            gc.collect()

    def load_local_model(self, model_name: str, compute_type: str = "int8") -> tuple[bool, str | None]:
        """Loads model ONLY from local cache (local_files_only=True). Never downloads silently."""
        if WhisperModel is None:
            return False, "faster-whisper n'est pas installé dans l'environnement Python."

        if (
            self._model is not None
            and self._loaded_model_name == model_name
            and self._loaded_compute_type == compute_type
        ):
            return True, None

        # Free previous model before loading a new one to preserve 8 GB RAM
        if self._model is not None:
            self.unload_model()

        try:
            self._model = WhisperModel(
                model_name,
                device="cpu",
                compute_type=compute_type,
                cpu_threads=2,
                local_files_only=True,
            )
            self._loaded_model_name = model_name
            self._loaded_compute_type = compute_type
            return True, None
        except Exception as exc:
            self._model = None
            return (
                False,
                f"Modèle STT '{model_name}' absent du cache local. "
                f"Téléchargez-le explicitement depuis l'onglet Audio & STT ({exc}).",
            )

    def download_model_explicitly(self, model_name: str, compute_type: str = "int8") -> tuple[bool, str]:
        """Triggered ONLY upon explicit user button click."""
        if WhisperModel is None:
            return False, "faster-whisper n'est pas installé."
        if model_name not in SUPPORTED_WHISPER_MODELS:
            return False, f"Modèle non pris en charge : {model_name}."
        try:
            self._model = WhisperModel(
                model_name,
                device="cpu",
                compute_type=compute_type,
                cpu_threads=2,
                local_files_only=False,
            )
            self._loaded_model_name = model_name
            self._loaded_compute_type = compute_type
            return True, f"Modèle STT '{model_name}' installé et prêt."
        except Exception as exc:
            return False, f"Échec du téléchargement de '{model_name}' : {exc}"

    def transcribe_wav(
        self,
        wav_path: Path,
        *,
        model_name: str = "small",
        compute_type: str = "int8",
        language: str = "fr",
    ) -> TranscriptionResult:
        start = time.perf_counter()
        ok, err = self.load_local_model(model_name, compute_type)
        if not ok or self._model is None:
            return TranscriptionResult(
                text="",
                is_empty=True,
                is_uncertain=True,
                avg_logprob=-99.0,
                duration_ms=int((time.perf_counter() - start) * 1000),
                error=err,
            )

        try:
            segments, _info = self._model.transcribe(
                str(wav_path),
                language=language,
                beam_size=1,
                vad_filter=False,
                condition_on_previous_text=False,
            )
            texts: list[str] = []
            logprobs: list[float] = []
            no_speech_probs: list[float] = []
            for seg in segments:
                txt = (seg.text or "").strip()
                if txt:
                    texts.append(txt)
                logprobs.append(float(getattr(seg, "avg_logprob", -0.3)))
                no_speech_probs.append(float(getattr(seg, "no_speech_prob", 0.0)))

            full_text = " ".join(texts).strip()
            avg_lp = sum(logprobs) / len(logprobs) if logprobs else -1.0
            max_no_speech = max(no_speech_probs) if no_speech_probs else 1.0
            is_empty = len(full_text) < 2
            is_uncertain = is_empty or avg_lp < -1.15 or max_no_speech > 0.78

            return TranscriptionResult(
                text=full_text,
                is_empty=is_empty,
                is_uncertain=is_uncertain,
                avg_logprob=round(avg_lp, 3),
                duration_ms=int((time.perf_counter() - start) * 1000),
                error=None,
            )
        except Exception as exc:
            return TranscriptionResult(
                text="",
                is_empty=True,
                is_uncertain=True,
                avg_logprob=-99.0,
                duration_ms=int((time.perf_counter() - start) * 1000),
                error=f"Erreur STT Faster-Whisper : {exc}",
            )
