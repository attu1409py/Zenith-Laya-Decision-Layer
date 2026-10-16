"""PDF audit report generation for Team ZENITH decision layer.

Generates audit-ready PDF reports from session JSONL files using ReportLab.
Includes cryptographic verification status, summary KPIs, fallback rule compliance,
and tabular move logs.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from zenith.hash_chain import read_jsonl_records, verify_jsonl_file


class NumberedCanvas(colors.Color):
    """Placeholder to document canvas styling."""
    pass


def generate_session_pdf(
    log_path: Union[str, Path],
    output: Optional[Union[str, Path, io.BytesIO]] = None,
    max_table_rows: int = 1500,
) -> bytes:
    """Generate a PDF audit report for a session log.

    Args:
        log_path: Path to the session JSONL file.
        output: Destination filepath or BytesIO stream. If None, returns bytes.
        max_table_rows: Cap on move table rows to prevent excessive PDF generation.

    Returns:
        PDF content as bytes.
    """
    path = Path(log_path)
    if not path.exists():
        raise FileNotFoundError(f"Log file not found: {log_path}")

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    records = read_jsonl_records(lines)
    verify_result = verify_jsonl_file(path)

    buf = io.BytesIO() if output is None or isinstance(output, (str, Path)) else output

    doc = SimpleDocTemplate(
        buf if output is None or not isinstance(output, (str, Path)) else str(output),
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "ZenithTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#08090c"),
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "ZenithSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#4b5563"),
        spaceAfter=12,
    )
    section_heading = ParagraphStyle(
        "ZenithSection",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#08090c"),
        spaceBefore=10,
        spaceAfter=6,
    )
    cell_style = ParagraphStyle(
        "ZenithCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7,
        leading=9,
        textColor=colors.HexColor("#1f2937"),
    )
    cell_header = ParagraphStyle(
        "ZenithCellHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7,
        leading=9,
        textColor=colors.white,
    )
    mono_cell = ParagraphStyle(
        "ZenithMonoCell",
        parent=styles["Normal"],
        fontName="Courier",
        fontSize=6.5,
        leading=8,
        textColor=colors.HexColor("#111827"),
    )

    elements = []

    # Title Banner
    session_id = path.stem
    elements.append(Paragraph("ZENITH // DECISION LAYER AUDIT REPORT", title_style))
    elements.append(
        Paragraph(
            f"<b>Team:</b> ZENITH &nbsp;|&nbsp; <b>Problem Statement:</b> PS 02 Beat the Bot: Teach Laya to Play &nbsp;|&nbsp; <b>Session ID:</b> {session_id}",
            subtitle_style,
        )
    )
    elements.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#f59e0b"), spaceAfter=10))

    # Determine summary metrics from records
    total_moves = len(records)
    applied_moves = sum(1 for r in records if r.get("result") == "applied")
    rejected_moves = sum(1 for r in records if r.get("result") == "rejected")
    fallback_moves = sum(1 for r in records if (r.get("decision") or {}).get("source") == "fallback")
    fallback_pct = (fallback_moves / total_moves * 100.0) if total_moves > 0 else 0.0

    decide_times = [
        r.get("timing", {}).get("decide_ms", 0)
        for r in records
        if isinstance(r.get("timing"), dict) and "decide_ms" in r.get("timing")
    ]
    turn_times = [
        r.get("timing", {}).get("turn_ms", 0)
        for r in records
        if isinstance(r.get("timing"), dict) and "turn_ms" in r.get("timing")
    ]
    avg_decide = sum(decide_times) / len(decide_times) if decide_times else 0.0
    avg_turn = sum(turn_times) / len(turn_times) if turn_times else 0.0

    game_name = records[0].get("game", "unknown") if records else "unknown"
    is_mock = "mock" in session_id.lower() or session_id.startswith("dry") or session_id.startswith("test")
    mode_str = "DEV / SIMULATION (MOCK)" if is_mock else "LIVE ARENA (OFFICIAL)"

    chain_status_str = "VALID (CRYPTOGRAPHIC INTEGRITY CONFIRMED)" if verify_result.is_valid else f"FAILED: {verify_result.error_message}"
    chain_color = colors.HexColor("#10b981") if verify_result.is_valid else colors.HexColor("#ef4444")

    # Overview Table
    overview_data = [
        [
            Paragraph("<b>Session ID:</b>", cell_style),
            Paragraph(f"<font face='Courier'>{session_id}</font>", cell_style),
            Paragraph("<b>Game:</b>", cell_style),
            Paragraph(str(game_name).upper(), cell_style),
        ],
        [
            Paragraph("<b>Execution Mode:</b>", cell_style),
            Paragraph(mode_str, cell_style),
            Paragraph("<b>Agent Name:</b>", cell_style),
            Paragraph("ZENITH", cell_style),
        ],
        [
            Paragraph("<b>Total Moves Logged:</b>", cell_style),
            Paragraph(f"{total_moves} ({applied_moves} applied, {rejected_moves} rejected)", cell_style),
            Paragraph("<b>Fallback Compliance:</b>", cell_style),
            Paragraph(f"{fallback_moves}/{total_moves} ({fallback_pct:.1f}%) [RULE: &le;10% {'PASS' if fallback_pct <= 10.0 else 'VIOLATION'}]", cell_style),
        ],
        [
            Paragraph("<b>Hash Chain Status:</b>", cell_style),
            Paragraph(f"<b>{chain_status_str}</b>", ParagraphStyle("ChainStatus", parent=cell_style, textColor=chain_color)),
            Paragraph("<b>Avg Turn Latency:</b>", cell_style),
            Paragraph(f"{avg_turn:.1f} ms (decide: {avg_decide:.1f} ms)", cell_style),
        ],
    ]

    overview_table = Table(overview_data, colWidths=[1.4 * inch, 2.2 * inch, 1.4 * inch, 2.5 * inch])
    overview_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    elements.append(overview_table)
    elements.append(Spacer(1, 12))

    # Move Log Table Header
    elements.append(Paragraph(f"CHRONOLOGICAL STEP AUDIT LOG ({total_moves} moves)", section_heading))

    table_data = [
        [
            Paragraph("STEP", cell_header),
            Paragraph("ACTION", cell_header),
            Paragraph("RESULT", cell_header),
            Paragraph("CHOSEN", cell_header),
            Paragraph("CONF", cell_header),
            Paragraph("SOURCE", cell_header),
            Paragraph("DECIDE", cell_header),
            Paragraph("TURN", cell_header),
            Paragraph("SHA-256 HASH", cell_header),
        ]
    ]

    slice_records = records[:max_table_rows]
    for r in slice_records:
        dec = r.get("decision") or {}
        timing = r.get("timing") or {}
        h = str(r.get("hash", ""))
        short_h = (h[:14] + "..") if len(h) > 16 else h
        conf = dec.get("confidence", 0.0)
        conf_str = f"{float(conf)*100.0:.1f}%" if isinstance(conf, (int, float)) else str(conf)

        table_data.append([
            Paragraph(str(r.get("step", 0)), mono_cell),
            Paragraph(str(r.get("action", "")).upper(), mono_cell),
            Paragraph(str(r.get("result", "")).upper(), mono_cell),
            Paragraph(str(dec.get("chosen", "")).upper(), mono_cell),
            Paragraph(conf_str, mono_cell),
            Paragraph(str(dec.get("source", "")).upper(), mono_cell),
            Paragraph(f"{timing.get('decide_ms', 0)}ms", mono_cell),
            Paragraph(f"{timing.get('turn_ms', 0)}ms", mono_cell),
            Paragraph(short_h, mono_cell),
        ])

    steps_table = Table(
        table_data,
        colWidths=[
            0.5 * inch,
            0.65 * inch,
            0.75 * inch,
            0.65 * inch,
            0.65 * inch,
            0.75 * inch,
            0.65 * inch,
            0.65 * inch,
            2.25 * inch,
        ],
        repeatRows=1,
    )
    steps_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0e1015")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ])
    )
    elements.append(steps_table)

    if len(records) > max_table_rows:
        elements.append(Spacer(1, 8))
        elements.append(
            Paragraph(
                f"<i>Note: Table truncated at {max_table_rows} moves for PDF presentation. Download full JSONL or CSV for complete records.</i>",
                cell_style,
            )
        )

    # Build PDF
    doc.build(elements)

    if output is None or isinstance(output, (str, Path)):
        if isinstance(output, (str, Path)):
            with open(output, "rb") as f:
                return f.read()
        return buf.getvalue()
    return b""
