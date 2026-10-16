"""Unit tests for zenith/session_logger.py.

Tests:
- First record genesis linkage (prev_hash = 'GENESIS-<session_id>').
- Multi-record cryptographic chaining.
- Logging applied and rejected move records.
- Preservation of raw state_before and state_after dictionaries.
- Timing validation (non-negative integers, rejection of booleans/negatives).
- UTC ISO-8601 timestamp handling.
- Rejection of malformed records (no silent discard/corruption).
- Immediate flush and append behavior.
- Full-file verification using verify_jsonl_file / verify_log.
- Tamper detection on modified records in the file.
- Preservation of caller-supplied step values (including rejected moves).
- Persisting final Arena response JSON.
- MonotonicStopwatch accurate integer millisecond timing.
"""

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from zenith.decision_validator import DecisionValidationError
from zenith.hash_chain import verify_jsonl_file
from zenith.session_logger import (
    MonotonicStopwatch,
    SessionLogger,
    SessionLoggerError,
)


class TestSessionLogger(unittest.TestCase):
    """Test suite for SessionLogger append-only JSONL writing and integrity."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="zenith_test_logs_")
        self.session_id = "test-session-uuid-001"
        self.game = "snake"
        self.logger = SessionLogger(
            session_id=self.session_id,
            game=self.game,
            log_dir=self.temp_dir,
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _sample_decision(self, action="up", source="laya"):
        return {
            "questions": ["Next move for Snake?"],
            "probabilities": {"up": 0.70, "down": 0.10, "left": 0.10, "right": 0.10},
            "chosen": action,
            "confidence": 0.70,
            "source": source,
        }

    def _sample_timing(self, decide=15, api=25, turn=45):
        return {"decide_ms": decide, "api_ms": api, "turn_ms": turn}

    def test_first_record_genesis_linkage(self):
        """The first record written must have prev_hash equal to GENESIS-<session_id>."""
        record = self.logger.log_move(
            step=1,
            state_before={"snake": [{"x": 6, "y": 6}], "food": {"x": 3, "y": 2}},
            action="up",
            state_after={"snake": [{"x": 6, "y": 5}], "food": {"x": 3, "y": 2}},
            result="applied",
            decision=self._sample_decision(action="up"),
            timing=self._sample_timing(),
        )

        self.assertEqual(record["prev_hash"], f"GENESIS-{self.session_id}")
        self.assertIn("hash", record)
        self.assertEqual(len(record["hash"]), 64)
        self.assertEqual(self.logger.record_count, 1)

    def test_multi_record_chaining(self):
        """Sequential records must chain each subsequent prev_hash to the previous hash."""
        rec1 = self.logger.log_move(
            step=1,
            state_before={"step": 0},
            action="up",
            state_after={"step": 1},
            result="applied",
            decision=self._sample_decision(action="up"),
            timing=self._sample_timing(),
        )

        rec2 = self.logger.log_move(
            step=2,
            state_before={"step": 1},
            action="up",
            state_after={"step": 2},
            result="applied",
            decision=self._sample_decision(action="up"),
            timing=self._sample_timing(),
        )

        rec3 = self.logger.log_move(
            step=3,
            state_before={"step": 2},
            action="up",
            state_after={"step": 3},
            result="applied",
            decision=self._sample_decision(action="up"),
            timing=self._sample_timing(),
        )

        self.assertEqual(rec2["prev_hash"], rec1["hash"])
        self.assertEqual(rec3["prev_hash"], rec2["hash"])
        self.assertEqual(self.logger.record_count, 3)

        # File-level verification
        verification = self.logger.verify_log()
        self.assertTrue(verification.is_valid)
        self.assertEqual(verification.record_count, 3)
        self.assertEqual(verification.session_id, self.session_id)

    def test_applied_and_rejected_moves_logged(self):
        """Both applied and rejected moves must be written and chained without issue."""
        rec1 = self.logger.log_move(
            step=1,
            state_before={"score": 0},
            action="up",
            state_after={"score": 60},
            result="applied",
            decision=self._sample_decision(action="up"),
            timing=self._sample_timing(),
        )

        rec2 = self.logger.log_move(
            step=1,  # Same step count preserved if caller does not advance on rejection
            state_before={"score": 60},
            action="up",
            state_after={"score": 60},
            result="rejected",
            decision=self._sample_decision(action="up"),
            timing=self._sample_timing(),
        )

        self.assertEqual(rec1["result"], "applied")
        self.assertEqual(rec2["result"], "rejected")
        self.assertEqual(rec2["prev_hash"], rec1["hash"])

        verification = self.logger.verify_log()
        self.assertTrue(verification.is_valid)
        self.assertEqual(verification.record_count, 2)

    def test_exact_state_preservation(self):
        """state_before and state_after must be preserved exactly as passed."""
        complex_state_before = {
            "grid": [[0, 1, 2], [3, 0, 0]],
            "snake": [{"x": 1, "y": 2, "extra": "data"}],
            "nested": {"deep": {"value": 42}},
        }
        complex_state_after = {
            "grid": [[0, 0, 2], [1, 3, 0]],
            "snake": [{"x": 1, "y": 3, "extra": "data"}],
            "nested": {"deep": {"value": 43}},
        }

        rec = self.logger.log_move(
            step=1,
            state_before=complex_state_before,
            action="up",
            state_after=complex_state_after,
            result="applied",
            decision=self._sample_decision(action="up"),
            timing=self._sample_timing(),
        )

        self.assertEqual(rec["state_before"], complex_state_before)
        self.assertEqual(rec["state_after"], complex_state_after)

        # Check raw JSON on disk
        with open(self.logger.log_path, "r", encoding="utf-8") as f:
            disk_line = json.loads(f.readline())
        self.assertEqual(disk_line["state_before"], complex_state_before)
        self.assertEqual(disk_line["state_after"], complex_state_after)

    def test_timing_validation_rejection_of_booleans_and_negatives(self):
        """Timing fields must be non-negative integers; booleans and negatives must be rejected."""
        # Boolean decide_ms rejected
        with self.assertRaises(SessionLoggerError):
            self.logger.log_move(
                step=1,
                state_before={},
                action="up",
                state_after={},
                result="applied",
                decision=self._sample_decision("up"),
                timing={"decide_ms": True, "api_ms": 10, "turn_ms": 20},
            )

        # Negative api_ms rejected
        with self.assertRaises(SessionLoggerError):
            self.logger.log_move(
                step=1,
                state_before={},
                action="up",
                state_after={},
                result="applied",
                decision=self._sample_decision("up"),
                timing={"decide_ms": 10, "api_ms": -5, "turn_ms": 20},
            )

        # Missing turn_ms rejected
        with self.assertRaises(SessionLoggerError):
            self.logger.log_move(
                step=1,
                state_before={},
                action="up",
                state_after={},
                result="applied",
                decision=self._sample_decision("up"),
                timing={"decide_ms": 10, "api_ms": 10},
            )

    def test_timestamp_formatting(self):
        """Timestamps must default to UTC ISO-8601 ending in 'Z'."""
        rec = self.logger.log_move(
            step=1,
            state_before={},
            action="up",
            state_after={},
            result="applied",
            decision=self._sample_decision("up"),
            timing=self._sample_timing(),
        )
        self.assertTrue(rec["ts"].endswith("Z"))
        self.assertIn("T", rec["ts"])

        # Custom valid UTC timestamp preserved
        custom_ts = "2026-11-07T09:30:12Z"
        rec2 = self.logger.log_move(
            step=2,
            state_before={},
            action="up",
            state_after={},
            result="applied",
            decision=self._sample_decision("up"),
            timing=self._sample_timing(),
            ts=custom_ts,
        )
        self.assertEqual(rec2["ts"], custom_ts)

    def test_malformed_step_rejected(self):
        """Invalid step numbers must be rejected."""
        with self.assertRaises(SessionLoggerError):
            self.logger.log_move(
                step=0,  # Must start at 1
                state_before={},
                action="up",
                state_after={},
                result="applied",
                decision=self._sample_decision("up"),
                timing=self._sample_timing(),
            )
        with self.assertRaises(SessionLoggerError):
            self.logger.log_move(
                step=True,  # Boolean rejected
                state_before={},
                action="up",
                state_after={},
                result="applied",
                decision=self._sample_decision("up"),
                timing=self._sample_timing(),
            )

    def test_invalid_decision_aborts_write(self):
        """If decision fails validation, nothing must be written to disk."""
        invalid_decision = self._sample_decision("up")
        invalid_decision["confidence"] = 0.99  # Does not match probabilities['up']

        initial_size = self.logger.log_path.stat().st_size if self.logger.log_path.exists() else 0

        with self.assertRaises(DecisionValidationError):
            self.logger.log_move(
                step=1,
                state_before={},
                action="up",
                state_after={},
                result="applied",
                decision=invalid_decision,
                timing=self._sample_timing(),
            )

        final_size = self.logger.log_path.stat().st_size if self.logger.log_path.exists() else 0
        self.assertEqual(initial_size, final_size)
        self.assertEqual(self.logger.record_count, 0)

    def test_tamper_detection_on_disk(self):
        """Modifying any byte on disk must trigger verification failure."""
        self.logger.log_move(
            step=1,
            state_before={"score": 0},
            action="up",
            state_after={"score": 60},
            result="applied",
            decision=self._sample_decision("up"),
            timing=self._sample_timing(),
        )
        self.logger.log_move(
            step=2,
            state_before={"score": 60},
            action="up",
            state_after={"score": 120},
            result="applied",
            decision=self._sample_decision("up"),
            timing=self._sample_timing(),
        )

        # File is currently valid
        self.assertTrue(self.logger.verify_log().is_valid)

        # Tamper line 1 on disk
        with open(self.logger.log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        data = json.loads(lines[0])
        data["action"] = "down"  # Changed without recomputing hash
        lines[0] = json.dumps(data) + "\n"
        with open(self.logger.log_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        # Verification must now fail on line 1
        verif = self.logger.verify_log()
        self.assertFalse(verif.is_valid)
        self.assertEqual(verif.error_line_index, 1)

    def test_save_final_response(self):
        """save_final_response must write formatted JSON to log directory immediately."""
        final_data = {
            "session_id": self.session_id,
            "game": "snake",
            "score": 660,
            "won": True,
            "steps": 150,
        }
        saved_path = self.logger.save_final_response(final_data)

        self.assertTrue(saved_path.is_file())
        with open(saved_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertEqual(loaded, final_data)

    def test_monotonic_stopwatch(self):
        """MonotonicStopwatch must record non-negative elapsed milliseconds."""
        timer = MonotonicStopwatch()
        time.sleep(0.01)  # 10ms
        elapsed = timer.elapsed_ms()
        self.assertIsInstance(elapsed, int)
        self.assertGreaterEqual(elapsed, 5)

        timer.reset()
        elapsed_after_reset = timer.elapsed_ms()
        self.assertGreaterEqual(elapsed_after_reset, 0)


if __name__ == "__main__":
    unittest.main()
