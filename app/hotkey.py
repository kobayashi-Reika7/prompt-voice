"""Windows hotkey helpers for push-to-talk and key simulation."""

from __future__ import annotations

import sys
from dataclasses import dataclass


class HotkeyError(RuntimeError):
    """Raised when hotkey operations are unavailable or misconfigured."""


@dataclass(slots=True)
class PushToTalkKeyState:
    """Lightweight poll-based push-to-talk key state checker on Windows."""

    ctrl_required: bool = True
    key_vk: int = 0x20  # space

    def is_pressed(self) -> bool:
        if not sys.platform.startswith("win"):
            raise HotkeyError("Push-to-talk polling is only supported on Windows.")

        import ctypes

        user32 = ctypes.windll.user32
        key_pressed = bool(user32.GetAsyncKeyState(self.key_vk) & 0x8000)
        if not key_pressed:
            return False
        if not self.ctrl_required:
            return True
        ctrl_pressed = bool(user32.GetAsyncKeyState(0x11) & 0x8000)  # VK_CONTROL
        return ctrl_pressed

