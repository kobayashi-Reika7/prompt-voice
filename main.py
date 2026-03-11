"""CLI entrypoint for local realtime voice input MVP."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import Any, Optional

from app.audio_capture import (
    AudioCapture,
    AudioCaptureError,
    get_default_input_device_index,
    list_input_devices,
)
from app.clipboard_util import ClipboardManager
from app.config import DEFAULT_MODE, MODEL_SIZE, PARTIAL_INTERVAL_MS
from app.formatter import FormatterError, TextFormatter
from app.history import HistoryStore
from app.hotkey import HotkeyError, PushToTalkKeyState
from app.transcriber import LocalTranscriber, TranscriberError
from app.vad import VADError, create_default_detector

try:
    from rich.console import Console, Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.text import Text
    from rich.rule import Rule
except Exception:  # pragma: no cover - fallback for minimal environments
    Console = None  # type: ignore[assignment]
    Live = None  # type: ignore[assignment]
    Panel = None  # type: ignore[assignment]
    Group = None  # type: ignore[assignment]
    Text = None  # type: ignore[assignment]
    Rule = None  # type: ignore[assignment]


LOGGER = logging.getLogger("prompt_voice.main")
ALLOWED_MODES = ("raw", "clean", "cursor", "minutes")


def _source_label(source_type: str) -> str:
    # Prepared for future: auto|mic|system selection.
    if source_type == "mic":
        return "マイク"
    if source_type == "system":
        return "システム音"
    return "不明"


def _diagnostic_lines(diag) -> list[str]:
    """User-friendly, non-technical diagnostic lines."""
    lines: list[str] = []
    if diag.has_signal:
        lines.append(f"入力OK: {_source_label(diag.source_type)}音声を検出しました")
    else:
        lines.append("音が入っていません（入力なし）")
    lines.append(f"入力デバイス: {diag.device_name}")
    lines.append(f"レベル: peak={diag.peak_level:.3f} / rms={diag.avg_level:.3f}")
    if not diag.has_signal:
        lines.append("会議相手の声は通常、マイクではなくスピーカー出力です")
        lines.append("Teams / Zoom / Meet の会議全体をまとめたい場合は、今後 system audio 対応が必要です")
    if diag.note:
        lines.append(str(diag.note))
    return lines


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local realtime voice input MVP (Windows/CLI).",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default=DEFAULT_MODE,
        choices=ALLOWED_MODES,
        help="Output formatting mode.",
    )
    parser.add_argument(
        "--device",
        type=str,
        default=None,
        help="Input device index or name (optional).",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default=None,
        help="User prompt for formatting (optional). If omitted, you can enter it before recording.",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List available input devices and exit.",
    )
    parser.add_argument(
        "--no-copy",
        action="store_true",
        help="Disable clipboard copy on final output.",
    )
    parser.add_argument(
        "--show-partial",
        action="store_true",
        help="Show partial realtime recognition during speech.",
    )
    parser.add_argument(
        "--push-to-talk",
        action="store_true",
        help="Enable push-to-talk. Hold Ctrl+Space while speaking.",
    )
    parser.add_argument(
        "--auto-paste",
        action="store_true",
        help="After copy, automatically send Ctrl+V.",
    )
    parser.add_argument(
        "--history-path",
        type=str,
        default="logs/history.json",
        help="Path to history JSON file.",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Logging level.",
    )
    return parser


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )


def _resolve_device(raw_device: Optional[str]) -> Optional[int | str]:
    if raw_device is None:
        return None
    stripped = raw_device.strip()
    if stripped == "":
        return None
    if stripped.isdigit() or (stripped.startswith("-") and stripped[1:].isdigit()):
        return int(stripped)
    return stripped


def _print(console: Optional[Console], message: str, style: str = "") -> None:
    safe_message = message
    try:
        safe_message = message.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
            sys.stdout.encoding or "utf-8", errors="replace"
        )
    except Exception:
        safe_message = message

    if console is not None:
        try:
            if style:
                console.print(safe_message, style=style)
            else:
                console.print(safe_message)
            return
        except UnicodeEncodeError:
            pass
    print(safe_message)


def _get_device_display_name(device: Optional[int | str]) -> str:
    """Return a short display name for the given device (for header)."""
    try:
        devices = list_input_devices()
    except AudioCaptureError:
        return "Default"
    if device is None:
        default_idx = get_default_input_device_index()
        if default_idx is not None:
            for d in devices:
                if d["index"] == default_idx:
                    return d["name"][:36] + ("..." if len(d["name"]) > 36 else "")
        return "Default"
    if isinstance(device, int):
        for d in devices:
            if d["index"] == device:
                return d["name"][:36] + ("..." if len(d["name"]) > 36 else "")
        return f"Device {device}"
    return str(device)[:40]


def _build_header_panel(mode: str, device_name: str, model_size: str):
    """Build the header panel (rich)."""
    if Panel is None or Text is None:
        return None
    lines = [
        Text("prompt_voice", style="bold cyan"),
        Text(f"mode: {mode}", style="dim"),
        Text(f"model: faster-whisper-{model_size}", style="dim"),
        Text(f"device: {device_name}", style="dim"),
    ]
    return Panel(Group(*lines), title="", border_style="blue", padding=(0, 1))


def _build_live_renderable(state: dict[str, Any], use_rich: bool) -> Any:
    """Build the single refreshable layout for Live display."""
    if not use_rich or Group is None or Panel is None or Text is None or Rule is None:
        return None
    parts = []
    # Header
    header = state.get("header")
    if header:
        parts.append(header)
    # Status line with icon
    icon = state.get("status_icon", "⏳")
    status = state.get("status", "Listening...")
    parts.append(Text().append(icon + " ", style="bold").append(status, style="cyan"))
    parts.append(Rule(style="dim"))
    # Partial (dim)
    partial = (state.get("partial_text") or "").strip()
    if partial:
        parts.append(Text("partial", style="dim italic"))
        parts.append(Text(partial, style="dim"))
        parts.append(Rule(style="dim"))
    # Final result panel
    final_text = (state.get("final_text") or "").strip()
    if final_text:
        parts.append(Panel(Text(final_text, style="white"), title="RESULT", border_style="green", padding=(0, 1)))
        parts.append(Rule(style="dim"))
    # Copy status
    copy_msg = state.get("copy_message", "")
    if copy_msg:
        style = "bold green" if state.get("copied", False) else "dim"
        parts.append(Text(copy_msg, style=style))
    # Error
    err = state.get("error_message", "")
    if err:
        parts.append(Text("⚠ " + err, style="bold red"))
    return Group(*parts)


def show_devices(console: Optional[Console]) -> int:
    try:
        devices = list_input_devices()
    except AudioCaptureError as exc:
        _print(console, f"Failed to list input devices: {exc}", "red")
        return 1

    if not devices:
        _print(console, "No input devices found.", "yellow")
        return 0

    _print(console, "Available input devices:", "bold cyan")
    for dev in devices:
        _print(
            console,
            (
                f"[{dev['index']}] {dev['name']} | "
                f"max_in={dev['max_input_channels']} | "
                f"default_sr={int(dev['default_samplerate'])}"
            ),
        )
    return 0


def _handle_final_segment(
    *,
    segment,
    transcriber: LocalTranscriber,
    formatter: TextFormatter,
    clipboard: ClipboardManager,
    history: HistoryStore,
    console: Optional[Console],
    mode: str,
    prompt: Optional[str],
    no_copy: bool,
    auto_paste: bool,
    finalized_count: int,
    state: Optional[dict[str, Any]] = None,
) -> tuple[int, str, str, bool]:
    """Returns (finalized_count, formatted_text, copy_status_display, copied)."""
    try:
        transcript = transcriber.transcribe_segment(segment)
    except TranscriberError as exc:
        msg = f"Transcription failed: {exc}"
        _print(console, msg, "red")
        if state is not None:
            state["error_message"] = msg
        return finalized_count, "", msg, False

    if transcript is None or not transcript.text.strip():
        return finalized_count, "", "", False

    raw_text = transcript.text.strip()
    try:
        formatted = formatter.format_text(raw_text, mode=mode, prompt=prompt, is_partial=False)
    except FormatterError as exc:
        _print(console, f"Formatting failed: {exc}", "red")
        formatted = raw_text

    if not formatted:
        return finalized_count, "", "", False

    copied = False
    copy_status = "copy skipped"
    if not no_copy:
        copied = clipboard.copy_text(formatted)
        if copied:
            copy_status = "✓ Copied to clipboard"
        else:
            copy_status = f"copy failed ({clipboard.last_error or 'unknown error'})"

    pasted = False
    if auto_paste and copied:
        pasted = clipboard.trigger_paste()
        if pasted:
            copy_status += " · Pasted"
        else:
            copy_status += f" · paste failed ({clipboard.last_error or 'unknown error'})"

    history.append(
        {
            "type": "final",
            "mode": mode,
            "raw_text": raw_text,
            "formatted_text": formatted,
            "copied": copied,
            "pasted": pasted,
            "confidence": transcript.confidence,
            "language": transcript.language,
            "utterance_id": transcript.utterance_id,
            "started_at": getattr(transcript, "started_at", None),
            "ended_at": getattr(transcript, "ended_at", None),
        }
    )

    finalized_count += 1
    if state is None:
        _print(console, f"\n--- final #{finalized_count} ({copy_status}) ---", "bold magenta")
        _print(console, formatted)
    return finalized_count, formatted, copy_status, copied


def run(args: argparse.Namespace) -> int:
    console = Console() if Console is not None else None
    use_live = (
        Console is not None
        and Live is not None
        and Panel is not None
        and Group is not None
        and Text is not None
        and Rule is not None
    )

    if args.list_devices:
        return show_devices(console)

    # Prompt input (before recording). MVP: keep it optional and simple.
    prompt: Optional[str] = (args.prompt or "").strip() or None
    if prompt is None and sys.stdin is not None and sys.stdin.isatty():
        _print(console, "整形プロンプトを入力してください（空でスキップ）。複数行OK、空行で確定。", "bold cyan")
        lines: list[str] = []
        while True:
            try:
                line = input()
            except EOFError:
                break
            if line.strip() == "":
                break
            lines.append(line)
        prompt = "\n".join(lines).strip() or None

    try:
        formatter = TextFormatter(default_mode=args.mode)
    except FormatterError as exc:
        _print(console, f"Invalid formatter setup: {exc}", "red")
        return 1

    clipboard = ClipboardManager()
    history = HistoryStore(path=args.history_path)

    try:
        detector = create_default_detector()
    except VADError as exc:
        _print(console, f"Failed to initialize VAD: {exc}", "red")
        return 1

    try:
        transcriber = LocalTranscriber()
    except TranscriberError as exc:
        _print(console, f"Failed to initialize transcriber: {exc}", "red")
        return 1

    ptt_key: Optional[PushToTalkKeyState] = None
    if args.push_to_talk:
        try:
            ptt_key = PushToTalkKeyState(ctrl_required=True, key_vk=0x20)
            _ = ptt_key.is_pressed()
        except HotkeyError as exc:
            _print(console, f"Push-to-talk unavailable: {exc}", "red")
            return 1

    device = _resolve_device(args.device)
    capture = AudioCapture(device=device)
    device_name = _get_device_display_name(device)

    # Display state for Live UI (or fallback prints)
    state: dict[str, Any] = {
        "header": _build_header_panel(args.mode, device_name, MODEL_SIZE) if use_live else None,
        "status_icon": "🎙",
        "status": "Starting...",
        "partial_text": "",
        "final_text": "",
        "copy_message": "",
        "copied": False,
        "error_message": "",
    }

    if not use_live:
        _print(console, "Starting audio capture... (Ctrl+C to stop)", "bold green")
        _print(
            console,
            f"mode={args.mode}, copy={'off' if args.no_copy else 'on'}, "
            f"partial={'on' if args.show_partial else 'off'}, "
            f"ptt={'on (Ctrl+Space)' if args.push_to_talk else 'off'}, "
            f"autopaste={'on' if args.auto_paste else 'off'}",
            "cyan",
        )
        if prompt:
            _print(console, "整形プロンプト:", "bold cyan")
            _print(console, prompt, "cyan")

    # Input self-test (before starting capture) for UX-friendly feedback.
    try:
        diag = capture.run_self_test(2.5)
        # Prefer actual device name from capture/PortAudio over device list label.
        device_name = diag.device_name or device_name
        if use_live:
            state["header"] = _build_header_panel(args.mode, device_name, MODEL_SIZE)
            state["status_icon"] = "✅" if diag.has_signal else "⚠"
            state["status"] = " / ".join(_diagnostic_lines(diag)[:2])
            state["error_message"] = "" if diag.has_signal else " / ".join(_diagnostic_lines(diag)[2:])
        else:
            style = "bold green" if diag.has_signal else "bold yellow"
            for line in _diagnostic_lines(diag):
                _print(console, line, style if line.startswith(("入力OK", "音が入っていません")) else "cyan")
    except Exception as exc:
        # Do not block MVP flow; capture.start() may still work even if self-test fails.
        LOGGER.warning("Self-test failed: %s", exc)
        if use_live:
            state["status_icon"] = "⚠"
            state["status"] = "入力診断に失敗しました（録音は続行します）"
        else:
            _print(console, f"入力診断に失敗しました（録音は続行します）: {exc}", "yellow")

    last_partial_ts = 0.0
    last_partial_text = ""
    finalized_count = 0
    ptt_prev_pressed = not args.push_to_talk

    try:
        capture.start()
    except AudioCaptureError as exc:
        _print(console, f"Could not start audio capture: {exc}", "red")
        return 1

    def update_display() -> None:
        if use_live and Live is not None:
            renderable = _build_live_renderable(state, use_rich=True)
            if renderable is not None and live_ref[0] is not None:
                live_ref[0].update(renderable)

    live_ref: list[Optional[Any]] = [None]

    try:
        with (
            Live(
                _build_live_renderable(state, use_rich=use_live),
                console=console,
                refresh_per_second=4,
                transient=False,
            )
            if use_live
            else _NullContext()
        ) as live:
            if use_live:
                live_ref[0] = live
            while True:
                callback_error = capture.get_error()
                if callback_error:
                    LOGGER.warning("Audio capture warning: %s", callback_error)

                ptt_pressed = True
                if ptt_key is not None:
                    try:
                        ptt_pressed = ptt_key.is_pressed()
                    except HotkeyError as exc:
                        _print(console, f"Push-to-talk error: {exc}", "red")
                        return 1

                    if ptt_pressed and not ptt_prev_pressed:
                        detector.reset()
                        last_partial_text = ""
                        state["partial_text"] = ""
                        state["status_icon"] = "🎙"
                        state["status"] = "Recording..."
                        if not use_live:
                            _print(console, "[ptt] recording started", "green")
                    elif (not ptt_pressed) and ptt_prev_pressed:
                        tail = detector.flush()
                        if tail is not None:
                            finalized_count, fmt, copy_status, copied = _handle_final_segment(
                                segment=tail,
                                transcriber=transcriber,
                                formatter=formatter,
                                clipboard=clipboard,
                                history=history,
                                console=None if use_live else console,
                                mode=args.mode,
                                no_copy=args.no_copy,
                                auto_paste=args.auto_paste,
                                finalized_count=finalized_count,
                                state=state if use_live else None,
                            )
                            if use_live and fmt:
                                state["final_text"] = fmt
                                state["copy_message"] = copy_status
                                state["copied"] = copied
                                state["error_message"] = ""
                                update_display()
                        detector.reset()
                        last_partial_text = ""
                        state["partial_text"] = ""
                        state["status_icon"] = "🎙"
                        state["status"] = "Listening..."
                        if not use_live:
                            _print(console, "[ptt] recording stopped", "yellow")
                    ptt_prev_pressed = ptt_pressed

                chunk = capture.get_chunk(timeout=0.2)
                if chunk is None:
                    if use_live:
                        update_display()
                    continue
                if not ptt_pressed:
                    continue

                segment = detector.process_chunk(chunk)

                if args.show_partial:
                    now = time.time()
                    if now - last_partial_ts >= PARTIAL_INTERVAL_MS / 1000.0:
                        current = detector.get_current_segment()
                        if current is not None and current.duration_sec > 0.1:
                            try:
                                partial = transcriber.partial_transcribe(current)
                                raw_partial_text = (partial.text if partial is not None else "").strip()
                                if raw_partial_text and raw_partial_text != last_partial_text:
                                    formatted_partial = formatter.format_text(
                                        raw_partial_text,
                                        mode=args.mode,
                                        prompt=prompt,
                                        is_partial=True,
                                    )
                                    state["status_icon"] = "🧠"
                                    state["status"] = "Transcribing..."
                                    state["partial_text"] = formatted_partial or raw_partial_text
                                    last_partial_text = raw_partial_text
                                    if use_live:
                                        update_display()
                                    else:
                                        _print(console, f"[partial] {state['partial_text']}", "dim")
                            except TranscriberError as exc:
                                LOGGER.debug("Partial transcription skipped: %s", exc)
                        else:
                            state["status_icon"] = "🎙"
                            state["status"] = "Listening..."
                        last_partial_ts = now

                if segment is not None:
                    state["status_icon"] = "🧠"
                    state["status"] = "Transcribing..."
                    if use_live:
                        update_display()
                    finalized_count, fmt, copy_status, copied = _handle_final_segment(
                        segment=segment,
                        transcriber=transcriber,
                        formatter=formatter,
                        clipboard=clipboard,
                        history=history,
                        console=None if use_live else console,
                        mode=args.mode,
                        prompt=prompt,
                        no_copy=args.no_copy,
                        auto_paste=args.auto_paste,
                        finalized_count=finalized_count,
                        state=state if use_live else None,
                    )
                    if use_live and fmt:
                        state["final_text"] = fmt
                        state["copy_message"] = copy_status
                        state["copied"] = copied
                        state["error_message"] = ""
                    state["status_icon"] = "🎙"
                    state["status"] = "Listening..."
                    if use_live:
                        update_display()
                    # when not use_live, _handle_final_segment already printed

    except KeyboardInterrupt:
        if not use_live:
            _print(console, "\nStopping... finalizing buffered utterance.", "yellow")
    except Exception as exc:
        LOGGER.exception("Unexpected runtime error")
        _print(console, f"Unexpected error: {exc}", "red")
        return 1
    finally:
        try:
            tail_segment = detector.flush()
            if tail_segment is not None:
                finalized_count, fmt, copy_status, copied = _handle_final_segment(
                    segment=tail_segment,
                    transcriber=transcriber,
                    formatter=formatter,
                    clipboard=clipboard,
                    history=history,
                    console=None if use_live else console,
                    mode=args.mode,
                    prompt=prompt,
                    no_copy=args.no_copy,
                    auto_paste=args.auto_paste,
                    finalized_count=finalized_count,
                    state=state if use_live else None,
                )
                if use_live and fmt and console is not None and Panel is not None and Text is not None:
                    state["final_text"] = fmt
                    state["copy_message"] = copy_status
                    state["copied"] = copied
                    console.print(Panel(Text(fmt, style="white"), title="RESULT", border_style="green", padding=(0, 1)))
                    console.print(Text("✓ Copied to clipboard", style="bold green") if copied else Text(copy_status, style="dim"))
        except Exception as exc:
            LOGGER.warning("Flush processing failed: %s", exc)
        finally:
            capture.stop()
            if use_live:
                _print(console, "Stopped.", "dim")
            else:
                _print(console, "Stopped.", "bold green")

    return 0


class _NullContext:
    """No-op context manager when Live is not used."""

    def __enter__(self) -> None:
        pass

    def __exit__(self, *args: Any) -> None:
        pass


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.log_level)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())

