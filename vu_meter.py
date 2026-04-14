"""Real-time VU meter widget driven by pre-computed audio levels."""
from __future__ import annotations

import numpy as np
import subprocess
import os
import tempfile

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget


# Level thresholds for colour zones
GREEN_MAX = 0.55
YELLOW_MAX = 0.80
# Above YELLOW_MAX = red zone


class VUMeter(QWidget):
    """Horizontal audio level meter with green/yellow/red zones."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._level = 0.0       # 0.0 – 1.0+
        self._peak = 0.0        # peak hold
        self._peak_decay = 0.0  # decay counter
        self.setFixedHeight(14)
        self.setMinimumWidth(100)

    def set_level(self, level: float) -> None:
        """Set the current level (0.0 = silence, 1.0 = 0 dB, >1.0 = hot)."""
        self._level = max(0.0, min(level, 1.5))
        # Peak hold
        if self._level > self._peak:
            self._peak = self._level
            self._peak_decay = 20  # hold for ~20 paint cycles
        elif self._peak_decay > 0:
            self._peak_decay -= 1
        else:
            self._peak = max(self._peak - 0.03, self._level)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()

        # Background
        painter.fillRect(0, 0, w, h, QColor("#0A0A1A"))

        # Draw level bar
        bar_w = int(min(self._level, 1.0) * w)
        if bar_w > 0:
            # Build gradient: green -> yellow -> red
            grad = QLinearGradient(0, 0, w, 0)
            grad.setColorAt(0.0, QColor("#00E676"))       # green
            grad.setColorAt(GREEN_MAX, QColor("#00E676"))  # green end
            grad.setColorAt(GREEN_MAX + 0.01, QColor("#FFD600"))  # yellow start
            grad.setColorAt(YELLOW_MAX, QColor("#FFD600"))  # yellow end
            grad.setColorAt(YELLOW_MAX + 0.01, QColor("#FF1744"))  # red start
            grad.setColorAt(1.0, QColor("#FF1744"))        # red

            painter.fillRect(0, 1, bar_w, h - 2, grad)

        # Overdrive glow (beyond 100%)
        if self._level > 1.0:
            over_w = int((self._level - 1.0) * w * 2)  # exaggerate the overdrive zone
            over_w = min(over_w, w - bar_w)
            if over_w > 0:
                painter.fillRect(bar_w, 1, over_w, h - 2, QColor(255, 23, 68, 180))

        # Peak indicator line
        peak_x = int(min(self._peak, 1.2) * w / 1.2)
        if peak_x > 0 and peak_x < w:
            pen = QPen(QColor("#FFFFFF"), 2)
            painter.setPen(pen)
            painter.drawLine(peak_x, 0, peak_x, h)

        # Tick marks at 25%, 50%, 75%, 100%
        painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
        for pct in [0.25, 0.50, 0.75, 1.0]:
            x = int(pct * w)
            painter.drawLine(x, 0, x, h)

        painter.end()


class AudioLevelProvider:
    """Pre-compute RMS levels from an audio file for real-time VU display."""

    def __init__(self):
        self._levels: np.ndarray | None = None
        self._duration: float = 0.0
        self._chunk_duration: float = 0.05  # 50ms per chunk

    @property
    def ready(self) -> bool:
        return self._levels is not None and len(self._levels) > 0

    def load(self, audio_path: str) -> None:
        """Pre-compute levels from audio file using ffmpeg + numpy."""
        try:
            self._levels = None
            ffmpeg = _find_ffmpeg()

            with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as tmp:
                tmp_path = tmp.name

            try:
                # Extract raw PCM: 16kHz mono 16-bit
                subprocess.run(
                    [
                        ffmpeg, "-y", "-i", audio_path,
                        "-ac", "1", "-ar", "16000",
                        "-f", "s16le", "-acodec", "pcm_s16le",
                        "-loglevel", "error",
                        tmp_path,
                    ],
                    check=True,
                    capture_output=True,
                )

                # Read raw PCM
                raw = np.fromfile(tmp_path, dtype=np.int16)
                if len(raw) == 0:
                    return

                # Convert to float
                audio = raw.astype(np.float32) / 32768.0

                # Compute RMS per chunk
                sample_rate = 16000
                chunk_samples = int(self._chunk_duration * sample_rate)
                n_chunks = len(audio) // chunk_samples

                if n_chunks == 0:
                    return

                # Reshape and compute RMS
                trimmed = audio[: n_chunks * chunk_samples].reshape(n_chunks, chunk_samples)
                rms = np.sqrt(np.mean(trimmed ** 2, axis=1))

                # Normalize: map typical speech RMS (~0.05-0.15) to ~0.4-0.8 range
                # This makes the meter visually active for normal speech
                max_rms = np.percentile(rms, 98) if len(rms) > 100 else np.max(rms)
                if max_rms > 0:
                    self._levels = rms / max_rms  # normalized to 0-1
                else:
                    self._levels = rms

                self._duration = len(audio) / sample_rate

            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        except Exception:
            self._levels = None

    def level_at(self, seconds: float, volume_multiplier: float = 1.0) -> float:
        """Get the audio level at a given time, scaled by volume."""
        if not self.ready or self._duration <= 0:
            return 0.0
        idx = int(seconds / self._chunk_duration)
        idx = max(0, min(idx, len(self._levels) - 1))
        return float(self._levels[idx]) * volume_multiplier


def _find_ffmpeg() -> str:
    """Locate ffmpeg executable."""
    import shutil
    import glob
    path = shutil.which("ffmpeg")
    if path:
        return path
    candidates = glob.glob(
        os.path.expanduser("~/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg-*/bin/ffmpeg.exe")
    )
    if candidates:
        return candidates[0]
    for p in [r"C:\ffmpeg\bin\ffmpeg.exe", r"C:\Program Files\FFmpeg\bin\ffmpeg.exe"]:
        if os.path.isfile(p):
            return p
    raise FileNotFoundError("ffmpeg not found")
