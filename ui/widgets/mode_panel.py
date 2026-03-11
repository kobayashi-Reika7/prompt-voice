"""Mode panel: raw / clean / cursor / minutes with selection."""

from __future__ import annotations

from textual.widgets import Static

from ui.state import ALL_MODES


class ModePanel(Static):
    """Shows formatting modes and highlights the current one."""

    DEFAULT_CSS = """
    ModePanel {
        padding: 1 0;
        width: 100%;
    }
    ModePanel .mode-item {
        color: $text-muted;
    }
    ModePanel .mode-selected {
        color: $accent;
        text-style: bold;
    }
    """

    def __init__(self, current_mode: str = "clean", *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._current = current_mode
        self._update_content()

    def _update_content(self) -> None:
        lines = []
        for m in ALL_MODES:
            if m == self._current:
                lines.append(f"[bold #5c7cfa]▸ {m}[/]")
            else:
                lines.append(f"[dim]  {m}[/]")
        self.update("\n".join(lines))

    def set_mode(self, mode: str) -> None:
        if mode in ALL_MODES:
            self._current = mode
            self._update_content()
