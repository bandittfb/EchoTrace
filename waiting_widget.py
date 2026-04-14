"""Animated waiting screen shown during transcription."""
from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QSize,
    QTimer,
    Qt,
    Property,
)
from PySide6.QtGui import QPixmap
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


class PulsingLogo(QLabel):
    """Logo that gently pulses (breathes) via opacity."""

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self.setPixmap(pixmap)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity_effect)

        self._anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._anim.setDuration(PULSE_DURATION_MS)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.45)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._anim.setLoopCount(-1)  # loop forever

    def start(self):
        self._anim.start()

    def stop(self):
        self._anim.stop()
        self._opacity_effect.setOpacity(1.0)


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

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFixedHeight(10)
        self._progress.setTextVisible(False)
        layout.addWidget(self._progress)

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
        self._progress.setValue(pct)
        self._status.setText(status)
        if segment_count > 0:
            self._segments_label.setText(f"{segment_count} segments transcribed...")
        if pct < 70:
            self._title.setText("Transcribing audio...")
        elif pct < 95:
            self._title.setText("Detecting speakers...")
        else:
            self._title.setText("Almost done...")
