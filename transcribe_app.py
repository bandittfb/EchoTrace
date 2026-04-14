"""Banditt-Tek EchoTrace — AI-Enhanced Audio & Video Transcription.

Main window: Phase 1 (transcription) -> Phase 2 (correction editor).
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Slot, QSize
from PySide6.QtGui import QBrush, QDragEnterEvent, QDropEvent, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsDropShadowEffect
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from editor import CorrectionEditor
from exporters import export_docx, export_json, export_pdf, export_txt
from models import Segment, TranscriptDocument
from theme import APP_NAME, APP_SUBTITLE, STYLESHEET
from transcriber import TranscriberWorker
from waiting_widget import WaitingWidget

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".wma", ".aac", ".mp4", ".mkv", ".webm"}
MODEL_SIZES = ["tiny", "base", "small", "medium", "large-v3"]
LOGO_PATH = Path(__file__).parent / "logo.png"


def _circular_pixmap(pixmap: QPixmap, size: int) -> QPixmap:
    """Return *pixmap* scaled and clipped to a circle of *size* px."""
    scaled = pixmap.scaled(QSize(size, size), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    circle = QPixmap(size, size)
    circle.fill(Qt.GlobalColor.transparent)
    painter = QPainter(circle)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = painter.clipPath() if False else None  # unused, use brush
    painter.setBrush(QBrush(scaled))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(0, 0, size, size)
    painter.end()
    return circle


class DropZone(QLabel):
    """Large label that accepts drag-and-drop audio files."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropzone")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setText("\n\n\nDrop audio or video file here\n\nor click Browse below\n\n\n")
        self.setAcceptDrops(True)
        self._callback = None

    def on_files(self, callback):
        self._callback = callback

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setProperty("dragOver", True)
            self.style().unpolish(self)
            self.style().polish(self)

    def dragLeaveEvent(self, event) -> None:
        self.setProperty("dragOver", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent) -> None:
        self.setProperty("dragOver", False)
        self.style().unpolish(self)
        self.style().polish(self)
        files = []
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if Path(p).suffix.lower() in AUDIO_EXTS:
                files.append(p)
        if files and self._callback:
            self._callback(files[0])
        elif not files:
            QMessageBox.warning(self, "Unsupported file", "Drop an audio or video file (.mp3, .wav, .m4a, .mp4, etc.)")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(960, 680)
        self.setAcceptDrops(True)

        # Window icon
        if LOGO_PATH.exists():
            self.setWindowIcon(QIcon(str(LOGO_PATH)))

        self._worker = None
        self._doc = None
        self._editor = None
        self._project_path = None

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)
        self._segment_count = 0

        self._build_phase1()
        self._build_waiting_screen()
        self._build_phase2_placeholder()

    # -- Phase 1 UI ----------------------------------------------------------

    def _build_phase1(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(8)

        # Logo + branding header
        header = QVBoxLayout()
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if LOGO_PATH.exists():
            logo_label = QLabel()
            logo_label.setPixmap(_circular_pixmap(QPixmap(str(LOGO_PATH)), 160))
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            header.addWidget(logo_label)
            header.addSpacing(4)

        title = QLabel(APP_NAME)
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(title)

        subtitle = QLabel(APP_SUBTITLE)
        subtitle.setObjectName("subtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(subtitle)

        layout.addLayout(header)
        layout.addSpacing(16)

        # Drop zone
        self.drop_zone = DropZone()
        self.drop_zone.on_files(self._start_transcription)
        layout.addWidget(self.drop_zone, 1)

        layout.addSpacing(8)

        # Controls row
        controls = QHBoxLayout()
        controls.setSpacing(10)

        self.btn_browse = QPushButton("Browse Audio...")
        self.btn_browse.setFixedWidth(130)
        self.btn_browse.clicked.connect(self._browse)
        controls.addWidget(self.btn_browse)

        self.btn_open_project = QPushButton("Open Project...")
        self.btn_open_project.setFixedWidth(130)
        self.btn_open_project.clicked.connect(self._open_project)
        controls.addWidget(self.btn_open_project)

        model_label = QLabel("Model:")
        model_label.setFixedWidth(45)
        controls.addWidget(model_label)

        self.combo_model = QComboBox()
        self.combo_model.addItems(MODEL_SIZES)
        self.combo_model.setCurrentText("base")
        self.combo_model.setFixedWidth(110)
        controls.addWidget(self.combo_model)

        controls.addStretch()

        # Diarization toggle
        self.btn_diarize = QPushButton("Speaker Detection: ON")
        self.btn_diarize.setCheckable(True)
        self.btn_diarize.setChecked(True)
        self.btn_diarize.setFixedWidth(170)
        self.btn_diarize.clicked.connect(self._toggle_diarize)
        controls.addWidget(self.btn_diarize)

        layout.addLayout(controls)
        layout.addSpacing(8)

        self.lbl_status = QLabel("Ready — drop a file or click Browse to begin.")
        self.lbl_status.setObjectName("hint")
        layout.addWidget(self.lbl_status)

        self._stack.addWidget(page)  # index 0

    def _build_waiting_screen(self) -> None:
        logo_pixmap = None
        if LOGO_PATH.exists():
            logo_pixmap = _circular_pixmap(QPixmap(str(LOGO_PATH)), 140)
        self._waiting = WaitingWidget(logo_pixmap, self)
        self._stack.addWidget(self._waiting)  # index 1

    def _build_phase2_placeholder(self) -> None:
        self._phase2_page = QWidget()
        self._stack.addWidget(self._phase2_page)  # index 2

    def _toggle_diarize(self) -> None:
        on = self.btn_diarize.isChecked()
        self.btn_diarize.setText(f"Speaker Detection: {'ON' if on else 'OFF'}")

    # -- Phase 1 actions -----------------------------------------------------

    def _browse(self) -> None:
        ext_str = " ".join(f"*{e}" for e in AUDIO_EXTS)
        path, _ = QFileDialog.getOpenFileName(
            self, "Select audio or video file", "", f"Audio/Video ({ext_str});;All (*.*)"
        )
        if path:
            self._start_transcription(path)

    def _open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open EchoTrace project", "", "EchoTrace projects (*.echotrace);;All (*.*)"
        )
        if path:
            try:
                self._doc = TranscriptDocument.load_json(Path(path))
                self._project_path = Path(path)

                # Check if the original media file still exists
                if self._doc.audio_path and not self._doc.audio_path.exists():
                    reply = QMessageBox.question(
                        self,
                        "Media file not found",
                        f"The original file was at:\n{self._doc.audio_path}\n\n"
                        f"It has been moved or deleted. Would you like to locate it?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    )
                    if reply == QMessageBox.StandardButton.Yes:
                        ext_str = " ".join(f"*{e}" for e in AUDIO_EXTS)
                        new_path, _ = QFileDialog.getOpenFileName(
                            self, "Locate media file", "",
                            f"Audio/Video ({ext_str});;All (*.*)",
                        )
                        if new_path:
                            self._doc.audio_path = Path(new_path)
                        else:
                            # User cancelled — open transcript-only (no playback)
                            self._doc.audio_path = None
                    else:
                        # Open transcript-only (no playback)
                        self._doc.audio_path = None

                self._open_editor()
            except Exception as e:
                QMessageBox.critical(self, "Load Error", str(e))

    def _save_project(self) -> None:
        if not self._doc:
            return
        if self._editor:
            self._editor._sync_text_to_model()
        # Default save path: same folder as audio, or last project path
        if hasattr(self, "_project_path") and self._project_path:
            default = str(self._project_path)
        elif self._doc.audio_path:
            default = str(self._doc.audio_path.with_suffix(".echotrace"))
        else:
            default = "transcript.echotrace"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save EchoTrace project", default, "EchoTrace projects (*.echotrace)"
        )
        if path:
            try:
                self._doc.save_json(Path(path))
                self._project_path = Path(path)
                QMessageBox.information(self, "Saved", f"Project saved to:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "Save Error", str(e))

    def _start_transcription(self, path: str) -> None:
        self._segment_count = 0
        self._waiting.start()
        self._stack.setCurrentWidget(self._waiting)

        self._audio_path = path
        self._worker = TranscriberWorker(
            audio_path=path,
            model_size=self.combo_model.currentText(),
            enable_diarization=self.btn_diarize.isChecked(),
            parent=self,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    @Slot(int, str)
    def _on_progress(self, pct: int, msg: str) -> None:
        # Count segments from the transcription percentage (0-70% range)
        if pct > 5 and pct < 70:
            self._segment_count += 1
        self._waiting.update_progress(pct, msg, self._segment_count)

    @Slot(list)
    def _on_finished(self, segments: list[Segment]) -> None:
        self._waiting.stop()
        self._doc = TranscriptDocument(
            segments=segments,
            audio_path=Path(self._audio_path),
            model_size=self.combo_model.currentText(),
            created_at=datetime.now().isoformat(),
        )
        self._open_editor()

    @Slot(str)
    def _on_error(self, msg: str) -> None:
        self._waiting.stop()
        self._stack.setCurrentIndex(0)
        self.lbl_status.setText(f"Error: {msg}")
        QMessageBox.critical(self, "Transcription Error", msg)

    # -- Phase 2 transition --------------------------------------------------

    def _open_editor(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Top bar
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(12, 10, 12, 10)

        if LOGO_PATH.exists():
            mini_logo = QLabel()
            mini_logo.setPixmap(_circular_pixmap(QPixmap(str(LOGO_PATH)), 32))
            top_bar.addWidget(mini_logo)

        lbl_brand = QLabel(f"EchoTrace")
        lbl_brand.setStyleSheet("font-size: 15px; font-weight: bold; margin-right: 12px;")
        top_bar.addWidget(lbl_brand)

        lbl_file = QLabel(f"{self._doc.audio_path.name}")
        lbl_file.setObjectName("fileLabel")
        lbl_file.setStyleSheet("color: #8892A0; font-weight: normal;")
        top_bar.addWidget(lbl_file)

        top_bar.addStretch()

        btn_save = QPushButton("Save Project")
        btn_save.setObjectName("exportBtn")
        btn_save.clicked.connect(self._save_project)
        top_bar.addWidget(btn_save)

        btn_new = QPushButton("New File")
        btn_new.clicked.connect(self._back_to_phase1)
        top_bar.addWidget(btn_new)

        for label, fn in [
            ("Export TXT", self._export_txt),
            ("Export DOCX", self._export_docx),
            ("Export JSON", self._export_json),
            ("Export PDF", self._export_pdf),
        ]:
            btn = QPushButton(label)
            btn.setObjectName("exportBtn")
            btn.clicked.connect(fn)
            top_bar.addWidget(btn)

        layout.addLayout(top_bar)

        # Separator line
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: #2A2A4A;")
        layout.addWidget(sep)

        # The editor
        self._editor = CorrectionEditor(self._doc, parent=page)
        layout.addWidget(self._editor)

        # Replace phase2 placeholder
        self._stack.removeWidget(self._phase2_page)
        self._phase2_page.deleteLater()
        self._phase2_page = page
        self._stack.addWidget(page)
        self._stack.setCurrentWidget(page)

    def _back_to_phase1(self) -> None:
        reply = QMessageBox.question(
            self, "Save project?",
            "Do you want to save your project before starting a new file?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Cancel:
            return
        if reply == QMessageBox.StandardButton.Yes:
            self._save_project()

        self._stack.setCurrentIndex(0)
        self.lbl_status.setText("Ready — drop a file or click Browse to begin.")
        if self._editor:
            self._editor.player.pause()

    # -- Export actions -------------------------------------------------------

    def _export_txt(self) -> None:
        self._do_export("Text files (*.txt)", ".txt", export_txt)

    def _export_docx(self) -> None:
        self._do_export("Word documents (*.docx)", ".docx", export_docx)

    def _export_json(self) -> None:
        self._do_export("JSON files (*.json)", ".json", export_json)

    def _export_pdf(self) -> None:
        self._do_export("PDF files (*.pdf)", ".pdf", export_pdf)

    def _do_export(self, filter_str: str, suffix: str, exporter) -> None:
        if not self._doc:
            return
        if self._editor:
            self._editor._sync_text_to_model()

        default_name = self._doc.audio_path.stem + suffix if self._doc.audio_path else f"transcript{suffix}"
        path, _ = QFileDialog.getSaveFileName(self, "Export transcript", default_name, filter_str)
        if path:
            try:
                exporter(self._doc, Path(path))
                QMessageBox.information(self, "Exported", f"Saved to:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", str(e))

    # -- Drag and drop on main window ----------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if Path(p).suffix.lower() in AUDIO_EXTS:
                if self._stack.currentIndex() == 0:
                    self._start_transcription(p)
                return


def main():
    import warnings
    import os
    # Suppress torchcodec warnings globally (broken on Windows, pyannote falls back to torchaudio)
    os.environ["TORCHCODEC_DISABLE_LOAD"] = "1"
    warnings.filterwarnings("ignore", message=".*torchcodec.*")
    warnings.filterwarnings("ignore", message=".*libtorchcodec.*")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)

    if LOGO_PATH.exists():
        app.setWindowIcon(QIcon(str(LOGO_PATH)))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
