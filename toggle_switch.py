"""Custom iOS-style slider toggle switch widget."""
from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QAbstractButton


class ToggleSwitch(QAbstractButton):
    """A horizontal slide switch: gray (off) → green (on) with an animated thumb.

    Clicking, or dragging the thumb, flips the state. Emits `toggled(bool)`
    like QCheckBox, so it's a drop-in replacement for signal wiring.
    """

    # Colours
    TRACK_OFF = QColor("#3A3A55")
    TRACK_ON = QColor("#00C853")        # material green
    THUMB = QColor("#F5F5F5")
    BORDER_OFF = QColor("#55556E")
    BORDER_ON = QColor("#00E676")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._thumb_pos = 0.0  # 0.0 = left (off), 1.0 = right (on)
        self._anim = QPropertyAnimation(self, b"thumb_pos", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:
        return QSize(40, 20)

    # Animated thumb position property -------------------------------------

    def _get_thumb_pos(self) -> float:
        return self._thumb_pos

    def _set_thumb_pos(self, value: float) -> None:
        self._thumb_pos = value
        self.update()

    thumb_pos = Property(float, _get_thumb_pos, _set_thumb_pos)

    def _animate(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._thumb_pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def setChecked(self, checked: bool) -> None:
        super().setChecked(checked)
        # If no animation has run yet, snap to the final position
        if not self._anim.state() == QPropertyAnimation.State.Running:
            self._thumb_pos = 1.0 if checked else 0.0
            self.update()

    # Paint ----------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        radius = h / 2

        # Track
        track_rect = QRectF(0, 0, w, h)
        path = QPainterPath()
        path.addRoundedRect(track_rect, radius, radius)

        # Interpolate track colour based on thumb position for smooth fade
        t = self._thumb_pos
        track_color = self._lerp_color(self.TRACK_OFF, self.TRACK_ON, t)
        border_color = self._lerp_color(self.BORDER_OFF, self.BORDER_ON, t)

        painter.fillPath(path, track_color)
        painter.setPen(border_color)
        painter.drawPath(path)

        # Thumb
        thumb_margin = 2
        thumb_diameter = h - 2 * thumb_margin
        thumb_x_range = w - thumb_diameter - 2 * thumb_margin
        thumb_x = thumb_margin + thumb_x_range * t
        thumb_rect = QRectF(thumb_x, thumb_margin, thumb_diameter, thumb_diameter)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.THUMB)
        painter.drawEllipse(thumb_rect)

    @staticmethod
    def _lerp_color(a: QColor, b: QColor, t: float) -> QColor:
        t = max(0.0, min(1.0, t))
        return QColor(
            int(a.red() + t * (b.red() - a.red())),
            int(a.green() + t * (b.green() - a.green())),
            int(a.blue() + t * (b.blue() - a.blue())),
        )
