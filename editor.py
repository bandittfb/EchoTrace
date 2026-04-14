"""Express Scribe-style correction editor with optional video panel."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut, QTextBlockFormat, QTextCursor
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from audio_player import AudioPlayer
from models import TranscriptDocument, fmt_timestamp, fmt_timestamp_ms
from theme import ACCENT, BG_DARK, BG_PANEL, SEGMENT_HIGHLIGHT, TEXT_SECONDARY, TEXT_TIMESTAMP

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".wmv", ".flv", ".m4v"}
SPEED_PRESETS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]


class CorrectionEditor(QWidget):
    """Transport controls + optional video + editable transcript."""

    def __init__(self, document: TranscriptDocument, parent=None) -> None:
        super().__init__(parent)
        self.doc = document
        self.player = AudioPlayer(self)
        self._current_seg_idx = -1
        self._block_sync = False
        self._is_video = self._detect_video()

        self._build_ui()
        self._connect_signals()
        self._register_hotkeys()
        self._render_transcript()

        if self.doc.audio_path:
            self.player.load(str(self.doc.audio_path))

    def _detect_video(self) -> bool:
        if self.doc.audio_path:
            return self.doc.audio_path.suffix.lower() in VIDEO_EXTS
        return False

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(8)

        # -- Transport bar ---------------------------------------------------
        transport = QHBoxLayout()
        transport.setSpacing(8)

        self.btn_play = QPushButton("Play  (F5)")
        self.btn_play.setObjectName("playBtn")
        self.btn_play.setFixedWidth(120)

        self.btn_rw = QPushButton("- 5s  (F6)")
        self.btn_rw.setFixedWidth(90)
        self.btn_ff = QPushButton("+ 5s  (F7)")
        self.btn_ff.setFixedWidth(90)

        self.slider_pos = QSlider(Qt.Orientation.Horizontal)
        self.slider_pos.setRange(0, 1000)

        self.lbl_time = QLabel("00:00:00 / 00:00:00")
        self.lbl_time.setFixedWidth(150)
        self.lbl_time.setStyleSheet(f"color: {TEXT_TIMESTAMP}; font-family: Consolas; font-size: 13px;")

        transport.addWidget(self.btn_play)
        transport.addWidget(self.btn_rw)
        transport.addWidget(self.btn_ff)
        transport.addWidget(self.slider_pos, 1)
        transport.addWidget(self.lbl_time)
        root.addLayout(transport)

        # -- Speed + volume --------------------------------------------------
        speed_row = QHBoxLayout()
        speed_row.setSpacing(6)

        spd_label = QLabel("Speed:")
        spd_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        speed_row.addWidget(spd_label)

        self._speed_buttons_list = []
        for spd in SPEED_PRESETS:
            btn = QPushButton(f"{spd}x")
            btn.setFixedWidth(48)
            btn.setCheckable(True)
            btn.setChecked(spd == 1.0)
            btn.clicked.connect(lambda checked, s=spd: self._set_speed(s))
            speed_row.addWidget(btn)
            self._speed_buttons_list.append(btn)

        speed_row.addStretch()

        self.lbl_speed = QLabel("1.0x")
        self.lbl_speed.setStyleSheet(f"color: {ACCENT}; font-weight: bold; font-size: 12px;")
        speed_row.addWidget(self.lbl_speed)

        vol_label = QLabel("  Vol:")
        vol_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        speed_row.addWidget(vol_label)

        self.slider_vol = QSlider(Qt.Orientation.Horizontal)
        self.slider_vol.setRange(0, 100)
        self.slider_vol.setValue(80)
        self.slider_vol.setFixedWidth(100)
        speed_row.addWidget(self.slider_vol)

        root.addLayout(speed_row)

        # -- Main content: video (optional) + transcript ---------------------
        if self._is_video:
            splitter = QSplitter(Qt.Orientation.Horizontal)
            splitter.setHandleWidth(6)
            splitter.setStyleSheet(f"""
                QSplitter::handle {{
                    background-color: #2A2A4A;
                    border-radius: 3px;
                }}
                QSplitter::handle:hover {{
                    background-color: {ACCENT};
                }}
            """)

            # Video panel
            video_container = QWidget()
            video_layout = QVBoxLayout(video_container)
            video_layout.setContentsMargins(0, 0, 0, 0)
            video_layout.setSpacing(4)

            video_header = QLabel("VIDEO")
            video_header.setStyleSheet(
                f"font-size: 9px; font-weight: bold; color: {TEXT_SECONDARY}; "
                f"letter-spacing: 2px; padding: 2px 0;"
            )
            video_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
            video_layout.addWidget(video_header)

            self._video_widget = QVideoWidget()
            self._video_widget.setMinimumSize(320, 240)
            self._video_widget.setStyleSheet(f"background-color: black; border-radius: 4px;")
            video_layout.addWidget(self._video_widget, 1)

            self.player.set_video_output(self._video_widget)
            splitter.addWidget(video_container)

            # Transcript panel
            transcript_container = QWidget()
            transcript_layout = QVBoxLayout(transcript_container)
            transcript_layout.setContentsMargins(0, 0, 0, 0)
            transcript_layout.setSpacing(4)

            transcript_header = QLabel("TRANSCRIPT")
            transcript_header.setStyleSheet(
                f"font-size: 9px; font-weight: bold; color: {TEXT_SECONDARY}; "
                f"letter-spacing: 2px; padding: 2px 0;"
            )
            transcript_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
            transcript_layout.addWidget(transcript_header)

            self.text_edit = QPlainTextEdit()
            self.text_edit.setFont(QFont("Consolas", 11))
            self.text_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
            transcript_layout.addWidget(self.text_edit, 1)

            splitter.addWidget(transcript_container)

            # Default split: 45% video, 55% transcript
            splitter.setSizes([450, 550])

            root.addWidget(splitter, 1)
        else:
            # Audio-only: just the transcript, full width
            self.text_edit = QPlainTextEdit()
            self.text_edit.setFont(QFont("Consolas", 11))
            self.text_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
            root.addWidget(self.text_edit, 1)

        # -- Hint bar --------------------------------------------------------
        hint_text = "F5 Play/Pause  |  F6 Rewind 5s  |  F7 Forward 5s  |  Click timestamp to seek"
        if self._is_video:
            hint_text += "  |  Drag splitter to resize video"
        hint = QLabel(hint_text)
        hint.setObjectName("hint")
        root.addWidget(hint)

    def _connect_signals(self) -> None:
        self.btn_play.clicked.connect(self.player.toggle)
        self.btn_rw.clicked.connect(lambda: self.player.rewind(5000))
        self.btn_ff.clicked.connect(lambda: self.player.forward(5000))

        self.player.position_changed.connect(self._on_position)
        self.player.duration_changed.connect(self._on_duration)
        self.player.state_changed.connect(self._on_state)

        self.slider_pos.sliderMoved.connect(self._on_seek_slider)
        self.slider_vol.valueChanged.connect(lambda v: self.player.set_volume(v / 100.0))

        self.text_edit.textChanged.connect(self._sync_text_to_model)
        self.text_edit.mouseReleaseEvent = self._on_text_click

    def _register_hotkeys(self) -> None:
        QShortcut(QKeySequence(Qt.Key.Key_F5), self, self.player.toggle, context=Qt.ShortcutContext.WindowShortcut)
        QShortcut(QKeySequence(Qt.Key.Key_F6), self, lambda: self.player.rewind(5000), context=Qt.ShortcutContext.WindowShortcut)
        QShortcut(QKeySequence(Qt.Key.Key_F7), self, lambda: self.player.forward(5000), context=Qt.ShortcutContext.WindowShortcut)

    # -- Render transcript ---------------------------------------------------

    def _render_transcript(self) -> None:
        self._block_sync = True
        self.text_edit.clear()
        lines = []
        for seg in self.doc.segments:
            ts = f"[{fmt_timestamp(seg.start)} -> {fmt_timestamp(seg.end)}]"
            speaker = f"  {seg.speaker}:" if seg.speaker else ""
            lines.append(f"{ts}{speaker}  {seg.text}")
        self.text_edit.setPlainText("\n".join(lines))
        self._block_sync = False

    # -- Sync text back to model ---------------------------------------------

    def _sync_text_to_model(self) -> None:
        if self._block_sync:
            return
        lines = self.text_edit.toPlainText().split("\n")
        for i, line in enumerate(lines):
            if i >= len(self.doc.segments):
                break
            bracket_end = line.find("]")
            if bracket_end != -1:
                rest = line[bracket_end + 1:].strip()
                # Parse "SpeakerName: text" — everything before first ":" is speaker
                colon_pos = rest.find(":")
                if colon_pos != -1:
                    potential_speaker = rest[:colon_pos].strip()
                    # Only treat as speaker if it looks like a name (not too long,
                    # no line-like content). Speaker names are typically short labels.
                    if 1 <= len(potential_speaker) <= 40 and "\n" not in potential_speaker:
                        self.doc.segments[i].speaker = potential_speaker
                        self.doc.segments[i].text = rest[colon_pos + 1:].strip()
                    else:
                        self.doc.segments[i].text = rest
                else:
                    # No colon — no speaker label, just text
                    self.doc.segments[i].speaker = ""
                    self.doc.segments[i].text = rest

    # -- Click to seek -------------------------------------------------------

    def _on_text_click(self, event) -> None:
        QPlainTextEdit.mouseReleaseEvent(self.text_edit, event)
        cursor = self.text_edit.cursorForPosition(event.pos())
        block_num = cursor.blockNumber()
        col = cursor.positionInBlock()

        if block_num < len(self.doc.segments) and col < 25:
            seg = self.doc.segments[block_num]
            self.player.seek(int(seg.start * 1000))
            if not self.player.is_playing:
                self.player.play()

    # -- Playback callbacks --------------------------------------------------

    @Slot(int)
    def _on_position(self, ms: int) -> None:
        total = self.player.duration_ms
        self.lbl_time.setText(f"{fmt_timestamp_ms(ms)} / {fmt_timestamp_ms(total)}")

        if not self.slider_pos.isSliderDown() and total > 0:
            self.slider_pos.setValue(int(ms / total * 1000))

        idx = self.doc.segment_at_time(ms / 1000.0)
        if idx != self._current_seg_idx:
            self._highlight_segment(idx)
            self._current_seg_idx = idx

    @Slot(int)
    def _on_duration(self, ms: int) -> None:
        self.lbl_time.setText(f"00:00:00 / {fmt_timestamp_ms(ms)}")

    @Slot(str)
    def _on_state(self, state: str) -> None:
        if state == "playing":
            self.btn_play.setText("Pause (F5)")
        else:
            self.btn_play.setText("Play  (F5)")

    def _on_seek_slider(self, value: int) -> None:
        total = self.player.duration_ms
        if total > 0:
            self.player.seek(int(value / 1000 * total))

    # -- Speed ---------------------------------------------------------------

    def _set_speed(self, rate: float) -> None:
        self.player.set_speed(rate)
        self.lbl_speed.setText(f"{rate}x")
        for btn in self._speed_buttons_list:
            btn.setChecked(btn.text() == f"{rate}x")

    # -- Highlight current segment -------------------------------------------

    def _highlight_segment(self, idx: int) -> None:
        self._block_sync = True

        cursor = self.text_edit.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        normal_fmt = QTextBlockFormat()
        normal_fmt.setBackground(QColor(BG_PANEL))
        cursor.setBlockFormat(normal_fmt)

        if 0 <= idx < self.text_edit.blockCount():
            block = self.text_edit.document().findBlockByNumber(idx)
            cursor = QTextCursor(block)
            fmt = QTextBlockFormat()
            fmt.setBackground(QColor(SEGMENT_HIGHLIGHT))
            cursor.setBlockFormat(fmt)
            self.text_edit.setTextCursor(cursor)
            self.text_edit.ensureCursorVisible()

        self._block_sync = False
