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


def records_to_csv_text(records: Sequence[Mapping[str, Any]]) -> str:
    """Convert sequence of session JSONL records to CSV string."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_FIELDNAMES)

    for rec in records:
        step = rec.get("step", 0)
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
        lines = f.readlines()

    records = read_jsonl_records(lines)
    return records_to_csv_text(records)
