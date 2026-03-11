"""Footer: shortcuts and hints."""

from __future__ import annotations

from textual.widgets import Static


class FooterBar(Static):
    """Shows key bindings: R Start/Stop, M Mode, C Copy, H History, Q Quit."""

    DEFAULT_CSS = """
    FooterBar {
        height: 1;
        padding: 0 2;
        background: $surface-darken-1;
        color: $text-muted;
    }
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.update(
            "[dim]R[/] Start/Stop  [dim]M[/] Mode  [dim]C[/] Copy  [dim]H[/] History  [dim]Q[/] Quit"
        )
