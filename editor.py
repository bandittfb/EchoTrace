"""Express Scribe-style correction editor with optional video panel."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, Qt, QTimer, Slot
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QShortcut, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument, QTextFormat
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem, QVideoWidget
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from audio_player import AudioPlayer
from flow_layout import FlowLayout
from models import FormattedRun, TranscriptDocument, fmt_timestamp, fmt_timestamp_ms
from pedal import FootPedalListener, PedalButton
from theme import ACCENT, BG_DARK, BG_PANEL, BORDER, SEGMENT_HIGHLIGHT, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TIMESTAMP
from speaker_dialog import SpeakerManagerDialog
from toggle_switch import ToggleSwitch
from transcript_format import (
    TRANSLATION_PREFIX,
    format_segment,
    parse_line,
    parse_translation,
)
from vu_meter import AudioLevelProvider, VUMeter

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".wmv", ".flv", ".m4v"}
SPEED_PRESETS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]

# Font choices — curated for transcript readability on Windows. A mix of
# monospaced fonts (good for timestamp alignment) and proportional fonts
# (easier on the eyes for long reading sessions). All ship with Windows.
FONT_FAMILIES = [
    "Consolas",         # default — clean monospace, great with timestamps
    "Cascadia Code",    # modern Microsoft monospace, ligatures
    "Courier New",      # classic monospace, familiar legal/transcript feel
    "Segoe UI",         # Windows default proportional, very readable
    "Calibri",          # modern proportional, clean
    "Verdana",          # designed for screen readability
    "Arial",            # universal proportional
]
DEFAULT_FONT_FAMILY = "Consolas"
DEFAULT_FONT_SIZE = 11
# How many points the active-segment highlight adds on top of the current
# editor font size. Keeps the "pop" proportional regardless of base size.
HIGHLIGHT_SIZE_BUMP = 3

# Flag presentation. Keys must match models.FLAG_KINDS.
# (label, background tint, accent dot color)
FLAG_DISPLAY = {
    "inaudible":     ("Inaudible",        "#3F3A1A", "#FFD600"),
    "admission":     ("Possible Admission", "#3F1A1A", "#FF1744"),
    "contradiction": ("Contradiction",    "#3F2A1A", "#FF6F00"),
    "follow_up":     ("Follow-up",        "#1A2F3F", "#40C4FF"),
    "custom":        ("Custom",           "#2A1A3F", "#B388FF"),
}


def _coalesce_runs(runs: list[FormattedRun]) -> list[FormattedRun]:
    """Merge consecutive runs whose B/I/U flags match — Qt sometimes splits
    a fragment for cursor-position reasons even when nothing changed."""
    out: list[FormattedRun] = []
    for r in runs:
        if out and (
            out[-1].bold == r.bold
            and out[-1].italic == r.italic
            and out[-1].underline == r.underline
        ):
            out[-1] = FormattedRun(
                text=out[-1].text + r.text,
                bold=r.bold,
                italic=r.italic,
                underline=r.underline,
            )
        else:
            out.append(r)
    return out


class RotatableVideoView(QGraphicsView):
    """QGraphicsView wrapper around a QGraphicsVideoItem that supports
    90-degree rotation and scroll-wheel zoom.

    Used in place of the plain QVideoWidget so the user can correct
    rotated body-cam / dash-cam footage and zoom into details without
    re-encoding the file.

    Controls:
    * Scroll wheel — zoom in / out (1.0× → 5.0×)
    * Double-click — reset to fit-to-view (1.0×)
    * Click + drag — pan when zoomed in
    * rotate_cw() / rotate_ccw() — 90° steps
    """

    ZOOM_MIN = 1.0
    ZOOM_MAX = 5.0
    ZOOM_STEP = 1.15  # each scroll notch multiplies/divides by this

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._video_item = QGraphicsVideoItem()
        self._scene.addItem(self._video_item)
        self.setScene(self._scene)
        self._rotation = 0
        self._zoom = 1.0

        # Clean look: no scrollbars, black background, no frame
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("background-color: black;")

        # Drag-to-pan when zoomed in
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

        # Refit whenever the video's native resolution becomes known
        self._video_item.nativeSizeChanged.connect(lambda _: self._fit_video())

    @property
    def video_item(self) -> QGraphicsVideoItem:
        return self._video_item

    @property
    def rotation_degrees(self) -> int:
        return self._rotation

    @property
    def zoom_factor(self) -> float:
        return self._zoom

    def rotate_cw(self) -> None:
        """Rotate 90° clockwise."""
        self._rotation = (self._rotation + 90) % 360
        self._video_item.setRotation(self._rotation)
        self._zoom = 1.0
        self._fit_video()

    def rotate_ccw(self) -> None:
        """Rotate 90° counter-clockwise."""
        self._rotation = (self._rotation - 90) % 360
        self._video_item.setRotation(self._rotation)
        self._zoom = 1.0
        self._fit_video()

    def zoom_in(self) -> None:
        """Zoom in one step."""
        self._apply_zoom(self._zoom * self.ZOOM_STEP)

    def zoom_out(self) -> None:
        """Zoom out one step."""
        self._apply_zoom(self._zoom / self.ZOOM_STEP)

    def zoom_reset(self) -> None:
        """Reset to fit-to-view (1.0×)."""
        self._zoom = 1.0
        self._fit_video()

    def _apply_zoom(self, new_zoom: float) -> None:
        new_zoom = max(self.ZOOM_MIN, min(self.ZOOM_MAX, new_zoom))
        if abs(new_zoom - self._zoom) < 0.01:
            return
        factor = new_zoom / self._zoom
        self._zoom = new_zoom
        self.scale(factor, factor)
        # Show scrollbars only when zoomed past 1×
        policy = (
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
            if self._zoom > 1.05
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.setHorizontalScrollBarPolicy(policy)
        self.setVerticalScrollBarPolicy(policy)

    def _fit_video(self) -> None:
        rect = self._video_item.boundingRect()
        if rect.isValid() and rect.width() > 0 and rect.height() > 0:
            self.fitInView(self._video_item, Qt.AspectRatioMode.KeepAspectRatio)
        # Hide scrollbars at 1× since we're fully fitted
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    # -- Qt event overrides -------------------------------------------------

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._zoom <= 1.05:
            self._fit_video()

    def wheelEvent(self, event) -> None:
        """Scroll wheel zooms in/out instead of scrolling."""
        delta = event.angleDelta().y()
        if delta > 0:
            self._apply_zoom(self._zoom * self.ZOOM_STEP)
        elif delta < 0:
            self._apply_zoom(self._zoom / self.ZOOM_STEP)

    def mouseDoubleClickEvent(self, event) -> None:
        """Double-click resets to fit-to-view."""
        self._zoom = 1.0
        self._fit_video()
        super().mouseDoubleClickEvent(event)


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
        self._pedal_momentary = True  # hold center to play (Express Scribe default)
        self._search_matches: list[tuple[int, int]] = []  # (start, end) char positions
        self._search_idx = -1
        self._search_query = ""
        self._editor_font_family = DEFAULT_FONT_FAMILY
        self._editor_font_size = DEFAULT_FONT_SIZE
        self._segment_bg_selection: QTextEdit.ExtraSelection | None = None
        self._segment_text_selection: QTextEdit.ExtraSelection | None = None
        # Animated highlight: flashes brighter when segment changes, then
        # decays to the steady SEGMENT_HIGHLIGHT color over ~400ms.
        self._highlight_intensity = 0.0  # 1.0 = peak flash, 0.0 = steady

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
        self._pedal.released.connect(self._on_pedal_released)
        self._pedal.connected.connect(self._on_pedal_connected)
        self._pedal.disconnected.connect(self._on_pedal_disconnected)
        self.switch_pedal_hold.toggled.connect(self._on_pedal_mode_changed)
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

            # Header row: rotate buttons flanking the "VIDEO" label
            video_header_row = QHBoxLayout()
            video_header_row.setSpacing(4)
            video_header_row.setContentsMargins(0, 0, 0, 0)

            video_btn_css = (
                "QPushButton { padding: 3px; min-width: 0; font-size: 18px; "
                f"background: transparent; color: {TEXT_SECONDARY}; border: none; }}"
                f"QPushButton:hover {{ color: {ACCENT}; }}"
            )

            self.btn_rotate_ccw = QPushButton("⟲")
            self.btn_rotate_ccw.setToolTip("Rotate video 90° counter-clockwise")
            self.btn_rotate_ccw.setFixedSize(34, 30)
            self.btn_rotate_ccw.setStyleSheet(video_btn_css)
            self.btn_rotate_ccw.clicked.connect(lambda: self._rotate_video("ccw"))
            video_header_row.addWidget(self.btn_rotate_ccw)

            video_header = QLabel("VIDEO")
            video_header.setStyleSheet(
                f"font-size: 9px; font-weight: bold; color: {TEXT_SECONDARY}; "
                f"letter-spacing: 2px; padding: 2px 0;"
            )
            video_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
            video_header_row.addWidget(video_header, 1)

            self.btn_rotate_cw = QPushButton("⟳")
            self.btn_rotate_cw.setToolTip("Rotate video 90° clockwise")
            self.btn_rotate_cw.setFixedSize(34, 30)
            self.btn_rotate_cw.setStyleSheet(video_btn_css)
            self.btn_rotate_cw.clicked.connect(lambda: self._rotate_video("cw"))
            video_header_row.addWidget(self.btn_rotate_cw)

            # Zoom controls
            self.btn_zoom_in = QPushButton("+")
            self.btn_zoom_in.setToolTip("Zoom in (or scroll wheel)")
            self.btn_zoom_in.setFixedSize(34, 30)
            self.btn_zoom_in.setStyleSheet(video_btn_css)
            self.btn_zoom_in.clicked.connect(lambda: self._zoom_video("in"))
            video_header_row.addWidget(self.btn_zoom_in)

            self.btn_zoom_out = QPushButton("−")
            self.btn_zoom_out.setToolTip("Zoom out (or scroll wheel)")
            self.btn_zoom_out.setFixedSize(34, 30)
            self.btn_zoom_out.setStyleSheet(video_btn_css)
            self.btn_zoom_out.clicked.connect(lambda: self._zoom_video("out"))
            video_header_row.addWidget(self.btn_zoom_out)

            self.btn_zoom_reset = QPushButton("1:1")
            self.btn_zoom_reset.setToolTip("Reset zoom to fit (or double-click video)")
            self.btn_zoom_reset.setFixedSize(40, 30)
            self.btn_zoom_reset.setStyleSheet(video_btn_css)
            self.btn_zoom_reset.clicked.connect(lambda: self._zoom_video("reset"))
            video_header_row.addWidget(self.btn_zoom_reset)

            video_layout.addLayout(video_header_row)

            self._video_view = RotatableVideoView()
            self._video_view.setMinimumSize(320, 240)
            video_layout.addWidget(self._video_view, 1)

            self.player.set_video_output(self._video_view.video_item)
            splitter.addWidget(video_container)

            # Transcript panel
            transcript_container = QWidget()
            transcript_layout = QVBoxLayout(transcript_container)
            transcript_layout.setContentsMargins(0, 0, 0, 0)
            transcript_layout.setSpacing(4)

            # Header: TRANSCRIPT label, then a FlowLayout that wraps the
            # search bar + format toolbar onto a second row when narrow.
            transcript_header = QLabel("TRANSCRIPT")
            transcript_header.setStyleSheet(
                f"font-size: 9px; font-weight: bold; color: {TEXT_SECONDARY}; "
                f"letter-spacing: 2px; padding: 2px 0;"
            )
            transcript_layout.addWidget(transcript_header)

            toolbar_container = QWidget()
            toolbar_flow = FlowLayout(toolbar_container, margin=0, spacing=6)
            toolbar_flow.addWidget(self._build_search_bar())
            toolbar_flow.addWidget(self._build_format_toolbar())
            transcript_layout.addWidget(toolbar_container)

            self.text_edit = QTextEdit()
            self.text_edit.setFont(QFont(self._editor_font_family, self._editor_font_size))
            self.text_edit.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
            self.text_edit.setAcceptRichText(True)
            transcript_layout.addWidget(self.text_edit, 1)

            splitter.addWidget(transcript_container)

            # Default split: 45% video, 55% transcript
            splitter.setSizes([450, 550])

            root.addWidget(splitter, 1)
        else:
            # Audio-only: search + format toolbars in a flow layout
            # so they wrap to a second row when the window is narrow.
            toolbar_container = QWidget()
            toolbar_flow = FlowLayout(toolbar_container, margin=0, spacing=6)
            toolbar_flow.addWidget(self._build_search_bar())
            toolbar_flow.addWidget(self._build_format_toolbar())
            root.addWidget(toolbar_container)

            self.text_edit = QTextEdit()
            self.text_edit.setFont(QFont(self._editor_font_family, self._editor_font_size))
            self.text_edit.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
            self.text_edit.setAcceptRichText(True)
            root.addWidget(self.text_edit, 1)

        # -- Hint bar --------------------------------------------------------
        hint_row = QHBoxLayout()
        hint_row.setContentsMargins(0, 0, 0, 0)

        hint_text = "F5 Play/Pause  |  F6 Rewind 5s  |  F7 Forward 5s  |  Ctrl+B/I/U Format  |  Click timestamp to seek  |  Click speaker to change"
        if self._is_video:
            hint_text += "  |  Drag splitter to resize video"
        hint = QLabel(hint_text)
        hint.setObjectName("hint")
        hint_row.addWidget(hint)

        hint_row.addStretch()

        # Foot pedal: mode label + slider switch + status indicator
        self.lbl_pedal_mode = QLabel("Hold to play")
        self.lbl_pedal_mode.setStyleSheet(
            f"color: #00E676; font-size: 10px; font-weight: bold;"
        )
        hint_row.addWidget(self.lbl_pedal_mode)

        self.switch_pedal_hold = ToggleSwitch()
        self.switch_pedal_hold.setChecked(True)  # momentary = Express Scribe default
        self.switch_pedal_hold.setFixedSize(36, 18)
        self.switch_pedal_hold.setToolTip(
            "Center pedal behaviour:\n"
            "  ON (green):   Hold to play — release to pause\n"
            "  OFF (gray):   Continuous play — press once to play, again to pause"
        )
        hint_row.addWidget(self.switch_pedal_hold)

        hint_row.addSpacing(10)

        self.lbl_pedal = QLabel("○ Pedal scanning…")
        self.lbl_pedal.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px;")
        self.lbl_pedal.setToolTip("Scanning for a connected USB foot pedal…")
        hint_row.addWidget(self.lbl_pedal)

        root.addLayout(hint_row)

    def _build_search_bar(self) -> QWidget:
        """Build the find-in-transcript bar: input, counter, prev/next, clear.
        Returns a self-contained QWidget so it can be placed in any layout
        and wrap as a single unit in a FlowLayout."""
        container = QWidget()
        row = QHBoxLayout(container)
        row.setSpacing(4)
        row.setContentsMargins(0, 0, 0, 0)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Find…")
        self.search_input.setFixedSize(190, 38)
        self.search_input.setStyleSheet(
            f"QLineEdit {{"
            f"  background-color: {BG_PANEL}; color: {TEXT_PRIMARY};"
            f"  border: 1px solid {ACCENT}; border-radius: 4px;"
            f"  padding: 5px 8px; font-size: 14px;"
            f"  selection-background-color: {ACCENT};"
            f"}}"
        )
        self.search_input.setToolTip("Find in transcript (Ctrl+F). Esc to clear.")
        row.addWidget(self.search_input)

        self.lbl_search_count = QLabel("0/0")
        self.lbl_search_count.setFixedWidth(44)
        self.lbl_search_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_search_count.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 13px; font-family: 'Segoe UI';"
        )
        row.addWidget(self.lbl_search_count)

        nav_css = "QPushButton { padding: 4px; min-width: 0; font-size: 16px; }"

        self.btn_search_prev = QPushButton("◀")
        self.btn_search_prev.setToolTip("Previous match (Shift+F3)")
        self.btn_search_prev.setFixedSize(36, 38)
        self.btn_search_prev.setStyleSheet(nav_css)
        self.btn_search_prev.setEnabled(False)
        row.addWidget(self.btn_search_prev)

        self.btn_search_next = QPushButton("▶")
        self.btn_search_next.setToolTip("Next match (F3)")
        self.btn_search_next.setFixedSize(36, 38)
        self.btn_search_next.setStyleSheet(nav_css)
        self.btn_search_next.setEnabled(False)
        row.addWidget(self.btn_search_next)

        self.btn_search_clear = QPushButton("✕")
        self.btn_search_clear.setToolTip("Clear search (Esc)")
        self.btn_search_clear.setFixedSize(36, 38)
        self.btn_search_clear.setStyleSheet(nav_css)
        row.addWidget(self.btn_search_clear)

        return container

    def _build_format_toolbar(self) -> QWidget:
        """Build the font picker + B/I/U + Undo/Redo/Clear toolbar.

        Layout follows the standard word-processor order:
        Font Family | Font Size | | B I U | | Undo Redo | Clear | Flags | Speakers

        Uses QFont on the buttons so the theme's button text colour still
        applies (stylesheet-based font styling was rendering blank buttons).
        Returns a self-contained QWidget so it wraps as a single unit in
        a FlowLayout."""
        container = QWidget()
        row = QHBoxLayout(container)
        row.setSpacing(4)
        row.setContentsMargins(0, 0, 0, 0)

        # Toolbar-wide sizing constants
        BTN_H = 38  # uniform button height across the toolbar
        SEP_H = 28  # separator line height

        # Small square buttons need reduced padding; global theme's
        # 6px 14px would clip the single-letter label.
        compact_css = f"QPushButton {{ padding: 4px; min-width: 0; font-size: 16px; }}"
        # Medium buttons: same visual language as compact, just wider for labels.
        medium_css = f"QPushButton {{ padding: 4px 14px; font-size: 14px; }}"
        # Combo/spin styling for the font controls — larger text, more padding.
        ctrl_css = (
            f"QComboBox, QSpinBox {{ background-color: {BG_PANEL}; color: {TEXT_PRIMARY}; "
            f"border: 1px solid {BORDER}; border-radius: 4px; padding: 5px 8px; font-size: 14px; }}"
        )

        # -- Font family picker -----------------------------------------------
        self.combo_font = QComboBox()
        for family in FONT_FAMILIES:
            self.combo_font.addItem(family)
        self.combo_font.setCurrentText(self._editor_font_family)
        self.combo_font.setFixedHeight(BTN_H)
        self.combo_font.setMinimumWidth(170)
        self.combo_font.setToolTip("Editor font family")
        self.combo_font.setStyleSheet(ctrl_css)
        self.combo_font.currentTextChanged.connect(self._on_font_family_changed)
        row.addWidget(self.combo_font)

        # -- Font size spinner ------------------------------------------------
        self.spin_font_size = QSpinBox()
        self.spin_font_size.setRange(8, 28)
        self.spin_font_size.setValue(self._editor_font_size)
        self.spin_font_size.setSuffix("pt")
        self.spin_font_size.setFixedHeight(BTN_H)
        self.spin_font_size.setFixedWidth(86)
        self.spin_font_size.setToolTip("Editor font size (use arrows or type a number)")
        self.spin_font_size.setStyleSheet(ctrl_css)
        self.spin_font_size.valueChanged.connect(self._on_font_size_changed)
        row.addWidget(self.spin_font_size)

        sep_font = QFrame()
        sep_font.setFrameShape(QFrame.Shape.VLine)
        sep_font.setFixedHeight(SEP_H)
        sep_font.setStyleSheet(f"color: {TEXT_SECONDARY};")
        row.addWidget(sep_font)

        # -- B / I / U --------------------------------------------------------
        bold_font = QFont("Segoe UI", 13)
        bold_font.setBold(True)
        self.btn_bold = QPushButton("B")
        self.btn_bold.setToolTip("Bold (Ctrl+B)")
        self.btn_bold.setCheckable(True)
        self.btn_bold.setFixedSize(40, BTN_H)
        self.btn_bold.setFont(bold_font)
        self.btn_bold.setStyleSheet(compact_css)
        row.addWidget(self.btn_bold)

        italic_font = QFont("Segoe UI", 13)
        italic_font.setItalic(True)
        self.btn_italic = QPushButton("I")
        self.btn_italic.setToolTip("Italic (Ctrl+I)")
        self.btn_italic.setCheckable(True)
        self.btn_italic.setFixedSize(40, BTN_H)
        self.btn_italic.setFont(italic_font)
        self.btn_italic.setStyleSheet(compact_css)
        row.addWidget(self.btn_italic)

        underline_font = QFont("Segoe UI", 13)
        underline_font.setUnderline(True)
        self.btn_underline = QPushButton("U")
        self.btn_underline.setToolTip("Underline (Ctrl+U)")
        self.btn_underline.setCheckable(True)
        self.btn_underline.setFixedSize(40, BTN_H)
        self.btn_underline.setFont(underline_font)
        self.btn_underline.setStyleSheet(compact_css)
        row.addWidget(self.btn_underline)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFixedHeight(SEP_H)
        sep.setStyleSheet(f"color: {TEXT_SECONDARY};")
        row.addWidget(sep)

        self.btn_undo = QPushButton("↩ Undo")
        self.btn_undo.setToolTip("Undo (Ctrl+Z)")
        self.btn_undo.setFixedSize(88, BTN_H)
        self.btn_undo.setStyleSheet(medium_css)
        row.addWidget(self.btn_undo)

        self.btn_redo = QPushButton("↪ Redo")
        self.btn_redo.setToolTip("Redo (Ctrl+Y)")
        self.btn_redo.setFixedSize(88, BTN_H)
        self.btn_redo.setStyleSheet(medium_css)
        row.addWidget(self.btn_redo)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setFixedHeight(SEP_H)
        sep2.setStyleSheet(f"color: {TEXT_SECONDARY};")
        row.addWidget(sep2)

        self.btn_clear_fmt = QPushButton("✕ Clear")
        self.btn_clear_fmt.setToolTip("Remove formatting from selection")
        self.btn_clear_fmt.setFixedSize(88, BTN_H)
        self.btn_clear_fmt.setStyleSheet(medium_css)
        row.addWidget(self.btn_clear_fmt)

        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.VLine)
        sep3.setFixedHeight(SEP_H)
        sep3.setStyleSheet(f"color: {TEXT_SECONDARY};")
        row.addWidget(sep3)

        # Flags dropdown — count updates as user flags segments
        self.btn_flags = QPushButton("Flags  ▾")
        self.btn_flags.setToolTip(
            "Jump to a flagged segment.\n"
            "Right-click any line in the transcript to add a flag."
        )
        self.btn_flags.setFixedHeight(BTN_H)
        self.btn_flags.setMinimumWidth(90)
        self.btn_flags.setStyleSheet(medium_css)
        self.btn_flags.clicked.connect(self._open_flags_menu)
        row.addWidget(self.btn_flags)

        # Speakers... — opens the speaker management dialog
        self.btn_speakers = QPushButton("Speakers...")
        self.btn_speakers.setToolTip(
            "Rename or merge speakers across the entire transcript"
        )
        self.btn_speakers.setFixedHeight(BTN_H)
        self.btn_speakers.setMinimumWidth(100)
        self.btn_speakers.setStyleSheet(medium_css)
        self.btn_speakers.clicked.connect(self._open_speaker_manager)
        row.addWidget(self.btn_speakers)

        return container

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
        self.text_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.text_edit.customContextMenuRequested.connect(self._on_text_context_menu)

        # Speaker hover affordance: cursor turns into a hand over speaker
        # names, signaling "click to change speaker." Mouse tracking has to
        # be on at both the QTextEdit and its viewport, otherwise move
        # events only fire while a button is held.
        self.text_edit.setMouseTracking(True)
        self.text_edit.viewport().setMouseTracking(True)
        self._orig_mouse_move = self.text_edit.mouseMoveEvent
        self.text_edit.mouseMoveEvent = self._on_text_mouse_move

        # Formatting toolbar
        self.btn_bold.clicked.connect(self._toggle_bold)
        self.btn_italic.clicked.connect(self._toggle_italic)
        self.btn_underline.clicked.connect(self._toggle_underline)
        self.btn_undo.clicked.connect(self.text_edit.undo)
        self.btn_redo.clicked.connect(self.text_edit.redo)
        self.btn_clear_fmt.clicked.connect(self._clear_formatting)

        # Search bar
        self.search_input.textChanged.connect(self._on_search_text_changed)
        self.search_input.returnPressed.connect(self._search_next)
        self.btn_search_next.clicked.connect(self._search_next)
        self.btn_search_prev.clicked.connect(self._search_prev)
        self.btn_search_clear.clicked.connect(self._clear_search)

    def _register_hotkeys(self) -> None:
        QShortcut(QKeySequence(Qt.Key.Key_F5), self, self.player.toggle, context=Qt.ShortcutContext.WindowShortcut)
        QShortcut(QKeySequence(Qt.Key.Key_F6), self, lambda: self.player.rewind(5000), context=Qt.ShortcutContext.WindowShortcut)
        QShortcut(QKeySequence(Qt.Key.Key_F7), self, lambda: self.player.forward(5000), context=Qt.ShortcutContext.WindowShortcut)
        # Search shortcuts
        QShortcut(QKeySequence("Ctrl+F"), self, self._focus_search, context=Qt.ShortcutContext.WindowShortcut)
        QShortcut(QKeySequence(Qt.Key.Key_F3), self, self._search_next, context=Qt.ShortcutContext.WindowShortcut)
        QShortcut(QKeySequence("Shift+F3"), self, self._search_prev, context=Qt.ShortcutContext.WindowShortcut)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self.search_input, self._clear_search, context=Qt.ShortcutContext.WidgetShortcut)

    # -- Render transcript ---------------------------------------------------

    def _render_transcript(self) -> None:
        self._block_sync = True
        self.text_edit.clear()
        # Each segment contributes one block (main line) plus an optional
        # second block (translation continuation). format_segment emits
        # them as a single "\n"-separated string so the join below puts
        # exactly one newline between every block in the final document.
        blocks = [
            format_segment(
                seg.start, seg.end, seg.text, seg.speaker,
                language=seg.language, translation=seg.translation,
            )
            for seg in self.doc.segments
        ]
        self.text_edit.setPlainText("\n".join(blocks))
        self._block_sync = False
        # Re-paint flag tints + update Flags button count for the loaded doc
        self._refresh_extra_selections()
        self._refresh_flag_button()

    # -- Sync text back to model ---------------------------------------------

    def _sync_text_to_model(self) -> None:
        """Rebuild the segment list from the editor text, matching by timestamp.

        Flags and notes aren't represented in the editor text, so we
        preserve them across the rebuild by keying on the (start, end)
        timestamp pair — those columns are stable as long as the user
        doesn't edit the timestamp text itself.

        Translation continuation lines (indented with ``↳``) are folded
        onto whichever main segment precedes them. This is the one place
        where line-by-line parsing becomes stateful.
        """
        if self._block_sync:
            return
        from models import Segment

        # Snapshot existing flag/note metadata before we rebuild
        old_meta = {
            (s.start, s.end): (s.flag, s.note) for s in self.doc.segments
        }

        new_segments: list[Segment] = []
        for line in self.text_edit.toPlainText().split("\n"):
            # Translation line? Attach to the previous segment and move on.
            if new_segments:
                trans = parse_translation(line)
                if trans is not None:
                    # Preserve any previously-attached translation by
                    # appending subsequent lines with a space separator —
                    # multi-line translations aren't the common case but
                    # shouldn't silently drop content.
                    if new_segments[-1].translation:
                        new_segments[-1].translation += " " + trans
                    else:
                        new_segments[-1].translation = trans
                    continue

            parsed = parse_line(line)
            if parsed is None:
                continue  # skip blank lines or lines without valid timestamps
            start, end, speaker, language, text = parsed
            flag, note = old_meta.get((start, end), ("", ""))
            new_segments.append(Segment(
                start=start, end=end, text=text, speaker=speaker,
                flag=flag, note=note, language=language,
            ))

        self.doc.segments = new_segments

        # If a search is active, refresh the highlights since text changed
        # underneath them. Without this, edits leave stale match positions
        # and a wrong "N of M" counter until the user retypes the query.
        if self._search_query:
            old_idx = self._search_idx
            self._find_all_matches()
            # Try to keep the user near where they were
            if self._search_matches:
                self._search_idx = min(max(0, old_idx), len(self._search_matches) - 1)
            else:
                self._search_idx = -1
            self._apply_search_highlights()
            self._update_search_ui()

    def extract_rich_runs(self) -> tuple[list[list[FormattedRun]], list[list[FormattedRun]]]:
        """Return per-segment B/I/U formatting captured from the editor.

        Returns a tuple ``(main_runs, translation_runs)``. Both lists are
        parallel to ``self.doc.segments``:

        * ``main_runs[i]`` covers only the *text* portion of segment i's
          main line (timestamps and speaker prefixes are skipped).
        * ``translation_runs[i]`` covers the translation continuation
          line's text portion (after the ``↳`` glyph). Empty list if the
          segment has no translation.

        DOCX/PDF exporters use this to re-apply Bold/Italic/Underline
        that the user toggled in the editor. TXT/JSON exports ignore it.
        """
        main_per_segment: list[list[FormattedRun]] = []
        trans_per_segment: list[list[FormattedRun]] = []
        doc = self.text_edit.document()

        # Walk blocks. Main lines produce an entry in both arrays (the
        # translation entry stays empty unless a continuation block
        # follows). Translation continuation blocks overwrite the last
        # translation entry in-place.
        for i in range(doc.blockCount()):
            block = doc.findBlockByNumber(i)
            plain = block.text()

            # Translation continuation? Attach to the previous segment.
            trans_text = parse_translation(plain)
            if trans_text is not None and main_per_segment:
                runs = self._extract_runs_after_prefix(
                    block, plain, TRANSLATION_PREFIX, trans_text,
                )
                trans_per_segment[-1] = runs
                continue

            parsed = parse_line(plain)
            if parsed is None:
                continue
            _, _, _speaker, _lang, text = parsed
            if not text:
                main_per_segment.append([])
                trans_per_segment.append([])
                continue

            # Find where the text portion begins inside the block's plain
            # text. The render uses "  text" suffix, so rfind is reliable
            # even if the timestamp/speaker contains the same string.
            text_start = plain.rfind(text)
            if text_start < 0:
                main_per_segment.append([FormattedRun(text=text)])
                trans_per_segment.append([])
                continue

            runs = self._extract_runs_in_range(
                block, text_start, text_start + len(text),
            )
            main_per_segment.append(
                _coalesce_runs(runs) if runs else [FormattedRun(text=text)]
            )
            trans_per_segment.append([])
        return main_per_segment, trans_per_segment

    def _extract_runs_after_prefix(
        self, block, plain: str, prefix: str, body_text: str,
    ) -> list[FormattedRun]:
        """Extract B/I/U runs from the portion of *block* that comes
        after *prefix*. Used for translation continuation lines whose
        body starts at a fixed indent marker."""
        text_start = plain.find(prefix)
        if text_start < 0:
            return [FormattedRun(text=body_text)]
        text_start += len(prefix)
        text_end = text_start + len(body_text)
        runs = self._extract_runs_in_range(block, text_start, text_end)
        return _coalesce_runs(runs) if runs else [FormattedRun(text=body_text)]

    def _extract_runs_in_range(
        self, block, text_start: int, text_end: int,
    ) -> list[FormattedRun]:
        """Walk the fragments of *block* and emit a FormattedRun for each
        fragment that overlaps [text_start, text_end)."""
        block_runs: list[FormattedRun] = []
        it = block.begin()
        block_pos = block.position()
        while not it.atEnd():
            fragment = it.fragment()
            if fragment.isValid():
                frag_offset = fragment.position() - block_pos
                frag_text = fragment.text()
                frag_end = frag_offset + len(frag_text)
                overlap_start = max(frag_offset, text_start)
                overlap_end = min(frag_end, text_end)
                if overlap_start < overlap_end:
                    sliced = frag_text[
                        overlap_start - frag_offset : overlap_end - frag_offset
                    ]
                    fmt = fragment.charFormat()
                    block_runs.append(
                        FormattedRun(
                            text=sliced,
                            bold=fmt.fontWeight() >= QFont.Weight.Bold,
                            italic=fmt.fontItalic(),
                            underline=fmt.fontUnderline(),
                        )
                    )
            it += 1
        return block_runs

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

    # -- Font picker ---------------------------------------------------------

    def _on_font_family_changed(self, family: str) -> None:
        """Change the base font family of the entire editor."""
        self._editor_font_family = family
        self._apply_editor_font()

    def _on_font_size_changed(self, size: int) -> None:
        """Change the base font size of the entire editor."""
        self._editor_font_size = size
        self._apply_editor_font()

    def _apply_editor_font(self) -> None:
        """Set the editor's document-wide font without destroying content.

        ``setFont()`` on a QTextEdit only sets the default font for newly
        typed text — existing text keeps whatever char format it already
        has. To change *everything*, we walk the document and reset each
        block's character format to the new font, preserving B/I/U that
        the user may have applied. We also suppress the sync-to-model
        callback so the segment list isn't rebuilt mid-operation.
        """
        new_font = QFont(self._editor_font_family, self._editor_font_size)
        # Set the widget-level default (affects new typing + empty lines)
        self.text_edit.setFont(new_font)

        # Walk every block and update existing text to the new font/size,
        # keeping any B/I/U the user toggled.
        self._block_sync = True
        doc = self.text_edit.document()
        cursor = QTextCursor(doc)
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.movePosition(
            QTextCursor.MoveOperation.End,
            QTextCursor.MoveMode.KeepAnchor,
        )
        fmt = QTextCharFormat()
        fmt.setFontFamilies([self._editor_font_family])
        fmt.setFontPointSize(float(self._editor_font_size))
        cursor.mergeCharFormat(fmt)
        cursor.endEditBlock()
        self._block_sync = False

        # Refresh the playback highlight so its enlarged-text layer stays
        # proportional to the new base size.
        if self._segment_bg_selection is not None:
            self._highlight_segment(self._current_seg_idx)

    # -- Find in transcript --------------------------------------------------

    def _focus_search(self) -> None:
        self.search_input.setFocus()
        self.search_input.selectAll()

    def _on_search_text_changed(self, text: str) -> None:
        self._search_query = text
        self._find_all_matches()
        # When typing, jump to the first match (not the previous "current")
        self._search_idx = 0 if self._search_matches else -1
        self._apply_search_highlights()
        self._update_search_ui()
        if self._search_idx >= 0:
            self._scroll_to_current_match()

    def _find_all_matches(self) -> None:
        """Scan the document for all occurrences of the query (case-insensitive)."""
        self._search_matches = []
        if not self._search_query:
            return
        doc = self.text_edit.document()
        cursor = QTextCursor(doc)
        # Case-insensitive find. Pass 0 flags = no case sensitivity by default.
        while True:
            cursor = doc.find(self._search_query, cursor)
            if cursor.isNull():
                break
            self._search_matches.append((cursor.selectionStart(), cursor.selectionEnd()))

    def _apply_search_highlights(self) -> None:
        """Repaint search-match backgrounds (delegates to the unified
        extra-selections refresh so segment highlight stays intact)."""
        self._refresh_extra_selections()

    def _update_search_ui(self) -> None:
        total = len(self._search_matches)
        if total == 0:
            self.lbl_search_count.setText("0/0" if self._search_query else "")
            self.lbl_search_count.setStyleSheet(
                f"color: {'#FF1744' if self._search_query else TEXT_SECONDARY}; "
                f"font-size: 10px; font-family: 'Segoe UI';"
            )
            self.btn_search_prev.setEnabled(False)
            self.btn_search_next.setEnabled(False)
        else:
            self.lbl_search_count.setText(f"{self._search_idx + 1}/{total}")
            self.lbl_search_count.setStyleSheet(
                f"color: #00E676; font-size: 10px; font-family: 'Segoe UI'; font-weight: bold;"
            )
            self.btn_search_prev.setEnabled(True)
            self.btn_search_next.setEnabled(True)

    def _scroll_to_current_match(self) -> None:
        """Move the visible cursor to the current match and ensure it's on-screen."""
        if not (0 <= self._search_idx < len(self._search_matches)):
            return
        start, end = self._search_matches[self._search_idx]
        cursor = QTextCursor(self.text_edit.document())
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        # Don't trigger sync logic — extra selections handle the visual
        self._block_sync = True
        self.text_edit.setTextCursor(cursor)
        self.text_edit.ensureCursorVisible()
        self._block_sync = False

    def _search_next(self) -> None:
        if not self._search_matches:
            return
        self._search_idx = (self._search_idx + 1) % len(self._search_matches)
        self._apply_search_highlights()
        self._update_search_ui()
        self._scroll_to_current_match()

    def _search_prev(self) -> None:
        if not self._search_matches:
            return
        self._search_idx = (self._search_idx - 1) % len(self._search_matches)
        self._apply_search_highlights()
        self._update_search_ui()
        self._scroll_to_current_match()

    def _clear_search(self) -> None:
        self.search_input.clear()
        self._search_matches = []
        self._search_idx = -1
        self._search_query = ""
        self._refresh_extra_selections()  # keeps segment highlight intact
        self._update_search_ui()
        self.text_edit.setFocus()

    # -- Foot pedal ---------------------------------------------------------

    def _on_pedal_pressed(self, button: int) -> None:
        """Express Scribe mapping: L=rewind, C=play/pause, R=forward.

        Center pedal behaviour depends on the 'Hold to play' setting:
          - momentary (default): press starts playback, release pauses
          - toggle: press flips play/pause state
        """
        if button == PedalButton.LEFT:
            self.player.rewind(5000)
        elif button == PedalButton.CENTER:
            if self._pedal_momentary:
                self.player.play()
            else:
                self.player.toggle()
        elif button == PedalButton.RIGHT:
            self.player.forward(5000)

    def _on_pedal_released(self, button: int) -> None:
        """In momentary mode, releasing the center pedal pauses playback."""
        if button == PedalButton.CENTER and self._pedal_momentary:
            self.player.pause()

    def _on_pedal_mode_changed(self, checked: bool) -> None:
        self._pedal_momentary = checked
        if checked:
            self.lbl_pedal_mode.setText("Hold to play")
            self.lbl_pedal_mode.setStyleSheet(
                f"color: #00E676; font-size: 10px; font-weight: bold;"
            )
        else:
            self.lbl_pedal_mode.setText("Continuous play")
            self.lbl_pedal_mode.setStyleSheet(
                f"color: {TEXT_SECONDARY}; font-size: 10px;"
            )

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

    def cleanup(self) -> None:
        """Tear down background resources (pedal listener thread, audio
        player) without requiring closeEvent() to fire.

        Qt does NOT guarantee closeEvent runs when a widget is removed
        from a layout / parent and deleteLater'd — only when it's
        explicitly closed via close() or the OS dismisses its window.
        Callers that swap out the editor (e.g. main window 'New File')
        MUST call this first or the FootPedalListener thread will
        keep running and double-handle pedal input on the next editor.

        Idempotent — safe to call from cleanup() and then closeEvent().
        """
        if getattr(self, "_pedal", None) is not None:
            try:
                self._pedal.stop()
            except Exception:
                pass
            self._pedal = None

    def closeEvent(self, event) -> None:
        self.cleanup()
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

    # -- Click to seek / change speaker --------------------------------------

    def _on_text_click(self, event) -> None:
        QTextEdit.mouseReleaseEvent(self.text_edit, event)
        # Only intercept plain left-clicks. Anything with modifiers, or
        # right-clicks, or middle-clicks fall through to default behavior
        # (e.g. context menu, paste, native selection extend).
        if event.button() != Qt.MouseButton.LeftButton:
            return
        cursor = self.text_edit.cursorForPosition(event.pos())
        col = cursor.positionInBlock()
        block = cursor.block()
        block_text = block.text()
        parsed = parse_line(block_text)
        if not parsed:
            return
        start, end, _speaker, _lang, _text = parsed

        # Speaker click takes priority over timestamp click — the speaker
        # name sits *after* the timestamp, so the column ranges don't
        # overlap, but we check it first for clarity.
        sp_range = self._speaker_range_in_block(block_text)
        if sp_range and sp_range[0] <= col <= sp_range[1]:
            seg = self._segment_at_cursor(cursor)
            if seg is not None:
                global_pos = self.text_edit.viewport().mapToGlobal(event.pos())
                self._open_speaker_menu_for_segment(seg, global_pos)
            return

        # Timestamp click → seek (first ~25 chars covers `[HH:MM:SS -> HH:MM:SS]`)
        if col < 25:
            self.player.seek(int(start * 1000))
            if not self.player.is_playing:
                self.player.play()

    def _on_text_mouse_move(self, event) -> None:
        """Hover affordance: turn the cursor into a hand over speaker names
        so the click target is discoverable. Falls back to the standard
        I-beam everywhere else."""
        self._orig_mouse_move(event)
        cursor = self.text_edit.cursorForPosition(event.pos())
        col = cursor.positionInBlock()
        block_text = cursor.block().text()
        sp_range = self._speaker_range_in_block(block_text)
        if sp_range and sp_range[0] <= col <= sp_range[1]:
            self.text_edit.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.text_edit.viewport().setCursor(Qt.CursorShape.IBeamCursor)

    @staticmethod
    def _speaker_range_in_block(block_text: str):
        """Return ``(start_col, end_col)`` for the speaker portion of a
        rendered transcript line, or ``None`` if no speaker is present.

        Range is inclusive of leading whitespace right after the closing
        bracket, and stops at the start of any optional ``(XX)`` language
        tag so clicking the tag doesn't open the speaker menu. Mirrors
        the same 1..40 char heuristic that ``parse_line`` uses so we
        don't false-trigger on text lines that happen to contain a colon.
        """
        from transcript_format import LANG_TAG_RE

        ts_end = block_text.find("]")
        if ts_end < 0:
            return None
        colon_pos = block_text.find(":", ts_end + 1)
        if colon_pos < 0:
            return None
        raw = block_text[ts_end + 1:colon_pos]
        stripped = raw.strip()
        # Peel off trailing "(XX)" tag so the click range stops at the
        # end of the speaker name itself.
        tag_match = LANG_TAG_RE.search(stripped)
        if tag_match:
            stripped = stripped[: tag_match.start()].strip()
        if not (1 <= len(stripped) <= 40):
            return None
        # Find where the name ends inside the original (un-stripped) raw
        # substring so we return column positions relative to the block.
        name_end_in_raw = raw.rfind(stripped) + len(stripped)
        return (ts_end + 1, ts_end + 1 + name_end_in_raw)

    # -- Video rotation ------------------------------------------------------

    def _rotate_video(self, direction: str) -> None:
        """Rotate the video 90° in the given direction and log it."""
        if not hasattr(self, "_video_view"):
            return
        if direction == "cw":
            self._video_view.rotate_cw()
        else:
            self._video_view.rotate_ccw()
        deg = self._video_view.rotation_degrees
        self.doc.log("Video rotated", f"{deg}° (user adjusted)")

    def _zoom_video(self, action: str) -> None:
        """Zoom the video in, out, or reset."""
        if not hasattr(self, "_video_view"):
            return
        if action == "in":
            self._video_view.zoom_in()
        elif action == "out":
            self._video_view.zoom_out()
        else:
            self._video_view.zoom_reset()

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
            parsed = parse_line(block.text())
            if parsed:
                start, end, _, _, _ = parsed
                if start <= seconds <= end:
                    return i
                # Also track the closest preceding segment
                if start <= seconds:
                    best_idx = i
        return best_idx

    # -- Highlight current segment -------------------------------------------

    def _highlight_segment(self, idx: int) -> None:
        """Highlight the currently-playing segment using a single
        ExtraSelection that combines a full-width background bar with
        enlarged, brightened text.

        Uses ONE ExtraSelection (not two stacked layers) to avoid
        rendering issues where a character-range selection can mask the
        background of a full-width selection underneath on some PySide6
        builds. FullWidthSelection extends the background colour across
        the full editor width while the character formatting (font size,
        weight, foreground) applies only to the selected text range.

        Purely visual — does NOT modify the document, so it doesn't
        pollute the undo stack.
        """
        if 0 <= idx < self.text_edit.document().blockCount():
            block = self.text_edit.document().findBlockByNumber(idx)

            # Layer 1: full-width background bar (no text selection —
            # FullWidthSelection only works with a positioned cursor,
            # NOT a character-range selection).
            bg = QTextEdit.ExtraSelection()
            bg.cursor = QTextCursor(block)
            bg.format = QTextCharFormat()
            bg.format.setBackground(self._current_highlight_color())
            bg.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            self._segment_bg_selection = bg

            self._segment_text_selection = None

            # Auto-scroll to keep the playhead line visible — but only
            # if the user isn't actively editing, so we don't yank their
            # cursor mid-keystroke.
            if not self.text_edit.hasFocus():
                self._scroll_to_block(idx)
            # Kick off the flash animation
            self._start_highlight_flash()
        else:
            self._segment_bg_selection = None
            self._segment_text_selection = None

        self._refresh_extra_selections()

    # -- Animated segment highlight -----------------------------------------

    def _current_highlight_color(self) -> QColor:
        """Interpolate between the bright flash color and the steady
        ``SEGMENT_HIGHLIGHT`` based on the current intensity (0..1)."""
        steady = QColor(SEGMENT_HIGHLIGHT)
        # Flash color: vivid purple burst, clearly visible even at a glance.
        flash = QColor("#7040A0")
        t = max(0.0, min(1.0, self._highlight_intensity))
        return QColor(
            int(steady.red() + t * (flash.red() - steady.red())),
            int(steady.green() + t * (flash.green() - steady.green())),
            int(steady.blue() + t * (flash.blue() - steady.blue())),
        )

    def _get_highlight_intensity(self) -> float:
        return self._highlight_intensity

    def _set_highlight_intensity(self, value: float) -> None:
        self._highlight_intensity = value
        # Re-color the existing background selection without rebuilding it
        if self._segment_bg_selection is not None:
            self._segment_bg_selection.format.setBackground(self._current_highlight_color())
            self._refresh_extra_selections()

    highlight_intensity = Property(float, _get_highlight_intensity, _set_highlight_intensity)

    def _start_highlight_flash(self) -> None:
        """Animate the highlight from peak (1.0) down to steady (0.0)."""
        if not hasattr(self, "_highlight_anim"):
            self._highlight_anim = QPropertyAnimation(self, b"highlight_intensity", self)
            self._highlight_anim.setDuration(400)
            self._highlight_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._highlight_anim.stop()
        self._highlight_anim.setStartValue(1.0)
        self._highlight_anim.setEndValue(0.0)
        self._highlight_anim.start()

    def _scroll_to_block(self, block_number: int) -> None:
        """Scroll the viewport so the given block is visible, without
        moving the user's text cursor."""
        block = self.text_edit.document().findBlockByNumber(block_number)
        if not block.isValid():
            return
        layout = self.text_edit.document().documentLayout()
        rect = layout.blockBoundingRect(block)
        viewport_h = self.text_edit.viewport().height()
        scroll = self.text_edit.verticalScrollBar()
        block_top = rect.y()
        block_bottom = block_top + rect.height()
        if block_top < scroll.value() or block_bottom > scroll.value() + viewport_h:
            # Center the block in the viewport
            scroll.setValue(int(block_top - viewport_h / 2 + rect.height() / 2))

    def _refresh_extra_selections(self) -> None:
        """Compose all editor highlights into one ``setExtraSelections`` call.

        Z-order (lowest first):
          1. Per-segment flag tints (full-width row backgrounds)
          2. Currently-playing segment highlight
          3. Search match highlights
        """
        selections: list[QTextEdit.ExtraSelection] = []
        # 1. Flag highlights — one per flagged segment
        selections.extend(self._build_flag_selections())
        # 2. Currently-playing segment (background bar + enlarged text)
        if self._segment_bg_selection is not None:
            selections.append(self._segment_bg_selection)
        if self._segment_text_selection is not None:
            selections.append(self._segment_text_selection)
        # 3. Search matches
        if self._search_query and self._search_matches:
            all_match_fmt = QTextCharFormat()
            all_match_fmt.setBackground(QColor("#FFEB3B"))
            all_match_fmt.setForeground(QColor("#000000"))
            current_match_fmt = QTextCharFormat()
            current_match_fmt.setBackground(QColor("#FF9800"))
            current_match_fmt.setForeground(QColor("#000000"))
            for i, (start, end) in enumerate(self._search_matches):
                sel = QTextEdit.ExtraSelection()
                sel.cursor = QTextCursor(self.text_edit.document())
                sel.cursor.setPosition(start)
                sel.cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                sel.format = current_match_fmt if i == self._search_idx else all_match_fmt
                selections.append(sel)
        self.text_edit.setExtraSelections(selections)

    # -- Flags / bookmarks ---------------------------------------------------

    def _build_flag_selections(self) -> list:
        """Return one ExtraSelection per flagged segment, full-width tinted."""
        sels = []
        doc = self.text_edit.document()
        # Map segment timestamp -> block index by walking the rendered text
        seg_to_block: dict[tuple[float, float], int] = {}
        for i in range(doc.blockCount()):
            parsed = parse_line(doc.findBlockByNumber(i).text())
            if parsed:
                start, end, _, _, _ = parsed
                seg_to_block[(start, end)] = i
        for seg in self.doc.segments:
            if not seg.flag:
                continue
            block_idx = seg_to_block.get((seg.start, seg.end))
            if block_idx is None:
                continue
            display = FLAG_DISPLAY.get(seg.flag)
            if not display:
                continue
            _label, bg_hex, _accent = display
            block = doc.findBlockByNumber(block_idx)
            sel = QTextEdit.ExtraSelection()
            sel.cursor = QTextCursor(block)
            sel.format = QTextCharFormat()
            sel.format.setBackground(QColor(bg_hex))
            sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            sels.append(sel)
        return sels

    def _segment_at_cursor(self, cursor: QTextCursor):
        """Return the Segment object at the given cursor's block, or None.

        Also resolves translation continuation blocks: if the cursor is
        on an indented ``↳`` line, we walk back to the preceding main
        line so the right-click menu still targets the right segment.
        """
        block = cursor.block()
        plain = block.text()
        # Translation continuation? Walk back to the main line.
        if parse_translation(plain) is not None:
            prev = block.previous()
            while prev.isValid() and parse_translation(prev.text()) is not None:
                prev = prev.previous()
            if prev.isValid():
                plain = prev.text()
        parsed = parse_line(plain)
        if not parsed:
            return None
        start, end, _, _, _ = parsed
        for seg in self.doc.segments:
            if seg.start == start and seg.end == end:
                return seg
        return None

    def _on_text_context_menu(self, pos) -> None:
        """Right-click menu for flagging the segment under the cursor."""
        cursor = self.text_edit.cursorForPosition(pos)
        seg = self._segment_at_cursor(cursor)

        # Start with Qt's default menu (Cut/Copy/Paste/Undo etc.) so we
        # don't take features away from the user.
        menu = self.text_edit.createStandardContextMenu()

        if seg is not None:
            menu.addSeparator()
            # Speaker submenu — same content as the click-the-name menu,
            # but reachable via right-click for lines that don't have a
            # speaker yet (no clickable name to land on).
            speaker_menu = menu.addMenu(
                f"Set speaker  (current: {seg.speaker or '—'})"
            )
            self._populate_speaker_menu(speaker_menu, seg)

            # Language / translation submenu. We offer the common choices
            # inline and an "Other…" item for any ISO code Whisper
            # supports. Re-transcription runs the audio slice through
            # Whisper again with the chosen language forced — see
            # transcriber.SegmentRetranscribeWorker.
            current_lang = seg.language.upper() if seg.language else "EN"
            retrans_menu = menu.addMenu(
                f"Re-transcribe as  (current: {current_lang})"
            )
            for display, code in (("English", ""), ("Spanish", "es"), ("Other…", "__other__")):
                act = QAction(display, retrans_menu)
                act.triggered.connect(
                    lambda _=False, s=seg, c=code: self._retranscribe_segment(s, c)
                )
                retrans_menu.addAction(act)

            trans_label = (
                f"Edit translation ({len(seg.translation)} chars)..."
                if seg.translation else "Add translation..."
            )
            trans_act = QAction(trans_label, menu)
            trans_act.triggered.connect(lambda _=False, s=seg: self._edit_translation(s))
            menu.addAction(trans_act)

            if seg.language:
                clear_lang_act = QAction("Clear language tag (mark as default)", menu)
                clear_lang_act.triggered.connect(
                    lambda _=False, s=seg: self._set_language(s, "")
                )
                menu.addAction(clear_lang_act)

            menu.addSeparator()

            flag_menu = menu.addMenu("Flag segment as...")
            for kind in ("inaudible", "admission", "contradiction", "follow_up", "custom"):
                label, _bg, accent = FLAG_DISPLAY[kind]
                act = QAction(f"  ●  {label}", flag_menu)
                # Color the menu item dot — not strictly necessary but
                # gives a quick legend without an extra panel.
                act.setData(kind)
                act.triggered.connect(lambda _checked=False, s=seg, k=kind: self._set_flag(s, k))
                flag_menu.addAction(act)

            note_act = QAction(
                "Add/edit note..." if not seg.note else f"Edit note ({len(seg.note)} chars)...",
                menu,
            )
            note_act.triggered.connect(lambda _=False, s=seg: self._edit_note(s))
            menu.addAction(note_act)

            if seg.flag or seg.note:
                clear_act = QAction("Clear flag and note", menu)
                clear_act.triggered.connect(lambda _=False, s=seg: self._set_flag(s, "", clear_note=True))
                menu.addAction(clear_act)

        menu.exec(self.text_edit.viewport().mapToGlobal(pos))

    # -- Language / translation handlers ------------------------------------

    def _edit_translation(self, segment) -> None:
        """Prompt the user for the translation of a segment.

        We always sync from the editor first in case the user typed
        something in the translation line and hasn't tabbed away yet.
        """
        self._sync_text_to_model()
        text, ok = QInputDialog.getMultiLineText(
            self,
            "Translation",
            f"Translation for segment at {fmt_timestamp(segment.start)}"
            + (f" ({segment.language.upper()})" if segment.language else "")
            + ":",
            segment.translation,
        )
        if not ok:
            return
        segment.translation = text.strip()
        self._replace_block_for_segment(segment)
        self.doc.log(
            "Translation edited",
            f"@ {fmt_timestamp(segment.start)} ({len(segment.translation)} chars)",
        )

    def _set_language(self, segment, language: str) -> None:
        """Update a segment's language tag without re-transcribing."""
        prev = segment.language or "(default)"
        new = language or "(default)"
        if prev == new:
            return
        segment.language = language
        self._replace_block_for_segment(segment)
        self.doc.log(
            "Language tag changed",
            f"@ {fmt_timestamp(segment.start)}: {prev} → {new}",
        )

    def _retranscribe_segment(self, segment, language_code: str) -> None:
        """Re-transcribe *segment*'s audio slice with the given language
        forced. ``language_code`` is a lowercase ISO code, or "" for the
        document's default language, or "__other__" to prompt.
        """
        if language_code == "__other__":
            code, ok = QInputDialog.getText(
                self, "Re-transcribe segment",
                "ISO language code (e.g. fr, de, zh):",
                text="",
            )
            if not ok:
                return
            language_code = code.strip().lower()
            if not language_code:
                return

        if not self.doc.audio_path or not Path(self.doc.audio_path).exists():
            return  # source audio is missing; nothing to re-run

        # Flush editor text so segment.text is current before we overwrite
        # it with the re-transcription result.
        self._sync_text_to_model()

        from transcriber import SegmentRetranscribeWorker
        worker = SegmentRetranscribeWorker(
            audio_path=str(self.doc.audio_path),
            start=segment.start,
            end=segment.end,
            language=language_code or "en",  # empty → default (English)
            model_size=self.doc.model_size,
            parent=self,
        )
        # Keep a reference so the QThread isn't GC'd mid-run
        self._retrans_worker = worker
        worker.finished_text.connect(
            lambda new_text, s=segment, lc=language_code: self._on_retranscribe_done(
                s, lc, new_text
            )
        )
        worker.failed.connect(self._on_retranscribe_failed)
        worker.start()

    def _on_retranscribe_done(self, segment, language_code: str, new_text: str) -> None:
        prev_text = segment.text
        prev_lang = segment.language or "(default)"
        segment.text = new_text.strip() or segment.text
        segment.language = language_code  # "" means default
        self._replace_block_for_segment(segment)
        self.doc.log(
            "Segment re-transcribed",
            f"@ {fmt_timestamp(segment.start)}: lang {prev_lang} → "
            f"{segment.language or '(default)'}; "
            f"{len(prev_text)} → {len(segment.text)} chars",
        )

    def _on_retranscribe_failed(self, msg: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(self, "Re-transcription failed", msg)

    def _set_flag(self, segment, kind: str, clear_note: bool = False) -> None:
        """Set or clear a segment's flag, log it, and refresh visuals."""
        prev = segment.flag or "(none)"
        segment.flag = kind
        if clear_note:
            segment.note = ""
        new = kind or "(cleared)"
        # Log to audit trail at document level
        self.doc.log(
            "Flag changed",
            f"@ {fmt_timestamp(segment.start)}: {prev} → {new}",
        )
        self._refresh_extra_selections()
        self._refresh_flag_button()

    def _edit_note(self, segment) -> None:
        """Prompt the user for a free-form note attached to a segment."""
        text, ok = QInputDialog.getMultiLineText(
            self, "Segment note",
            f"Note for segment at {fmt_timestamp(segment.start)}:",
            segment.note,
        )
        if not ok:
            return
        segment.note = text.strip()
        self.doc.log(
            "Note edited",
            f"@ {fmt_timestamp(segment.start)} ({len(segment.note)} chars)",
        )
        self._refresh_flag_button()

    def _refresh_flag_button(self) -> None:
        """Update the 'Flags ▾' button label with the current count."""
        if not hasattr(self, "btn_flags"):
            return
        count = sum(1 for s in self.doc.segments if s.flag)
        self.btn_flags.setText(f"Flags  ({count})  ▾" if count else "Flags  ▾")
        self.btn_flags.setEnabled(count > 0 or True)  # always enabled (menu shows hint)

    def _open_flags_menu(self) -> None:
        """Build & show the Flags menu — one entry per flagged segment,
        sorted by timestamp; selecting one jumps the cursor + playback."""
        menu = QMenu(self.btn_flags)
        flagged = [s for s in self.doc.segments if s.flag]
        flagged.sort(key=lambda s: s.start)

        if not flagged:
            act = QAction("(no flagged segments — right-click a line to flag it)", menu)
            act.setEnabled(False)
            menu.addAction(act)
        else:
            for seg in flagged:
                label, _bg, _accent = FLAG_DISPLAY.get(seg.flag, ("?", "", ""))
                snippet = (seg.text[:50] + "…") if len(seg.text) > 50 else seg.text
                title = f"●  [{fmt_timestamp(seg.start)}]  {label}: {snippet}"
                if seg.note:
                    title += f"   📝"
                act = QAction(title, menu)
                act.setToolTip(seg.note if seg.note else "")
                act.triggered.connect(lambda _=False, s=seg: self._jump_to_segment(s))
                menu.addAction(act)

        menu.exec(self.btn_flags.mapToGlobal(self.btn_flags.rect().bottomLeft()))

    def _jump_to_segment(self, segment) -> None:
        """Move cursor to the segment's line and seek playback there."""
        doc = self.text_edit.document()
        for i in range(doc.blockCount()):
            parsed = parse_line(doc.findBlockByNumber(i).text())
            if parsed and parsed[0] == segment.start and parsed[1] == segment.end:
                cursor = QTextCursor(doc.findBlockByNumber(i))
                self.text_edit.setTextCursor(cursor)
                self.text_edit.ensureCursorVisible()
                self.player.seek(int(segment.start * 1000))
                break

    # -- Per-line speaker change --------------------------------------------

    # Quick-add labels offered in the per-line menu when the user wants a
    # standard role. We only offer one not already in use; "Officer 1"
    # auto-bumps to "Officer 2" if Officer 1 already exists.
    _QUICK_ADD_ROLES = ("Officer", "Witness", "Suspect", "Detective")

    def _existing_speakers_with_counts(self) -> list[tuple[str, int]]:
        """Return [(speaker, count), ...] sorted by count desc, name asc.
        Empty speakers are excluded."""
        counts: dict[str, int] = {}
        for s in self.doc.segments:
            if s.speaker:
                counts[s.speaker] = counts.get(s.speaker, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))

    def _next_role_label(self, role: str) -> str:
        """Return ``role`` if not already in use, else ``role 2``, ``role 3``…"""
        existing = {s.speaker for s in self.doc.segments if s.speaker}
        if role not in existing:
            return role
        i = 2
        while f"{role} {i}" in existing:
            i += 1
        return f"{role} {i}"

    def _open_speaker_menu_for_segment(self, segment, global_pos) -> None:
        """Pop the per-line speaker chooser at *global_pos*."""
        menu = QMenu(self)
        self._populate_speaker_menu(menu, segment)
        menu.exec(global_pos)

    def _populate_speaker_menu(self, menu: QMenu, segment) -> None:
        """Fill *menu* with: existing speakers (sorted by frequency, current
        one checked) → quick-add roles → New… → Clear. Used by both the
        click-the-name popup and the right-click submenu."""
        existing = self._existing_speakers_with_counts()
        current = segment.speaker

        if existing:
            for name, count in existing:
                act = QAction(f"{name}  ({count})", menu)
                act.setCheckable(True)
                act.setChecked(name == current)
                act.triggered.connect(
                    lambda _checked=False, s=segment, n=name: self._set_segment_speaker(s, n)
                )
                menu.addAction(act)
            menu.addSeparator()

        # Quick-add roles (skip ones already in use to avoid duplicate clutter)
        existing_names = {n for n, _ in existing}
        any_quick = False
        for role in self._QUICK_ADD_ROLES:
            label = self._next_role_label(role)
            if label in existing_names:
                continue
            any_quick = True
            act = QAction(f"+ {label}", menu)
            act.triggered.connect(
                lambda _checked=False, s=segment, n=label: self._set_segment_speaker(s, n)
            )
            menu.addAction(act)
        if any_quick:
            menu.addSeparator()

        new_act = QAction("New speaker name…", menu)
        new_act.triggered.connect(lambda _=False, s=segment: self._prompt_new_speaker(s))
        menu.addAction(new_act)

        if current:
            clear_act = QAction("Clear speaker", menu)
            clear_act.triggered.connect(lambda _=False, s=segment: self._set_segment_speaker(s, ""))
            menu.addAction(clear_act)

    def _prompt_new_speaker(self, segment) -> None:
        """Prompt for a new speaker name and apply it to a single segment."""
        text, ok = QInputDialog.getText(
            self, "New speaker", "Speaker name:", text=segment.speaker or "",
        )
        if not ok:
            return
        name = text.strip().rstrip(":")  # colon would break parse_line
        if not name:
            return
        self._set_segment_speaker(segment, name)

    def _set_segment_speaker(self, segment, new_speaker: str) -> None:
        """Update one segment's speaker, re-render only that line, log it."""
        prev = segment.speaker or "(none)"
        new = new_speaker or "(cleared)"
        if prev == new:
            return  # no-op; don't pollute the audit log
        segment.speaker = new_speaker
        self._replace_block_for_segment(segment)
        self.doc.log(
            "Speaker changed",
            f"@ {fmt_timestamp(segment.start)}: {prev} → {new}",
        )

    def _replace_block_for_segment(self, segment) -> None:
        """Rewrite the block(s) whose timestamps match *segment* with
        fresh format_segment() output. Handles segments that span two
        blocks (main + translation continuation) by replacing the range
        from the start of the main block through the end of the
        continuation block, if present. Preserves cursor position and
        undo for unrelated blocks.
        """
        doc = self.text_edit.document()
        for i in range(doc.blockCount()):
            block = doc.findBlockByNumber(i)
            parsed = parse_line(block.text())
            if not parsed:
                continue
            if parsed[0] == segment.start and parsed[1] == segment.end:
                new_text = format_segment(
                    segment.start, segment.end, segment.text, segment.speaker,
                    language=segment.language, translation=segment.translation,
                )
                # Determine the ending block — if the next block is this
                # segment's existing translation continuation, include it
                # in the replacement so we don't leave a stale line behind.
                end_block = block
                next_block = block.next()
                if next_block.isValid() and parse_translation(next_block.text()) is not None:
                    end_block = next_block

                # Suppress sync — we already updated the model directly.
                # Otherwise textChanged would round-trip and rebuild.
                self._block_sync = True
                cursor = QTextCursor(block)
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                end_cursor = QTextCursor(end_block)
                end_cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                cursor.setPosition(
                    end_cursor.position(), QTextCursor.MoveMode.KeepAnchor,
                )
                cursor.insertText(new_text)
                self._block_sync = False
                # Search highlights might point at moved character offsets
                # within this block — refresh them defensively.
                self._refresh_extra_selections()
                if self._search_query:
                    self._find_all_matches()
                    self._apply_search_highlights()
                    self._update_search_ui()
                return

    # -- Speaker management --------------------------------------------------

    def _open_speaker_manager(self) -> None:
        """Open the speaker rename/merge dialog. On Apply, re-render the
        transcript so the new labels show up immediately."""
        # Make sure model reflects current editor state before we operate
        self._sync_text_to_model()
        dlg = SpeakerManagerDialog(self.doc.segments, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            mapping = dlg.rename_map()
            if mapping:
                self.doc.log(
                    "Speakers renamed",
                    "; ".join(f"{k} → {v}" for k, v in mapping.items()),
                )
                self._render_transcript()
