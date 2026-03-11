from __future__ import annotations

from textual.widgets import Static


class FooterBar(Static):
    def __init__(self, **kwargs) -> None:
        super().__init__("R Start/Stop   M Mode   C Copy   Q Quit", **kwargs)
