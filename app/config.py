"""Application-wide configuration for prompt_voice MVP."""

from __future__ import annotations

# Audio capture settings
SAMPLE_RATE: int = 16_000
CHANNELS: int = 1
BLOCK_MS: int = 30
BLOCK_SIZE: int = max(1, int(SAMPLE_RATE * BLOCK_MS / 1000))

# Voice activity detection defaults（閾値を下げると発話を検知しやすくなる）
VAD_THRESHOLD: float = 0.35
VAD_MIN_SILENCE_MS: int = 600
VAD_MIN_SPEECH_MS: int = 150
MAX_UTTERANCE_SECONDS: int = 30
MAX_BUFFER_SECONDS: int = 45

# Transcription settings
PARTIAL_INTERVAL_MS: int = 500
MODEL_SIZE: str = "small"
DEVICE: str = "cpu"  # "cpu" or "cuda"
COMPUTE_TYPE: str = "int8"  # ex: int8 / float16
LANGUAGE: str = "ja"

# Output formatting mode
DEFAULT_MODE: str = "clean"
