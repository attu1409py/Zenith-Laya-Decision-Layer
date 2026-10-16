"""CSV export utility for Team ZENITH audit logs.

Extracts chronological step metrics from session JSONL files into tabular CSV format.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Union

from zenith.hash_chain import read_jsonl_records

CSV_FIELDNAMES = [
    "step",
    "action",
    "result",
    "chosen",
    "confidence",
    "source",
    "decide_ms",
    "api_ms",
    "turn_ms",
    "prob_up",
    "prob_down",
    "prob_left",
    "prob_right",
    "hash",
    "prev_hash",
    "ts",
]


def records_to_csv_text(records: Sequence[Mapping[str, Any]], lineterminator: str = "\r\n") -> str:
    """Convert sequence of session JSONL records to RFC 4180-compliant CSV string."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator=lineterminator)
    writer.writerow(CSV_FIELDNAMES)

    for rec in records:
        step = rec.get("step")
        if step is None:
            continue
        action = rec.get("action", "")
        result = rec.get("result", "")
        decision = rec.get("decision", {}) or {}
        chosen = decision.get("chosen", "")
        confidence = decision.get("confidence", 0.0)
        source = decision.get("source", "")
        timing = rec.get("timing", {}) or {}
        decide_ms = timing.get("decide_ms", 0)
        api_ms = timing.get("api_ms", 0)
        turn_ms = timing.get("turn_ms", 0)
        probs = decision.get("probabilities", {}) or {}
        prob_up = probs.get("up", 0.0)
        prob_down = probs.get("down", 0.0)
        prob_left = probs.get("left", 0.0)
        prob_right = probs.get("right", 0.0)
        h = rec.get("hash", "")
        prev_h = rec.get("prev_hash", "")
        ts = rec.get("ts", "")

        writer.writerow([
            step,
            action,
            result,
            chosen,
            f"{confidence:.4f}" if isinstance(confidence, (int, float)) else str(confidence),
            source,
            decide_ms,
            api_ms,
            turn_ms,
            f"{prob_up:.4f}" if isinstance(prob_up, (int, float)) else str(prob_up),
            f"{prob_down:.4f}" if isinstance(prob_down, (int, float)) else str(prob_down),
            f"{prob_left:.4f}" if isinstance(prob_left, (int, float)) else str(prob_left),
            f"{prob_right:.4f}" if isinstance(prob_right, (int, float)) else str(prob_right),
            h,
            prev_h,
            ts,
        ])

    return out.getvalue()


def export_session_to_csv(log_path: Union[str, Path]) -> str:
    """Read a session JSONL file and return formatted CSV content."""
    path = Path(log_path)
    if not path.exists():
        raise FileNotFoundError(f"Log file {log_path} not found.")

    with open(path, "r", encoding="utf-8") as f:
        lines = [line for line in f if line.strip()]

    records = read_jsonl_records(lines)
    return records_to_csv_text(records)


def export_session_to_csv_file(
    log_path: Union[str, Path],
    out_csv_path: Optional[Union[str, Path]] = None,
    with_bom: bool = True,
) -> Path:
    """Read session JSONL and write RFC-4180 CSV file to disk with optional UTF-8 BOM."""
    src = Path(log_path)
    if not src.exists():
        raise FileNotFoundError(f"Log file {log_path} not found.")

    dest = Path(out_csv_path) if out_csv_path else src.with_suffix(".csv")
    csv_text = export_session_to_csv(src)

    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        if with_bom:
            f.write(b"\xef\xbb\xbf")
        f.write(csv_text.encode("utf-8"))

    return dest

