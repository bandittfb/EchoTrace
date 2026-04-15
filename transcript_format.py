"""Shared formatting helpers for transcript lines.

The editor renders each segment as a single line in the form:

    [HH:MM:SS -> HH:MM:SS]  Speaker:  text

`format_line()` produces that string from a Segment-like object.
`parse_line()` parses one back into ``(start, end, speaker, text)``.

These were originally inlined in editor.py; pulled out so exporters and
any future consumers can share the same canonical format without
re-implementing the regex.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

from models import fmt_timestamp

# "[HH:MM:SS -> HH:MM:SS]" + optional "  Speaker:  text"
TIMESTAMP_RE = re.compile(
    r"^\[(\d{2}):(\d{2}):(\d{2})\s*->\s*(\d{2}):(\d{2}):(\d{2})\](.*)$"
)


def _hms_to_seconds(h: str, m: str, s: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s)


def parse_line(line: str) -> Optional[Tuple[float, float, str, str]]:
    """Parse a transcript line.

    Returns ``(start, end, speaker, text)`` on success, or ``None`` if the
    line does not start with a valid ``[HH:MM:SS -> HH:MM:SS]`` timestamp.
    Speaker is the empty string when no ``Speaker:`` prefix is present.
    """
    match = TIMESTAMP_RE.match(line.strip())
    if not match:
        return None
    start = _hms_to_seconds(match.group(1), match.group(2), match.group(3))
    end = _hms_to_seconds(match.group(4), match.group(5), match.group(6))
    rest = match.group(7).strip()

    speaker = ""
    text = rest
    colon_pos = rest.find(":")
    if colon_pos != -1:
        potential_speaker = rest[:colon_pos].strip()
        # 1..40 char heuristic — long sentences with colons aren't speakers.
        if 1 <= len(potential_speaker) <= 40:
            speaker = potential_speaker
            text = rest[colon_pos + 1:].strip()
    return start, end, speaker, text


def format_line(start: float, end: float, text: str, speaker: str = "") -> str:
    """Build the canonical transcript line for a segment."""
    ts = f"[{fmt_timestamp(start)} -> {fmt_timestamp(end)}]"
    speaker_part = f"  {speaker}:" if speaker else ""
    return f"{ts}{speaker_part}  {text}"
