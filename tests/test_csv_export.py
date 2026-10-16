"""Unit tests for CSV export utility."""

from __future__ import annotations

import csv
import io
import tempfile
import unittest
from pathlib import Path

from zenith.csv_export import CSV_FIELDNAMES, export_session_to_csv, records_to_csv_text
from zenith.session_logger import SessionLogger


class TestCsvExport(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()

    def test_records_to_csv_format(self) -> None:
        records = [
            {
                "step": 1,
                "action": "up",
                "result": "applied",
                "decision": {
                    "chosen": "up",
                    "confidence": 0.85,
                    "source": "laya",
                    "probabilities": {"up": 0.85, "down": 0.05, "left": 0.05, "right": 0.05},
                },
                "timing": {"decide_ms": 12, "api_ms": 25, "turn_ms": 37},
                "hash": "abc123hash",
                "prev_hash": "GENESIS-test",
                "ts": "2026-10-17T00:00:00Z",
            }
        ]
        csv_str = records_to_csv_text(records)
        reader = list(csv.reader(io.StringIO(csv_str)))
        self.assertEqual(reader[0], CSV_FIELDNAMES)
        self.assertEqual(len(reader), 2)
        row = reader[1]
        self.assertEqual(row[0], "1")
        self.assertEqual(row[1], "up")
        self.assertEqual(row[2], "applied")
        self.assertEqual(row[3], "up")
        self.assertEqual(row[4], "0.8500")
        self.assertEqual(row[5], "laya")
        self.assertEqual(row[6], "12")
        self.assertEqual(row[7], "25")
        self.assertEqual(row[8], "37")
        self.assertEqual(row[9], "0.8500")
        self.assertEqual(row[13], "abc123hash")
        self.assertEqual(row[14], "GENESIS-test")

    def test_export_session_to_csv_from_file(self) -> None:
        logger = SessionLogger(session_id="test-csv-sess", game="snake", log_dir=self.tmp_dir)
        logger.log_move(
            step=1,
            state_before={"snake": [{"x": 5, "y": 5}]},
            action="up",
            state_after={"snake": [{"x": 5, "y": 4}]},
            result="applied",
            decision={
                "questions": ["Move?"],
                "probabilities": {"up": 0.7, "down": 0.1, "left": 0.1, "right": 0.1},
                "chosen": "up",
                "confidence": 0.7,
                "source": "laya",
            },
            timing={"decide_ms": 10, "api_ms": 15, "turn_ms": 25},
        )
        csv_content = export_session_to_csv(logger.log_path)
        self.assertIn("GENESIS-test-csv-sess", csv_content)
        self.assertIn("0.7000", csv_content)


if __name__ == "__main__":
    unittest.main()
