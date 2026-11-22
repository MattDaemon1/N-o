"""Local CPU Piper TTS synthesis engine (supports piper-tts Python or piper binary)."""

from __future__ import annotations

import array
import gc
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.tts.voice_manager import VoiceManager

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None  # type: ignore[assignment]

try:
    from piper.voice import PiperVoice
except Exception:  # pragma: no cover - optional when using standalone piper.exe binary
    PiperVoice = None  # type: ignore[assignment]


@dataclass
class SynthesizedAudio:
    pcm_int16: bytes
    sample_rate: int
    duration_ms: int
    error: str | None = None


class PiperTTSEngine:
    """Thread-safe local CPU Piper wrapper with lazy-load, RAM unload, and immediate abort."""

    def __init__(
        self,
        voice_manager: VoiceManager | None = None,
        tools_dir: Path | str | None = None,
    ) -> None:
        self.voice_manager = voice_manager or VoiceManager()
        default_tools = Path(__file__).resolve().parents[2] / "tools" / "piper"
        self.tools_dir = Path(tools_dir) if tools_dir else default_tools

        self._model_lock = threading.RLock()
        self._proc_lock = threading.RLock()
        self._abort_requested = threading.Event()
        self._loaded_voice_id: str = ""
        self._piper_voice: Any = None
        self._active_proc: subprocess.Popen[bytes] | None = None
        self._last_used_monotonic: float = 0.0

    def find_piper_binary(self) -> Path | None:
        env_path = os.environ.get("PIPER_EXE_PATH", "").strip()
        if env_path:
            p = Path(env_path)
            if p.is_file():
                return p

        for candidate in (
            self.tools_dir / "piper.exe",
            self.tools_dir / "piper",
        ):
            if candidate.is_file():
                return candidate

        which_bin = shutil.which("piper.exe") or shutil.which("piper")
        return Path(which_bin) if which_bin else None

    def get_backend_info(self) -> dict[str, Any]:
        bin_path = self.find_piper_binary()
        python_ok = PiperVoice is not None
        available = python_ok or (bin_path is not None)
        backend = "python_piper" if python_ok else ("piper_cli" if bin_path is not None else "absent")
        return {
            "available": available,
            "backend": backend,
            "python_piper_installed": python_ok,
            "piper_binary_path": str(bin_path) if bin_path else "",
            "model_loaded": self._piper_voice is not None,
            "loaded_voice": self._loaded_voice_id,
        }

    def is_loaded(self) -> bool:
        with self._model_lock:
            return self._piper_voice is not None

    def last_used_monotonic(self) -> float:
        return self._last_used_monotonic

    def unload(self) -> None:
        self.abort_synthesis()
        with self._model_lock:
            if self._piper_voice is not None:
                self._piper_voice = None
                self._loaded_voice_id = ""
                gc.collect()

    def abort_synthesis(self) -> None:
        self._abort_requested.set()
        with self._proc_lock:
            proc = self._active_proc
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=0.35)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                self._active_proc = None

    @staticmethod
    def apply_volume_int16(pcm_int16: bytes, volume: float) -> bytes:
        vol = max(0.0, min(1.0, float(volume)))
        if not pcm_int16 or abs(vol - 1.0) < 1e-3:
            return pcm_int16
        if vol <= 0.0:
            return b"\x00" * len(pcm_int16)

        if np is not None:
            arr = np.frombuffer(pcm_int16, dtype=np.int16).astype(np.float32)
            scaled = np.clip(arr * vol, -32768.0, 32767.0).astype(np.int16)
            return scaled.tobytes()

        arr_py = array.array("h")
        arr_py.frombytes(pcm_int16)
        for i, sample in enumerate(arr_py):
            val = int(sample * vol)
            if val > 32767:
                val = 32767
            elif val < -32768:
                val = -32768
            arr_py[i] = val
        return arr_py.tobytes()

    def _synthesize_with_python_piper(
        self,
        *,
        text: str,
        voice_id: str,
        onnx_path: Path,
        json_path: Path,
        sample_rate: int,
        length_scale: float,
    ) -> SynthesizedAudio:
        with self._model_lock:
            if self._piper_voice is None or self._loaded_voice_id != voice_id:
                if self._piper_voice is not None:
                    self._piper_voice = None
                    gc.collect()
                self._piper_voice = PiperVoice.load(str(onnx_path), config_path=str(json_path), use_cuda=False)
                self._loaded_voice_id = voice_id

            chunks: list[bytes] = []
            if hasattr(self._piper_voice, "synthesize_stream_raw"):
                try:
                    gen = self._piper_voice.synthesize_stream_raw(text, length_scale=length_scale)
                except TypeError:
                    gen = self._piper_voice.synthesize_stream_raw(text)
                for chunk in gen:
                    if self._abort_requested.is_set():
                        return SynthesizedAudio(pcm_int16=b"", sample_rate=sample_rate, duration_ms=0, error="Synthèse annulée.")
                    chunks.append(bytes(chunk))
            else:
                for audio_chunk in self._piper_voice.synthesize(text):
                    if self._abort_requested.is_set():
                        return SynthesizedAudio(pcm_int16=b"", sample_rate=sample_rate, duration_ms=0, error="Synthèse annulée.")
                    raw = getattr(audio_chunk, "audio_int16_bytes", None)
                    chunks.append(bytes(raw) if raw is not None else bytes(audio_chunk))

        return SynthesizedAudio(
            pcm_int16=b"".join(chunks),
            sample_rate=sample_rate,
            duration_ms=0,
            error=None,
        )

    def _synthesize_with_cli(
        self,
        *,
        bin_path: Path,
        text: str,
        onnx_path: Path,
        json_path: Path,
        sample_rate: int,
        length_scale: float,
        timeout: float,
    ) -> SynthesizedAudio:
        cmd = [
            str(bin_path),
            "--model",
            str(onnx_path),
            "--config",
            str(json_path),
            "--length_scale",
            f"{length_scale:.3f}",
            "--output_raw",
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
        )
        with self._proc_lock:
            self._active_proc = proc

        try:
            stdout_data, stderr_data = proc.communicate(input=text.encode("utf-8"), timeout=timeout)
        except subprocess.TimeoutExpired:
            self.abort_synthesis()
            return SynthesizedAudio(
                pcm_int16=b"",
                sample_rate=sample_rate,
                duration_ms=0,
                error=f"Délai TTS dépassé ({timeout:.0f} s).",
            )
        finally:
            with self._proc_lock:
                if self._active_proc is proc:
                    self._active_proc = None

        if self._abort_requested.is_set():
            return SynthesizedAudio(
                pcm_int16=b"",
                sample_rate=sample_rate,
                duration_ms=0,
                error="Synthèse annulée.",
            )

        if proc.returncode != 0:
            err_txt = stderr_data.decode("utf-8", errors="replace").strip()
            return SynthesizedAudio(
                pcm_int16=b"",
                sample_rate=sample_rate,
                duration_ms=0,
                error=f"Erreur moteur Piper (code {proc.returncode}) : {err_txt or 'échec synthèse'}",
            )

        return SynthesizedAudio(
            pcm_int16=stdout_data,
            sample_rate=sample_rate,
            duration_ms=0,
            error=None,
        )

    def synthesize_pcm(
        self,
        *,
        text: str,
        voice_id: str,
        speed: float = 1.0,
        volume: float = 0.9,
        timeout: float = 15.0,
    ) -> SynthesizedAudio:
        start = time.perf_counter()
        if not text or not text.strip():
            return SynthesizedAudio(pcm_int16=b"", sample_rate=22050, duration_ms=0, error="Texte vide.")

        valid, v_err, sample_rate = self.voice_manager.validate_voice(voice_id)
        if not valid:
            return SynthesizedAudio(
                pcm_int16=b"",
                sample_rate=sample_rate,
                duration_ms=int((time.perf_counter() - start) * 1000),
                error=v_err,
            )

        onnx_path, json_path = self.voice_manager.get_voice_paths(voice_id)
        length_scale = round(1.0 / max(0.65, min(1.5, float(speed))), 3)
        self._abort_requested.clear()
        self._last_used_monotonic = time.monotonic()

        try:
            if PiperVoice is not None:
                res = self._synthesize_with_python_piper(
                    text=text,
                    voice_id=voice_id,
                    onnx_path=onnx_path,
                    json_path=json_path,
                    sample_rate=sample_rate,
                    length_scale=length_scale,
                )
            else:
                bin_path = self.find_piper_binary()
                if bin_path is None:
                    return SynthesizedAudio(
                        pcm_int16=b"",
                        sample_rate=sample_rate,
                        duration_ms=int((time.perf_counter() - start) * 1000),
                        error=(
                            "Moteur Piper TTS introuvable. Installez 'piper-tts' dans .venv "
                            "ou placez piper.exe dans neo/tools/piper/."
                        ),
                    )
                res = self._synthesize_with_cli(
                    bin_path=bin_path,
                    text=text,
                    onnx_path=onnx_path,
                    json_path=json_path,
                    sample_rate=sample_rate,
                    length_scale=length_scale,
                    timeout=timeout,
                )

            if self._abort_requested.is_set() and not res.error:
                return SynthesizedAudio(
                    pcm_int16=b"",
                    sample_rate=sample_rate,
                    duration_ms=int((time.perf_counter() - start) * 1000),
                    error="Synthèse annulée.",
                )

            if res.error:
                res.duration_ms = int((time.perf_counter() - start) * 1000)
                return res

            if not res.pcm_int16:
                return SynthesizedAudio(
                    pcm_int16=b"",
                    sample_rate=sample_rate,
                    duration_ms=int((time.perf_counter() - start) * 1000),
                    error="Synthèse vocale vide retournée par Piper.",
                )

            scaled_pcm = self.apply_volume_int16(res.pcm_int16, volume)
            self._last_used_monotonic = time.monotonic()
            return SynthesizedAudio(
                pcm_int16=scaled_pcm,
                sample_rate=res.sample_rate,
                duration_ms=int((time.perf_counter() - start) * 1000),
                error=None,
            )
        except Exception as exc:
            return SynthesizedAudio(
                pcm_int16=b"",
                sample_rate=sample_rate,
                duration_ms=int((time.perf_counter() - start) * 1000),
                error=f"Erreur interne synthèse vocale : {exc}",
            )
