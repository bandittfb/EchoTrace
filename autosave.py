"""Autosave + crash recovery for EchoTrace projects.

Strategy: a single global autosave file at
``~/.echotrace/autosave.echotrace``. Written every ``AUTOSAVE_INTERVAL_MS``
while a document is open, and deleted on any clean exit point (Save
Project, New File, app close).

On next launch, ``find_recoverable()`` returns the file's contents (and
its timestamp) so the main window can offer the user a recovery prompt.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

AUTOSAVE_INTERVAL_MS = 30_000  # write every 30s while editing


def autosave_dir() -> Path:
    """Return the directory holding the global autosave file (creates if
    missing)."""
    d = Path.home() / ".echotrace"
    d.mkdir(parents=True, exist_ok=True)
    return d


def autosave_path() -> Path:
    """The single canonical autosave location."""
    return autosave_dir() / "autosave.echotrace"


def write_autosave(doc_json: str) -> None:
    """Write the JSON-serialized document to the autosave path. Atomic
    on Windows via os.replace."""
    target = autosave_path()
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(doc_json, encoding="utf-8")
    os.replace(tmp, target)


def clear_autosave() -> None:
    """Remove the autosave file. No-op if it doesn't exist."""
    p = autosave_path()
    try:
        p.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        # Best-effort cleanup; never crash the app over an autosave delete
        pass


def find_recoverable() -> Optional[tuple[Path, datetime]]:
    """If an autosave file exists, return ``(path, modified_at)``.
    Otherwise None."""
    p = autosave_path()
    if not p.exists():
        return None
    try:
        mtime = datetime.fromtimestamp(p.stat().st_mtime)
    except OSError:
        return None
    return p, mtime
