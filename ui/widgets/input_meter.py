from __future__ import annotations

from textual.widget import Widget
from rich.text import Text


class InputMeter(Widget):
    """Simple audio level meter for 0.0 - 1.0 normalized input."""

    def __init__(self, total_bars: int = 12, **kwargs) -> None:
        super().__init__(**kwargs)
        self.total_bars = total_bars
        self._level = 0.0

    def set_level(self, value: float) -> None:
        self._level = max(0.0, min(1.0, float(value)))
        self.refresh()

    def render(self) -> Text:
        active = int(self._level * self.total_bars)
        active = max(0, min(self.total_bars, active))
        bar = "█" * active + "░" * (self.total_bars - active)

        if active == 0:
            style = "dim"
        elif active < self.total_bars * 0.5:
            style = "yellow"
        else:
            style = "green"

        return Text(f"Input  {bar}", style=style)
