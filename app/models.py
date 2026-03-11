"""Shared data models used across the application."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Literal

import numpy as np


@dataclass(slots=True)
class AudioChunk:
    """Single audio chunk captured from the microphone."""

    samples: np.ndarray
    sample_rate: int
    timestamp: float
    sequence_id: int
    is_speech: Optional[bool] = None

    @property
    def duration_sec(self) -> float:
        if self.sample_rate <= 0:
            return 0.0
        return float(len(self.samples)) / float(self.sample_rate)


@dataclass(slots=True)
class UtteranceSegment:
    """A complete utterance assembled from one or more chunks."""

    chunks: List[AudioChunk] = field(default_factory=list)
    start_time: Optional[float] = None
    end_time: Optional[float] = None

    def add_chunk(self, chunk: AudioChunk) -> None:
        if not self.chunks:
            self.start_time = chunk.timestamp
        self.chunks.append(chunk)
        self.end_time = chunk.timestamp + chunk.duration_sec

    @property
    def duration_sec(self) -> float:
        if self.start_time is None or self.end_time is None:
            return 0.0
        return max(0.0, self.end_time - self.start_time)

    def to_numpy(self) -> np.ndarray:
        if not self.chunks:
            return np.empty(0, dtype=np.float32)
        return np.concatenate([c.samples for c in self.chunks]).astype(np.float32, copy=False)


@dataclass(slots=True)
class TranscriptResult:
    """Recognition result object used by transcriber/formatter."""

    text: str
    is_final: bool
    mode: str
    language: str
    created_at: float
    confidence: Optional[float] = None
    utterance_id: Optional[str] = None


@dataclass(slots=True)
class InputDiagnosticResult:
    """Lightweight input diagnostic for UX-friendly messaging."""

    has_signal: bool
    avg_level: float
    peak_level: float
    device_name: str
    source_type: Literal["mic", "system", "mixed", "unknown"] = "unknown"
    note: Optional[str] = None
