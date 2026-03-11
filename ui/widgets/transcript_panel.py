"""Transcript panel: partial (dim) + final (prominent)."""

from __future__ import annotations

from textual.widgets import Static
from textual.app import ComposeResult


class TranscriptPanel(Static):
    """Two sections: partial (live) and final (result)."""

    DEFAULT_CSS = """
    TranscriptPanel {
        height: auto;
        min-height: 12;
        padding: 1 2;
        background: $surface-darken-2;
    }
    TranscriptPanel #partial-block {
        color: $text-muted;
        border: round $primary-darken-2;
        padding: 1 2;
        min-height: 4;
        margin-bottom: 1;
    }
    TranscriptPanel #final-block {
        color: $text;
        border: round $primary;
        background: $surface-darken-1;
        padding: 1 2;
        min-height: 10;
    }
    TranscriptPanel #partial-label {
        color: $text-muted;
        text-style: italic;
    }
    TranscriptPanel #final-label {
        color: $primary-lighten-1;
        text-style: bold;
    }
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._partial = ""
        self._final = ""
        self._partial_widget: Static | None = None
        self._final_widget: Static | None = None

    def compose(self) -> ComposeResult:
        yield Static("PARTIAL", id="partial-label")
        yield Static("", id="partial-block")
        yield Static("FINAL", id="final-label")
        yield Static("", id="final-block")

    def on_mount(self) -> None:
        self._partial_widget = self.query_one("#partial-block", Static)
        self._final_widget = self.query_one("#final-block", Static)
        self._partial_widget.update(self._partial or "[dim]—[/]")
        self._final_widget.update(self._final or "[dim]—[/]")

    def set_partial(self, text: str) -> None:
        self._partial = text
        if self._partial_widget:
            self._partial_widget.update(text.strip() or "[dim]—[/]")

    def set_final(self, text: str) -> None:
        self._final = text
        if self._final_widget:
            self._final_widget.update(text.strip() or "[dim]—[/]")

    def clear_partial(self) -> None:
        self.set_partial("")
