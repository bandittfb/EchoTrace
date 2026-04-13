"""Thin wrapper around QMediaPlayer for audio playback with variable speed."""
from __future__ import annotations

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer


class AudioPlayer(QObject):
    """High-level audio player with play/pause/seek/speed controls."""

    position_changed = Signal(int)   # milliseconds
    duration_changed = Signal(int)   # milliseconds
    state_changed = Signal(str)      # "playing" | "paused" | "stopped"

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_output)

        self._player.positionChanged.connect(self.position_changed.emit)
        self._player.durationChanged.connect(self.duration_changed.emit)
        self._player.playbackStateChanged.connect(self._on_state)

        self._audio_output.setVolume(0.8)

    # -- public API ----------------------------------------------------------

    def load(self, path: str) -> None:
        self._player.setSource(QUrl.fromLocalFile(path))

    def play(self) -> None:
        self._player.play()

    def pause(self) -> None:
        self._player.pause()

    def toggle(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.pause()
        else:
            self.play()

    def seek(self, ms: int) -> None:
        self._player.setPosition(max(0, ms))

    def rewind(self, ms: int = 5000) -> None:
        self.seek(self._player.position() - ms)

    def forward(self, ms: int = 5000) -> None:
        self.seek(self._player.position() + ms)

    def set_speed(self, rate: float) -> None:
        self._player.setPlaybackRate(rate)

    def set_volume(self, vol: float) -> None:
        self._audio_output.setVolume(max(0.0, min(1.0, vol)))

    @property
    def position_ms(self) -> int:
        return self._player.position()

    @property
    def duration_ms(self) -> int:
        return self._player.duration()

    @property
    def is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    @property
    def speed(self) -> float:
        return self._player.playbackRate()

    # -- internal ------------------------------------------------------------

    @Slot(QMediaPlayer.PlaybackState)
    def _on_state(self, state: QMediaPlayer.PlaybackState) -> None:
        names = {
            QMediaPlayer.PlaybackState.PlayingState: "playing",
            QMediaPlayer.PlaybackState.PausedState: "paused",
            QMediaPlayer.PlaybackState.StoppedState: "stopped",
        }
        self.state_changed.emit(names.get(state, "stopped"))
