"""Dedicated non-blocking TTS worker thread with single-slot execution & instant stop."""

from __future__ import annotations

import os
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.tts.engine import PiperTTSEngine

try:
    import sounddevice as sd
except Exception:  # pragma: no cover
    sd = None  # type: ignore[assignment]

try:
    import winsound  # type: ignore[import-not-found]
except ImportError:
    winsound = None  # type: ignore[assignment]


@dataclass
class SpeechJob:
    job_id: int
    text: str
    voice_id: str
    speed: float
    volume: float
    delay_ms: int
    on_start: Callable[[int, str], None] | None = None
    on_playback: Callable[[int, str], None] | None = None
    on_finish: Callable[[int, bool, int, str | None], None] | None = None


class SpeakerWorker:
    """Serialized single-speaker thread: max 1 active speech, instant stop (~20 ms chunks), zero audio backlog."""

    def __init__(self, engine: PiperTTSEngine) -> None:
        self.engine = engine
        self._lock = threading.RLock()
        self._wakeup = threading.Event()
        self._shutdown_event = threading.Event()
        self._cancel_event = threading.Event()

        self._thread: threading.Thread | None = None
        self._pending_job: SpeechJob | None = None
        self._active_job: SpeechJob | None = None
        self._job_counter = 0
        self._auto_unload_seconds = 120
        self._active_stream: Any = None

    def set_auto_unload_seconds(self, seconds: int) -> None:
        self._auto_unload_seconds = max(0, int(seconds))

    def current_job_id(self) -> int:
        with self._lock:
            return self._job_counter

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._shutdown_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop, name="neo-tts-worker", daemon=True
            )
            self._thread.start()

    def stop_worker(self) -> None:
        self.interrupt()
        self._shutdown_event.set()
        self._wakeup.set()
        with self._lock:
            thr = self._thread
        if thr is not None and thr.is_alive():
            thr.join(timeout=2.0)
        with self._lock:
            self._thread = None
        self.engine.unload()

    def is_busy(self) -> bool:
        with self._lock:
            return self._pending_job is not None or self._active_job is not None

    def enqueue(
        self,
        *,
        text: str,
        voice_id: str,
        speed: float,
        volume: float,
        delay_ms: int = 0,
        on_start: Callable[[int, str], None] | None = None,
        on_playback: Callable[[int, str], None] | None = None,
        on_finish: Callable[[int, bool, int, str | None], None] | None = None,
    ) -> int:
        """Schedules speech in a single slot (never accumulates an uncontrolled queue)."""
        self.start()
        with self._lock:
            if self._active_job is not None or self._pending_job is not None:
                self._cancel_current_locked()
            self._cancel_event.clear()
            self._job_counter += 1
            job = SpeechJob(
                job_id=self._job_counter,
                text=text,
                voice_id=voice_id,
                speed=speed,
                volume=volume,
                delay_ms=max(0, int(delay_ms)),
                on_start=on_start,
                on_playback=on_playback,
                on_finish=on_finish,
            )
            self._pending_job = job
            self._wakeup.set()
            return job.job_id

    def _cancel_current_locked(self) -> None:
        self._cancel_event.set()
        self._pending_job = None
        self.engine.abort_synthesis()
        # Note: Only call stream.abort() here (safe across threads in PortAudio).
        # stream.close() MUST run exclusively in the worker thread's finally block.
        stream = self._active_stream
        if stream is not None:
            try:
                stream.abort()
            except Exception:
                pass
        if winsound is not None:
            try:
                winsound.PlaySound(None, 0)
            except Exception:
                pass

    def interrupt(self) -> bool:
        """Immediately halts active playback/synthesis and discards any pending speech."""
        with self._lock:
            was_busy = self._pending_job is not None or self._active_job is not None
            self._cancel_current_locked()
            self._wakeup.set()
            return was_busy

    def _run_loop(self) -> None:
        while not self._shutdown_event.is_set():
            self._wakeup.wait(timeout=0.5)
            self._wakeup.clear()
            if self._shutdown_event.is_set():
                break

            with self._lock:
                job = self._pending_job
                self._pending_job = None
                if job is None:
                    if (
                        self._auto_unload_seconds > 0
                        and self.engine.is_loaded()
                        and (time.monotonic() - self.engine.last_used_monotonic()) >= self._auto_unload_seconds
                    ):
                        self.engine.unload()
                    continue
                self._active_job = job
                self._cancel_event.clear()

            self._execute_job(job)

            with self._lock:
                self._active_job = None

    def _execute_job(self, job: SpeechJob) -> None:
        start_total = time.perf_counter()
        interrupted = False
        err_msg: str | None = None

        try:
            # 1. Optional pre-speech delay (allows immediate cancellation if human starts speaking)
            if job.delay_ms > 0:
                deadline = time.monotonic() + (job.delay_ms / 1000.0)
                while time.monotonic() < deadline:
                    if self._shutdown_event.is_set() or self._cancel_event.is_set():
                        interrupted = True
                        return
                    time.sleep(0.02)

            if self._shutdown_event.is_set() or self._cancel_event.is_set():
                interrupted = True
                return

            if job.on_start:
                job.on_start(job.job_id, job.text)

            # 2. CPU synthesis via Piper
            synth = self.engine.synthesize_pcm(
                text=job.text,
                voice_id=job.voice_id,
                speed=job.speed,
                volume=job.volume,
            )
            if self._shutdown_event.is_set() or self._cancel_event.is_set():
                interrupted = True
                return

            if synth.error:
                err_msg = synth.error
                return

            if job.on_playback:
                job.on_playback(job.job_id, job.text)

            # 3. Chunked audio playback (20 ms chunks for rapid interruption)
            interrupted, play_err = self._play_pcm_chunked(synth.pcm_int16, synth.sample_rate)
            if play_err:
                err_msg = play_err
        except Exception as exc:
            err_msg = f"Erreur lecture audio TTS : {exc}"
        finally:
            total_ms = int((time.perf_counter() - start_total) * 1000)
            if job.on_finish:
                try:
                    job.on_finish(job.job_id, interrupted, total_ms, err_msg)
                except Exception:
                    pass

    def _play_pcm_chunked(self, pcm_int16: bytes, sample_rate: int) -> tuple[bool, str | None]:
        if not pcm_int16:
            return False, None

        if sd is not None:
            chunk_frames = max(160, int(sample_rate * 0.02))  # 20 ms per chunk
            chunk_bytes = chunk_frames * 2  # int16 mono
            stream = None
            try:
                stream = sd.RawOutputStream(
                    samplerate=sample_rate,
                    channels=1,
                    dtype="int16",
                    blocksize=chunk_frames,
                )
                with self._lock:
                    self._active_stream = stream
                stream.start()

                for offset in range(0, len(pcm_int16), chunk_bytes):
                    if self._shutdown_event.is_set() or self._cancel_event.is_set():
                        try:
                            stream.abort()
                        except Exception:
                            pass
                        return True, None
                    chunk = pcm_int16[offset : offset + chunk_bytes]
                    stream.write(chunk)
                return False, None
            except Exception as exc:
                if self._cancel_event.is_set() or self._shutdown_event.is_set():
                    return True, None
                return False, f"Sortie audio indisponible : {exc}"
            finally:
                with self._lock:
                    if self._active_stream is stream:
                        self._active_stream = None
                if stream is not None:
                    try:
                        stream.stop()
                        stream.close()
                    except Exception:
                        pass

        # Fallback for Windows if sounddevice is absent: temporary WAV deleted in finally
        if winsound is not None:
            tmp_path: Path | None = None
            try:
                fd, p_str = tempfile.mkstemp(prefix="neo_tts_", suffix=".wav")
                os.close(fd)
                tmp_path = Path(p_str)
                with wave.open(str(tmp_path), "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    wf.writeframes(pcm_int16)
                winsound.PlaySound(str(tmp_path), winsound.SND_FILENAME)
                return self._cancel_event.is_set(), None
            except Exception as exc:
                return self._cancel_event.is_set(), f"Erreur lecture audio Windows : {exc}"
            finally:
                if tmp_path is not None and tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass

        return False, "Aucun module de sortie audio disponible (sounddevice requis)."
