"""Background worker that runs faster-whisper transcription + pyannote diarization.

The language parameter controls how Whisper is invoked:

* ``"en"`` / ``"es"`` / any ISO code — force that language for the whole
  file. Fastest and most accurate when you know the language up front.
* ``None`` — let Whisper detect the language once at the start. Classic
  Whisper behaviour; prone to mis-detection on short or noisy audio.
* ``"multi"`` — per-segment language detection. First transcribes with
  the primary (default) language forced, then on the second pass checks
  each segment's audio against Whisper's language detector; segments
  that came back as a different language get re-transcribed individually
  with that language forced. This is the mode that produces faithful
  mixed-language transcripts (e.g. an English-speaking officer and a
  Spanish-speaking witness in the same recording).
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from models import Segment

# Document-level default language. Segments whose language matches this
# render in the editor WITHOUT a "(XX)" tag — it's the baseline everyone
# expects. Kept as a module constant so it's trivial to change later if
# we ever expose "default language" as a per-project setting.
DEFAULT_LANGUAGE = "en"


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
        # Populated by _transcribe(); main thread reads these in _on_finished()
        self.detected_language: str = ""
        self.detected_language_probability: float = 0.0

    def run(self) -> None:
        try:
            if self.language == "multi":
                segments = self._transcribe_multilingual()
            else:
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

        # Capture language detection results so the main thread can store
        # them on the TranscriptDocument (used by exporters and the editor).
        self.detected_language = getattr(info, "language", "") or ""
        self.detected_language_probability = float(
            getattr(info, "language_probability", 0.0) or 0.0
        )

        # Tag segments whose language differs from the document default —
        # that way, if the user picked "Spanish" up front, every segment
        # renders with an "(ES)" tag, and the exports reflect that too.
        tag = (
            self.detected_language if self.detected_language
            and self.detected_language != DEFAULT_LANGUAGE else ""
        )

        result: list[Segment] = []
        for seg in segments_gen:
            result.append(Segment(
                start=seg.start, end=seg.end,
                text=seg.text.strip(), language=tag,
            ))
            pct = min(69, int(seg.end / duration * 70))  # 0-70% for transcription
            self.progress.emit(pct, f"Transcribing... {pct}%")

        return result

    def _transcribe_multilingual(self) -> list[Segment]:
        """Three-pass multilingual pipeline.

        1. Transcribe the full file with the default language forced
           (English). Whisper's VAD gives us well-segmented chunks with
           accurate timestamps for the default-language portions.
        2. For each segment, extract its audio slice and run Whisper's
           own detect_language() on it. Cheap — no decoding, just the
           encoder pass and a softmax over the language tokens.
        3. Segments whose detected language differs from the default
           (with sufficient confidence) are re-transcribed individually
           with the detected language forced. Everything else is kept
           from pass 1.

        The final list carries a non-empty ``Segment.language`` only for
        segments whose language differs from the document default, so
        the editor can show ``(ES)`` tags only where they actually matter.
        """
        from faster_whisper import WhisperModel
        from faster_whisper.audio import decode_audio

        primary = DEFAULT_LANGUAGE
        self.progress.emit(0, f"Loading transcription model '{self.model_size}'...")
        model = WhisperModel(self.model_size, device="auto", compute_type="auto")

        # --- Pass 1: full transcription in primary language -----------------
        self.progress.emit(5, f"Transcribing pass 1 ({primary.upper()})...")
        segments_gen, info = model.transcribe(
            self.audio_path, beam_size=5, vad_filter=True, language=primary,
        )
        duration = info.duration or 1.0
        pass1: list[Segment] = []
        for seg in segments_gen:
            pass1.append(Segment(
                start=seg.start, end=seg.end, text=seg.text.strip(),
            ))
            pct = min(49, int(seg.end / duration * 50))
            self.progress.emit(pct, f"Transcribing pass 1... {pct}%")

        # Record the language metadata for the document, using the
        # detected primary (should equal the forced language).
        self.detected_language = getattr(info, "language", primary) or primary
        self.detected_language_probability = float(
            getattr(info, "language_probability", 1.0) or 1.0
        )

        # --- Pass 2 & 3: per-segment language audit + selective re-run ------
        self.progress.emit(55, "Loading audio for language audit...")
        try:
            audio = decode_audio(self.audio_path, sampling_rate=16000)
        except Exception:
            # If audio decode fails, bail out gracefully — return pass 1
            # results as-is rather than losing the whole transcript.
            return pass1

        total = max(1, len(pass1))
        for i, seg in enumerate(pass1):
            s_i = int(seg.start * 16000)
            e_i = int(seg.end * 16000)
            # Skip very short chunks — language detection is unreliable
            # below ~0.5s and such segments are usually interjections
            # ("um", "sí") anyway. Leave them tagged with the default.
            if e_i - s_i < 8000:  # < 0.5 s at 16 kHz
                continue

            chunk = audio[s_i:e_i]
            try:
                det = model.detect_language(chunk)
            except Exception:
                det = None

            # faster-whisper's detect_language return shape has varied
            # across versions — handle both the tuple and the object forms.
            detected_lang, det_prob = primary, 0.0
            if det is not None:
                if hasattr(det, "language"):
                    detected_lang = det.language or primary
                    det_prob = float(getattr(det, "language_probability", 0.0) or 0.0)
                elif isinstance(det, tuple) and len(det) >= 2:
                    detected_lang = det[0] or primary
                    det_prob = float(det[1] or 0.0)

            # Confidence threshold: we only rewrite the pass-1 text if
            # language detection is reasonably sure it's different. 0.5
            # is empirical — below that, mis-detection on short or noisy
            # chunks becomes the dominant error.
            if detected_lang != primary and det_prob >= 0.5:
                try:
                    new_segs, _ = model.transcribe(
                        chunk, beam_size=5, vad_filter=False,
                        language=detected_lang,
                    )
                    new_text = " ".join(s.text.strip() for s in new_segs).strip()
                except Exception:
                    new_text = ""
                if new_text:
                    seg.text = new_text
                    seg.language = detected_lang

            pct = 55 + min(40, int(i / total * 40))
            self.progress.emit(pct, f"Language audit... segment {i+1}/{total}")

        return pass1

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


class SegmentRetranscribeWorker(QThread):
    """Re-transcribe a single time range of an audio file with a specific
    language forced, and emit the resulting text.

    Used by the editor's right-click "Re-transcribe as…" menu. Kept
    lightweight on purpose — we load a fresh WhisperModel for each run
    rather than trying to share state with the main transcription
    worker; re-transcription is a user-initiated one-off, and loading
    the model once costs a few seconds at most on the "base" size the
    user is likely to have open.

    Signals
    -------
    finished_text(str) - the new text for the segment
    failed(str)        - human-readable error message
    """

    finished_text = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        audio_path: str,
        start: float,
        end: float,
        language: str,
        model_size: str = "base",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.audio_path = audio_path
        self.start = start
        self.end = end
        self.language = language
        self.model_size = model_size

    def run(self) -> None:
        try:
            from faster_whisper import WhisperModel
            from faster_whisper.audio import decode_audio

            model = WhisperModel(
                self.model_size, device="auto", compute_type="auto"
            )
            audio = decode_audio(self.audio_path, sampling_rate=16000)
            s_i = max(0, int(self.start * 16000))
            e_i = min(len(audio), int(self.end * 16000))
            if e_i <= s_i:
                self.failed.emit("Invalid segment range")
                return
            chunk = audio[s_i:e_i]
            segs, _info = model.transcribe(
                chunk,
                beam_size=5,
                vad_filter=False,
                language=self.language,
            )
            text = " ".join(s.text.strip() for s in segs).strip()
            self.finished_text.emit(text)
        except Exception as exc:
            self.failed.emit(str(exc))
