"""Lightweight non-blocking microphone capture compatible with Windows CPU."""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

try:
    import numpy as np
except ImportError:  # pragma: no cover - fallback when numpy absent in minimal env
    np = None  # type: ignore[assignment]

try:
    import sounddevice as sd
except Exception:  # pragma: no cover - PortAudio / sounddevice optional during unit tests
    sd = None  # type: ignore[assignment]


@dataclass
class MicrophoneDevice:
    index: int
    name: str
    max_input_channels: int
    default_samplerate: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "max_input_channels": self.max_input_channels,
            "default_samplerate": self.default_samplerate,
        }


class AudioCapture:
    """Manages microphone enumeration, testing, and non-blocking frame capture."""

    def __init__(self, frame_queue_size: int = 240) -> None:
        self._frame_queue: queue.Queue[bytes] = queue.Queue(maxsize=frame_queue_size)
        self._stream: Any = None
        self._lock = threading.RLock()
        self._running = False
        self._last_error: str | None = None
        self._current_level: float = 0.0
        self._last_frame_at: float = 0.0

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def current_level(self) -> float:
        return self._current_level

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @staticmethod
    def list_devices() -> tuple[list[MicrophoneDevice], str | None]:
        if sd is None:
            return [], "Module sounddevice indisponible dans cet environnement."
        try:
            devices = sd.query_devices()
            result: list[MicrophoneDevice] = []
            for idx, dev in enumerate(devices):
                if int(dev.get("max_input_channels", 0)) > 0:
                    result.append(
                        MicrophoneDevice(
                            index=idx,
                            name=str(dev.get("name", f"Micro {idx}")),
                            max_input_channels=int(dev.get("max_input_channels", 1)),
                            default_samplerate=int(dev.get("default_samplerate", 16000)),
                        )
                    )
            return result, None
        except Exception as exc:
            return [], f"Impossible de lister les microphones : {exc}"

    @staticmethod
    def compute_rms_int16(pcm_bytes: bytes) -> float:
        if not pcm_bytes:
            return 0.0
        if np is not None:
            arr = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
            if arr.size == 0:
                return 0.0
            rms = float(np.sqrt(np.mean((arr / 32768.0) ** 2)))
            return min(1.0, rms)
        # Pure Python fallback
        import array
        import math

        arr_py = array.array("h")
        arr_py.frombytes(pcm_bytes)
        if not arr_py:
            return 0.0
        mean_sq = sum((s / 32768.0) ** 2 for s in arr_py) / len(arr_py)
        return min(1.0, math.sqrt(mean_sq))

    def test_microphone(
        self,
        device_index: int | None = None,
        sample_rate: int = 16000,
        duration_seconds: float = 1.2,
    ) -> dict[str, Any]:
        if sd is None or np is None:
            return {
                "ok": False,
                "peak_level": 0.0,
                "error": "sounddevice ou numpy indisponible pour tester le microphone.",
            }
        try:
            frames = int(sample_rate * duration_seconds)
            recording = sd.rec(
                frames,
                samplerate=sample_rate,
                channels=1,
                dtype="int16",
                device=device_index,
            )
            sd.wait()
            rms = float(np.sqrt(np.mean((recording.astype(np.float32) / 32768.0) ** 2)))
            peak = float(np.max(np.abs(recording.astype(np.float32) / 32768.0)))
            return {
                "ok": True,
                "rms_level": round(min(1.0, rms), 4),
                "peak_level": round(min(1.0, peak), 4),
                "error": None,
            }
        except Exception as exc:
            return {
                "ok": False,
                "rms_level": 0.0,
                "peak_level": 0.0,
                "error": f"Erreur lors du test microphone : {exc}",
            }

    def start(
        self,
        *,
        device_index: int | None,
        sample_rate: int = 16000,
        channels: int = 1,
        block_size: int = 512,
        on_error: Callable[[str], None] | None = None,
    ) -> bool:
        if sd is None:
            err = "Capture audio impossible : sounddevice n'est pas installé."
            self._last_error = err
            if on_error:
                on_error(err)
            return False

        self.stop()
        self._last_error = None

        def _callback(indata: Any, _frames: int, _time_info: Any, status: Any) -> None:
            if status:
                # PortAudio input overflow/underflow or device warning
                self._last_error = f"Alerte flux audio : {status}"
            else:
                self._last_error = None
            try:
                if np is not None:
                    pcm = bytes(indata)
                else:
                    pcm = bytes(indata)
                self._current_level = self.compute_rms_int16(pcm)
                self._last_frame_at = time.monotonic()
                if self._frame_queue.full():
                    try:
                        self._frame_queue.get_nowait()
                    except queue.Empty:
                        pass
                self._frame_queue.put_nowait(pcm)
            except Exception as exc:
                self._last_error = f"Erreur capture audio : {exc}"

        try:
            with self._lock:
                self._stream = sd.RawInputStream(
                    samplerate=sample_rate,
                    blocksize=block_size,
                    device=device_index,
                    channels=channels,
                    dtype="int16",
                    callback=_callback,
                )
                self._stream.start()
                self._running = True
                self._last_frame_at = time.monotonic()
            return True
        except Exception as exc:
            err = f"Microphone indisponible ou débranché : {exc}"
            self._last_error = err
            self._running = False
            if on_error:
                on_error(err)
            return False

    def read_frame(self, timeout: float = 0.2) -> bytes | None:
        try:
            return self._frame_queue.get(timeout=timeout)
        except queue.Empty:
            # Check for silent disconnection watchdog if running > 4s without frames
            if self._running and self._last_frame_at > 0 and (time.monotonic() - self._last_frame_at) > 4.0:
                self._last_error = "Aucun flux audio reçu : vérifiez que le microphone est branché."
            return None

    def stop(self) -> None:
        with self._lock:
            self._running = False
            self._current_level = 0.0
            self._last_error = None
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            while not self._frame_queue.empty():
                try:
                    self._frame_queue.get_nowait()
                except queue.Empty:
                    break
