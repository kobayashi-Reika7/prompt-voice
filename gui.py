"""Desktop UI for prompt_voice (tkinter)."""

from __future__ import annotations

import queue
import sys
from pathlib import Path

# Allow "python gui.py" from prompt_voice/ or project root
if __name__ == "__main__":
    _root = Path(__file__).resolve().parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional

from app.audio_capture import get_default_input_device_index
from app.recording_session import RecordingSession, get_input_devices


MODES = ("raw", "clean", "cursor", "minutes")
DEFAULT_MODE = "clean"
HISTORY_PATH = "logs/history.json"
POLL_MS = 150


class PromptVoiceApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("prompt_voice")
        self.root.minsize(420, 380)
        self.root.geometry("520x480")

        self._event_queue: queue.Queue = queue.Queue()
        self._session: Optional[RecordingSession] = None
        self._recording = False

        self._build_ui()
        self._poll_queue()

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        # Prompt (initial_prompt for Whisper)
        prompt_frame = ttk.LabelFrame(main, text="プロンプト（認識のヒント・固有名詞など）", padding=4)
        prompt_frame.pack(fill=tk.X, pady=(0, 6))
        self._prompt_text = tk.Text(
            prompt_frame, height=2, wrap=tk.WORD, font=("Segoe UI", 10)
        )
        self._prompt_text.pack(fill=tk.X)
        self._prompt_text.insert("1.0", "")
        self._prompt_text.bind(
            "<Control-a>",
            lambda e: (self._prompt_text.tag_add("sel", "1.0", tk.END), "break")[1],
        )

        # Toolbar
        bar = ttk.Frame(main)
        bar.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(bar, text="モード:").pack(side=tk.LEFT, padx=(0, 4))
        self._mode_var = tk.StringVar(value=DEFAULT_MODE)
        mode_combo = ttk.Combobox(
            bar, textvariable=self._mode_var, values=MODES, state="readonly", width=10
        )
        mode_combo.pack(side=tk.LEFT, padx=(0, 12))

        ttk.Label(bar, text="マイク:").pack(side=tk.LEFT, padx=(0, 4))
        devices = get_input_devices()
        device_names = [f"{d['index']}: {d['name'][:30]}" for d in devices]
        default_idx = get_default_input_device_index()
        initial_device = device_names[0] if device_names else ""
        if device_names and default_idx is not None:
            for s in device_names:
                if s.startswith(f"{default_idx}:") or s.startswith(f"{default_idx} "):
                    initial_device = s
                    break
        self._device_var = tk.StringVar(value=initial_device)
        self._device_combo = ttk.Combobox(
            bar, textvariable=self._device_var, values=device_names, width=28
        )
        self._device_combo.pack(side=tk.LEFT, padx=(0, 8))

        self._copy_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="コピー", variable=self._copy_var).pack(side=tk.LEFT, padx=(8, 0))
        self._autopaste_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="自動貼り付け", variable=self._autopaste_var).pack(
            side=tk.LEFT, padx=(4, 0)
        )
        self._partial_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="暫定表示", variable=self._partial_var).pack(
            side=tk.LEFT, padx=(4, 0)
        )

        self._record_btn = ttk.Button(bar, text="録音開始", command=self._toggle_recording)
        self._record_btn.pack(side=tk.RIGHT, padx=(8, 0))
        if not device_names:
            self._record_btn.config(state=tk.DISABLED)

        # Partial (live) area
        partial_frame = ttk.LabelFrame(main, text="暫定 (partial)", padding=4)
        partial_frame.pack(fill=tk.BOTH, expand=False, pady=(0, 4))
        self._partial_text = tk.Text(
            partial_frame, height=3, wrap=tk.WORD, state=tk.DISABLED,
            font=("Segoe UI", 10), bg="#f5f5f5", fg="#555"
        )
        self._partial_text.pack(fill=tk.BOTH, expand=True)

        # Final area
        final_frame = ttk.LabelFrame(main, text="確定 (final)", padding=4)
        final_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 4))
        self._final_text = tk.Text(
            final_frame, wrap=tk.WORD, state=tk.DISABLED,
            font=("Segoe UI", 10)
        )
        self._final_text.pack(fill=tk.BOTH, expand=True)

        # Actions + status
        row = ttk.Frame(main)
        row.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(row, text="クリップボードにコピー", command=self._copy_final).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(row, text="確定テキストをクリア", command=self._clear_final).pack(side=tk.LEFT)
        self._status_var = tk.StringVar(value="停止中")
        if not device_names:
            self._status_var.set("マイクが見つかりません。接続とWindowsのマイク許可を確認してください。")
        ttk.Label(row, textvariable=self._status_var).pack(side=tk.RIGHT)

    def _device_index_or_name(self) -> Optional[str]:
        s = self._device_var.get().strip()
        if not s:
            return None
        if ":" in s and s.split(":")[0].strip().isdigit():
            return s.split(":")[0].strip()
        return s

    def _toggle_recording(self) -> None:
        if self._recording:
            if self._session:
                self._session.stop()
            self._record_btn.config(text="録音開始")
            self._status_var.set("停止中")
            self._recording = False
            return

        mode = self._mode_var.get().strip() or DEFAULT_MODE
        if mode not in MODES:
            mode = DEFAULT_MODE
        device = self._device_index_or_name()
        no_copy = not self._copy_var.get()
        auto_paste = self._autopaste_var.get()
        show_partial = self._partial_var.get()
        initial_prompt = self._prompt_text.get("1.0", tk.END).strip() or None

        self._session = RecordingSession(
            self._event_queue,
            mode=mode,
            device=device,
            no_copy=no_copy,
            auto_paste=auto_paste,
            history_path=HISTORY_PATH,
            show_partial=show_partial,
            initial_prompt=initial_prompt,
        )
        self._session.start()
        self._recording = True
        self._record_btn.config(text="録音停止")
        self._status_var.set("録音中…")

    def _copy_final(self) -> None:
        text = self._final_text.get("1.0", tk.END).strip()
        if not text:
            self._status_var.set("コピーするテキストがありません")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._status_var.set("コピーしました")

    def _clear_final(self) -> None:
        self._final_text.config(state=tk.NORMAL)
        self._final_text.delete("1.0", tk.END)
        self._final_text.config(state=tk.DISABLED)
        self._partial_text.config(state=tk.NORMAL)
        self._partial_text.delete("1.0", tk.END)
        self._partial_text.config(state=tk.DISABLED)
        self._status_var.set("クリアしました")

    def _poll_queue(self) -> None:
        try:
            while True:
                ev = self._event_queue.get_nowait()
                kind = ev.get("type", "")
                if kind == "partial":
                    self._partial_text.config(state=tk.NORMAL)
                    self._partial_text.delete("1.0", tk.END)
                    self._partial_text.insert(tk.END, ev.get("text", ""))
                    self._partial_text.config(state=tk.DISABLED)
                elif kind == "final":
                    self._partial_text.config(state=tk.NORMAL)
                    self._partial_text.delete("1.0", tk.END)
                    self._partial_text.config(state=tk.DISABLED)
                    self._final_text.config(state=tk.NORMAL)
                    text = ev.get("text", "")
                    if self._final_text.get("1.0", tk.END).strip():
                        self._final_text.insert(tk.END, "\n\n")
                    self._final_text.insert(tk.END, text)
                    self._final_text.see(tk.END)
                    self._final_text.config(state=tk.DISABLED)
                    self._status_var.set("確定テキストを追加しました")
                elif kind == "error":
                    msg = ev.get("message", "不明なエラー")
                    self._status_var.set(f"エラー: {msg}")
                    messagebox.showerror(
                        "prompt_voice",
                        msg + "\n\nマイクが正しく選ばれているか、Windowsのマイク許可を確認してください。",
                    )
                elif kind == "status":
                    self._status_var.set(ev.get("message", ""))
                elif kind == "stopped":
                    self._status_var.set("停止しました")
        except queue.Empty:
            pass
        self.root.after(POLL_MS, self._poll_queue)

    def run(self) -> None:
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _on_close(self) -> None:
        if self._recording and self._session:
            self._session.stop()
        self.root.destroy()


def main() -> int:
    app = PromptVoiceApp()
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
