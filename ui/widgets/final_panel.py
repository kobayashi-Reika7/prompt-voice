from __future__ import annotations

from textual.widgets import Static
from rich.panel import Panel
from rich.text import Text


class FinalPanel(Static):
    """Shows finalized formatted transcript."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._final_text = ""

    def set_final(self, text: str) -> None:
        self._final_text = (text or "").strip()
        self.refresh()

    def render(self) -> Panel:
        body = self._final_text or "No final output yet."
        return Panel(
            Text(body, style="white"),
            title="FINAL",
            border_style="#5c7cfa",
        )
