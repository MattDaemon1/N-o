"""Lightweight CPU Voice Activity Detector (audio segmentation only)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from app.audio.capture import AudioCapture


@dataclass
class VadEvent:
    speech_started: bool = False
    speech_ended: bool = False
    is_speaking: bool = False
    segment_pcm: bytes | None = None
    duration_seconds: float = 0.0


class VoiceActivityDetector:
    """Energy-based VAD with pre-roll, silence hold, min/max duration guards.

    Strictly responsible for speech/silence segmentation—never makes pedagogical decisions.
    """

    def __init__(
        self,
        *,
        sample_rate: int = 16000,
        energy_threshold: float = 0.018,
        min_speech_seconds: float = 0.6,
        silence_duration_seconds: float = 1.2,
        max_segment_seconds: float = 18.0,
        pre_roll_frames: int = 8,
    ) -> None:
        self.sample_rate = sample_rate
        self.energy_threshold = energy_threshold
        self.min_speech_seconds = min_speech_seconds
        self.silence_duration_seconds = silence_duration_seconds
        self.max_segment_seconds = max_segment_seconds
        self._pre_roll: deque[bytes] = deque(maxlen=max(1, pre_roll_frames))

        self._speaking = False
        self._speech_buffer = bytearray()
        self._speech_seconds = 0.0
        self._silence_seconds = 0.0

    def reset(self) -> None:
        self._speaking = False
        self._speech_buffer.clear()
        self._speech_seconds = 0.0
        self._silence_seconds = 0.0
        self._pre_roll.clear()

    def process_frame(self, pcm_int16: bytes, level_override: float | None = None) -> VadEvent:
        if not pcm_int16:
            return VadEvent(is_speaking=self._speaking)

        frame_seconds = (len(pcm_int16) / 2) / max(1, self.sample_rate)
        rms = level_override if level_override is not None else AudioCapture.compute_rms_int16(pcm_int16)
        is_voice = rms >= self.energy_threshold

        if not self._speaking:
            self._pre_roll.append(pcm_int16)
            if is_voice:
                self._speaking = True
                self._speech_buffer.clear()
                for pre in self._pre_roll:
                    self._speech_buffer.extend(pre)
                self._speech_seconds = frame_seconds
                self._silence_seconds = 0.0
                return VadEvent(speech_started=True, is_speaking=True)
            return VadEvent(is_speaking=False)

        # Currently inside active speech segment
        self._speech_buffer.extend(pcm_int16)
        self._speech_seconds += frame_seconds

        if is_voice:
            self._silence_seconds = 0.0
        else:
            self._silence_seconds += frame_seconds

        reached_max = self._speech_seconds >= self.max_segment_seconds
        reached_silence = self._silence_seconds >= self.silence_duration_seconds

        if reached_max or reached_silence:
            dur = self._speech_seconds
            payload = bytes(self._speech_buffer) if dur >= self.min_speech_seconds else None
            self.reset()
            return VadEvent(
                speech_ended=True,
                is_speaking=False,
                segment_pcm=payload,
                duration_seconds=dur,
            )

        return VadEvent(is_speaking=True)

    def flush(self) -> VadEvent:
        if not self._speaking:
            return VadEvent(is_speaking=False)
        dur = self._speech_seconds
        payload = bytes(self._speech_buffer) if dur >= self.min_speech_seconds else None
        self.reset()
        return VadEvent(
            speech_ended=True,
            is_speaking=False,
            segment_pcm=payload,
            duration_seconds=dur,
        )
