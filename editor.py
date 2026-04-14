"""Express Scribe-style correction editor with optional video panel."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut, QTextBlockFormat, QTextCharFormat, QTextCursor
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from audio_player import AudioPlayer
from models import TranscriptDocument, fmt_timestamp, fmt_timestamp_ms
from pedal import FootPedalListener, PedalButton
from theme import ACCENT, BG_DARK, BG_PANEL, SEGMENT_HIGHLIGHT, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TIMESTAMP
from vu_meter import AudioLevelProvider, VUMeter

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".wmv", ".flv", ".m4v"}
SPEED_PRESETS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]

# Regex to parse "[HH:MM:SS -> HH:MM:SS]  Speaker:  text"
_TS_RE = re.compile(
    r"^\[(\d{2}):(\d{2}):(\d{2})\s*->\s*(\d{2}):(\d{2}):(\d{2})\](.*)$"
)


def _parse_ts(h: str, m: str, s: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s)


def _parse_line(line: str):
    """Parse a transcript line. Returns (start, end, speaker, text) or None."""
    m = _TS_RE.match(line.strip())
    if not m:
        return None
    start = _parse_ts(m.group(1), m.group(2), m.group(3))
    end = _parse_ts(m.group(4), m.group(5), m.group(6))
    rest = m.group(7).strip()
    # Parse optional "Speaker: text"
    speaker = ""
    text = rest
    colon_pos = rest.find(":")
    if colon_pos != -1:
        potential_speaker = rest[:colon_pos].strip()
        if 1 <= len(potential_speaker) <= 40:
            speaker = potential_speaker
            text = rest[colon_pos + 1:].strip()
    return start, end, speaker, text


class CorrectionEditor(QWidget):
    """Transport controls + optional video + editable transcript."""

    def __init__(self, document: TranscriptDocument, parent=None) -> None:
        super().__init__(parent)
        self.doc = document
        self.player = AudioPlayer(self)
        self._current_seg_idx = -1
        self._block_sync = False
        self._is_video = self._detect_video()
        self._volume_pct = 80  # default 80%
        self._level_provider = AudioLevelProvider()

        self._build_ui()
        self._connect_signals()
        self._register_hotkeys()
        self._render_transcript()

        if self.doc.audio_path:
            self.player.load(str(self.doc.audio_path))
            # Pre-compute audio levels in background
            self._precompute_levels()

        # VU meter refresh timer (50ms = 20fps)
        self._vu_timer = QTimer(self)
        self._vu_timer.setInterval(50)
        self._vu_timer.timeout.connect(self._update_vu)
        self._vu_timer.start()

        # Start foot pedal listener
        self._pedal = FootPedalListener(self)
        self._pedal.pressed.connect(self._on_pedal_pressed)
        self._pedal.connected.connect(self._on_pedal_connected)
        self._pedal.disconnected.connect(self._on_pedal_disconnected)
        self._pedal.start()

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
        self.btn_play.setMinimumWidth(130)

        self.btn_rw = QPushButton("- 5s  (F6)")
        self.btn_rw.setMinimumWidth(100)
        self.btn_ff = QPushButton("+ 5s  (F7)")
        self.btn_ff.setMinimumWidth(100)

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
            btn.setMinimumWidth(52)
            btn.setCheckable(True)
            btn.setChecked(spd == 1.0)
            btn.clicked.connect(lambda checked, s=spd: self._set_speed(s))
            speed_row.addWidget(btn)
            self._speed_buttons_list.append(btn)

        self.lbl_speed = QLabel("1.0x")
        self.lbl_speed.setStyleSheet(f"color: {ACCENT}; font-weight: bold; font-size: 12px;")
        speed_row.addWidget(self.lbl_speed)

        speed_row.addStretch()

        vol_label = QLabel("Vol:")
        vol_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        speed_row.addWidget(vol_label)

        self.slider_vol = QSlider(Qt.Orientation.Horizontal)
        self.slider_vol.setRange(0, 120)
        self.slider_vol.setValue(80)
        self.slider_vol.setFixedWidth(120)
        speed_row.addWidget(self.slider_vol)

        self.lbl_vol = QLabel("80%")
        self.lbl_vol.setFixedWidth(44)
        self.lbl_vol.setStyleSheet(f"color: #00E676; font-family: 'Segoe UI', sans-serif; font-size: 11px; font-weight: bold;")
        speed_row.addWidget(self.lbl_vol)

        root.addLayout(speed_row)

        # -- VU Meter --------------------------------------------------------
        vu_row = QHBoxLayout()
        vu_row.setSpacing(6)
        vu_label = QLabel("Level:")
        vu_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px;")
        vu_label.setFixedWidth(40)
        vu_row.addWidget(vu_label)

        self._vu_meter = VUMeter()
        vu_row.addWidget(self._vu_meter, 1)

        root.addLayout(vu_row)

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

            # Header row: TRANSCRIPT label on left, formatting toolbar on right
            header_row = QHBoxLayout()
            header_row.setContentsMargins(0, 0, 0, 0)
            transcript_header = QLabel("TRANSCRIPT")
            transcript_header.setStyleSheet(
                f"font-size: 9px; font-weight: bold; color: {TEXT_SECONDARY}; "
                f"letter-spacing: 2px; padding: 2px 0;"
            )
            header_row.addWidget(transcript_header)
            header_row.addStretch()
            header_row.addLayout(self._build_format_toolbar())
            transcript_layout.addLayout(header_row)

            self.text_edit = QTextEdit()
            self.text_edit.setFont(QFont("Consolas", 11))
            self.text_edit.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
            self.text_edit.setAcceptRichText(True)
            transcript_layout.addWidget(self.text_edit, 1)

            splitter.addWidget(transcript_container)

            # Default split: 45% video, 55% transcript
            splitter.setSizes([450, 550])

            root.addWidget(splitter, 1)
        else:
            # Audio-only: toolbar on right, transcript full width below
            toolbar_row = QHBoxLayout()
            toolbar_row.setContentsMargins(0, 0, 0, 0)
            toolbar_row.addStretch()
            toolbar_row.addLayout(self._build_format_toolbar())
            root.addLayout(toolbar_row)

            self.text_edit = QTextEdit()
            self.text_edit.setFont(QFont("Consolas", 11))
            self.text_edit.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
            self.text_edit.setAcceptRichText(True)
            root.addWidget(self.text_edit, 1)

        # -- Hint bar --------------------------------------------------------
        hint_row = QHBoxLayout()
        hint_row.setContentsMargins(0, 0, 0, 0)

        hint_text = "F5 Play/Pause  |  F6 Rewind 5s  |  F7 Forward 5s  |  Ctrl+B/I/U Format  |  Click timestamp to seek"
        if self._is_video:
            hint_text += "  |  Drag splitter to resize video"
        hint = QLabel(hint_text)
        hint.setObjectName("hint")
        hint_row.addWidget(hint)

        hint_row.addStretch()

        # Foot pedal status indicator
        self.lbl_pedal = QLabel("○ Pedal scanning…")
        self.lbl_pedal.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px;")
        self.lbl_pedal.setToolTip("Scanning for a connected USB foot pedal…")
        hint_row.addWidget(self.lbl_pedal)

        root.addLayout(hint_row)

    def _build_format_toolbar(self) -> QHBoxLayout:
        """Build the B/I/U + Undo/Redo/Clear toolbar. Uses QFont on the buttons
        so the theme's button text colour still applies (stylesheet-based
        font styling was rendering blank buttons)."""
        row = QHBoxLayout()
        row.setSpacing(4)
        row.setContentsMargins(0, 0, 0, 0)

        # Small square buttons need reduced padding; global theme's
        # 6px 14px would clip the single-letter label.
        compact_css = "QPushButton { padding: 2px; min-width: 0; font-size: 13px; }"

        bold_font = QFont("Segoe UI", 11)
        bold_font.setBold(True)
        self.btn_bold = QPushButton("B")
        self.btn_bold.setToolTip("Bold (Ctrl+B)")
        self.btn_bold.setCheckable(True)
        self.btn_bold.setFixedSize(32, 26)
        self.btn_bold.setFont(bold_font)
        self.btn_bold.setStyleSheet(compact_css)
        row.addWidget(self.btn_bold)

        italic_font = QFont("Segoe UI", 11)
        italic_font.setItalic(True)
        self.btn_italic = QPushButton("I")
        self.btn_italic.setToolTip("Italic (Ctrl+I)")
        self.btn_italic.setCheckable(True)
        self.btn_italic.setFixedSize(32, 26)
        self.btn_italic.setFont(italic_font)
        self.btn_italic.setStyleSheet(compact_css)
        row.addWidget(self.btn_italic)

        underline_font = QFont("Segoe UI", 11)
        underline_font.setUnderline(True)
        self.btn_underline = QPushButton("U")
        self.btn_underline.setToolTip("Underline (Ctrl+U)")
        self.btn_underline.setCheckable(True)
        self.btn_underline.setFixedSize(32, 26)
        self.btn_underline.setFont(underline_font)
        self.btn_underline.setStyleSheet(compact_css)
        row.addWidget(self.btn_underline)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFixedHeight(20)
        sep.setStyleSheet(f"color: {TEXT_SECONDARY};")
        row.addWidget(sep)

        self.btn_undo = QPushButton("↩ Undo")
        self.btn_undo.setToolTip("Undo (Ctrl+Z)")
        self.btn_undo.setMinimumWidth(70)
        self.btn_undo.setFixedHeight(26)
        row.addWidget(self.btn_undo)

        self.btn_redo = QPushButton("↪ Redo")
        self.btn_redo.setToolTip("Redo (Ctrl+Y)")
        self.btn_redo.setMinimumWidth(70)
        self.btn_redo.setFixedHeight(26)
        row.addWidget(self.btn_redo)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setFixedHeight(20)
        sep2.setStyleSheet(f"color: {TEXT_SECONDARY};")
        row.addWidget(sep2)

        self.btn_clear_fmt = QPushButton("✕ Clear")
        self.btn_clear_fmt.setToolTip("Remove formatting from selection")
        self.btn_clear_fmt.setMinimumWidth(70)
        self.btn_clear_fmt.setFixedHeight(26)
        row.addWidget(self.btn_clear_fmt)

        return row

    def _connect_signals(self) -> None:
        self.btn_play.clicked.connect(self.player.toggle)
        self.btn_rw.clicked.connect(lambda: self.player.rewind(5000))
        self.btn_ff.clicked.connect(lambda: self.player.forward(5000))

        self.player.position_changed.connect(self._on_position)
        self.player.duration_changed.connect(self._on_duration)
        self.player.state_changed.connect(self._on_state)

        self.slider_pos.sliderMoved.connect(self._on_seek_slider)
        self.slider_vol.valueChanged.connect(self._on_volume_change)

        self.text_edit.textChanged.connect(self._sync_text_to_model)
        self.text_edit.mouseReleaseEvent = self._on_text_click
        self.text_edit.cursorPositionChanged.connect(self._update_format_buttons)

        # Formatting toolbar
        self.btn_bold.clicked.connect(self._toggle_bold)
        self.btn_italic.clicked.connect(self._toggle_italic)
        self.btn_underline.clicked.connect(self._toggle_underline)
        self.btn_undo.clicked.connect(self.text_edit.undo)
        self.btn_redo.clicked.connect(self.text_edit.redo)
        self.btn_clear_fmt.clicked.connect(self._clear_formatting)

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
        """Rebuild the segment list from the editor text, matching by timestamp."""
        if self._block_sync:
            return
        from models import Segment

        new_segments: list[Segment] = []
        for line in self.text_edit.toPlainText().split("\n"):
            parsed = _parse_line(line)
            if parsed is None:
                continue  # skip blank lines or lines without valid timestamps
            start, end, speaker, text = parsed
            new_segments.append(Segment(start=start, end=end, text=text, speaker=speaker))

        self.doc.segments = new_segments

    # -- Volume --------------------------------------------------------------

    def _on_volume_change(self, value: int) -> None:
        self._volume_pct = value
        self.player.set_volume(value / 100.0)
        self.lbl_vol.setText(f"{value}%")
        # Colour gradient: green (low) → yellow (mid) → red (high/boost)
        color = self._volume_color(value)
        self.lbl_vol.setStyleSheet(
            f"color: {color}; font-family: 'Segoe UI', sans-serif; font-size: 11px; font-weight: bold;"
        )

    @staticmethod
    def _volume_color(value: int) -> str:
        """Return a hex colour for the volume label: green → yellow → red."""
        if value <= 50:
            # Green: #00E676
            return "#00E676"
        elif value <= 80:
            # Green → Yellow: interpolate #00E676 → #FFD600
            t = (value - 50) / 30.0
            r = int(0x00 + t * (0xFF - 0x00))
            g = int(0xE6 + t * (0xD6 - 0xE6))
            b = int(0x76 + t * (0x00 - 0x76))
            return f"#{r:02X}{g:02X}{b:02X}"
        elif value <= 100:
            # Yellow → Orange-red: interpolate #FFD600 → #FF5722
            t = (value - 80) / 20.0
            r = 0xFF
            g = int(0xD6 + t * (0x57 - 0xD6))
            b = int(0x00 + t * (0x22 - 0x00))
            return f"#{r:02X}{g:02X}{b:02X}"
        else:
            # 101-120: Red hot: #FF1744
            return "#FF1744"

    # -- Formatting toolbar --------------------------------------------------

    def _toggle_bold(self) -> None:
        fmt = QTextCharFormat()
        cursor = self.text_edit.textCursor()
        current = cursor.charFormat().fontWeight()
        is_bold = current >= QFont.Weight.Bold
        fmt.setFontWeight(QFont.Weight.Normal if is_bold else QFont.Weight.Bold)
        cursor.mergeCharFormat(fmt)
        self.text_edit.mergeCurrentCharFormat(fmt)

    def _toggle_italic(self) -> None:
        fmt = QTextCharFormat()
        cursor = self.text_edit.textCursor()
        fmt.setFontItalic(not cursor.charFormat().fontItalic())
        cursor.mergeCharFormat(fmt)
        self.text_edit.mergeCurrentCharFormat(fmt)

    def _toggle_underline(self) -> None:
        fmt = QTextCharFormat()
        cursor = self.text_edit.textCursor()
        fmt.setFontUnderline(not cursor.charFormat().fontUnderline())
        cursor.mergeCharFormat(fmt)
        self.text_edit.mergeCurrentCharFormat(fmt)

    def _clear_formatting(self) -> None:
        """Remove all character formatting from the selection."""
        cursor = self.text_edit.textCursor()
        if not cursor.hasSelection():
            return
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Weight.Normal)
        fmt.setFontItalic(False)
        fmt.setFontUnderline(False)
        cursor.mergeCharFormat(fmt)

    def _update_format_buttons(self) -> None:
        """Keep B/I/U toggle states in sync with the cursor's current format."""
        fmt = self.text_edit.textCursor().charFormat()
        self.btn_bold.setChecked(fmt.fontWeight() >= QFont.Weight.Bold)
        self.btn_italic.setChecked(fmt.fontItalic())
        self.btn_underline.setChecked(fmt.fontUnderline())

    # -- Foot pedal ---------------------------------------------------------

    def _on_pedal_pressed(self, button: int) -> None:
        """Default Express Scribe mapping: L=rewind, C=play/pause, R=forward."""
        if button == PedalButton.LEFT:
            self.player.rewind(5000)
        elif button == PedalButton.CENTER:
            self.player.toggle()
        elif button == PedalButton.RIGHT:
            self.player.forward(5000)

    def _on_pedal_connected(self, name: str) -> None:
        if hasattr(self, "lbl_pedal"):
            self.lbl_pedal.setText(f"● Pedal: {name}")
            self.lbl_pedal.setStyleSheet(
                f"color: #00E676; font-size: 10px; font-weight: bold;"
            )
            self.lbl_pedal.setToolTip(
                "Foot pedal connected.\n"
                "Left = Rewind 5s  |  Center = Play/Pause  |  Right = Forward 5s"
            )

    def _on_pedal_disconnected(self) -> None:
        if hasattr(self, "lbl_pedal"):
            self.lbl_pedal.setText("○ No pedal")
            self.lbl_pedal.setStyleSheet(
                f"color: {TEXT_SECONDARY}; font-size: 10px;"
            )
            self.lbl_pedal.setToolTip(
                "No foot pedal detected.\n"
                "Supported: VEC Infinity USB Foot Pedal.\n"
                "Plug it into any USB port — Windows will recognize it automatically."
            )

    def closeEvent(self, event) -> None:
        if hasattr(self, "_pedal"):
            self._pedal.stop()
        super().closeEvent(event)

    # -- VU Meter ------------------------------------------------------------

    def _precompute_levels(self) -> None:
        """Load audio levels in a background thread."""
        import threading
        path = str(self.doc.audio_path)
        def _worker():
            self._level_provider.load(path)
        threading.Thread(target=_worker, daemon=True).start()

    def _update_vu(self) -> None:
        """Called every 50ms to update the VU meter."""
        if not self.player.is_playing or not self._level_provider.ready:
            # Decay to zero when paused
            self._vu_meter.set_level(max(0, self._vu_meter._level - 0.05))
            return
        seconds = self.player.position_ms / 1000.0
        vol_mult = self._volume_pct / 80.0  # scale relative to 80% baseline
        level = self._level_provider.level_at(seconds, vol_mult)
        self._vu_meter.set_level(level)

    # -- Click to seek -------------------------------------------------------

    def _on_text_click(self, event) -> None:
        QTextEdit.mouseReleaseEvent(self.text_edit, event)
        cursor = self.text_edit.cursorForPosition(event.pos())
        col = cursor.positionInBlock()

        # Only seek if clicking in the timestamp portion (first ~25 chars)
        if col < 25:
            block = cursor.block()
            parsed = _parse_line(block.text())
            if parsed:
                start, end, speaker, text = parsed
                self.player.seek(int(start * 1000))
                if not self.player.is_playing:
                    self.player.play()

    # -- Playback callbacks --------------------------------------------------

    @Slot(int)
    def _on_position(self, ms: int) -> None:
        total = self.player.duration_ms
        self.lbl_time.setText(f"{fmt_timestamp_ms(ms)} / {fmt_timestamp_ms(total)}")

        if not self.slider_pos.isSliderDown() and total > 0:
            self.slider_pos.setValue(int(ms / total * 1000))

        # Find which editor line matches the current playback time
        line_idx = self._line_at_time(ms / 1000.0)
        if line_idx != self._current_seg_idx:
            self._highlight_segment(line_idx)
            self._current_seg_idx = line_idx

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

    # -- Find line by time ---------------------------------------------------

    def _line_at_time(self, seconds: float) -> int:
        """Find the editor line number whose timestamp range contains *seconds*."""
        best_idx = -1
        doc = self.text_edit.document()
        for i in range(doc.blockCount()):
            block = doc.findBlockByNumber(i)
            parsed = _parse_line(block.text())
            if parsed:
                start, end, _, _ = parsed
                if start <= seconds <= end:
                    return i
                # Also track the closest preceding segment
                if start <= seconds:
                    best_idx = i
        return best_idx

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
