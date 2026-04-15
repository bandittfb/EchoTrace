"""Data models for the transcription app."""
from __future__ import annotations

import bisect
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


# Flag taxonomy. Empty string = no flag. Keys are stored on disk; the
# label/color are presentation-only and live in the editor.
FLAG_KINDS = ("inaudible", "admission", "contradiction", "follow_up", "custom")


@dataclass
class Segment:
    start: float  # seconds
    end: float    # seconds
    text: str     # editable transcript text
    speaker: str = ""  # e.g. "Speaker 1", "Speaker 2"
    flag: str = ""  # one of FLAG_KINDS or "" for no flag
    note: str = ""  # optional free-form note attached to this segment


@dataclass
class FormattedRun:
    """A run of text inside a segment with optional B/I/U styling.

    Used only at export time for DOCX/PDF — the on-disk JSON format stores
    plain segments, since rich formatting doesn't survive a round-trip
    through the plain-text editor anyway. Captured directly from the
    QTextEdit's internal QTextDocument.
    """
    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False


@dataclass
class AuditEntry:
    """A single line in the document's audit trail."""
    ts: str          # ISO-8601 timestamp
    action: str      # short verb-phrase, e.g. "Project saved"
    details: str = ""  # free-form details, e.g. file path


@dataclass
class TranscriptDocument:
    segments: list[Segment] = field(default_factory=list)
    audio_path: Optional[Path] = None
    model_size: str = "base"
    language: str = ""
    language_probability: float = 0.0
    created_at: str = ""
    audit_log: list[AuditEntry] = field(default_factory=list)

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

    # -- audit trail ---------------------------------------------------------

    def log(self, action: str, details: str = "") -> AuditEntry:
        """Append an entry to the audit log and return it."""
        entry = AuditEntry(ts=datetime.now().isoformat(timespec="seconds"),
                           action=action, details=details)
        self.audit_log.append(entry)
        return entry

    # -- serialisation -------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "audio_path": str(self.audio_path) if self.audio_path else "",
            "model_size": self.model_size,
            "language": self.language,
            "language_probability": self.language_probability,
            "created_at": self.created_at or datetime.now().isoformat(),
            "segments": [asdict(s) for s in self.segments],
            "audit_log": [asdict(e) for e in self.audit_log],
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
            audit_log=[AuditEntry(**e) for e in d.get("audit_log", [])],
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
