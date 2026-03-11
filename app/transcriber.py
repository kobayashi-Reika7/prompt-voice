"""Local speech transcription module based on faster-whisper."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
from faster_whisper import WhisperModel

from .config import COMPUTE_TYPE, DEVICE, LANGUAGE, MODEL_SIZE, SAMPLE_RATE
from .models import TranscriptResult, UtteranceSegment

logger = logging.getLogger(__name__)


class TranscriberError(RuntimeError):
    """Raised when model loading or transcription fails."""


@dataclass(slots=True)
class TimedTranscriptResult(TranscriptResult):
    """Transcript result with utterance timing for downstream orchestration."""

    started_at: float = 0.0
    ended_at: float = 0.0


class LocalTranscriber:
    """
    Local transcriber using faster-whisper.

    MVP focuses on reliable final transcription.
    The API leaves room for future partial/context-aware transcription.
    """

    def __init__(
        self,
        *,
        model_size: str = MODEL_SIZE,
        device: str = DEVICE,
        compute_type: str = COMPUTE_TYPE,
        language: str = LANGUAGE,
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.language = language

        try:
            self.model = WhisperModel(
                model_size_or_path=self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
        except Exception as exc:
            raise TranscriberError(
                f"Failed to load faster-whisper model: size={model_size}, "
                f"device={device}, compute_type={compute_type}, error={exc}"
            ) from exc

    def transcribe_segment(
        self,
        segment: UtteranceSegment,
        *,
        language: Optional[str] = None,
        initial_prompt: Optional[str] = None,
        beam_size: int = 3,
    ) -> Optional[TranscriptResult]:
        """
        Transcribe a finalized utterance segment.

        Returns:
            TranscriptResult (final) when text is recognized, otherwise None.
        """
        audio, sample_rate = self._extract_audio(segment)
        if audio is None:
            return None

        lang = (language or self.language or "").strip() or None

        try:
            segments, info = self.model.transcribe(
                audio,
                language=lang,
                task="transcribe",
                beam_size=max(1, int(beam_size)),
                condition_on_previous_text=False,
                vad_filter=False,
                initial_prompt=initial_prompt,
                temperature=0.0,
            )

            texts: list[str] = []
            confidences: list[float] = []
            for seg in segments:
                text = (seg.text or "").strip()
                if text:
                    texts.append(text)
                avg_logprob = getattr(seg, "avg_logprob", None)
                if isinstance(avg_logprob, (float, int)):
                    confidences.append(float(avg_logprob))

            merged = " ".join(texts).strip()
            if not merged:
                return None

            confidence = float(np.mean(confidences)) if confidences else None
            effective_language = (lang or getattr(info, "language", None) or self.language)
            start_time = float(segment.start_time or time.time())
            end_time = float(segment.end_time or start_time)

            return TimedTranscriptResult(
                text=merged,
                is_final=True,
                mode="raw",
                language=effective_language,
                created_at=time.time(),
                confidence=confidence,
                utterance_id=f"{int(start_time * 1000)}-{int(end_time * 1000)}",
                started_at=start_time,
                ended_at=end_time,
            )
        except Exception as exc:
            raise TranscriberError(f"Transcription failed: {exc}") from exc

    def partial_transcribe(
        self,
        _segment: UtteranceSegment,
        *,
        initial_prompt: Optional[str] = None,
    ) -> Optional[TranscriptResult]:
        """
        Transcribe an in-progress segment for partial realtime display.
        """
        audio, _sample_rate = self._extract_audio(_segment)
        if audio is None:
            return None
        return self.transcribe_partial(audio, initial_prompt=initial_prompt)

    def transcribe_partial(
        self,
        audio: np.ndarray,
        *,
        initial_prompt: Optional[str] = None,
    ) -> Optional[TranscriptResult]:
        """Fast partial transcription for in-progress speech."""
        mono = np.asarray(audio, dtype=np.float32).reshape(-1)
        if mono.size < int(0.08 * SAMPLE_RATE):
            return None

        try:
            segments, info = self.model.transcribe(
                mono,
                language=(self.language or "").strip() or None,
                task="transcribe",
                beam_size=1,
                best_of=1,
                condition_on_previous_text=False,
                vad_filter=False,
                initial_prompt=initial_prompt,
                temperature=0.0,
            )
        except Exception as exc:
            raise TranscriberError(f"Partial transcription failed: {exc}") from exc

        texts: list[str] = []
        confidences: list[float] = []
        for seg in segments:
            text = (seg.text or "").strip()
            if text:
                texts.append(text)
            avg_logprob = getattr(seg, "avg_logprob", None)
            if isinstance(avg_logprob, (float, int)):
                confidences.append(float(avg_logprob))

        merged = " ".join(texts).strip()
        if not merged:
            return None

        confidence = float(np.mean(confidences)) if confidences else None
        effective_language = getattr(info, "language", None) or self.language
        now = time.time()
        return TranscriptResult(
            text=merged,
            is_final=False,
            mode="raw",
            language=str(effective_language),
            created_at=now,
            confidence=confidence,
            utterance_id=f"partial-{int(now * 1000)}",
        )

    def _extract_audio(self, segment: UtteranceSegment) -> tuple[Optional[np.ndarray], int]:
        """Extract and validate waveform from an utterance segment."""
        if segment is None:
            raise TranscriberError("segment is None")
        if not segment.chunks:
            return None, SAMPLE_RATE

        sample_rate = int(segment.chunks[0].sample_rate)
        if sample_rate <= 0:
            raise TranscriberError("Invalid sample_rate in segment.")

        audio = segment.to_numpy()
        if audio.size == 0:
            return None, sample_rate

        # This MVP pipeline is fixed at 16kHz; fail fast for mismatched input.
        if sample_rate != SAMPLE_RATE:
            raise TranscriberError(
                f"Unsupported sample rate {sample_rate}. Expected {SAMPLE_RATE}."
            )

        mono = np.asarray(audio, dtype=np.float32).reshape(-1)
        if mono.size < int(0.08 * SAMPLE_RATE):  # too short to transcribe stably
            return None, sample_rate

        return np.clip(mono, -1.0, 1.0), sample_rate

