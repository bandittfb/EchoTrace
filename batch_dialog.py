"""Batch transcription dialog — process multiple files in one go.

The user adds files, picks transcription settings and output formats,
then clicks Start. Each file is transcribed sequentially (so we don't
fight the GPU/CPU for resources), auto-exported to the chosen formats,
and the results are written to a user-selected output folder. The
dialog stays open showing per-file progress so the user can walk away
and come back to a folder full of finished transcripts.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from exporters import export_docx, export_json, export_pdf, export_txt
from models import Segment, TranscriptDocument
from transcriber import TranscriberWorker


# Re-use the canonical choice lists from transcribe_app so the labels
# and values stay in sync. Imported at function scope below to avoid a
# circular import (transcribe_app imports batch_dialog).
def _load_choices():
    from transcribe_app import LANGUAGE_CHOICES, MODEL_CHOICES
    return MODEL_CHOICES, LANGUAGE_CHOICES


# Status icons for the file list.
_ICON = {"pending": "○", "running": "⏳", "done": "✓", "failed": "✕"}


class BatchDialog(QDialog):
    """Modal dialog for configuring and running a batch transcription."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Batch Transcription")
        self.setMinimumSize(560, 520)
        self._model_choices, self._lang_choices = _load_choices()

        self._queue: list[str] = []          # file paths still to process
        self._results: dict[str, str] = {}   # path -> "done" | "failed"
        self._worker: Optional[TranscriberWorker] = None
        self._running = False
        self._current_path: str = ""
        self._total: int = 0

        self._build_ui()

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 14, 16, 14)

        # -- File list -------------------------------------------------------
        file_label = QLabel("Files to process:")
        file_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(file_label)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.file_list.setMinimumHeight(120)
        layout.addWidget(self.file_list)

        file_btn_row = QHBoxLayout()
        self.btn_add = QPushButton("+ Add Files")
        self.btn_add.setFixedHeight(28)
        self.btn_add.clicked.connect(self._add_files)
        file_btn_row.addWidget(self.btn_add)

        self.btn_remove = QPushButton("✕ Remove Selected")
        self.btn_remove.setFixedHeight(28)
        self.btn_remove.clicked.connect(self._remove_selected)
        file_btn_row.addWidget(self.btn_remove)

        file_btn_row.addStretch()
        layout.addLayout(file_btn_row)

        # -- Separator -------------------------------------------------------
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setStyleSheet("color: #2A2A4A;")
        layout.addWidget(sep1)

        # -- Settings --------------------------------------------------------
        settings_label = QLabel("Settings (applied to all files):")
        settings_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(settings_label)

        # Model
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Model:"))
        self.combo_model = QComboBox()
        for display, value in self._model_choices:
            self.combo_model.addItem(display, userData=value)
        self.combo_model.setCurrentIndex(1)  # Base
        model_row.addWidget(self.combo_model, 1)
        layout.addLayout(model_row)

        # Language
        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("Language:"))
        self.combo_lang = QComboBox()
        for display, value in self._lang_choices:
            self.combo_lang.addItem(display, userData=value)
        self.combo_lang.setCurrentIndex(0)  # English
        lang_row.addWidget(self.combo_lang, 1)
        layout.addLayout(lang_row)

        # Speaker detection
        self.chk_diarize = QCheckBox("Speaker Detection")
        self.chk_diarize.setChecked(True)
        layout.addWidget(self.chk_diarize)

        # -- Separator -------------------------------------------------------
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color: #2A2A4A;")
        layout.addWidget(sep2)

        # -- Output formats --------------------------------------------------
        fmt_label = QLabel("Output formats:")
        fmt_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(fmt_label)

        fmt_row1 = QHBoxLayout()
        self.chk_docx = QCheckBox("Word (.docx)")
        self.chk_docx.setChecked(True)
        fmt_row1.addWidget(self.chk_docx)
        self.chk_pdf = QCheckBox("PDF (.pdf)")
        self.chk_pdf.setChecked(True)
        fmt_row1.addWidget(self.chk_pdf)
        fmt_row1.addStretch()
        layout.addLayout(fmt_row1)

        fmt_row2 = QHBoxLayout()
        self.chk_txt = QCheckBox("Text (.txt)")
        fmt_row2.addWidget(self.chk_txt)
        self.chk_json = QCheckBox("JSON (.json)")
        fmt_row2.addWidget(self.chk_json)
        self.chk_project = QCheckBox("EchoTrace project (.echotrace)")
        self.chk_project.setChecked(True)
        fmt_row2.addWidget(self.chk_project)
        fmt_row2.addStretch()
        layout.addLayout(fmt_row2)

        # -- Output folder ---------------------------------------------------
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Output folder:"))
        self.txt_output = QLineEdit()
        self.txt_output.setPlaceholderText("Select a folder for the exported files...")
        folder_row.addWidget(self.txt_output, 1)
        self.btn_folder = QPushButton("📁")
        self.btn_folder.setFixedSize(32, 28)
        self.btn_folder.clicked.connect(self._browse_output)
        folder_row.addWidget(self.btn_folder)
        layout.addLayout(folder_row)

        # -- Progress --------------------------------------------------------
        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setStyleSheet("color: #2A2A4A;")
        layout.addWidget(sep3)

        self.lbl_overall = QLabel("")
        self.lbl_overall.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.lbl_overall)

        self.progress_overall = QProgressBar()
        self.progress_overall.setRange(0, 100)
        self.progress_overall.setValue(0)
        layout.addWidget(self.progress_overall)

        self.lbl_current = QLabel("")
        self.lbl_current.setStyleSheet("color: #8892A0; font-size: 11px;")
        layout.addWidget(self.lbl_current)

        # -- Buttons ---------------------------------------------------------
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.btn_close = QPushButton("Close")
        self.btn_close.setFixedHeight(32)
        self.btn_close.clicked.connect(self._on_close)
        btn_row.addWidget(self.btn_close)

        self.btn_start = QPushButton("Start Batch")
        self.btn_start.setObjectName("primaryBtn")
        self.btn_start.setFixedHeight(32)
        self.btn_start.setDefault(True)
        self.btn_start.clicked.connect(self._toggle_batch)
        btn_row.addWidget(self.btn_start)

        layout.addLayout(btn_row)

    # -- File management -----------------------------------------------------

    def _add_files(self) -> None:
        from transcribe_app import AUDIO_EXTS
        ext_str = " ".join(f"*{e}" for e in AUDIO_EXTS)
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select audio or video files", "",
            f"Audio/Video ({ext_str});;All (*.*)",
        )
        for p in paths:
            # Avoid duplicates
            existing = {
                self.file_list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.file_list.count())
            }
            if p not in existing:
                item = QListWidgetItem(f"{_ICON['pending']}  {Path(p).name}")
                item.setData(Qt.ItemDataRole.UserRole, p)
                self.file_list.addItem(item)

    def _remove_selected(self) -> None:
        for item in reversed(self.file_list.selectedItems()):
            row = self.file_list.row(item)
            self.file_list.takeItem(row)

    def _browse_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select output folder")
        if folder:
            self.txt_output.setText(folder)

    # -- Batch control -------------------------------------------------------

    def _toggle_batch(self) -> None:
        if self._running:
            self._stop_batch()
        else:
            self._start_batch()

    def _start_batch(self) -> None:
        # Validation
        if self.file_list.count() == 0:
            QMessageBox.warning(self, "No files", "Add at least one file to process.")
            return
        if not self.txt_output.text().strip():
            QMessageBox.warning(self, "No output folder", "Select an output folder.")
            return
        output = Path(self.txt_output.text().strip())
        if not output.exists():
            try:
                output.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                QMessageBox.critical(self, "Folder error", str(e))
                return
        if not any([
            self.chk_docx.isChecked(), self.chk_pdf.isChecked(),
            self.chk_txt.isChecked(), self.chk_json.isChecked(),
            self.chk_project.isChecked(),
        ]):
            QMessageBox.warning(
                self, "No output format",
                "Select at least one output format.",
            )
            return

        # Build the queue
        self._queue = []
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            self._queue.append(item.data(Qt.ItemDataRole.UserRole))
            item.setText(f"{_ICON['pending']}  {Path(item.data(Qt.ItemDataRole.UserRole)).name}")
        self._results.clear()
        self._total = len(self._queue)

        # Lock controls
        self._running = True
        self.btn_start.setText("Stop Batch")
        self.btn_add.setEnabled(False)
        self.btn_remove.setEnabled(False)
        self.combo_model.setEnabled(False)
        self.combo_lang.setEnabled(False)
        self.chk_diarize.setEnabled(False)
        self.btn_folder.setEnabled(False)
        self.txt_output.setEnabled(False)
        for chk in (self.chk_docx, self.chk_pdf, self.chk_txt, self.chk_json, self.chk_project):
            chk.setEnabled(False)

        self._process_next()

    def _stop_batch(self) -> None:
        self._queue.clear()
        if self._worker and self._worker.isRunning():
            # Don't use terminate() — it can leave GPU resources and
            # mutexes in a broken state. Instead, disconnect the
            # worker's signals so its results are silently discarded
            # when it finishes naturally. The worker will complete its
            # current file but we won't process any more after it.
            try:
                self._worker.progress.disconnect(self._on_file_progress)
                self._worker.finished.disconnect(self._on_file_finished)
                self._worker.error.disconnect(self._on_file_error)
            except RuntimeError:
                pass  # already disconnected
        self._finish_batch(cancelled=True)

    def _finish_batch(self, cancelled: bool = False) -> None:
        self._running = False
        self.btn_start.setText("Start Batch")
        self.btn_add.setEnabled(True)
        self.btn_remove.setEnabled(True)
        self.combo_model.setEnabled(True)
        self.combo_lang.setEnabled(True)
        self.chk_diarize.setEnabled(True)
        self.btn_folder.setEnabled(True)
        self.txt_output.setEnabled(True)
        for chk in (self.chk_docx, self.chk_pdf, self.chk_txt, self.chk_json, self.chk_project):
            chk.setEnabled(True)

        done = sum(1 for v in self._results.values() if v == "done")
        failed = sum(1 for v in self._results.values() if v == "failed")
        total = done + failed

        if cancelled:
            self.lbl_overall.setText(f"Batch cancelled — {done} completed, {failed} failed")
        else:
            self.lbl_overall.setText(f"Batch complete — {done} of {total} succeeded")
            if failed:
                self.lbl_overall.setText(
                    f"Batch complete — {done} succeeded, {failed} failed"
                )
            self.lbl_current.setText("")

    # -- Sequential processing -----------------------------------------------

    def _process_next(self) -> None:
        if not self._queue:
            self._finish_batch()
            return

        path = self._queue.pop(0)
        self._current_path = path
        done_count = len(self._results)

        # Update file list icon
        self._set_file_status(path, "running")
        self.lbl_overall.setText(
            f"Processing {done_count + 1} of {self._total}..."
        )
        self.lbl_current.setText(f"Current: {Path(path).name}")

        # Overall progress: fraction of files completed (the per-file
        # progress adds granularity within each file's slice).
        overall_pct = int(done_count / max(1, self._total) * 100)
        self.progress_overall.setValue(overall_pct)

        self._worker = TranscriberWorker(
            audio_path=path,
            model_size=self.combo_model.currentData(),
            language=self.combo_lang.currentData(),
            enable_diarization=self.chk_diarize.isChecked(),
            parent=self,
        )
        self._worker.progress.connect(self._on_file_progress)
        self._worker.finished.connect(self._on_file_finished)
        self._worker.error.connect(self._on_file_error)
        self._worker.start()

    @Slot(int, str)
    def _on_file_progress(self, pct: int, msg: str) -> None:
        done_count = len(self._results)
        # Map this file's 0-100 into its slice of the overall bar.
        file_slice = 100.0 / max(1, self._total)
        overall = int(done_count * file_slice + pct * file_slice / 100)
        self.progress_overall.setValue(min(100, overall))
        self.lbl_current.setText(
            f"Current: {Path(self._current_path).name} — {msg}"
        )

    @Slot(list)
    def _on_file_finished(self, segments: list[Segment]) -> None:
        path = self._current_path
        lang = getattr(self._worker, "detected_language", "") if self._worker else ""
        lang_prob = getattr(self._worker, "detected_language_probability", 0.0) if self._worker else 0.0

        doc = TranscriptDocument(
            segments=segments,
            audio_path=Path(path),
            model_size=self.combo_model.currentData(),
            language=lang,
            language_probability=lang_prob,
            created_at=datetime.now().isoformat(),
        )
        diar = " + diarization" if self.chk_diarize.isChecked() else ""
        doc.log(
            "Batch transcription completed",
            f"model={self.combo_model.currentData()}{diar}, "
            f"segments={len(segments)}, language={lang or 'unknown'}",
        )

        # Export to all selected formats
        try:
            self._export_doc(doc, path)
            self._results[path] = "done"
            self._set_file_status(path, "done")
        except Exception as e:
            self._results[path] = "failed"
            self._set_file_status(path, "failed", str(e))

        self._process_next()

    @Slot(str)
    def _on_file_error(self, msg: str) -> None:
        path = self._current_path
        self._results[path] = "failed"
        self._set_file_status(path, "failed", msg)
        self._process_next()

    # -- Export --------------------------------------------------------------

    def _export_doc(self, doc: TranscriptDocument, source_path: str) -> None:
        """Export the transcript to all user-selected formats."""
        output_dir = Path(self.txt_output.text().strip())
        stem = Path(source_path).stem

        if self.chk_docx.isChecked():
            export_docx(doc, output_dir / f"{stem}.docx")

        if self.chk_pdf.isChecked():
            export_pdf(doc, output_dir / f"{stem}.pdf")

        if self.chk_txt.isChecked():
            export_txt(doc, output_dir / f"{stem}.txt")

        if self.chk_json.isChecked():
            export_json(doc, output_dir / f"{stem}.json")

        if self.chk_project.isChecked():
            doc.save_json(output_dir / f"{stem}.echotrace")

    # -- Helpers -------------------------------------------------------------

    def _set_file_status(
        self, path: str, status: str, error_msg: str = ""
    ) -> None:
        """Update the icon/text for a file in the list."""
        icon = _ICON.get(status, "?")
        name = Path(path).name
        suffix = f"  — {error_msg}" if error_msg else ""
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                item.setText(f"{icon}  {name}{suffix}")
                break

    def _on_close(self) -> None:
        if self._running:
            reply = QMessageBox.question(
                self, "Batch in progress",
                "A batch is still running. Stop it and close?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self._stop_batch()
        self.accept()
