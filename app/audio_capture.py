"""Microphone audio capture module for Windows-friendly MVP."""

from __future__ import annotations

import logging
import queue
import threading
import time
from itertools import count
from typing import Any, Dict, List, Optional

import numpy as np
import sounddevice as sd

from .config import BLOCK_SIZE, CHANNELS, SAMPLE_RATE
from .models import AudioChunk, InputDiagnosticResult

logger = logging.getLogger(__name__)


class AudioCaptureError(RuntimeError):
    """Raised when audio capture cannot start or continue safely."""


class AudioCapture:
    """Continuously captures microphone audio and pushes AudioChunk to a queue."""

    def __init__(
        self,
        *,
        sample_rate: int = SAMPLE_RATE,
        channels: int = CHANNELS,
        block_size: int = BLOCK_SIZE,
        device: Optional[int | str] = None,
        queue_maxsize: int = 256,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.block_size = block_size
        self.device = device

        self.chunk_queue: "queue.Queue[AudioChunk]" = queue.Queue(maxsize=queue_maxsize)
        self.error_queue: "queue.Queue[str]" = queue.Queue(maxsize=64)

        self._stream: Optional[sd.InputStream] = None
        self._is_running = False
        self._lock = threading.Lock()
        self._counter = count(1)

        self._level_lock = threading.Lock()
        self._last_level_ts: float = 0.0
        self._last_rms: float = 0.0
        self._last_peak: float = 0.0

        self.source_type: str = "mic"  # future: "mic" | "system" | "unknown"
        self.selected_device: Optional[int | str] = self.device
        self.selected_device_info: Dict[str, Any] = {}
        self._discard_audio: bool = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    def start(self) -> None:
        """Start microphone input stream (uses default input device when device=None)."""
        with self._lock:
            if self._is_running:
                return

            self._clear_queue(self.chunk_queue)
            self._clear_queue(self.error_queue)

            try:
                resolved_device = self._resolve_default_input_device(self.device)
                self._start_stream(device=resolved_device)
                self._is_running = True
                logger.info(
                    "Audio capture started. source=%s device=%s",
                    self.source_type,
                    str(self.selected_device),
                )
            except Exception as exc:
                self._stream = None
                raise AudioCaptureError(f"Failed to start audio stream: {exc}") from exc

    def stop(self) -> None:
        """Stop microphone input stream safely."""
        with self._lock:
            if not self._is_running:
                return

            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception as exc:
                    logger.warning("Error while stopping audio stream: %s", exc)
                finally:
                    self._stream = None

            self._is_running = False
            logger.info("Audio capture stopped.")

    def get_chunk(self, timeout: Optional[float] = None) -> Optional[AudioChunk]:
        """Fetch one chunk from queue. Returns None on timeout."""
        try:
            return self.chunk_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def get_error(self) -> Optional[str]:
        """Fetch latest callback error/status message if exists."""
        try:
            return self.error_queue.get_nowait()
        except queue.Empty:
            return None

    def get_level(self) -> Dict[str, float]:
        """Return last measured level snapshot."""
        with self._level_lock:
            return {
                "ts": float(self._last_level_ts),
                "rms": float(self._last_rms),
                "peak": float(self._last_peak),
            }

    def get_active_device_name(self) -> str:
        """Return best-effort active device name for UI display."""
        info = self.selected_device_info or self._query_device_safe(self.selected_device)
        name = info.get("name") if isinstance(info, dict) else None
        return str(name) if name else "Default"

    def run_self_test(self, duration_sec: float = 2.5) -> InputDiagnosticResult:
        """
        Run a short level check. If stream isn't running, start a temporary stream and stop it.
        Returns UX-friendly diagnostics (no exception unless stream creation fails).
        """
        duration_sec = float(duration_sec)
        if duration_sec <= 0:
            duration_sec = 2.5

        if self.is_running:
            peak_max, avg_level = self._measure_levels(duration_sec=duration_sec)
            return self._to_diagnostic(peak_max=peak_max, avg_level=avg_level)

        # Temporary stream, do not enqueue chunks.
        with self._lock:
            if self._is_running:
                peak_max, avg_level = self._measure_levels(duration_sec=duration_sec)
                return self._to_diagnostic(peak_max=peak_max, avg_level=avg_level)

            self._clear_queue(self.chunk_queue)
            self._clear_queue(self.error_queue)

            try:
                resolved_device = self._resolve_default_input_device(self.device)
                self._discard_audio = True
                self._start_stream(device=resolved_device)
                peak_max, avg_level = self._measure_levels(duration_sec=duration_sec)
                return self._to_diagnostic(peak_max=peak_max, avg_level=avg_level)
            finally:
                self._discard_audio = False
                if self._stream is not None:
                    try:
                        self._stream.stop()
                        self._stream.close()
                    except Exception:
                        pass
                    finally:
                        self._stream = None
                self.selected_device = self.device
                self.selected_device_info = self._query_device_safe(self.device)

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        stream_time: Any,  # sounddevice callback type placeholder
        status: sd.CallbackFlags,
    ) -> None:
        """Sounddevice callback executed on audio thread."""
        del stream_time

        if status:
            self._push_error(f"Audio status warning: {status}")

        try:
            if not self._is_running:
                return

            if frames <= 0:
                return

            # Ensure mono float32 data for downstream modules.
            if indata.ndim == 2 and indata.shape[1] > 1:
                mono = np.mean(indata, axis=1, dtype=np.float32)
            else:
                mono = np.asarray(indata).reshape(-1).astype(np.float32, copy=False)

            # Update level meters (thread-safe, lightweight).
            try:
                peak = float(np.max(np.abs(mono))) if mono.size else 0.0
                rms = float(np.sqrt(np.mean(np.square(mono), dtype=np.float32))) if mono.size else 0.0
                with self._level_lock:
                    self._last_level_ts = time.time()
                    self._last_peak = peak
                    self._last_rms = rms
            except Exception:
                pass

            chunk = AudioChunk(
                samples=mono,
                sample_rate=self.sample_rate,
                timestamp=time.time(),
                sequence_id=next(self._counter),
            )

            try:
                if not self._discard_audio:
                    self.chunk_queue.put_nowait(chunk)
            except queue.Full:
                self._push_error("Audio chunk dropped: queue is full.")
        except Exception as exc:
            self._push_error(f"Audio callback error: {exc}")

    def _push_error(self, message: str) -> None:
        logger.warning(message)
        try:
            self.error_queue.put_nowait(message)
        except queue.Full:
            pass

    def _start_stream(self, *, device: Optional[int | str]) -> None:
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            blocksize=self.block_size,
            channels=self.channels,
            dtype="float32",
            device=device,
            callback=self._audio_callback,
        )
        self._stream.start()
        self.source_type = "mic"
        self.selected_device = device
        self.selected_device_info = self._query_device_safe(device)

    def _measure_levels(self, *, duration_sec: float) -> tuple[float, float]:
        start = time.time()
        peak_max = 0.0
        rms_max = 0.0
        while time.time() - start < max(0.2, float(duration_sec)):
            lvl = self.get_level()
            peak_max = max(peak_max, float(lvl.get("peak", 0.0)))
            rms_max = max(rms_max, float(lvl.get("rms", 0.0)))
            time.sleep(0.05)
        return peak_max, rms_max

    def _to_diagnostic(self, *, peak_max: float, avg_level: float) -> InputDiagnosticResult:
        has_signal = self._has_signal(peak_level=peak_max, avg_level=avg_level)
        device_name = self.get_active_device_name()
        note = None
        if not has_signal:
            note = (
                "音が入っていません。Windowsのマイク権限、既定の入力デバイス、ミュート状態を確認してください。"
                "会議相手の音声は通常スピーカー出力なので、マイク入力だけでは拾えない場合があります。"
            )
        return InputDiagnosticResult(
            has_signal=has_signal,
            avg_level=float(avg_level),
            peak_level=float(peak_max),
            device_name=device_name,
            source_type="mic",
            note=note,
        )

    @staticmethod
    def _has_signal(*, peak_level: float, avg_level: float) -> bool:
        # Heuristic threshold for float32 [-1, 1]
        return (float(peak_level) >= 0.01) or (float(avg_level) >= 0.003)

    @staticmethod
    def _resolve_default_input_device(device: Optional[int | str]) -> Optional[int | str]:
        # If caller specified device, respect it.
        if device is not None:
            return device
        # Otherwise prefer explicit default input device index (more deterministic on Windows),
        # but fall back to PortAudio default by returning None.
        idx = get_default_input_device_index()
        return idx if idx is not None else None

    @staticmethod
    def _query_device_safe(device: Optional[int | str]) -> Dict[str, Any]:
        try:
            if device is None:
                # PortAudio default input device index
                idx = get_default_input_device_index()
                if idx is None:
                    return {}
                device = idx
            info = dict(sd.query_devices(device))
            hostapi_idx = int(info.get("hostapi", -1))
            if hostapi_idx >= 0:
                ha = sd.query_hostapis(hostapi_idx)
                info["hostapi_name"] = str(ha.get("name", ""))
            return info
        except Exception:
            return {}

    @staticmethod
    def _clear_queue(target_queue: "queue.Queue[Any]") -> None:
        while True:
            try:
                target_queue.get_nowait()
            except queue.Empty:
                break


def get_default_input_device_index() -> Optional[int]:
    """Return the system default input (microphone) device index, or None to use PortAudio default."""
    try:
        default = sd.default.device
        if default is None:
            return None
        if isinstance(default, (list, tuple)):
            return int(default[0]) if len(default) > 0 and default[0] is not None else None
        return int(default)
    except Exception:
        return None


def get_default_output_device_index() -> Optional[int]:
    """Return the system default output (speaker) device index, or None. For future playback/TTS use."""
    try:
        default = sd.default.device
        if default is None:
            return None
        if isinstance(default, (list, tuple)):
            return int(default[1]) if len(default) > 1 and default[1] is not None else None
        return int(default)
    except Exception:
        return None


def list_input_devices() -> List[Dict[str, Any]]:
    """Return available input devices in a UI-friendly structure."""
    devices: List[Dict[str, Any]] = []
    try:
        all_devices = sd.query_devices()
        for idx, dev in enumerate(all_devices):
            max_input_channels = int(dev.get("max_input_channels", 0))
            if max_input_channels <= 0:
                continue
            devices.append(
                {
                    "index": idx,
                    "name": str(dev.get("name", f"Input Device {idx}")),
                    "max_input_channels": max_input_channels,
                    "default_samplerate": float(dev.get("default_samplerate", 0.0)),
                }
            )
    except Exception as exc:
        raise AudioCaptureError(f"Failed to query audio devices: {exc}") from exc
    return devices

