"""Bounded single-segment queue and temporary WAV lifecycle manager."""

from __future__ import annotations

import os
import queue
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AudioSegment:
    pcm_bytes: bytes
    sample_rate: int
    channels: int
    duration_seconds: float


class SegmentQueueManager:
    """Ensures bounded audio segment buffering and automatic temporary WAV cleanup."""

    def __init__(self, max_pending: int = 3, temp_dir: Path | str | None = None) -> None:
        self.max_pending = max(1, max_pending)
        self._queue: queue.Queue[AudioSegment] = queue.Queue(maxsize=self.max_pending)
        self.temp_dir = Path(temp_dir) if temp_dir else Path(tempfile.gettempdir()) / "neo_audio_tmp"
        self.dropped_count: int = 0

    def enqueue(self, segment: AudioSegment) -> bool:
        if not segment.pcm_bytes:
            return False
        if self._queue.full():
            try:
                self._queue.get_nowait()
                self.dropped_count += 1
            except queue.Empty:
                pass
        try:
            self._queue.put_nowait(segment)
            return True
        except queue.Full:
            return False

    def dequeue(self, timeout: float = 0.25) -> AudioSegment | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def pending_count(self) -> int:
        return self._queue.qsize()

    def set_max_pending(self, max_pending: int) -> None:
        new_max = max(1, int(max_pending))
        if new_max == self.max_pending:
            return
        old_items: list[AudioSegment] = []
        while not self._queue.empty():
            try:
                old_items.append(self._queue.get_nowait())
            except queue.Empty:
                break
        self.max_pending = new_max
        self._queue = queue.Queue(maxsize=self.max_pending)
        for seg in old_items[-self.max_pending :]:
            self._queue.put_nowait(seg)

    def clear(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def write_temp_wav(self, segment: AudioSegment) -> Path:
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        fd, path_str = tempfile.mkstemp(prefix="neo_seg_", suffix=".wav", dir=str(self.temp_dir))
        os.close(fd)
        wav_path = Path(path_str)
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(segment.channels)
            wf.setsampwidth(2)  # int16
            wf.setframerate(segment.sample_rate)
            wf.writeframes(segment.pcm_bytes)
        return wav_path

    @staticmethod
    def delete_temp_wav(wav_path: Path | None, keep_diagnostic: bool = False) -> None:
        if wav_path is None or keep_diagnostic:
            return
        try:
            if wav_path.exists():
                wav_path.unlink()
        except OSError:
            pass
