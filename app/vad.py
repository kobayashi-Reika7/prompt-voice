"""Voice activity detection and utterance segmentation for MVP."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import torch
from silero_vad import get_speech_timestamps, load_silero_vad

from .config import (
    MAX_BUFFER_SECONDS,
    MAX_UTTERANCE_SECONDS,
    SAMPLE_RATE,
    VAD_MIN_SILENCE_MS,
    VAD_MIN_SPEECH_MS,
    VAD_THRESHOLD,
)
from .models import AudioChunk, UtteranceSegment

logger = logging.getLogger(__name__)


class VADError(RuntimeError):
    """Raised when VAD initialization or inference fails."""


class SileroVADWrapper:
    """Thin wrapper around silero-vad to classify chunk-level speech."""

    def __init__(
        self,
        *,
        sample_rate: int = SAMPLE_RATE,
        threshold: float = VAD_THRESHOLD,
        min_silence_ms: int = VAD_MIN_SILENCE_MS,
    ) -> None:
        if sample_rate <= 0:
            raise VADError("sample_rate must be a positive integer.")
        if not (0.0 <= threshold <= 1.0):
            raise VADError("threshold must be between 0.0 and 1.0.")

        self.sample_rate = sample_rate
        self.threshold = threshold
        self.min_silence_ms = max(0, int(min_silence_ms))

        try:
            self._model = load_silero_vad()
        except Exception as exc:
            raise VADError(f"Failed to load silero-vad model: {exc}") from exc

    def is_speech(self, samples: np.ndarray, sample_rate: Optional[int] = None) -> bool:
        """Return True when the given chunk likely contains speech."""
        sr = sample_rate or self.sample_rate
        if sr <= 0:
            raise VADError("Invalid sample_rate passed to VAD.")

        try:
            mono = np.asarray(samples, dtype=np.float32).reshape(-1)
            if mono.size == 0:
                return False

            # silero-vad expects mono float tensor.
            tensor = torch.from_numpy(mono)
            speech_spans = get_speech_timestamps(
                tensor,
                self._model,
                threshold=self.threshold,
                sampling_rate=sr,
                min_silence_duration_ms=self.min_silence_ms,
                return_seconds=False,
            )
            return bool(speech_spans)
        except Exception as exc:
            raise VADError(f"VAD inference failed: {exc}") from exc


@dataclass(slots=True)
class DetectorConfig:
    """Runtime tunables for state-based utterance detection."""

    min_silence_ms: int = VAD_MIN_SILENCE_MS
    min_utterance_ms: int = VAD_MIN_SPEECH_MS
    start_trigger_chunks: int = 1
    max_utterance_seconds: int = MAX_UTTERANCE_SECONDS
    max_buffer_seconds: int = MAX_BUFFER_SECONDS


class UtteranceDetector:
    """
    Stateful utterance detector.

    State transitions:
    - idle -> speech      : speech detected consecutively
    - speech -> maybe_end : non-speech detected
    - maybe_end -> speech : speech resumes before silence timeout
    - maybe_end -> idle   : silence timeout reached, utterance finalized

    Guard rails:
    - max_utterance_seconds: force-finalize long speech without waiting silence
    - max_buffer_seconds: emergency reset to avoid unbounded memory growth
    """

    STATE_IDLE = "idle"
    STATE_SPEECH = "speech"
    STATE_MAYBE_END = "maybe_end"

    def __init__(
        self,
        vad: SileroVADWrapper,
        *,
        config: Optional[DetectorConfig] = None,
    ) -> None:
        self.vad = vad
        self.config = config or DetectorConfig()

        self.state = self.STATE_IDLE
        self._current_segment: Optional[UtteranceSegment] = None
        self._pending_silence_chunks: List[AudioChunk] = []
        self._pending_silence_ms: float = 0.0
        self._speech_ms: float = 0.0
        self._speech_trigger_count: int = 0

    def process_chunk(self, chunk: AudioChunk) -> Optional[UtteranceSegment]:
        """
        Process one chunk and return finalized utterance on end detection.

        Returns:
            - UtteranceSegment when an utterance end is confirmed
            - None for all other cases
        """
        try:
            has_speech = self.vad.is_speech(chunk.samples, chunk.sample_rate)
            chunk.is_speech = has_speech
            chunk_ms = chunk.duration_sec * 1000.0
        except Exception as exc:
            raise VADError(f"Failed to process chunk {chunk.sequence_id}: {exc}") from exc

        if self.state == self.STATE_IDLE:
            if has_speech:
                self._speech_trigger_count += 1
                if self._speech_trigger_count >= max(1, self.config.start_trigger_chunks):
                    self._start_new_segment(chunk)
                    self.state = self.STATE_SPEECH
                return None

            self._speech_trigger_count = 0
            return None

        if self.state == self.STATE_SPEECH:
            if has_speech:
                self._append_to_segment(chunk)
                self._speech_ms += chunk_ms
                if self._is_over_max_utterance():
                    return self._finalize_and_reset("max_utterance")
                if self._is_over_max_buffer():
                    logger.warning(
                        "Emergency VAD reset: buffered_duration=%.2fs exceeds max_buffer_seconds=%d",
                        self._buffered_duration_sec(),
                        max(1, self.config.max_buffer_seconds),
                    )
                    self._reset_runtime_state()
                    self.state = self.STATE_IDLE
                    return None
                return None

            self.state = self.STATE_MAYBE_END
            self._pending_silence_chunks = [chunk]
            self._pending_silence_ms = chunk_ms
            return None

        # maybe_end state
        if has_speech:
            # False end. Recover by merging pending silence back.
            self._merge_pending_silence_into_segment()
            self._append_to_segment(chunk)
            self._speech_ms += chunk_ms
            if self._is_over_max_utterance():
                return self._finalize_and_reset("max_utterance")
            if self._is_over_max_buffer():
                logger.warning(
                    "Emergency VAD reset: buffered_duration=%.2fs exceeds max_buffer_seconds=%d",
                    self._buffered_duration_sec(),
                    max(1, self.config.max_buffer_seconds),
                )
                self._reset_runtime_state()
                self.state = self.STATE_IDLE
                return None
            self.state = self.STATE_SPEECH
            return None

        self._pending_silence_chunks.append(chunk)
        self._pending_silence_ms += chunk_ms

        if self._pending_silence_ms >= self.config.min_silence_ms:
            return self._finalize_and_reset("silence_timeout")

        if self._is_over_max_buffer():
            logger.warning(
                "Emergency VAD reset: buffered_duration=%.2fs exceeds max_buffer_seconds=%d",
                self._buffered_duration_sec(),
                max(1, self.config.max_buffer_seconds),
            )
            self._reset_runtime_state()
            self.state = self.STATE_IDLE
            return None

        return None

    def flush(self) -> Optional[UtteranceSegment]:
        """
        Force finalize current utterance, useful when stopping recording.

        Pending trailing silence is ignored to keep output clean for ASR.
        """
        if self._current_segment is None:
            self._reset_runtime_state()
            self.state = self.STATE_IDLE
            return None

        finalized = self._finalize_current_segment()
        self._reset_runtime_state()
        self.state = self.STATE_IDLE
        return finalized

    def get_current_segment(self) -> Optional[UtteranceSegment]:
        """
        Return a snapshot of current speech buffer.

        This is useful for future partial transcription.
        """
        if self._current_segment is None:
            return None

        snapshot = UtteranceSegment(chunks=list(self._current_segment.chunks))
        if snapshot.chunks:
            snapshot.start_time = snapshot.chunks[0].timestamp
            last = snapshot.chunks[-1]
            snapshot.end_time = last.timestamp + last.duration_sec
        return snapshot

    def reset(self) -> None:
        """Reset detector state and discard current buffers."""
        self._reset_runtime_state()
        self.state = self.STATE_IDLE

    def _start_new_segment(self, chunk: AudioChunk) -> None:
        self._current_segment = UtteranceSegment()
        self._current_segment.add_chunk(chunk)
        self._speech_ms = chunk.duration_sec * 1000.0
        self._pending_silence_chunks = []
        self._pending_silence_ms = 0.0

    def _append_to_segment(self, chunk: AudioChunk) -> None:
        if self._current_segment is None:
            self._start_new_segment(chunk)
            return
        self._current_segment.add_chunk(chunk)

    def _merge_pending_silence_into_segment(self) -> None:
        if self._current_segment is None:
            return
        for pending in self._pending_silence_chunks:
            self._current_segment.add_chunk(pending)
        self._pending_silence_chunks = []
        self._pending_silence_ms = 0.0

    def _finalize_current_segment(self) -> Optional[UtteranceSegment]:
        segment = self._current_segment
        if segment is None:
            return None

        if self._speech_ms < max(0, self.config.min_utterance_ms):
            logger.debug(
                "Dropping too-short utterance: speech_ms=%.2f < min_utterance_ms=%d",
                self._speech_ms,
                self.config.min_utterance_ms,
            )
            return None
        return segment

    def _finalize_and_reset(self, reason: str) -> Optional[UtteranceSegment]:
        finalized = self._finalize_current_segment()
        if finalized is not None:
            logger.debug(
                "Utterance finalized: reason=%s, speech_ms=%.2f, duration_sec=%.2f",
                reason,
                self._speech_ms,
                finalized.duration_sec,
            )
        self._reset_runtime_state()
        self.state = self.STATE_IDLE
        return finalized

    def _is_over_max_utterance(self) -> bool:
        if self._current_segment is None:
            return False
        return self._current_segment.duration_sec >= float(max(1, self.config.max_utterance_seconds))

    def _is_over_max_buffer(self) -> bool:
        return self._buffered_duration_sec() >= float(max(1, self.config.max_buffer_seconds))

    def _buffered_duration_sec(self) -> float:
        segment_duration = self._current_segment.duration_sec if self._current_segment else 0.0
        pending_silence_sec = max(0.0, self._pending_silence_ms) / 1000.0
        return segment_duration + pending_silence_sec

    def _reset_runtime_state(self) -> None:
        self._current_segment = None
        self._pending_silence_chunks = []
        self._pending_silence_ms = 0.0
        self._speech_ms = 0.0
        self._speech_trigger_count = 0


def create_default_detector() -> UtteranceDetector:
    """Factory for default detector with config values."""
    vad = SileroVADWrapper()
    return UtteranceDetector(vad=vad)

