"""Bridge between UI and app: RecordingSession + event queue."""

from __future__ import annotations

import queue
from typing import Any, Callable, Optional

from app.audio_capture import get_default_input_device_index
from app.recording_session import RecordingSession, get_input_devices


def _device_display_name(device_index_or_name: Optional[int | str]) -> str:
    try:
        devices = get_input_devices()
    except Exception:
        return "Default"
    default_idx = get_default_input_device_index()
    if device_index_or_name is None:
        if default_idx is not None:
            for d in devices:
                if d.get("index") == default_idx:
                    name = d.get("name") or "Default"
                    return name[:36] + ("..." if len(name) > 36 else "")
        return devices[0].get("name", "Default")[:36] if devices else "Default"
    if isinstance(device_index_or_name, int):
        for d in devices:
            if d.get("index") == device_index_or_name:
                name = d.get("name") or f"Device {device_index_or_name}"
                return name[:36] + ("..." if len(name) > 36 else "")
        return f"Device {device_index_or_name}"
    name = str(device_index_or_name)
    return name[:36] + ("..." if len(name) > 36 else "")


class VoiceController:
    """
    Start/stop recording, consume session events, and notify UI via callbacks.
    UI only talks to this; no direct audio_capture/transcriber from UI.
    """

    def __init__(
        self,
        *,
        on_status: Optional[Callable[[str], None]] = None,
        on_partial: Optional[Callable[[str], None]] = None,
        on_final: Optional[Callable[[str, str], None]] = None,
        on_level: Optional[Callable[[float, bool], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_stopped: Optional[Callable[[], None]] = None,
        device: Optional[str] = None,
        history_path: str = "logs/history.json",
        no_copy: bool = False,
        auto_paste: bool = False,
    ) -> None:
        self._on_status = on_status
        self._on_partial = on_partial
        self._on_final = on_final
        self._on_level = on_level
        self._on_error = on_error
        self._on_stopped = on_stopped
        self._device = device
        self._history_path = history_path
        self._no_copy = no_copy
        self._auto_paste = auto_paste
        self._mode = "clean"
        self._event_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._session: Optional[RecordingSession] = None

    def set_mode(self, mode: str) -> None:
        self._mode = mode

    def get_mode(self) -> str:
        return self._mode

    def get_device_display_name(self) -> str:
        return _device_display_name(self._device)

    def start_recording(self) -> None:
        if self._session is not None and self._session._thread is not None and self._session._thread.is_alive():
            return
        self._session = RecordingSession(
            self._event_queue,
            mode=self._mode,
            device=self._device,
            no_copy=self._no_copy,
            auto_paste=self._auto_paste,
            history_path=self._history_path,
            show_partial=True,
        )
        self._session.start()

    def stop_recording(self) -> None:
        if self._session is None:
            return
        self._session.stop()
        self._session = None

    def is_recording(self) -> bool:
        if self._session is None:
            return False
        return self._session._thread is not None and self._session._thread.is_alive()

    def drain_events(self) -> None:
        """Process all pending events from the session queue (call from UI tick)."""
        while True:
            try:
                ev = self._event_queue.get_nowait()
            except queue.Empty:
                break
            t = ev.get("type")
            if t == "status":
                msg = ev.get("message", "")
                if self._on_status:
                    self._on_status(msg)
            elif t == "partial":
                text = ev.get("text", "")
                if self._on_partial:
                    self._on_partial(text)
            elif t == "final":
                raw = ev.get("raw", "")
                text = ev.get("text", "")
                if self._on_final:
                    self._on_final(raw, text)
            elif t == "level":
                if self._on_level:
                    level = float(ev.get("level", 0.0))
                    active = bool(ev.get("active", False))
                    self._on_level(level, active)
            elif t == "error":
                msg = ev.get("message", "")
                if self._on_error:
                    self._on_error(msg)
            elif t == "stopped":
                if self._on_stopped:
                    self._on_stopped()
