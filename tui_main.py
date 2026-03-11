"""Entry point for Textual TUI. Run: python -m prompt_voice.tui_main [options]."""

from __future__ import annotations

import argparse
import logging
import sys

from app.config import DEFAULT_MODE

# Ensure prompt_voice directory is on path when run as script (e.g. python tui_main.py)
if __name__ == "__main__":
    import os
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)

from ui.app import run_tui


def main() -> int:
    parser = argparse.ArgumentParser(
        description="prompt_voice TUI (Textual). R: Start/Stop, M: Mode, C: Copy, Q: Quit.",
    )
    parser.add_argument("--device", type=str, default=None, help="Input device index or name")
    parser.add_argument("--history-path", type=str, default="logs/history.json", help="History JSON path")
    parser.add_argument("--no-copy", action="store_true", help="Do not copy to clipboard on final")
    parser.add_argument("--auto-paste", action="store_true", help="Send Ctrl+V after copy")
    parser.add_argument("--log-level", type=str, default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

    run_tui(
        device=args.device,
        history_path=args.history_path,
        no_copy=args.no_copy,
        auto_paste=args.auto_paste,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
