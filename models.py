"""Data models for the transcription app."""
from __future__ import annotations

import bisect
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class Segment:
    start: float  # seconds
    end: float    # seconds
    text: str     # editable transcript text
    speaker: str = ""  # e.g. "Speaker 1", "Speaker 2"


@dataclass
class TranscriptDocument:
    segments: list[Segment] = field(default_factory=list)
    audio_path: Optional[Path] = None
    model_size: str = "base"
    language: str = ""
    language_probability: float = 0.0
    created_at: str = ""

    def segment_at_time(self, seconds: float) -> int:
        """Return index of the segment containing *seconds*, or -1."""
        if not self.segments:
            return -1
        starts = [s.start for s in self.segments]
        idx = bisect.bisect_right(starts, seconds) - 1
        if idx < 0:
            return 0
        if idx < len(self.segments) and seconds <= self.segments[idx].end:
            return idx
        return min(idx, len(self.segments) - 1)

    # -- serialisation -------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "audio_path": str(self.audio_path) if self.audio_path else "",
            "model_size": self.model_size,
            "language": self.language,
            "language_probability": self.language_probability,
            "created_at": self.created_at or datetime.now().isoformat(),
            "segments": [asdict(s) for s in self.segments],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TranscriptDocument":
        doc = cls(
            audio_path=Path(d["audio_path"]) if d.get("audio_path") else None,
            model_size=d.get("model_size", "base"),
            language=d.get("language", ""),
            language_probability=d.get("language_probability", 0.0),
            created_at=d.get("created_at", ""),
            segments=[Segment(**s) for s in d.get("segments", [])],
        )
        return doc

    def save_json(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load_json(cls, path: Path) -> "TranscriptDocument":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


def fmt_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def fmt_timestamp_ms(ms: int) -> str:
    return fmt_timestamp(ms / 1000.0)
