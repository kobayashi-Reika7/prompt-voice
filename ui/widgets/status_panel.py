from __future__ import annotations

from textual.containers import Vertical
from textual.widgets import Static

from ui.widgets.input_meter import InputMeter


class StatusPanel(Vertical):
    """Sidebar status block with app state and input meter."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.status_label = Static("○ Idle", id="status-label")
        self.source_label = Static("Source: mic", id="source-label")
        self.mode_label = Static("Mode: clean", id="mode-label")
        self.copy_label = Static("Clipboard: -", id="copy-label")
        self.input_meter = InputMeter(id="input-meter")

    def compose(self):
        yield Static("STATUS", classes="section-title")
        yield self.status_label
        yield self.source_label
        yield self.mode_label
        yield self.copy_label
        yield self.input_meter

    def set_status(self, status: str) -> None:
        mapping = {
            "idle": "○ Idle",
            "recording": "● Recording",
            "transcribing": "… Transcribing",
            "copied": "✓ Copied",
            "error": "⚠ Error",
        }
        self.status_label.update(mapping.get(status, status))

    def set_source(self, source: str) -> None:
        self.source_label.update(f"Source: {source}")

    def set_mode(self, mode: str) -> None:
        self.mode_label.update(f"Mode: {mode}")

    def set_copy_state(self, message: str) -> None:
        self.copy_label.update(f"Clipboard: {message}")

    def set_input_level(self, level: float) -> None:
        self.input_meter.set_level(level)
