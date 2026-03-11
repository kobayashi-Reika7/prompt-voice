"""Status panel: idle / recording / transcribing / copied / error."""

from __future__ import annotations

from textual.widgets import Static
from textual.reactive import reactive


class StatusPanel(Static):
    """Shows current status badge and optional message."""

    DEFAULT_CSS = """
    StatusPanel {
        padding: 1 0;
        width: 100%;
    }
    StatusPanel .status-idle {
        color: $text-muted;
    }
    StatusPanel .status-recording {
        color: #ff5d73;
        text-style: bold;
    }
    StatusPanel .status-transcribing {
        color: #ffd166;
    }
    StatusPanel .status-copied {
        color: #7bd88f;
    }
    StatusPanel .status-error {
        color: #ff6b6b;
    }
    """

    status = reactive("idle")
    message = reactive("")
    input_level = reactive(0.0)
    signal_active = reactive(False)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._refresh_content()

    def _label(self) -> str:
        labels = {
            "idle": "○ Idle",
            "recording": "● Recording",
            "transcribing": "… Transcribing",
            "copied": "✓ Copied",
            "error": "⚠ Error",
        }
        return labels.get(self.status, self.status)

    def _refresh_content(self) -> None:
        cls = f"status-{self.status}"
        line1 = f"[{cls}]{self._label()}[/]"
        meter_line = f"[dim]Input [[/]{self._meter_bar(self.input_level)}[dim]] {'LIVE' if self.signal_active else 'silent'}[/]"
        if self.message:
            self.update(f"{line1}\n{meter_line}\n[dim]{self.message}[/]")
        else:
            self.update(f"{line1}\n{meter_line}")

    @staticmethod
    def _meter_bar(level: float, width: int = 14) -> str:
        clamped = max(0.0, min(1.0, float(level)))
        filled = int(round(clamped * width))
        return ("█" * filled) + ("░" * max(0, width - filled))

    def watch_status(self) -> None:
        self._refresh_content()

    def watch_message(self) -> None:
        self._refresh_content()

    def watch_input_level(self) -> None:
        self._refresh_content()

    def watch_signal_active(self) -> None:
        self._refresh_content()
