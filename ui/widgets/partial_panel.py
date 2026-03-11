from __future__ import annotations

from textual.widgets import Static
from rich.panel import Panel
from rich.text import Text


class PartialPanel(Static):
    """Shows in-progress transcript."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._partial_text = ""

    def set_partial(self, text: str) -> None:
        self._partial_text = (text or "").strip()
        self.refresh()

    def render(self) -> Panel:
        body = self._partial_text or "Listening..."
        return Panel(
            Text(body, style="dim"),
            title="PARTIAL",
            border_style="#333333",
        )
