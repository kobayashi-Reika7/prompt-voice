"""Clipboard utility module for safe text copy on Windows."""

from __future__ import annotations

import ctypes
import logging
import sys
import time
from typing import Optional

import pyperclip

logger = logging.getLogger(__name__)


class ClipboardManager:
    """
    Clipboard utility focused on reliability for MVP.

    Design notes:
    - Returns bool for copy result to keep caller logic simple.
    - Stores last error/last copied text for future extensibility.
    - Never raises clipboard exceptions to caller in normal flow.
    """

    def __init__(self) -> None:
        self._last_error: Optional[str] = None
        self._last_copied_text: str = ""

    @property
    def last_error(self) -> Optional[str]:
        """Return last clipboard-related error message, if any."""
        return self._last_error

    @property
    def last_copied_text(self) -> str:
        """Return last successfully copied text."""
        return self._last_copied_text

    def copy_text(self, text: str | None) -> bool:
        """
        Copy text to clipboard.

        Returns:
            True when copy succeeds, False otherwise.
        """
        payload = self._normalize_text(text)
        self._last_error = None

        for attempt in range(2):
            try:
                pyperclip.copy(payload)

                # Read-back check to catch edge cases where copy silently fails.
                copied = pyperclip.paste()
                if copied == payload:
                    self._last_copied_text = payload
                    return True

                self._last_error = "Clipboard verification mismatch."
                logger.warning(self._last_error)
            except pyperclip.PyperclipException as exc:
                self._last_error = f"Clipboard is unavailable: {exc}"
                logger.warning(self._last_error)
            except Exception as exc:  # defensive fallback
                self._last_error = f"Unexpected clipboard error: {exc}"
                logger.exception(self._last_error)

            if attempt == 0:
                time.sleep(0.05)

        return False

    def get_text(self) -> str:
        """
        Read current clipboard text.

        Returns empty string when clipboard read fails.
        """
        self._last_error = None
        try:
            value = pyperclip.paste()
            return self._normalize_text(value)
        except pyperclip.PyperclipException as exc:
            self._last_error = f"Clipboard read unavailable: {exc}"
            logger.warning(self._last_error)
            return ""
        except Exception as exc:
            self._last_error = f"Unexpected clipboard read error: {exc}"
            logger.exception(self._last_error)
            return ""

    def clear(self) -> bool:
        """Clear clipboard text by copying an empty string."""
        return self.copy_text("")

    def trigger_paste(self, delay_ms: int = 20) -> bool:
        """
        Simulate Ctrl+V on Windows for auto-paste workflow.

        Returns:
            True when key events are sent, False otherwise.
        """
        self._last_error = None
        if not sys.platform.startswith("win"):
            self._last_error = "Auto-paste key simulation is only supported on Windows."
            return False

        KEYEVENTF_KEYUP = 0x0002
        VK_CONTROL = 0x11
        VK_V = 0x56

        try:
            user32 = ctypes.windll.user32
            user32.keybd_event(VK_CONTROL, 0, 0, 0)
            user32.keybd_event(VK_V, 0, 0, 0)
            time.sleep(max(0.0, float(delay_ms) / 1000.0))
            user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
            user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
            return True
        except Exception as exc:
            self._last_error = f"Failed to trigger Ctrl+V: {exc}"
            logger.warning(self._last_error)
            return False

    @staticmethod
    def _normalize_text(text: str | None) -> str:
        if text is None:
            return ""
        return str(text)

