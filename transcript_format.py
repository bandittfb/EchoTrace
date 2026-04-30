"""Shared formatting helpers for transcript lines.

The editor renders each segment as one or two lines in the form:

    [HH:MM:SS -> HH:MM:SS]  Speaker:  text
    [HH:MM:SS -> HH:MM:SS]  Speaker (ES):  text
        ↳ optional hand-written translation

`format_segment()` produces those lines from a Segment-like object.
`parse_line()` parses a single main line back into its fields.
`parse_translation()` recognises the indented continuation line.

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

# Trailing " (EN)" / " (ES)" etc. on the speaker/prefix portion. Two- or
# three-letter uppercase ISO codes — matches how Whisper returns them
# (lowercased here after capture).
LANG_TAG_RE = re.compile(r"\s*\(([A-Za-z]{2,3})\)\s*$")

# Translation continuation line. Two or more leading spaces + the arrow
# glyph + space + the translation body. The glyph was chosen because it
# is visually distinctive *and* unlikely to appear at the start of a
# transcript line naturally.
TRANSLATION_PREFIX = "    \u21b3 "  # 4 spaces + ↳ + space
TRANSLATION_RE = re.compile(r"^\s{2,}\u21b3\s+(.*)$")


def _hms_to_seconds(h: str, m: str, s: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s)


def parse_line(line: str) -> Optional[Tuple[float, float, str, str, str]]:
    """Parse a main transcript line.

    Returns ``(start, end, speaker, language, text)`` on success, or
    ``None`` if the line does not start with a valid ``[HH:MM:SS ->
    HH:MM:SS]`` timestamp. ``speaker`` and ``language`` are empty
    strings when not present. ``language`` is a lowercase ISO code
    (e.g. "es") — the rendered ``(ES)`` tag is uppercase but we store
    lowercase for consistency with faster-whisper.
    """
    match = TIMESTAMP_RE.match(line.strip())
    if not match:
        return None
    start = _hms_to_seconds(match.group(1), match.group(2), match.group(3))
    end = _hms_to_seconds(match.group(4), match.group(5), match.group(6))
    rest = match.group(7).strip()

    speaker = ""
    language = ""
    text = rest
    colon_pos = rest.find(":")
    if colon_pos != -1:
        prefix = rest[:colon_pos].strip()
        # Peel off a trailing "(XX)" language tag, if any.
        lang_match = LANG_TAG_RE.search(prefix)
        if lang_match:
            language = lang_match.group(1).lower()
            prefix = prefix[: lang_match.start()].strip()
        # 1..40 char heuristic — long sentences with colons aren't speakers.
        if 1 <= len(prefix) <= 40:
            speaker = prefix
            text = rest[colon_pos + 1 :].strip()
        elif prefix == "" and language:
            # "(ES): text" form — language only, no speaker
            text = rest[colon_pos + 1 :].strip()
        else:
            # Colon wasn't a speaker separator; put the language back in
            # case we falsely stripped it.
            language = ""
    return start, end, speaker, language, text


def parse_translation(line: str) -> Optional[str]:
    """Return the translation text if *line* is an indented continuation
    line, else None."""
    match = TRANSLATION_RE.match(line)
    if not match:
        return None
    return match.group(1).strip()


def format_segment(
    start: float,
    end: float,
    text: str,
    speaker: str = "",
    language: str = "",
    translation: str = "",
) -> str:
    """Build the canonical block for a segment — one or two lines.

    The returned string is the main line, optionally followed by a
    newline and an indented translation line. Callers that concatenate
    segments should use ``"\\n".join(...)`` — no trailing newline is
    appended here.
    """
    ts = f"[{fmt_timestamp(start)} -> {fmt_timestamp(end)}]"
    tag = f" ({language.upper()})" if language else ""
    if speaker:
        prefix = f"  {speaker}{tag}:"
    elif language:
        # Rare: language tag but no speaker assigned yet
        prefix = f"  {tag.strip()}:"
    else:
        prefix = ""
    main = f"{ts}{prefix}  {text}"
    if translation.strip():
        main += "\n" + TRANSLATION_PREFIX + translation.strip()
    return main


# Backwards-compatible alias — the previous public name. Keeps any
# external callers (tests, future tooling) from breaking on the new
# five-tuple return shape; they can migrate at their own pace.
def format_line(
    start: float,
    end: float,
    text: str,
    speaker: str = "",
    language: str = "",
) -> str:
    """Build only the main line (no translation)."""
    return format_segment(start, end, text, speaker=speaker, language=language)
