"""Simple JSON history storage for finalized transcription outputs."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class HistoryStore:
    """Append-only JSON history file writer."""

    def __init__(self, path: str = "logs/history.json", max_entries: int = 1000) -> None:
        self.path = Path(path)
        self.max_entries = max(1, int(max_entries))
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: dict[str, Any]) -> None:
        payload = dict(entry)
        payload.setdefault("saved_at", time.time())

        current = self._load()
        current.append(payload)
        if len(current) > self.max_entries:
            current = current[-self.max_entries :]
        self.path.write_text(
            json.dumps(current, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            raw = self.path.read_text(encoding="utf-8").strip()
            if not raw:
                return []
            loaded = json.loads(raw)
            if isinstance(loaded, list):
                return [item for item in loaded if isinstance(item, dict)]
            return []
        except Exception:
            return []

