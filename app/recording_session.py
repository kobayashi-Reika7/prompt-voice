"""Thread-based recording session: capture → VAD → transcribe → formatter → queue events."""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Optional

from .audio_capture import AudioCapture, AudioCaptureError, list_input_devices
from .clipboard_util import ClipboardManager
from .config import PARTIAL_INTERVAL_MS
from .formatter import FormatterError, TextFormatter
from .history import HistoryStore
from .transcriber import LocalTranscriber, TranscriberError
from .vad import VADError, create_default_detector

logger = logging.getLogger(__name__)


def _resolve_device(raw_device: Optional[str]) -> Optional[int | str]:
    if raw_device is None or not str(raw_device).strip():
        return None
    s = str(raw_device).strip()
    if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
        return int(s)
    return s


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
        self._queue.put({"type": "status", "message": f"録音開始（マイク入力）: {dev_name}"})

        last_partial_ts = 0.0
        last_partial_text = ""
        last_audio_warn_ts = 0.0

        try:
            while not self._stop_event.is_set():
                # Surface audio warnings from callback thread (e.g., overflows, dropouts).
                err = capture.get_error()
                if err:
                    now = time.time()
                    if now - last_audio_warn_ts > 1.0:
                        self._queue.put({"type": "status", "message": err})
                        last_audio_warn_ts = now

                chunk = capture.get_chunk(timeout=0.2)
                if chunk is None:
                    continue

                segment = detector.process_chunk(chunk)

                if self._show_partial:
                    now = time.time()
                    if now - last_partial_ts >= PARTIAL_INTERVAL_MS / 1000.0:
                        current = detector.get_current_segment()
                        if current is not None and current.duration_sec > 0.1:
                            try:
                                partial = transcriber.partial_transcribe(
                                    current, initial_prompt=self._initial_prompt
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
                    except Exception as exc:
                        self._queue.put({"type": "error", "message": str(exc)})
            except Exception as exc:
                logger.warning("Flush failed: %s", exc)
            finally:
                capture.stop()
                self._queue.put({"type": "stopped", "message": "録音停止"})


def get_input_devices() -> list[dict[str, Any]]:
    """Return list of input device dicts (index, name, ...)."""
    try:
        return list_input_devices()
    except AudioCaptureError:
        return []
