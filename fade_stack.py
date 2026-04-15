"""QStackedWidget that cross-fades between pages.

Drop-in replacement for QStackedWidget. Calling
``setCurrentIndex``/``setCurrentWidget`` triggers a short opacity fade on
the outgoing page, swap, then a fade-in on the incoming page. Set
``transition_ms`` to 0 to behave like a vanilla stack (useful for tests).
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QStackedWidget


class FadeStackedWidget(QStackedWidget):
    DEFAULT_DURATION_MS = 250

    def __init__(self, parent=None):
        super().__init__(parent)
        self.transition_ms = self.DEFAULT_DURATION_MS
        # Track the active animation so back-to-back transitions don't
        # leave half-faded ghosts on screen.
        self._anim: QPropertyAnimation | None = None
        self._effect: QGraphicsOpacityEffect | None = None

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802
        if index == self.currentIndex() or self.transition_ms <= 0:
            super().setCurrentIndex(index)
            return
        target = self.widget(index)
        if target is None:
            super().setCurrentIndex(index)
            return
        self._fade_to(target, lambda: super(FadeStackedWidget, self).setCurrentIndex(index))

    def setCurrentWidget(self, widget) -> None:  # noqa: N802
        if widget is self.currentWidget() or self.transition_ms <= 0:
            super().setCurrentWidget(widget)
            return
        self._fade_to(widget, lambda: super(FadeStackedWidget, self).setCurrentWidget(widget))

    # -- internals -----------------------------------------------------------

    def _fade_to(self, target_widget, swap_callback) -> None:
        """Half-fade the current page out, swap to target, then fade in."""
        # Stop any in-flight animation first
        if self._anim is not None:
            self._anim.stop()
        outgoing = self.currentWidget()
        if outgoing is None:
            swap_callback()
            return

        # Phase 1: fade outgoing to 0
        out_effect = QGraphicsOpacityEffect(outgoing)
        out_effect.setOpacity(1.0)
        outgoing.setGraphicsEffect(out_effect)
        out_anim = QPropertyAnimation(out_effect, b"opacity", self)
        out_anim.setDuration(self.transition_ms // 2)
        out_anim.setStartValue(1.0)
        out_anim.setEndValue(0.0)
        out_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        def _after_out():
            outgoing.setGraphicsEffect(None)  # cleanup
            swap_callback()
            # Phase 2: fade incoming back in
            in_effect = QGraphicsOpacityEffect(target_widget)
            in_effect.setOpacity(0.0)
            target_widget.setGraphicsEffect(in_effect)
            in_anim = QPropertyAnimation(in_effect, b"opacity", self)
            in_anim.setDuration(self.transition_ms // 2)
            in_anim.setStartValue(0.0)
            in_anim.setEndValue(1.0)
            in_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
            in_anim.finished.connect(lambda: target_widget.setGraphicsEffect(None))
            self._anim = in_anim
            self._effect = in_effect
            in_anim.start()

        out_anim.finished.connect(_after_out)
        self._anim = out_anim
        self._effect = out_effect
        out_anim.start()
