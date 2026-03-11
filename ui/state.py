"""UI state constants and helpers."""

from __future__ import annotations

# App status for display
STATUS_IDLE = "idle"
STATUS_RECORDING = "recording"
STATUS_TRANSCRIBING = "transcribing"
STATUS_COPIED = "copied"
STATUS_ERROR = "error"

ALL_MODES = ("raw", "clean", "cursor", "minutes")
