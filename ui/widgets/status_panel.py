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
        if self.message:
            self.update(f"{line1}\n[dim]{self.message}[/]")
        else:
            self.update(line1)

    def watch_status(self) -> None:
        self._refresh_content()

    def watch_message(self) -> None:
        self._refresh_content()
