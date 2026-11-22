"""Read-only environment verification script for NÉO (no downloads, no mutations)."""

from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path

REQUIRED_MODULES = [
    "fastapi",
    "uvicorn",
    "pydantic",
    "httpx",
    "sounddevice",
    "numpy",
    "faster_whisper",
    "psutil",
    "jinja2",
]


def _check_piper_tts(root: Path) -> str:
    try:
        importlib.import_module("piper.voice")
        return "Module Python piper-tts installé"
    except Exception:
        pass

    for candidate in (
        root / "tools" / "piper" / "piper.exe",
        root / "tools" / "piper" / "piper",
    ):
        if candidate.is_file():
            return f"Binaire local détecté ({candidate.name})"

    which_bin = shutil.which("piper.exe") or shutil.which("piper")
    if which_bin:
        return f"Binaire PATH détecté ({which_bin})"

    return "Non installé (optionnel : voir README.md pour installer Piper TTS)"


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    print(f"Python détecté : {sys.version.split()[0]}")
    if sys.version_info < (3, 11):
        print("ERREUR : Python 3.11 ou supérieur est recommandé.")
        return 1

    missing: list[str] = []
    for mod in REQUIRED_MODULES:
        try:
            importlib.import_module(mod)
            print(f"  [OK] {mod}")
        except ImportError:
            print(f"  [MANQUANT] {mod}")
            missing.append(mod)

    tts_status = _check_piper_tts(root)
    voices_dir = root / "models" / "voices"
    voice_count = len(list(voices_dir.glob("*.onnx"))) if voices_dir.exists() else 0
    print(f"  [TTS] Piper : {tts_status} | Voix locales (.onnx) : {voice_count}")

    if missing:
        print("\nDépendances manquantes. Exécutez :")
        print("  pip install -r requirements.txt")
        return 1

    print("\nEnvironnement prêt pour NÉO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
