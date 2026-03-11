"""PromptVoiceApp: Textual TUI with Header, Sidebar, Transcript, Footer."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Static
from textual.binding import Binding

from app.config import MODEL_SIZE
from ui.state import ALL_MODES, STATUS_IDLE, STATUS_RECORDING, STATUS_COPIED, STATUS_ERROR
from ui.controllers import VoiceController
from ui.widgets import AppHeader, StatusPanel, ModePanel, TranscriptPanel, FooterBar


class PromptVoiceApp(App[None]):
    """Main TUI: reactive state + VoiceController + key bindings."""

    TITLE = "prompt_voice"
    SUB_TITLE = "voice → text"
    CSS = """
    Screen {
        background: #111111;
        color: #f5f5f5;
    }
    #app-grid {
        layout: grid;
        grid-size: 2 3;
        grid-columns: 28 1fr;
        grid-rows: 3 1fr 1;
    }
    #header {
        column-span: 2;
        height: 3;
        background: #1b1b1b;
        padding: 0 2;
    }
    #sidebar {
        background: #161616;
        border: round #2f2f2f;
        padding: 1 2;
        width: 100%;
    }
    #main-pane {
        background: #101010;
        padding: 1 2;
        width: 100%;
        height: 100%;
    }
    #footer {
        column-span: 2;
        height: 1;
        background: #1b1b1b;
        padding: 0 2;
    }
    .section-title {
        color: #9aa0a6;
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding("r", "toggle_recording", "Start/Stop", show=True),
        Binding("m", "cycle_mode", "Mode", show=True),
        Binding("c", "copy_final", "Copy", show=True),
        Binding("h", "history", "History", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    mode = reactive("clean")
    status = reactive(STATUS_IDLE)
    status_message = reactive("")
    partial_text = reactive("")
    final_text = reactive("")
    last_final_for_copy = reactive("")  # last final text, used when user presses C
    input_level = reactive(0.0)
    signal_active = reactive(False)

    def __init__(
        self,
        device: str | None = None,
        history_path: str = "logs/history.json",
        no_copy: bool = False,
        auto_paste: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._device = device
        self._history_path = history_path
        self._no_copy = no_copy
        self._auto_paste = auto_paste
        self._controller: VoiceController | None = None
        self._setup_controller()

    def _setup_controller(self) -> None:
        self._controller = VoiceController(
            on_status=self._on_status,
            on_partial=self._on_partial,
            on_final=self._on_final,
            on_level=self._on_level,
            on_error=self._on_error,
            on_stopped=self._on_stopped,
            device=self._device,
            history_path=self._history_path,
            no_copy=self._no_copy,
            auto_paste=self._auto_paste,
        )
        self._controller.set_mode(self.mode)

    def _on_status(self, message: str) -> None:
        self.status = STATUS_RECORDING
        self.status_message = message
        self.call_from_thread(self._safe_set_status_message, message)

    def _safe_set_status_message(self, message: str) -> None:
        self.status_message = message

    def _on_partial(self, text: str) -> None:
        self.call_from_thread(self._safe_set_partial, text)

    def _safe_set_partial(self, text: str) -> None:
        self.partial_text = text
        try:
            panel = self.query_one(TranscriptPanel)
            panel.set_partial(text)
        except Exception:
            pass

    def _on_final(self, raw: str, text: str) -> None:
        self.call_from_thread(self._safe_set_final, raw, text)

    def _safe_set_final(self, raw: str, text: str) -> None:
        self.final_text = text
        self.last_final_for_copy = text
        self.status = STATUS_COPIED
        self.status_message = "Copied to clipboard" if not self._no_copy else "Final"
        try:
            panel = self.query_one(TranscriptPanel)
            panel.set_final(text)
            panel.clear_partial()
            self.partial_text = ""
        except Exception:
            pass

    def _on_level(self, level: float, active: bool) -> None:
        self.call_from_thread(self._safe_set_level, level, active)

    def _safe_set_level(self, level: float, active: bool) -> None:
        self.input_level = max(0.0, min(1.0, float(level)))
        self.signal_active = bool(active)
        try:
            status_panel = self.query_one(StatusPanel)
            status_panel.input_level = self.input_level
            status_panel.signal_active = self.signal_active
        except Exception:
            pass
        try:
            status_panel = self.query_one(StatusPanel)
            status_panel.status = STATUS_COPIED
            status_panel.message = self.status_message
        except Exception:
            pass

    def _on_error(self, message: str) -> None:
        self.call_from_thread(self._safe_set_error, message)

    def _safe_set_error(self, message: str) -> None:
        self.status = STATUS_ERROR
        self.status_message = message
        try:
            status_panel = self.query_one(StatusPanel)
            status_panel.status = STATUS_ERROR
            status_panel.message = message
        except Exception:
            pass
        self.notify(message, severity="error", timeout=5)

    def _on_stopped(self) -> None:
        self.call_from_thread(self._safe_set_stopped)

    def _safe_set_stopped(self) -> None:
        self.status = STATUS_IDLE
        self.status_message = ""
        try:
            status_panel = self.query_one(StatusPanel)
            status_panel.status = STATUS_IDLE
            status_panel.message = ""
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        device_name = self._controller.get_device_display_name() if self._controller else "Default"
        with Container(id="app-grid"):
            yield AppHeader(
                mode=self.mode,
                model=MODEL_SIZE,
                device=device_name,
                id="header",
            )
            with Vertical(id="sidebar"):
                yield Static("Status", classes="section-title")
                yield StatusPanel(id="status-panel")
                yield Static("Mode", classes="section-title")
                yield ModePanel(current_mode=self.mode, id="mode-panel")
                yield Static("Shortcuts", classes="section-title")
                yield Static("R start/stop\nM mode\nC copy\nQ quit", id="shortcuts")
            with Container(id="main-pane"):
                yield TranscriptPanel(id="transcript-panel")
            yield FooterBar(id="footer")

    def on_mount(self) -> None:
        self.set_interval(0.15, self._drain_events)
        header = self.query_one(AppHeader)
        header.set_mode(self.mode)
        header.set_device(self._controller.get_device_display_name() if self._controller else "Default")
        self.query_one(StatusPanel).status = STATUS_IDLE

    def _drain_events(self) -> None:
        if self._controller:
            self._controller.drain_events()
        # Sync status to panel when recording state changes from session
        if self._controller and self._controller.is_recording() and self.status != STATUS_RECORDING:
            self.status = STATUS_RECORDING
        try:
            sp = self.query_one(StatusPanel)
            if sp.status != self.status:
                sp.status = self.status
            if sp.message != self.status_message:
                sp.message = self.status_message
        except Exception:
            pass

    def action_toggle_recording(self) -> None:
        if not self._controller:
            return
        if self._controller.is_recording():
            self._controller.stop_recording()
        else:
            self._controller.set_mode(self.mode)
            self._controller.start_recording()
            self.status = STATUS_RECORDING
            self.status_message = "Starting…"
            try:
                self.query_one(StatusPanel).status = STATUS_RECORDING
                self.query_one(StatusPanel).message = "Starting…"
            except Exception:
                pass

    def action_cycle_mode(self) -> None:
        idx = list(ALL_MODES).index(self.mode) if self.mode in ALL_MODES else 0
        idx = (idx + 1) % len(ALL_MODES)
        self.mode = ALL_MODES[idx]
        if self._controller:
            self._controller.set_mode(self.mode)
        try:
            self.query_one(AppHeader).set_mode(self.mode)
            self.query_one(ModePanel).set_mode(self.mode)
        except Exception:
            pass
        self.notify(f"Mode: {self.mode}", timeout=1)

    def action_copy_final(self) -> None:
        text = self.last_final_for_copy or self.final_text
        if not text:
            self.notify("No final text to copy", severity="warning", timeout=2)
            return
        from app.clipboard_util import ClipboardManager
        cm = ClipboardManager()
        if cm.copy_text(text):
            self.status = STATUS_COPIED
            self.status_message = "Copied"
            try:
                self.query_one(StatusPanel).status = STATUS_COPIED
                self.query_one(StatusPanel).message = "Copied"
            except Exception:
                pass
            self.notify("Copied to clipboard", severity="information", timeout=2)
        else:
            self.notify(f"Copy failed: {cm.last_error or 'unknown'}", severity="error", timeout=3)

    def action_history(self) -> None:
        self.notify("History panel (Phase 4)", severity="information", timeout=2)

    def on_unmount(self) -> None:
        if self._controller:
            self._controller.stop_recording()


def run_tui(
    device: str | None = None,
    history_path: str = "logs/history.json",
    no_copy: bool = False,
    auto_paste: bool = False,
) -> None:
    app = PromptVoiceApp(
        device=device,
        history_path=history_path,
        no_copy=no_copy,
        auto_paste=auto_paste,
    )
    app.run()
