"""Background worker that runs faster-whisper transcription + pyannote diarization."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from models import Segment


def _load_hf_token() -> str:
    """Read HF_TOKEN from .env file next to this script."""
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("HF_TOKEN="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("HF_TOKEN", "")


def _assign_speakers(segments: list[Segment], diarization) -> None:
    """Assign speaker labels by finding the dominant speaker for each segment."""
    speaker_map: dict[str, str] = {}  # pyannote label -> friendly name
    counter = 0

    for seg in segments:
        mid = (seg.start + seg.end) / 2.0
        best_speaker = None
        best_overlap = 0.0

        for turn, _, speaker in diarization.itertracks(yield_label=True):
            # Calculate overlap between segment and speaker turn
            overlap_start = max(seg.start, turn.start)
            overlap_end = min(seg.end, turn.end)
            overlap = max(0.0, overlap_end - overlap_start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = speaker

        if best_speaker:
            if best_speaker not in speaker_map:
                counter += 1
                speaker_map[best_speaker] = f"Speaker {counter}"
            seg.speaker = speaker_map[best_speaker]


class TranscriberWorker(QThread):
    """Transcribes an audio file, then optionally diarizes speakers.

    Signals
    -------
    progress(int, str)  - (percentage 0-100, status message)
    finished(list)      - list[Segment] on success
    error(str)          - error description
    """

    progress = Signal(int, str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(
        self,
        audio_path: str,
        model_size: str = "base",
        language: str | None = None,
        enable_diarization: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.audio_path = audio_path
        self.model_size = model_size
        self.language = language
        self.enable_diarization = enable_diarization

    def run(self) -> None:
        try:
            segments = self._transcribe()
            if self.enable_diarization:
                self._diarize(segments)
            self.progress.emit(100, "Done.")
            self.finished.emit(segments)
        except Exception as exc:
            self.error.emit(str(exc))

    def _transcribe(self) -> list[Segment]:
        from faster_whisper import WhisperModel

        self.progress.emit(0, f"Loading transcription model '{self.model_size}'...")
        model = WhisperModel(self.model_size, device="auto", compute_type="auto")

        self.progress.emit(5, "Transcribing...")
        kwargs: dict = {"beam_size": 5, "vad_filter": True}
        if self.language:
            kwargs["language"] = self.language

        segments_gen, info = model.transcribe(self.audio_path, **kwargs)
        duration = info.duration or 1.0

        result: list[Segment] = []
        for seg in segments_gen:
            result.append(Segment(start=seg.start, end=seg.end, text=seg.text.strip()))
            pct = min(69, int(seg.end / duration * 70))  # 0-70% for transcription
            self.progress.emit(pct, f"Transcribing... {pct}%")

        return result

    def _diarize(self, segments: list[Segment]) -> None:
        token = _load_hf_token()
        if not token:
            self.progress.emit(75, "Skipping diarization (no HF_TOKEN in .env)")
            return

        self.progress.emit(72, "Loading speaker detection model...")
        try:
            from pyannote.audio import Pipeline

            pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=token,
            )
        except Exception as exc:
            self.progress.emit(75, f"Diarization model failed: {exc}")
            return

        self.progress.emit(80, "Detecting speakers...")
        diarization = pipeline(self.audio_path)

        self.progress.emit(95, "Assigning speaker labels...")
        _assign_speakers(segments, diarization)
