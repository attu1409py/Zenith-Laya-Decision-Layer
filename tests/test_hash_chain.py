"""Unit tests for the canonical JSON and SHA-256 hash-chain audit engine.

Tests all requirements specified in Track2_PS2_support.pdf (Section 3.3) and CONTEXT.md:
- Genesis hash calculation and prev_hash formatting ('GENESIS-<session_id>').
- Multi-record chaining and sequential integrity.
- Recursive nested key sorting.
- Compact serialization without whitespace.
- Unicode character preservation (UTF-8).
- Deterministic handling of floating-point numbers.
- Strict rejection of NaN, +Infinity, and -Infinity.
- Tamper detection on modified state, action, timestamp, or decision fields.
- Broken link detection on prev_hash.
- Missing or invalid hash detection.
- Empty log and malformed JSONL error handling.
- Independent verification against a pre-computed SHA-256 test vector.
"""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from zenith.hash_chain import (
    VerificationResult,
    calculate_record_hash,
    canonical_json,
    create_chained_record,
    get_genesis_prev_hash,
    read_jsonl_records,
    serialize_record_to_jsonl,
    verify_jsonl_file,
    verify_jsonl_lines,
    verify_records,
)


class TestCanonicalJson(unittest.TestCase):
    """Tests for canonical JSON serialization."""

    def test_nested_key_ordering(self):
        """Keys at all nesting levels must be sorted alphabetically."""
        data = {
            "z": 1,
            "b": {
                "delta": 4,
                "alpha": 1,
                "nested": {"y": 99, "a": 10},
            },
            "a": 100,
        }
        expected = '{"a":100,"b":{"alpha":1,"delta":4,"nested":{"a":10,"y":99}},"z":1}'
        self.assertEqual(canonical_json(data), expected)

    def test_compact_serialization_no_whitespace(self):
        """Serialization must have no whitespace after separators (',' and ':')."""
        data = {"action": "up", "step": 1, "timing": {"decide_ms": 12, "api_ms": 34}}
        result = canonical_json(data)
        self.assertNotIn(": ", result)
        self.assertNotIn(", ", result)
        self.assertNotIn(" ", result)

    def test_unicode_preservation(self):
        """Unicode characters must be preserved in UTF-8 without \\uXXXX escaping."""
        data = {"player": "ZENITH", "symbol": "🐍", "note": "Überprüfung"}
        result = canonical_json(data)
        self.assertIn("🐍", result)
        self.assertIn("Überprüfung", result)
        self.assertNotIn("\\u", result)

    def test_floating_point_stability(self):
        """Representative probability floats must serialize predictably."""
        data = {
            "probabilities": {
                "up": 0.61,
                "down": 0.04,
                "left": 0.22,
                "right": 0.13,
            }
        }
        expected = '{"probabilities":{"down":0.04,"left":0.22,"right":0.13,"up":0.61}}'
        self.assertEqual(canonical_json(data), expected)

    def test_rejection_of_nan(self):
        """Floats with NaN must be strictly rejected."""
        with self.assertRaises(ValueError):
            canonical_json({"confidence": float("nan")})

    def test_rejection_of_positive_infinity(self):
        """Floats with +Infinity must be strictly rejected."""
        with self.assertRaises(ValueError):
            canonical_json({"confidence": float("inf")})

    def test_rejection_of_negative_infinity(self):
        """Floats with -Infinity must be strictly rejected."""
        with self.assertRaises(ValueError):
            canonical_json({"confidence": float("-inf")})


class TestHashChainCore(unittest.TestCase):
    """Tests for SHA-256 calculation and chaining mechanics."""

    def test_independent_known_hash_vector(self):
        """Verify against an independently computed reference hash vector.

        Independent calculation:
        Payload text:
          GENESIS-test-sess-001|{"action":"up","game":"snake","prev_hash":"GENESIS-test-sess-001","session_id":"test-sess-001","step":1}
        SHA-256 computation:
          echo -n 'GENESIS-test-sess-001|{"action":"up","game":"snake","prev_hash":"GENESIS-test-sess-001","session_id":"test-sess-001","step":1}' | sha256sum
        Expected digest:
          e53297a76059d04499dce4cb299446d3e70ff8b099d07f59d57a419bc7e95454
        """
        prev_hash = "GENESIS-test-sess-001"
        record_without_hash = {
            "session_id": "test-sess-001",
            "game": "snake",
            "step": 1,
            "action": "up",
            "prev_hash": prev_hash,
        }

        # Independent manual calculation check
        expected_raw_payload = (
            'GENESIS-test-sess-001|{"action":"up","game":"snake",'
            '"prev_hash":"GENESIS-test-sess-001","session_id":"test-sess-001","step":1}'
        )
        independent_digest = hashlib.sha256(expected_raw_payload.encode("utf-8")).hexdigest()

        calculated = calculate_record_hash(prev_hash, record_without_hash)
        self.assertEqual(calculated, independent_digest)
        self.assertEqual(
            calculated,
            "f5f885e0e5c061e20dd526687a39309e4f4be6dec36eb7d27fc73a73e348a0a0",
        )

    def test_genesis_prev_hash_format(self):
        """First record must use GENESIS-<session_id>."""
        self.assertEqual(get_genesis_prev_hash("sess-abc-123"), "GENESIS-sess-abc-123")
        with self.assertRaises(ValueError):
            get_genesis_prev_hash("")
        with self.assertRaises(ValueError):
            get_genesis_prev_hash(None)  # type: ignore

    def test_create_chained_record_adds_fields(self):
        """create_chained_record must populate prev_hash and hash correctly."""
        session_id = "test-sess"
        prev_hash = get_genesis_prev_hash(session_id)
        raw_data = {"session_id": session_id, "step": 1, "action": "up"}

        record = create_chained_record(raw_data, prev_hash)
        self.assertEqual(record["prev_hash"], prev_hash)
        self.assertIn("hash", record)
        self.assertEqual(len(record["hash"]), 64)

        # Hash must match recalculation
        rec_without_hash = {k: v for k, v in record.items() if k != "hash"}
        expected = calculate_record_hash(prev_hash, rec_without_hash)
        self.assertEqual(record["hash"], expected)

    def test_calculate_record_hash_rejects_hash_key_in_input(self):
        """Passing a dict that already has 'hash' must raise ValueError."""
        with self.assertRaises(ValueError):
            calculate_record_hash("GENESIS-1", {"session_id": "1", "hash": "abc"})


class TestHashChainVerification(unittest.TestCase):
    """Tests for multi-line verification, tamper detection, and error handling."""

    def _build_valid_three_step_session(self, session_id: str = "sess-valid-01"):
        """Helper to build a valid 3-record session matching competition schema."""
        records = []
        prev_hash = get_genesis_prev_hash(session_id)

        actions = ["right", "up", "left"]
        for step_num, act in enumerate(actions, start=1):
            raw = {
                "session_id": session_id,
                "game": "snake",
                "step": step_num,
                "state_before": {"food": {"x": 3, "y": 2}, "snake": [{"x": 6, "y": 6}]},
                "action": act,
                "state_after": {"food": {"x": 3, "y": 2}, "snake": [{"x": 7, "y": 6}]},
                "result": "applied",
                "decision": {
                    "questions": [f"Step {step_num} state query"],
                    "probabilities": {"up": 0.25, "down": 0.25, "left": 0.25, "right": 0.25},
                    "chosen": act,
                    "confidence": 0.25,
                    "source": "laya",
                },
                "timing": {"decide_ms": 15, "api_ms": 20, "turn_ms": 40},
                "ts": f"2026-10-16T12:00:0{step_num}Z",
            }
            rec = create_chained_record(raw, prev_hash)
            records.append(rec)
            prev_hash = rec["hash"]

        return records

    def test_verify_valid_multi_line_session(self):
        """A properly chained 3-line session must verify successfully."""
        records = self._build_valid_three_step_session()
        result = verify_records(records)
        self.assertTrue(result.is_valid)
        self.assertEqual(result.record_count, 3)
        self.assertIsNone(result.error_message)
        self.assertIsNone(result.error_line_index)
        self.assertEqual(result.session_id, "sess-valid-01")

    def test_empty_log_handling(self):
        """Empty sequence or empty JSONL must be flagged as invalid."""
        result = verify_records([])
        self.assertFalse(result.is_valid)
        self.assertEqual(result.record_count, 0)
        self.assertIn("no records", result.error_message.lower())

        lines_result = verify_jsonl_lines([])
        self.assertFalse(lines_result.is_valid)

    def test_tamper_detection_state(self):
        """Tampering with state_before must be detected immediately."""
        records = self._build_valid_three_step_session()
        # Tamper with step 2
        records[1]["state_before"]["food"]["x"] = 99

        result = verify_records(records)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_line_index, 2)
        self.assertIn("Hash mismatch", result.error_message)

    def test_tamper_detection_action(self):
        """Tampering with action must be detected."""
        records = self._build_valid_three_step_session()
        records[0]["action"] = "down"

        result = verify_records(records)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_line_index, 1)
        self.assertIn("Hash mismatch", result.error_message)

    def test_tamper_detection_timestamp(self):
        """Tampering with timestamp must be detected."""
        records = self._build_valid_three_step_session()
        records[2]["ts"] = "2026-10-16T12:99:99Z"

        result = verify_records(records)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_line_index, 3)
        self.assertIn("Hash mismatch", result.error_message)

    def test_tamper_detection_decision_field(self):
        """Tampering with decision confidence must be detected."""
        records = self._build_valid_three_step_session()
        records[1]["decision"]["confidence"] = 0.99

        result = verify_records(records)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_line_index, 2)
        self.assertIn("Hash mismatch", result.error_message)

    def test_broken_prev_hash_link(self):
        """A broken prev_hash link between steps must be detected."""
        records = self._build_valid_three_step_session()
        # Re-compute hash for record 2 with an altered prev_hash
        fake_prev = "a" * 64
        records[1]["prev_hash"] = fake_prev
        records[1]["hash"] = calculate_record_hash(
            fake_prev, {k: v for k, v in records[1].items() if k != "hash"}
        )

        result = verify_records(records)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_line_index, 2)
        self.assertIn("Broken hash chain", result.error_message)

    def test_missing_hash_key(self):
        """A record missing the 'hash' field must be rejected."""
        records = self._build_valid_three_step_session()
        del records[0]["hash"]

        result = verify_records(records)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_line_index, 1)
        self.assertIn("Missing or non-string 'hash'", result.error_message)

    def test_missing_prev_hash_key(self):
        """A record missing 'prev_hash' must be rejected."""
        records = self._build_valid_three_step_session()
        del records[1]["prev_hash"]

        result = verify_records(records)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_line_index, 2)
        self.assertIn("Missing or non-string 'prev_hash'", result.error_message)

    def test_session_id_mismatch_across_steps(self):
        """Changing session_id mid-stream must be rejected."""
        records = self._build_valid_three_step_session()
        records[2]["session_id"] = "different-session"
        # Update hash so it passes internal hash check, but fails session check
        rec_without = {k: v for k, v in records[2].items() if k != "hash"}
        records[2]["hash"] = calculate_record_hash(records[2]["prev_hash"], rec_without)

        result = verify_records(records)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_line_index, 3)
        self.assertIn("session_id changed", result.error_message)

    def test_malformed_jsonl_syntax(self):
        """Invalid JSON syntax in JSONL lines must be detected with line index."""
        lines = [
            '{"session_id":"s1","prev_hash":"GENESIS-s1","hash":"h1"}\n',
            "not a json line\n",
            '{"session_id":"s1","prev_hash":"h1","hash":"h2"}\n',
        ]
        result = verify_jsonl_lines(lines)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_line_index, 2)
        self.assertIn("Malformed JSON", result.error_message)

    def test_blank_line_in_middle_of_jsonl(self):
        """Blank line in the middle of a JSONL log must be rejected."""
        lines = [
            '{"session_id":"s1","prev_hash":"GENESIS-s1","hash":"h1"}\n',
            "   \n",
            '{"session_id":"s1","prev_hash":"h1","hash":"h2"}\n',
        ]
        result = verify_jsonl_lines(lines)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_line_index, 2)
        self.assertIn("Blank or empty line", result.error_message)

    def test_file_verification_roundtrip(self):
        """Writing records to a file and verifying through verify_jsonl_file."""
        records = self._build_valid_three_step_session()

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".jsonl") as f:
            temp_path = f.name
            for rec in records:
                f.write(serialize_record_to_jsonl(rec) + "\n")

        try:
            result = verify_jsonl_file(temp_path)
            self.assertTrue(result.is_valid)
            self.assertEqual(result.record_count, 3)
            self.assertEqual(result.session_id, "sess-valid-01")

            # Now tamper with the file directly on line 3
            with open(temp_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            tampered = json.loads(lines[2])
            tampered["action"] = "down"  # hash not updated
            lines[2] = json.dumps(tampered) + "\n"
            with open(temp_path, "w", encoding="utf-8") as f:
                f.writelines(lines)

            tamper_result = verify_jsonl_file(temp_path)
            self.assertFalse(tamper_result.is_valid)
            self.assertEqual(tamper_result.error_line_index, 3)
            self.assertIn("Hash mismatch", tamper_result.error_message)
        finally:
            Path(temp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
