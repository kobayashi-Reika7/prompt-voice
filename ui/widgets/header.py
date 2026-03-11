"""Header: app name, mode, model, device."""

from __future__ import annotations

from textual.widgets import Static


class AppHeader(Static):
    """Displays app name, current mode, Whisper model, and input device."""

    DEFAULT_CSS = """
    AppHeader {
        height: 3;
        padding: 0 2;
        background: $surface-darken-1;
        color: $text;
    }
    """

    def __init__(
        self,
        app_name: str = "prompt_voice",
        mode: str = "clean",
        model: str = "small",
        device: str = "Default",
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._app_name = app_name
        self._mode = mode
        self._model = model
        self._device = device
        self._update_content()

    def _update_content(self) -> None:
        parts = [
            f"[bold cyan]{self._app_name}[/]",
            f"[dim]mode: {self._mode}[/]",
            f"[dim]model: faster-whisper-{self._model}[/]",
            f"[dim]device: {self._device}[/]",
        ]
        self.update("  │  ".join(parts))

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self._update_content()

    def set_model(self, model: str) -> None:
        self._model = model
        self._update_content()

    def set_device(self, device: str) -> None:
        self._device = device
        self._update_content()
