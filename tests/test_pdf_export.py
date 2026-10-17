"""Unit tests for PDF export utility."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zenith.pdf_export import generate_session_pdf
from zenith.session_logger import SessionLogger


class TestPdfExport(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()

    def test_generate_session_pdf_creates_valid_pdf_bytes(self) -> None:
        logger = SessionLogger(session_id="test-pdf-sess", game="snake", log_dir=self.tmp_dir)
        for i in range(1, 4):
            logger.log_move(
                step=i,
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

        pdf_bytes = generate_session_pdf(logger.log_path)
        self.assertTrue(len(pdf_bytes) > 100)
        # Standard PDF magic header
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_generate_session_pdf_missing_file_raises(self) -> None:
        missing_path = Path(self.tmp_dir) / "does_not_exist.jsonl"
        with self.assertRaises(FileNotFoundError):
            generate_session_pdf(missing_path)


if __name__ == "__main__":
    unittest.main()
