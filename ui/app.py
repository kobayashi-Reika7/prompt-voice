from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Static

from ui.widgets.status_panel import StatusPanel
from ui.widgets.partial_panel import PartialPanel
from ui.widgets.final_panel import FinalPanel
from ui.widgets.footer_bar import FooterBar


class PromptVoiceApp(App):
    CSS_PATH = "styles.tcss"
    BINDINGS = [
        ("r", "toggle_recording", "Start/Stop"),
        ("m", "cycle_mode", "Mode"),
        ("c", "copy_final", "Copy"),
        ("q", "quit", "Quit"),
    ]

    status = reactive("idle")
    mode = reactive("clean")
    source_label = reactive("mic")
    partial_text = reactive("")
    final_text = reactive("")
    input_level = reactive(0.0)
    copy_message = reactive("-")

    MODES = ["raw", "clean", "cursor", "minutes"]

    def compose(self) -> ComposeResult:
        yield Container(
            Static("prompt_voice", id="header-title"),
            Static("mode: clean", id="header-mode"),
            Static("source: mic", id="header-source"),
            id="header",
        )

        yield Horizontal(
            Vertical(
                StatusPanel(id="status-panel"),
                id="sidebar",
            ),
            Vertical(
                PartialPanel(id="partial-panel"),
                FinalPanel(id="final-panel"),
                id="main-pane",
            ),
            id="content",
        )

        yield FooterBar(id="footer")

    def on_mount(self) -> None:
        self._sync_ui()

    def _sync_ui(self) -> None:
        header_mode = self.query_one("#header-mode", Static)
        header_source = self.query_one("#header-source", Static)
        status_panel = self.query_one(StatusPanel)
        partial_panel = self.query_one(PartialPanel)
        final_panel = self.query_one(FinalPanel)

        header_mode.update(f"mode: {self.mode}")
        header_source.update(f"source: {self.source_label}")

        status_panel.set_status(self.status)
        status_panel.set_mode(self.mode)
        status_panel.set_source(self.source_label)
        status_panel.set_copy_state(self.copy_message)
        status_panel.set_input_level(self.input_level)

        partial_panel.set_partial(self.partial_text)
        final_panel.set_final(self.final_text)

    def watch_status(self, _: str) -> None:
        self._sync_ui()

    def watch_mode(self, _: str) -> None:
        self._sync_ui()

    def watch_source_label(self, _: str) -> None:
        self._sync_ui()

    def watch_partial_text(self, _: str) -> None:
        self._sync_ui()

    def watch_final_text(self, _: str) -> None:
        self._sync_ui()

    def watch_input_level(self, _: float) -> None:
        self._sync_ui()

    def watch_copy_message(self, _: str) -> None:
        self._sync_ui()

    def action_toggle_recording(self) -> None:
        if self.status == "recording":
            self.status = "transcribing"
            # ここで実際は controller.stop_recording() を呼ぶ
            self.partial_text = ""
            self.final_text = self.final_text or "録音終了後の整形済み結果をここに表示"
            self.copy_message = "ready"
        else:
            self.status = "recording"
            # ここで実際は controller.start_recording() を呼ぶ
            self.partial_text = "話し中の暫定文字起こしをここに表示"
            self.copy_message = "-"
            self.input_level = 0.2

    def action_cycle_mode(self) -> None:
        idx = self.MODES.index(self.mode)
        self.mode = self.MODES[(idx + 1) % len(self.MODES)]

    def action_copy_final(self) -> None:
        # ここで実際は clipboard manager を呼ぶ
        if self.final_text.strip():
            self.copy_message = "copied"
            self.status = "copied"

    # ---- 外部コントローラ接続用メソッド ----
    def update_input_level(self, level: float) -> None:
        self.input_level = max(0.0, min(1.0, float(level)))

    def update_partial_text(self, text: str) -> None:
        self.partial_text = text

    def update_final_text(self, text: str) -> None:
        self.final_text = text
        self.status = "idle"

    def update_source_label(self, source: str) -> None:
        self.source_label = source

    def update_status(self, status: str) -> None:
        self.status = status
