"""Export a TranscriptDocument to various formats.

DOCX and PDF exports optionally accept ``rich_runs`` — per-segment
formatting captured from the editor — so user-applied B/I/U survives the
trip out to attorneys / PI partners. TXT and JSON ignore formatting since
they have no way to represent it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from models import FormattedRun, TranscriptDocument, fmt_timestamp


def export_txt(doc: TranscriptDocument, path: Path) -> None:
    lines = []
    if doc.audio_path:
        lines.append(f"# {doc.audio_path.name}")
    if doc.language:
        lines.append(f"# Language: {doc.language} ({doc.language_probability:.2f})")
    lines.append("")
    for seg in doc.segments:
        speaker = f" {seg.speaker}:" if seg.speaker else ""
        lines.append(f"[{fmt_timestamp(seg.start)} -> {fmt_timestamp(seg.end)}]{speaker} {seg.text}")
    path.write_text("\n".join(lines), encoding="utf-8")


def export_json(doc: TranscriptDocument, path: Path) -> None:
    path.write_text(
        json.dumps(doc.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _runs_for_segment(
    seg_index: int,
    seg_text: str,
    rich_runs: Optional[list[list[FormattedRun]]],
) -> list[FormattedRun]:
    """Return the formatted runs for a segment, falling back to a single
    plain run when no formatting was captured (e.g., headless export)."""
    if rich_runs and seg_index < len(rich_runs) and rich_runs[seg_index]:
        return rich_runs[seg_index]
    return [FormattedRun(text=seg_text)]


def export_docx(
    doc: TranscriptDocument,
    path: Path,
    rich_runs: Optional[list[list[FormattedRun]]] = None,
) -> None:
    from docx import Document as DocxDocument
    from docx.shared import Pt, RGBColor

    d = DocxDocument()
    if doc.audio_path:
        d.add_heading(doc.audio_path.name, level=1)

    for i, seg in enumerate(doc.segments):
        p = d.add_paragraph()
        ts_run = p.add_run(f"[{fmt_timestamp(seg.start)} -> {fmt_timestamp(seg.end)}]  ")
        ts_run.bold = True
        ts_run.font.size = Pt(9)
        ts_run.font.color.rgb = RGBColor(108, 117, 125)
        if seg.speaker:
            spk_run = p.add_run(f"{seg.speaker}: ")
            spk_run.bold = True
            spk_run.font.size = Pt(11)
            spk_run.font.color.rgb = RGBColor(0, 102, 204)

        for run in _runs_for_segment(i, seg.text, rich_runs):
            text_run = p.add_run(run.text)
            text_run.font.size = Pt(11)
            if run.bold:
                text_run.bold = True
            if run.italic:
                text_run.italic = True
            if run.underline:
                text_run.underline = True

    d.save(str(path))


def export_pdf(
    doc: TranscriptDocument,
    path: Path,
    rich_runs: Optional[list[list[FormattedRun]]] = None,
) -> None:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # Title
    if doc.audio_path:
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 12, doc.audio_path.name, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

    if doc.language:
        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(0, 6, f"Language: {doc.language} ({doc.language_probability:.2f})", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

    for i, seg in enumerate(doc.segments):
        ts = f"[{fmt_timestamp(seg.start)} -> {fmt_timestamp(seg.end)}]"

        # Timestamp
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(108, 117, 125)
        pdf.cell(pdf.get_string_width(ts) + 2, 6, ts)

        # Speaker label
        if seg.speaker:
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(0, 102, 204)
            pdf.cell(pdf.get_string_width(seg.speaker + ": ") + 2, 6, f"  {seg.speaker}: ")

        # Text — emit each formatted run as a separate write() so B/I/U
        # styling sticks. Underline isn't a font-style flag in fpdf2; it's
        # part of the style string ("U", "BU", "BIU", etc.).
        pdf.set_text_color(0, 0, 0)
        runs = _runs_for_segment(i, seg.text, rich_runs)
        prefix = "" if seg.speaker else "  "
        for j, run in enumerate(runs):
            style = ""
            if run.bold:
                style += "B"
            if run.italic:
                style += "I"
            if run.underline:
                style += "U"
            pdf.set_font("Helvetica", style, 10)
            text = (prefix + run.text) if j == 0 else run.text
            pdf.write(6, text)
        pdf.ln(8)
        pdf.ln(1)

    pdf.output(str(path))
