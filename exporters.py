"""Export a TranscriptDocument to various formats."""
from __future__ import annotations

import json
from pathlib import Path

from models import TranscriptDocument, fmt_timestamp


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


def export_docx(doc: TranscriptDocument, path: Path) -> None:
    from docx import Document as DocxDocument
    from docx.shared import Pt, RGBColor

    d = DocxDocument()
    if doc.audio_path:
        d.add_heading(doc.audio_path.name, level=1)

    for seg in doc.segments:
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
        text_run = p.add_run(seg.text)
        text_run.font.size = Pt(11)

    d.save(str(path))


def export_pdf(doc: TranscriptDocument, path: Path) -> None:
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

    for seg in doc.segments:
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

        # Text
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(0, 0, 0)
        pdf.multi_cell(0, 6, f"  {seg.text}" if not seg.speaker else seg.text, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)

    pdf.output(str(path))
