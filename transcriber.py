"""Background worker that runs faster-whisper transcription + pyannote diarization."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from models import Segment


def _find_ffmpeg() -> str:
    """Locate ffmpeg executable, checking PATH and common install locations."""
    import shutil
    import glob
    path = shutil.which("ffmpeg")
    if path:
        return path
    # WinGet install location
    candidates = glob.glob(
        os.path.expanduser("~/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg-*/bin/ffmpeg.exe")
    )
    if candidates:
        return candidates[0]
    # Common manual installs
    for p in [r"C:\ffmpeg\bin\ffmpeg.exe", r"C:\Program Files\FFmpeg\bin\ffmpeg.exe"]:
        if os.path.isfile(p):
            return p
    raise FileNotFoundError("ffmpeg not found. Install it with: winget install ffmpeg")


def _load_audio_for_pyannote(audio_path: str) -> dict:
    """Load audio as a waveform dict for pyannote, bypassing broken torchcodec.

    Uses ffmpeg to convert to 16kHz mono WAV, then reads raw PCM with scipy.
    """
    import subprocess
    import tempfile
    import torch
    import numpy as np
    from scipy.io import wavfile

    ffmpeg = _find_ffmpeg()

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        subprocess.run(
            [
                ffmpeg, "-y", "-i", audio_path,
                "-ac", "1",           # mono
                "-ar", "16000",       # 16kHz (pyannote default)
                "-sample_fmt", "s16", # 16-bit PCM
                "-loglevel", "error",
                tmp_path,
            ],
            check=True,
            capture_output=True,
        )
        sample_rate, data = wavfile.read(tmp_path)
        # Convert int16 to float32 in [-1, 1]
        waveform = torch.from_numpy(data.astype(np.float32) / 32768.0).unsqueeze(0)
        return {"waveform": waveform, "sample_rate": sample_rate}
    finally:
        import os
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


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

    # pyannote v4 returns DiarizeOutput; get the Annotation from it
    if hasattr(diarization, "speaker_diarization"):
        annotation = diarization.speaker_diarization
    else:
        annotation = diarization  # fallback for older versions

    for seg in segments:
        mid = (seg.start + seg.end) / 2.0
        best_speaker = None
        best_overlap = 0.0

        for turn, _, speaker in annotation.itertracks(yield_label=True):
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
            import warnings
            import os
            # Suppress torchcodec warnings that crash on Windows
            os.environ["TORCHCODEC_DISABLE_LOAD"] = "1"
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=".*torchcodec.*")
                warnings.filterwarnings("ignore", message=".*libtorchcodec.*")
                warnings.filterwarnings("ignore", message=".*AudioDecoder.*")
                from pyannote.audio import Pipeline

            pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                token=token,
            )
        except Exception as exc:
            self.progress.emit(75, f"Diarization model failed: {exc}")
            return

        self.progress.emit(80, "Detecting speakers...")
        try:
            audio_input = _load_audio_for_pyannote(self.audio_path)
            diarization = pipeline(audio_input)
        except Exception as exc:
            self.progress.emit(90, f"Speaker detection failed: {exc}")
            return

        self.progress.emit(95, "Assigning speaker labels...")
        _assign_speakers(segments, diarization)
