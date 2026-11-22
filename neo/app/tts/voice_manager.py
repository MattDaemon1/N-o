"""Local French Piper voice model discovery, validation, and explicit download."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


@dataclass(frozen=True)
class FrenchVoiceSpec:
    voice_id: str
    label: str
    quality: str
    size_label: str
    license: str
    description: str
    onnx_url: str
    json_url: str


# Curated lightweight CPU-friendly French Piper voices (never auto-downloaded at startup)
CURATED_FRENCH_VOICES: dict[str, FrenchVoiceSpec] = {
    "fr_FR-siwis-medium": FrenchVoiceSpec(
        voice_id="fr_FR-siwis-medium",
        label="Siwis (FR · Medium — Recommandée 8 Go RAM)",
        quality="medium",
        size_label="~63 Mo",
        license="MIT (Piper) / Open Speech (SIWIS)",
        description="Voix française claire, posée et naturelle, optimisée pour CPU.",
        onnx_url="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx",
        json_url="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx.json",
    ),
    "fr_FR-upmc-medium": FrenchVoiceSpec(
        voice_id="fr_FR-upmc-medium",
        label="UPMC (FR · Medium)",
        quality="medium",
        size_label="~63 Mo",
        license="MIT (Piper) / CC-BY (UPMC)",
        description="Voix française articulée adaptée aux explications techniques.",
        onnx_url="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/fr/fr_FR/upmc/medium/fr_FR-upmc-medium.onnx",
        json_url="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/fr/fr_FR/upmc/medium/fr_FR-upmc-medium.onnx.json",
    ),
    "fr_FR-tom-medium": FrenchVoiceSpec(
        voice_id="fr_FR-tom-medium",
        label="Tom (FR · Medium)",
        quality="medium",
        size_label="~63 Mo",
        license="MIT (Piper) / Open Voice",
        description="Voix masculine calme et intelligible.",
        onnx_url="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/fr/fr_FR/tom/medium/fr_FR-tom-medium.onnx",
        json_url="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/fr/fr_FR/tom/medium/fr_FR-tom-medium.onnx.json",
    ),
    "fr_FR-gilles-low": FrenchVoiceSpec(
        voice_id="fr_FR-gilles-low",
        label="Gilles (FR · Low — Ultra légère)",
        quality="low",
        size_label="~18 Mo",
        license="MIT (Piper) / Open Voice",
        description="Voix très légère consommant un minimum de RAM et de disque.",
        onnx_url="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/fr/fr_FR/gilles/low/fr_FR-gilles-low.onnx",
        json_url="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/fr/fr_FR/gilles/low/fr_FR-gilles-low.onnx.json",
    ),
}


@dataclass
class FrenchVoiceInfo:
    voice_id: str
    label: str
    quality: str
    size_label: str
    license: str
    description: str
    installed: bool
    valid: bool
    error: str | None = None
    onnx_path: str = ""
    json_path: str = ""
    is_custom: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "voice_id": self.voice_id,
            "label": self.label,
            "quality": self.quality,
            "size_label": self.size_label,
            "license": self.license,
            "description": self.description,
            "installed": self.installed,
            "valid": self.valid,
            "error": self.error,
            "onnx_path": self.onnx_path,
            "json_path": self.json_path,
            "is_custom": self.is_custom,
        }


class VoiceManager:
    """Manages local Piper voice files in neo/models/voices/ without implicit downloads."""

    MIN_ONNX_BYTES = 512

    def __init__(self, voices_dir: Path | str | None = None) -> None:
        default_dir = Path(__file__).resolve().parents[2] / "models" / "voices"
        self.voices_dir = Path(voices_dir) if voices_dir else default_dir

    def get_voice_paths(self, voice_id: str) -> tuple[Path, Path]:
        safe_id = Path(voice_id).name
        onnx_path = self.voices_dir / f"{safe_id}.onnx"
        json_path = self.voices_dir / f"{safe_id}.onnx.json"
        return onnx_path, json_path

    def validate_voice(self, voice_id: str) -> tuple[bool, str | None, int]:
        """Validates local .onnx + .onnx.json files; returns (ok, error, sample_rate)."""
        if not voice_id or not voice_id.strip():
            return False, "Aucun identifiant de voix sélectionné.", 22050

        onnx_path, json_path = self.get_voice_paths(voice_id)
        if not onnx_path.exists():
            return (
                False,
                f"Modèle vocal '{voice_id}' absent ({onnx_path.name}). Téléchargez-le explicitement ou placez-le dans models/voices/.",
                22050,
            )
        if not json_path.exists():
            return (
                False,
                f"Fichier de configuration '{json_path.name}' manquant pour la voix '{voice_id}'.",
                22050,
            )

        try:
            size_bytes = onnx_path.stat().st_size
            if size_bytes < self.MIN_ONNX_BYTES:
                return (
                    False,
                    f"Modèle vocal '{voice_id}' invalide ou corrompu (fichier .onnx trop petit : {size_bytes} octets).",
                    22050,
                )
            cfg_data = json.loads(json_path.read_text(encoding="utf-8"))
            if not isinstance(cfg_data, dict):
                return False, f"Configuration JSON invalide pour '{voice_id}'.", 22050
            audio_cfg = cfg_data.get("audio") or {}
            sample_rate = int(audio_cfg.get("sample_rate") or 0)
            if sample_rate < 8000 or sample_rate > 48000:
                return (
                    False,
                    f"Configuration audio invalide dans '{json_path.name}' (sample_rate={sample_rate}).",
                    22050,
                )
            return True, None, sample_rate
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return False, f"Modèle vocal '{voice_id}' illisible ou corrompu : {exc}", 22050

    def list_voices(self) -> list[FrenchVoiceInfo]:
        results: list[FrenchVoiceInfo] = []
        seen: set[str] = set()

        for vid, spec in CURATED_FRENCH_VOICES.items():
            seen.add(vid)
            onnx_p, json_p = self.get_voice_paths(vid)
            installed = onnx_p.exists() and json_p.exists()
            valid, err, _ = self.validate_voice(vid) if installed else (False, None, 22050)
            results.append(
                FrenchVoiceInfo(
                    voice_id=vid,
                    label=spec.label,
                    quality=spec.quality,
                    size_label=spec.size_label,
                    license=spec.license,
                    description=spec.description,
                    installed=installed,
                    valid=valid,
                    error=err,
                    onnx_path=str(onnx_p) if onnx_p.exists() else "",
                    json_path=str(json_p) if json_p.exists() else "",
                    is_custom=False,
                )
            )

        if self.voices_dir.exists():
            for onnx_file in sorted(self.voices_dir.glob("*.onnx")):
                vid = onnx_file.stem
                if vid in seen:
                    continue
                seen.add(vid)
                onnx_p, json_p = self.get_voice_paths(vid)
                installed = onnx_p.exists() and json_p.exists()
                valid, err, _ = self.validate_voice(vid)
                size_mb = max(1, int(onnx_file.stat().st_size / (1024 * 1024)))
                results.append(
                    FrenchVoiceInfo(
                        voice_id=vid,
                        label=f"{vid} (Voix locale personnalisée)",
                        quality="locale",
                        size_label=f"~{size_mb} Mo",
                        license="Locale",
                        description="Voix ONNX détectée localement dans models/voices/.",
                        installed=installed,
                        valid=valid,
                        error=err,
                        onnx_path=str(onnx_p),
                        json_path=str(json_p) if json_p.exists() else "",
                        is_custom=True,
                    )
                )
        return results

    def list_installed_voice_ids(self) -> list[str]:
        return [v.voice_id for v in self.list_voices() if v.valid]

    async def download_voice_explicitly(
        self, voice_id: str, timeout_seconds: float = 120.0
    ) -> tuple[bool, str]:
        """Downloads a curated French Piper voice ONLY when triggered explicitly by the user."""
        spec = CURATED_FRENCH_VOICES.get(voice_id)
        if spec is None:
            return (
                False,
                f"Voix '{voice_id}' absente du catalogue intégré. Placez manuellement {voice_id}.onnx et {voice_id}.onnx.json dans models/voices/.",
            )

        self.voices_dir.mkdir(parents=True, exist_ok=True)
        onnx_path, json_path = self.get_voice_paths(voice_id)
        onnx_tmp = onnx_path.with_suffix(".onnx.tmp")
        json_tmp = json_path.with_suffix(".json.tmp")

        try:
            async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
                json_resp = await client.get(spec.json_url)
                json_resp.raise_for_status()
                json_tmp.write_bytes(json_resp.content)

                async with client.stream("GET", spec.onnx_url) as resp:
                    resp.raise_for_status()
                    with onnx_tmp.open("wb") as fh:
                        async for chunk in resp.aiter_bytes(chunk_size=65536):
                            fh.write(chunk)

            os.replace(json_tmp, json_path)
            os.replace(onnx_tmp, onnx_path)
            ok, err, _ = self.validate_voice(voice_id)
            if not ok:
                self.delete_voice(voice_id)
                return False, err or "Voix téléchargée invalide."
            return True, f"Voix française '{voice_id}' installée et prête."
        except Exception as exc:
            for tmp in (onnx_tmp, json_tmp):
                try:
                    if tmp.exists():
                        tmp.unlink()
                except OSError:
                    pass
            return False, f"Échec du téléchargement de la voix '{voice_id}' : {exc}"

    def delete_voice(self, voice_id: str) -> tuple[bool, str]:
        onnx_path, json_path = self.get_voice_paths(voice_id)
        removed = False
        for p in (onnx_path, json_path):
            try:
                if p.exists():
                    p.unlink()
                    removed = True
            except OSError as exc:
                return False, f"Impossible de supprimer {p.name} : {exc}"
        if not removed:
            return False, f"Aucun fichier trouvé pour la voix '{voice_id}'."
        return True, f"Modèle vocal '{voice_id}' désinstallé."
