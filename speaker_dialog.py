"""Speaker management dialog: rename and merge speakers in one place.

Inline editing in the transcript still works for one-off touch-ups, but
this dialog is the canonical surface for sweeping speaker work — e.g.
renaming all "Speaker 1" → "Officer Smith" or merging "Speaker 3" into
"Speaker 1" because diarization split them.
"""
from __future__ import annotations

from collections import Counter
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from models import Segment


class SpeakerManagerDialog(QDialog):
    """Modal dialog for renaming and merging speakers across all segments.

    The dialog is *non-destructive*: it builds a rename map, and only when
    the user clicks Apply does it mutate the segments in-place. Cancel
    discards everything.
    """

    def __init__(self, segments: list[Segment], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Speaker Management")
        self.resize(560, 420)
        self._segments = segments
        # Maps current speaker label -> proposed new label. Empty string =
        # no change; a non-empty value is what the user typed in the Rename
        # column.
        self._rename_map: dict[str, str] = {}

        layout = QVBoxLayout(self)

        intro = QLabel(
            "Rename or merge speakers. Type a new name in the right column "
            "to rename. To merge, give two speakers the same target name."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #8892A0; font-size: 11px;")
        layout.addWidget(intro)

        # Build the table
        counts = Counter(s.speaker for s in segments if s.speaker)
        self._speakers = sorted(counts.keys())

        self._table = QTableWidget(len(self._speakers), 3, self)
        self._table.setHorizontalHeaderLabels(["Current speaker", "Segments", "Rename to (blank = keep)"])
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        for i, name in enumerate(self._speakers):
            current = QTableWidgetItem(name)
            current.setFlags(current.flags() & ~Qt.ItemFlag.ItemIsEditable)
            font = QFont()
            font.setBold(True)
            current.setFont(font)
            self._table.setItem(i, 0, current)

            count = QTableWidgetItem(str(counts[name]))
            count.setFlags(count.flags() & ~Qt.ItemFlag.ItemIsEditable)
            count.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(i, 1, count)

            edit = QLineEdit()
            edit.setPlaceholderText(name)
            edit.textChanged.connect(lambda txt, src=name: self._on_edit(src, txt))
            self._table.setCellWidget(i, 2, edit)

        layout.addWidget(self._table, 1)

        if not self._speakers:
            no_speakers = QLabel(
                "No speaker labels found. Run a transcription with "
                "Speaker Detection ON to populate this list, or assign "
                "speakers inline in the transcript."
            )
            no_speakers.setStyleSheet("color: #8892A0; font-style: italic; padding: 12px;")
            no_speakers.setWordWrap(True)
            layout.addWidget(no_speakers)

        # Quick-rename helpers row
        helper_row = QHBoxLayout()
        helper_row.addWidget(QLabel("Quick fill:"))
        for prefill in ["Officer ", "Witness ", "Suspect ", "Detective "]:
            btn = QPushButton(prefill.strip())
            btn.setFixedHeight(24)
            btn.clicked.connect(lambda _=False, p=prefill: self._prefill_first_blank(p))
            helper_row.addWidget(btn)
        helper_row.addStretch()
        layout.addLayout(helper_row)

        # Buttons — use a manual layout instead of QDialogButtonBox's
        # built-in Apply button, which has ApplyRole quirks on Windows
        # that can swallow clicks or silently drop the signal's bool
        # parameter before it reaches the slot.
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(28)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        apply_btn = QPushButton("Apply")
        apply_btn.setFixedHeight(28)
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(lambda _checked=False: self._apply())
        btn_row.addWidget(apply_btn)

        layout.addLayout(btn_row)

    # -- Internals -----------------------------------------------------------

    def _on_edit(self, source: str, new_text: str) -> None:
        new_text = new_text.strip()
        if new_text:
            self._rename_map[source] = new_text
        else:
            self._rename_map.pop(source, None)

    def _prefill_first_blank(self, prefix: str) -> None:
        """Convenience: tap "Officer" and the first un-renamed row gets
        "Officer 1" pre-filled, the next "Officer 2", etc."""
        # Count existing prefixed entries to suggest a number
        existing = [v for v in self._rename_map.values() if v.startswith(prefix)]
        next_num = len(existing) + 1
        for row in range(self._table.rowCount()):
            edit: QLineEdit = self._table.cellWidget(row, 2)
            if edit and not edit.text().strip():
                edit.setText(f"{prefix.strip()} {next_num}")
                return

    def _apply(self) -> None:
        """Mutate segments in-place using the rename map, then accept."""
        if not self._rename_map:
            self.accept()
            return
        # Confirm if a merge would happen (two sources mapping to same target)
        targets = list(self._rename_map.values())
        if len(targets) != len(set(targets)):
            duplicates = [t for t in set(targets) if targets.count(t) > 1]
            reply = QMessageBox.question(
                self, "Confirm merge",
                f"This will merge multiple speakers into:\n  • " +
                "\n  • ".join(duplicates) +
                "\n\nProceed?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        for seg in self._segments:
            if seg.speaker in self._rename_map:
                seg.speaker = self._rename_map[seg.speaker]
        self.accept()

    # -- Public --------------------------------------------------------------

    def rename_map(self) -> dict[str, str]:
        """Return the rename map that was applied (empty if cancelled)."""
        return dict(self._rename_map) if self.result() == QDialog.DialogCode.Accepted else {}
