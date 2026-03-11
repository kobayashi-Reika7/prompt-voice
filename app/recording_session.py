"""Thread-based recording session: capture → VAD → transcribe → formatter → queue events."""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from typing import Any, Optional

from .audio_capture import AudioCapture, AudioCaptureError, list_input_devices
from .clipboard_util import ClipboardManager
from .config import (
    ENABLE_INPUT_METER,
    INPUT_ACTIVE_THRESHOLD,
    PARTIAL_MAX_AUDIO_SEC,
    PARTIAL_MIN_AUDIO_SEC,
    PARTIAL_UPDATE_INTERVAL_SEC,
)
from .formatter import FormatterError, TextFormatter
from .history import HistoryStore
from .models import UtteranceSegment
from .transcriber import LocalTranscriber, TranscriberError
from .vad import VADError, create_default_detector

logger = logging.getLogger(__name__)
FALLBACK_MIN_DURATION_SEC = 0.8
FALLBACK_MAX_DURATION_SEC = 20.0


def _resolve_device(raw_device: Optional[str]) -> Optional[int | str]:
    if raw_device is None or not str(raw_device).strip():
        return None
    s = str(raw_device).strip()
    if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
        return int(s)
    return s


def _segment_tail_for_partial(segment: UtteranceSegment, *, max_audio_sec: float) -> UtteranceSegment:
    """
    Keep only the tail window for partial ASR to keep latency stable.
    """
    if max_audio_sec <= 0 or segment.duration_sec <= max_audio_sec:
        return segment
    selected = []
    acc = 0.0
    for chunk in reversed(segment.chunks):
        selected.append(chunk)
        acc += chunk.duration_sec
        if acc >= max_audio_sec:
            break
    selected.reverse()
    if not selected:
        return segment
    sliced = UtteranceSegment(chunks=list(selected))
    sliced.start_time = selected[0].timestamp
    last = selected[-1]
    sliced.end_time = last.timestamp + last.duration_sec
    return sliced


def _handle_final(
    *,
    segment,
    transcriber: LocalTranscriber,
    formatter: TextFormatter,
    clipboard: ClipboardManager,
    history: HistoryStore,
    mode: str,
    no_copy: bool,
    auto_paste: bool,
    initial_prompt: Optional[str] = None,
) -> tuple[str, str]:
    """Transcribe, format, copy/paste, save history. Returns (raw_text, formatted_text)."""
    try:
        transcript = transcriber.transcribe_segment(segment, initial_prompt=initial_prompt)
    except TranscriberError as exc:
        raise RuntimeError(f"Transcription failed: {exc}") from exc

    if transcript is None or not transcript.text.strip():
        return "", ""

    raw_text = transcript.text.strip()
    try:
        formatted = formatter.format_text(raw_text, mode=mode)
    except FormatterError as exc:
        formatted = raw_text

    if not formatted:
        return raw_text, ""

    if not no_copy:
        clipboard.copy_text(formatted)
        if auto_paste:
            clipboard.trigger_paste()

    history.append({
        "type": "final",
        "mode": mode,
        "raw_text": raw_text,
        "formatted_text": formatted,
        "copied": not no_copy,
        "confidence": transcript.confidence,
        "language": transcript.language,
        "utterance_id": transcript.utterance_id,
    })
    return raw_text, formatted


class RecordingSession:
    """Runs the capture/VAD/transcribe pipeline in a worker thread and pushes events to a queue."""

    def __init__(
        self,
        event_queue: queue.Queue[dict[str, Any]],
        *,
        mode: str = "clean",
        device: Optional[str] = None,
        no_copy: bool = False,
        auto_paste: bool = False,
        history_path: str = "logs/history.json",
        show_partial: bool = True,
        initial_prompt: Optional[str] = None,
    ) -> None:
        self._queue = event_queue
        self._mode = mode
        self._device = _resolve_device(device)
        self._no_copy = no_copy
        self._auto_paste = auto_paste
        self._history_path = history_path
        self._show_partial = show_partial
        self._initial_prompt = (initial_prompt or "").strip() or None

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def _run(self) -> None:
        try:
            formatter = TextFormatter(default_mode=self._mode)
        except FormatterError as exc:
            self._queue.put({"type": "error", "message": f"Formatter: {exc}"})
            return

        clipboard = ClipboardManager()
        history = HistoryStore(path=self._history_path)

        try:
            detector = create_default_detector()
        except VADError as exc:
            self._queue.put({"type": "error", "message": f"VAD: {exc}"})
            return

        try:
            transcriber = LocalTranscriber()
        except TranscriberError as exc:
            self._queue.put({"type": "error", "message": f"Transcriber: {exc}"})
            return

        capture = AudioCapture(device=self._device)
        try:
            capture.start()
        except AudioCaptureError as exc:
            self._queue.put({"type": "error", "message": f"Audio: {exc}"})
            return

        dev_name = capture.get_active_device_name()
        self._queue.put({"type": "status", "message": f"録音開始（自動入力）: {dev_name}"})

        last_partial_ts = 0.0
        last_partial_text = ""
        last_audio_warn_ts = 0.0
        last_level_push_ts = 0.0
        recent_chunks = deque()
        recent_duration_sec = 0.0
        finalized_count = 0

        try:
            while not self._stop_event.is_set():
                # Surface audio warnings from callback thread (e.g., overflows, dropouts).
                err = capture.get_error()
                if err:
                    now = time.time()
                    if now - last_audio_warn_ts > 1.0:
                        self._queue.put({"type": "status", "message": err})
                        last_audio_warn_ts = now

                if ENABLE_INPUT_METER:
                    now = time.time()
                    if now - last_level_push_ts >= 0.12:
                        lvl = capture.get_level()
                        rms = float(lvl.get("rms", 0.0))
                        peak = float(lvl.get("peak", 0.0))
                        level = max(rms * 12.0, peak * 4.0)
                        level = max(0.0, min(1.0, level))
                        self._queue.put(
                            {
                                "type": "level",
                                "level": level,
                                "rms": rms,
                                "peak": peak,
                                "active": bool(rms >= INPUT_ACTIVE_THRESHOLD or peak >= INPUT_ACTIVE_THRESHOLD),
                            }
                        )
                        last_level_push_ts = now

                chunk = capture.get_chunk(timeout=0.2)
                if chunk is None:
                    continue
                recent_chunks.append(chunk)
                recent_duration_sec += float(chunk.duration_sec)
                while recent_chunks and recent_duration_sec > FALLBACK_MAX_DURATION_SEC:
                    oldest = recent_chunks.popleft()
                    recent_duration_sec = max(0.0, recent_duration_sec - float(oldest.duration_sec))

                segment = detector.process_chunk(chunk)

                if self._show_partial:
                    now = time.time()
                    if now - last_partial_ts >= PARTIAL_UPDATE_INTERVAL_SEC:
                        current = detector.get_current_segment()
                        if current is not None and current.duration_sec >= PARTIAL_MIN_AUDIO_SEC:
                            try:
                                partial_target = _segment_tail_for_partial(
                                    current,
                                    max_audio_sec=PARTIAL_MAX_AUDIO_SEC,
                                )
                                partial = transcriber.partial_transcribe(
                                    partial_target, initial_prompt=self._initial_prompt
                                )
                                text = (partial.text if partial else "").strip()
                                if text and text != last_partial_text:
                                    self._queue.put({"type": "partial", "text": text})
                                    last_partial_text = text
                            except TranscriberError:
                                pass
                        last_partial_ts = now

                if segment is not None:
                    try:
                        raw, formatted = _handle_final(
                            segment=segment,
                            transcriber=transcriber,
                            formatter=formatter,
                            clipboard=clipboard,
                            history=history,
                            mode=self._mode,
                            no_copy=self._no_copy,
                            auto_paste=self._auto_paste,
                            initial_prompt=self._initial_prompt,
                        )
                        if formatted:
                            self._queue.put({"type": "final", "raw": raw, "text": formatted})
                            finalized_count += 1
                    except Exception as exc:
                        self._queue.put({"type": "error", "message": str(exc)})
        finally:
            try:
                tail = detector.flush()
                if tail is not None:
                    try:
                        raw, formatted = _handle_final(
                            segment=tail,
                            transcriber=transcriber,
                            formatter=formatter,
                            clipboard=clipboard,
                            history=history,
                            mode=self._mode,
                            no_copy=self._no_copy,
                            auto_paste=self._auto_paste,
                            initial_prompt=self._initial_prompt,
                        )
                        if formatted:
                            self._queue.put({"type": "final", "raw": raw, "text": formatted})
                            finalized_count += 1
                    except Exception as exc:
                        self._queue.put({"type": "error", "message": str(exc)})
            except Exception as exc:
                logger.warning("Flush failed: %s", exc)
            if finalized_count == 0 and recent_duration_sec >= FALLBACK_MIN_DURATION_SEC and recent_chunks:
                # Manual stop fallback: transcribe recent buffered audio even if VAD missed speech.
                try:
                    fallback_segment = UtteranceSegment(chunks=list(recent_chunks))
                    raw, formatted = _handle_final(
                        segment=fallback_segment,
                        transcriber=transcriber,
                        formatter=formatter,
                        clipboard=clipboard,
                        history=history,
                        mode=self._mode,
                        no_copy=self._no_copy,
                        auto_paste=self._auto_paste,
                        initial_prompt=self._initial_prompt,
                    )
                    if formatted:
                        self._queue.put({"type": "final", "raw": raw, "text": formatted})
                        self._queue.put(
                            {"type": "status", "message": "VAD未検出のため、停止時バッファから文字起こししました"}
                        )
                except Exception as exc:
                    self._queue.put({"type": "error", "message": f"Fallback transcription failed: {exc}"})
            capture.stop()
            self._queue.put({"type": "stopped", "message": "録音停止"})


def get_input_devices() -> list[dict[str, Any]]:
    """Return list of input device dicts (index, name, ...)."""
    try:
        return list_input_devices()
    except AudioCaptureError:
        return []
