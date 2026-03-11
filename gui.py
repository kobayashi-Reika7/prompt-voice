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

from app.recording_session import RecordingSession


MODES = ("raw", "clean", "cursor", "minutes")
DEFAULT_MODE = "clean"
HISTORY_PATH = "logs/history.json"
POLL_MS = 150


class PromptVoiceApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("prompt_voice — 音声で文字起こし")
        self.root.minsize(480, 520)
        self.root.geometry("560x580")

        self._event_queue: queue.Queue = queue.Queue()
        self._session: Optional[RecordingSession] = None
        self._recording = False
        self._emotion_frames = ["🎧", "🎙", "✨", "🎧"]
        self._emotion_index = 0
        self._is_transcribing = False

        self._build_ui()
        self._poll_queue()
        self._animate_emotion()

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        # ステータスバー（常に上部で見える）
        self._status_var = tk.StringVar(value="準備完了")
        self._emotion_var = tk.StringVar(value="😊")
        status_frame = ttk.Frame(main)
        status_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(status_frame, text="状態:", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Label(status_frame, textvariable=self._emotion_var, font=("Segoe UI Emoji", 13)).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Label(
            status_frame, textvariable=self._status_var,
            font=("Segoe UI", 10), foreground="#333"
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._level_var = tk.StringVar(value="input: [░░░░░░░░░░░░]")
        ttk.Label(status_frame, textvariable=self._level_var, font=("Consolas", 9), foreground="#666").pack(
            side=tk.RIGHT
        )

        # メイン操作: 大きめの「話す」ボタン
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(0, 12))
        self._record_btn = tk.Button(
            btn_frame,
            text="🎙 話す",
            command=self._toggle_recording,
            font=("Segoe UI", 16, "bold"),
            fg="white",
            bg="#0d6efd",
            activebackground="#0a58ca",
            activeforeground="white",
            relief=tk.FLAT,
            padx=32,
            pady=14,
            cursor="hand2",
        )
        self._record_btn.pack(side=tk.LEFT)
        self._record_btn.bind("<Enter>", lambda e: self._record_btn.config(bg="#0a58ca") if not self._recording else None)
        self._record_btn.bind("<Leave>", lambda e: self._record_btn.config(bg="#0d6efd") if not self._recording else None)
        ttk.Label(btn_frame, text="  → 話し終わったら「停止」で確定・コピー", font=("Segoe UI", 10), foreground="#666").pack(side=tk.LEFT, padx=(12, 0))

        # オプション行（モード・チェック）
        opt = ttk.LabelFrame(main, text="オプション", padding=6)
        opt.pack(fill=tk.X, pady=(0, 8))

        row1 = ttk.Frame(opt)
        row1.pack(fill=tk.X)
        ttk.Label(row1, text="出力:").pack(side=tk.LEFT, padx=(0, 4))
        self._mode_var = tk.StringVar(value=DEFAULT_MODE)
        mode_combo = ttk.Combobox(
            row1, textvariable=self._mode_var, values=MODES, state="readonly", width=8
        )
        mode_combo.pack(side=tk.LEFT, padx=(0, 20))
        ttk.Label(row1, text="入力: 自動（マイク + 内部音）", foreground="#555").pack(side=tk.LEFT, padx=(0, 10))

        self._copy_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row1, text="確定時にコピー", variable=self._copy_var).pack(side=tk.LEFT, padx=(8, 0))
        self._autopaste_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row1, text="自動貼り付け", variable=self._autopaste_var).pack(side=tk.LEFT, padx=(4, 0))
        self._partial_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row1, text="話し中も表示", variable=self._partial_var).pack(side=tk.LEFT, padx=(4, 0))

        # プロンプト（任意）
        prompt_frame = ttk.LabelFrame(main, text="プロンプト（任意・固有名詞や整形のヒント）", padding=4)
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

        # 話し中表示
        partial_frame = ttk.LabelFrame(main, text="話し中（暫定）", padding=4)
        partial_frame.pack(fill=tk.BOTH, expand=False, pady=(0, 4))
        self._partial_text = tk.Text(
            partial_frame, height=2, wrap=tk.WORD, state=tk.DISABLED,
            font=("Segoe UI", 10), bg="#f0f4f8", fg="#555"
        )
        self._partial_text.pack(fill=tk.BOTH, expand=True)

        # 確定テキスト
        final_frame = ttk.LabelFrame(main, text="確定テキスト（ここに表示され、コピーされます）", padding=4)
        final_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        self._final_text = tk.Text(
            final_frame, wrap=tk.WORD, state=tk.DISABLED,
            font=("Segoe UI", 11)
        )
        self._final_text.pack(fill=tk.BOTH, expand=True)

        # 操作ボタン
        row = ttk.Frame(main)
        row.pack(fill=tk.X)
        ttk.Button(row, text="📋 クリップボードにコピー", command=self._copy_final).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(row, text="クリア", command=self._clear_final).pack(side=tk.LEFT)

    def _toggle_recording(self) -> None:
        if self._recording:
            if self._session:
                self._session.stop()
            self._record_btn.config(text="🎙 話す", bg="#0d6efd")
            self._record_btn.bind("<Leave>", lambda e: self._record_btn.config(bg="#0d6efd"))
            self._is_transcribing = False
            self._set_status("😌", "停止しました")
            self._recording = False
            return

        mode = self._mode_var.get().strip() or DEFAULT_MODE
        if mode not in MODES:
            mode = DEFAULT_MODE
        no_copy = not self._copy_var.get()
        auto_paste = self._autopaste_var.get()
        show_partial = self._partial_var.get()
        initial_prompt = self._prompt_text.get("1.0", tk.END).strip() or None

        self._session = RecordingSession(
            self._event_queue,
            mode=mode,
            no_copy=no_copy,
            auto_paste=auto_paste,
            history_path=HISTORY_PATH,
            show_partial=show_partial,
            initial_prompt=initial_prompt,
        )
        self._session.start()
        self._recording = True
        self._is_transcribing = False
        self._record_btn.config(text="⏹ 停止", bg="#dc3545")
        self._record_btn.bind("<Leave>", lambda e: None)  # 録音中はホバーで色を戻さない
        self._set_status("🎧", "録音中… 話し終わったら「停止」を押してください")

    def _copy_final(self) -> None:
        text = self._final_text.get("1.0", tk.END).strip()
        if not text:
            self._set_status("🤔", "コピーするテキストがありません")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._set_status("📋", "コピーしました")

    def _clear_final(self) -> None:
        self._final_text.config(state=tk.NORMAL)
        self._final_text.delete("1.0", tk.END)
        self._final_text.config(state=tk.DISABLED)
        self._partial_text.config(state=tk.NORMAL)
        self._partial_text.delete("1.0", tk.END)
        self._partial_text.config(state=tk.DISABLED)
        self._set_status("🧹", "クリアしました")

    def _set_status(self, emotion: str, text: str) -> None:
        self._emotion_var.set(emotion)
        self._status_var.set(text)

    @staticmethod
    def _meter_bar(level: float, width: int = 12) -> str:
        clamped = max(0.0, min(1.0, float(level)))
        filled = int(round(clamped * width))
        return ("█" * filled) + ("░" * max(0, width - filled))

    def _animate_emotion(self) -> None:
        # 録音中は軽いアニメーションで「読み取り中」を視覚化する。
        if self._recording and not self._is_transcribing:
            self._emotion_var.set(self._emotion_frames[self._emotion_index % len(self._emotion_frames)])
            self._emotion_index += 1
        self.root.after(350, self._animate_emotion)

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
                    self._is_transcribing = True
                    self._set_status("🧠", "読み取り中…")
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
                    self._is_transcribing = False
                    self._set_status("✨", "確定テキストを追加しました")
                elif kind == "error":
                    msg = ev.get("message", "不明なエラー")
                    self._is_transcribing = False
                    self._set_status("⚠", f"エラー: {msg}")
                    messagebox.showerror(
                        "prompt_voice",
                        msg + "\n\nWindowsのマイク許可と既定のスピーカー設定を確認してください。",
                    )
                elif kind == "status":
                    self._set_status("🎧", ev.get("message", ""))
                elif kind == "level":
                    level = float(ev.get("level", 0.0))
                    active = bool(ev.get("active", False))
                    self._level_var.set(f"input: [{self._meter_bar(level)}]")
                    if self._recording and not self._is_transcribing:
                        self._emotion_var.set("🎙" if active else "🎧")
                elif kind == "stopped":
                    self._is_transcribing = False
                    self._set_status("😌", "停止しました")
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
