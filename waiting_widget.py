"""Animated waiting screen shown during transcription."""
from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    QSize,
    QTimer,
    Qt,
    Property,
)
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from fun_facts import get_shuffled_content
from theme import ACCENT, BG_PANEL, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TIMESTAMP


CAROUSEL_INTERVAL_MS = 10_000  # rotate content every 10s
PULSE_DURATION_MS = 2000       # logo breath cycle


class PulsingLogo(QWidget):
    """Logo that gently breathes — combined opacity + subtle scale.

    Custom paint instead of QLabel + QGraphicsOpacityEffect so we can
    apply both a scale transform and an opacity multiplier in one go.
    The motion is intentionally restrained (3% scale swing) to read
    "premium / alive" rather than "loading.gif".
    """

    SCALE_MIN = 0.97
    SCALE_MAX = 1.03

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        self._opacity = 1.0
        self._scale = 1.0
        # Reserve enough space for the largest scaled size so the layout
        # doesn't twitch when the scale animates upward.
        max_w = int(pixmap.width() * self.SCALE_MAX)
        max_h = int(pixmap.height() * self.SCALE_MAX)
        self.setMinimumSize(max_w, max_h)

        # Two synchronized animations — opacity dips slightly while scale
        # peaks, like a slow inhale/exhale.
        self._opacity_anim = QPropertyAnimation(self, b"pulse_opacity", self)
        self._opacity_anim.setDuration(PULSE_DURATION_MS)
        self._opacity_anim.setStartValue(1.0)
        self._opacity_anim.setEndValue(0.55)
        self._opacity_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._opacity_anim.setLoopCount(-1)

        self._scale_anim = QPropertyAnimation(self, b"pulse_scale", self)
        self._scale_anim.setDuration(PULSE_DURATION_MS)
        self._scale_anim.setStartValue(self.SCALE_MIN)
        self._scale_anim.setEndValue(self.SCALE_MAX)
        self._scale_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._scale_anim.setLoopCount(-1)

    # -- animated properties (both call update() to repaint) ----------------

    def _get_opacity(self) -> float:
        return self._opacity

    def _set_opacity(self, value: float) -> None:
        self._opacity = value
        self.update()

    pulse_opacity = Property(float, _get_opacity, _set_opacity)

    def _get_scale(self) -> float:
        return self._scale

    def _set_scale(self, value: float) -> None:
        self._scale = value
        self.update()

    pulse_scale = Property(float, _get_scale, _set_scale)

    def start(self):
        self._opacity_anim.start()
        self._scale_anim.start()

    def stop(self):
        self._opacity_anim.stop()
        self._scale_anim.stop()
        self._opacity = 1.0
        self._scale = 1.0
        self.update()

    def paintEvent(self, event):
        if self._pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        painter.setOpacity(self._opacity)
        # Centered scale — translate to center, scale, then draw the
        # pixmap offset by half its (un-scaled) size.
        painter.translate(self.width() / 2, self.height() / 2)
        painter.scale(self._scale, self._scale)
        target = QRectF(
            -self._pixmap.width() / 2, -self._pixmap.height() / 2,
            self._pixmap.width(), self._pixmap.height(),
        )
        painter.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))


class CarouselLabel(QWidget):
    """Text area that fades between content items."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = get_shuffled_content()
        self._index = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._category_label = QLabel()
        self._category_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._category_label.setStyleSheet(
            f"font-size: 10px; font-weight: bold; color: {ACCENT}; "
            f"text-transform: uppercase; letter-spacing: 2px;"
        )
        layout.addWidget(self._category_label)

        self._text_label = QLabel()
        self._text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._text_label.setWordWrap(True)
        self._text_label.setStyleSheet(
            f"font-size: 13px; color: {TEXT_PRIMARY}; padding: 4px 20px; line-height: 1.4;"
        )
        self._text_label.setMinimumHeight(60)
        layout.addWidget(self._text_label)

        # Fade effect on text
        self._fade_effect = QGraphicsOpacityEffect(self._text_label)
        self._fade_effect.setOpacity(1.0)
        self._text_label.setGraphicsEffect(self._fade_effect)

        self._fade_out = QPropertyAnimation(self._fade_effect, b"opacity", self)
        self._fade_out.setDuration(500)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._fade_out.finished.connect(self._swap_and_fade_in)

        self._fade_in = QPropertyAnimation(self._fade_effect, b"opacity", self)
        self._fade_in.setDuration(500)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.Type.InOutQuad)

        # Timer
        self._timer = QTimer(self)
        self._timer.setInterval(CAROUSEL_INTERVAL_MS)
        self._timer.timeout.connect(self._next)

        # Show first item immediately
        self._show_current()

    def start(self):
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def _next(self):
        self._fade_out.start()

    def _swap_and_fade_in(self):
        self._index = (self._index + 1) % len(self._items)
        self._show_current()
        self._fade_in.start()

    def _show_current(self):
        category, text = self._items[self._index]
        labels = {"fact": "DID YOU KNOW?", "tip": "ECHOTRACE TIP", "quote": "INVESTIGATOR WISDOM"}
        self._category_label.setText(labels.get(category, ""))
        self._text_label.setText(text)


class WaitingWidget(QWidget):
    """Full waiting screen: pulsing logo + progress + segment counter + carousel."""

    def __init__(self, logo_pixmap: QPixmap | None = None, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 20, 40, 20)
        layout.setSpacing(12)

        layout.addStretch(1)

        # Pulsing logo
        if logo_pixmap and not logo_pixmap.isNull():
            self._logo = PulsingLogo(logo_pixmap, self)
            layout.addWidget(self._logo, 0, Qt.AlignmentFlag.AlignCenter)
            layout.addSpacing(8)
        else:
            self._logo = None

        # "Analyzing audio..." title
        self._title = QLabel("Analyzing audio...")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {TEXT_PRIMARY};")
        layout.addWidget(self._title)

        # Status text (e.g. "Loading model..." / "Transcribing...")
        self._status = QLabel("")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet(f"font-size: 12px; color: {TEXT_SECONDARY};")
        layout.addWidget(self._status)

        # Progress bar — animated rather than snapping to each new value
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFixedHeight(10)
        self._progress.setTextVisible(False)
        layout.addWidget(self._progress)

        self._progress_anim = QPropertyAnimation(self._progress, b"value", self)
        self._progress_anim.setDuration(280)
        self._progress_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Segment counter
        self._segments_label = QLabel("")
        self._segments_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._segments_label.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {TEXT_TIMESTAMP}; "
            f"font-family: Consolas;"
        )
        layout.addWidget(self._segments_label)

        layout.addSpacing(16)

        # Divider
        div = QWidget()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background-color: #2A2A4A;")
        layout.addWidget(div)

        layout.addSpacing(8)

        # Carousel
        self._carousel = CarouselLabel(self)
        layout.addWidget(self._carousel)

        layout.addStretch(1)

    def start(self):
        if self._logo:
            self._logo.start()
        self._carousel.start()
        self._segments_label.setText("")

    def stop(self):
        if self._logo:
            self._logo.stop()
        self._carousel.stop()

    def update_progress(self, pct: int, status: str, segment_count: int = 0):
        # Animate to the new value rather than snapping. Restart from the
        # *displayed* value, not the previously-targeted one, so back-to-
        # back rapid updates still feel smooth.
        self._progress_anim.stop()
        self._progress_anim.setStartValue(self._progress.value())
        self._progress_anim.setEndValue(pct)
        self._progress_anim.start()

        self._status.setText(status)
        if segment_count > 0:
            # Stronger wording — reads as accomplishment, not activity
            self._segments_label.setText(
                f"{segment_count} transcript segments ready for review"
            )
        if pct < 70:
            self._title.setText("Transcribing audio...")
        elif pct < 95:
            self._title.setText("Detecting speakers...")
        else:
            self._title.setText("Almost done...")
