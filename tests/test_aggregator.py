"""Unit tests for zenith/aggregator.py.

Validates discovery, extraction, deduplication, hash-chain verification,
missing metadata handling, CSV/JSONL/Markdown consistency, and CLI interface.
No live Arena network calls are made.
"""

from __future__ import annotations

import csv
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

from zenith.aggregator import (
    SUMMARY_FIELDNAMES,
    classify_run_type,
    discover_and_aggregate_runs,
    export_to_csv,
    export_to_jsonl,
    generate_benchmark_report_md,
    load_benchmark_collections,
    parse_final_response,
    parse_jsonl_session,
    run_aggregator_cli,
)
from zenith.hash_chain import create_chained_record, get_genesis_prev_hash, serialize_record_to_jsonl


class TestAggregatorClassification(unittest.TestCase):
    """Tests for run type classification."""

    def test_classify_mock(self):
        self.assertEqual(classify_run_type("mock-snake-1234"), "mock")

    def test_classify_benchmark(self):
        self.assertEqual(classify_run_type("bench-v1-42"), "local_simulator")
        self.assertEqual(classify_run_type("custom-sim", is_benchmark_entry=True), "local_simulator")

    def test_classify_live_arena(self):
        self.assertEqual(
            classify_run_type("f240cb86-0d3d-4445-9708-79989ecff36e"),
            "live_arena",
        )
        self.assertEqual(
            classify_run_type("12345678-1234-1234-1234-123456789abc"),
            "live_arena",
        )


class TestAggregatorProcessing(unittest.TestCase):
    """Tests for parsing, aggregation, and export logic."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="zenith_test_agg_")
        self.tmp_path = Path(self._tmp_dir)

    def tearDown(self):
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def _create_synthetic_jsonl_session(
        self,
        session_id: str,
        game: str = "snake",
        num_moves: int = 3,
        question_text: str = "Which safe direction should the snake choose to advance toward the food?",
        source: str = "laya",
    ) -> Path:
        """Create a cryptographically valid JSONL log file for testing."""
        log_file = self.tmp_path / f"{session_id}.jsonl"
        prev_hash = get_genesis_prev_hash(session_id)

        with open(log_file, "w", encoding="utf-8") as f:
            for step in range(1, num_moves + 1):
                raw_rec = {
                    "session_id": session_id,
                    "game": game,
                    "step": step,
                    "state_before": {"snake": [{"x": 6, "y": 6}], "food": {"x": 6, "y": 5}, "foodEaten": step - 1},
                    "action": "up",
                    "state_after": {"snake": [{"x": 6, "y": 5}], "food": {"x": 6, "y": 4}, "foodEaten": step},
                    "result": "applied",
                    "decision": {
                        "questions": [question_text],
                        "probabilities": {"up": 0.7, "down": 0.1, "left": 0.1, "right": 0.1},
                        "chosen": "up",
                        "confidence": 0.7,
                        "source": source,
                    },
                    "timing": {"decide_ms": 50, "api_ms": 20, "turn_ms": 70},
                    "ts": f"2026-10-16T12:00:0{step}Z",
                }
                chained = create_chained_record(raw_rec, prev_hash)
                f.write(serialize_record_to_jsonl(chained) + "\n")
                prev_hash = chained["hash"]

        return log_file

    def test_parse_valid_jsonl_session(self):
        """parse_jsonl_session correctly parses metrics and verifies hash chain."""
        log_file = self._create_synthetic_jsonl_session("sess-valid-1", num_moves=4)
        info = parse_jsonl_session(log_file, check_hash=True)

        self.assertEqual(info["session_id"], "sess-valid-1")
        self.assertEqual(info["game"], "snake")
        self.assertEqual(info["applied_moves"], 4)
        self.assertEqual(info["rejected_moves"], 0)
        self.assertEqual(info["fallback_moves"], 0)
        self.assertEqual(info["avg_decision_ms"], 50.0)
        self.assertEqual(info["total_duration_s"], 3.0)
        self.assertTrue(info["hash_chain_valid"])
        self.assertEqual(info["prompt_version"], "v2")
        self.assertIsNone(info["error"])

    def test_parse_tampered_jsonl_session(self):
        """Tampering with any byte of a JSONL log must report hash_chain_valid=False."""
        log_file = self._create_synthetic_jsonl_session("sess-tampered", num_moves=3)
        # Tamper with the file
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        tampered_line = lines[1].replace('"confidence":0.7', '"confidence":0.99')
        lines[1] = tampered_line
        with open(log_file, "w", encoding="utf-8") as f:
            f.writelines(lines)

        info = parse_jsonl_session(log_file, check_hash=True)
        self.assertFalse(info["hash_chain_valid"])
        self.assertIsNotNone(info["error"])

    def test_parse_malformed_jsonl_line(self):
        """Malformed JSON line must not crash parser and should set hash_chain_valid=False."""
        log_file = self.tmp_path / "sess-corrupted.jsonl"
        with open(log_file, "w", encoding="utf-8") as f:
            f.write('{"session_id":"sess-corrupted","step":1}\n')
            f.write('CORRUPTED NOT JSON LINE\n')
            f.write('{"session_id":"sess-corrupted","step":2}\n')

        info = parse_jsonl_session(log_file, check_hash=False)
        self.assertFalse(info["hash_chain_valid"])
        self.assertIn("Malformed JSON", info["error"])

    def test_missing_optional_metadata_remains_null(self):
        """Missing optional metadata fields must remain strictly None / null without fabrication."""
        log_file = self._create_synthetic_jsonl_session("sess-no-meta", num_moves=1)
        records = discover_and_aggregate_runs(
            log_dirs=[self.tmp_path],
            check_hash=True,
            aggregation_timestamp="2026-10-17T00:00:00Z",
        )

        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["session_id"], "sess-no-meta")
        self.assertIsNone(rec["agent_name"])
        self.assertIsNone(rec["model_id"])
        self.assertIsNone(rec["seed"])
        self.assertIsNone(rec["score"])  # No _final.json present
        self.assertIsNone(rec["won"])
        self.assertIsNone(rec["termination_reason"])

    def test_duplicate_handling_and_determinism(self):
        """Aggregator must deduplicate multiple occurrences of the same session and sort deterministically."""
        # Create session in subfolder 1
        dir1 = self.tmp_path / "run_set_a"
        dir1.mkdir()
        self._create_synthetic_jsonl_session("sess-dup-1", num_moves=2)
        shutil.copy(self.tmp_path / "sess-dup-1.jsonl", dir1 / "sess-dup-1.jsonl")

        # Discover across multiple directories containing the duplicate
        records1 = discover_and_aggregate_runs(
            [self.tmp_path, dir1],
            check_hash=False,
            aggregation_timestamp="2026-10-17T00:00:00Z",
        )
        records2 = discover_and_aggregate_runs(
            [dir1, self.tmp_path],
            check_hash=False,
            aggregation_timestamp="2026-10-17T00:00:00Z",
        )

        # Count must be exactly 1, not 2
        self.assertEqual(len(records1), 1)
        self.assertEqual(len(records2), 1)
        self.assertEqual(records1[0]["session_id"], "sess-dup-1")
        self.assertEqual(records1, records2)

    def test_jsonl_and_csv_consistency(self):
        """Exported JSONL and CSV must contain identical record counts and corresponding fields."""
        # Create 2 sessions: 1 mock, 1 live
        self._create_synthetic_jsonl_session("mock-snake-test", num_moves=2)
        self._create_synthetic_jsonl_session("88888888-4444-4444-4444-121212121212", num_moves=3)

        records = discover_and_aggregate_runs([self.tmp_path], check_hash=True)
        self.assertEqual(len(records), 2)

        jsonl_path = self.tmp_path / "run_history.jsonl"
        csv_path = self.tmp_path / "run_history.csv"

        export_to_jsonl(records, jsonl_path)
        export_to_csv(records, csv_path)

        # Read JSONL
        with open(jsonl_path, "r", encoding="utf-8") as f:
            jsonl_lines = [json.loads(line) for line in f if line.strip()]

        # Read CSV
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            csv_rows = list(reader)

        self.assertEqual(len(jsonl_lines), len(records))
        self.assertEqual(len(csv_rows), len(records))

        for j_rec, c_row in zip(jsonl_lines, csv_rows):
            self.assertEqual(j_rec["session_id"], c_row["session_id"])
            self.assertEqual(j_rec["run_type"], c_row["run_type"])
            self.assertEqual(j_rec["applied_moves"], int(c_row["applied_moves"]))
            # Boolean check
            expected_hash_str = "true" if j_rec["hash_chain_valid"] else "false"
            self.assertEqual(c_row["hash_chain_valid"], expected_hash_str)

    def test_benchmark_collection_merging(self):
        """Benchmark JSON summaries merge with corresponding JSONL logs seamlessly."""
        # Create bench-v1-42.jsonl
        self._create_synthetic_jsonl_session(
            "bench-v1-42",
            num_moves=7,
            question_text="In this Snake game on a 12x12 board, which way to go?",
        )
        # Create baseline_v1.json
        bench_json = [
            {
                "seed": 42,
                "prompt_version": "v1",
                "model_id": "convaiinnovations/laya",
                "score": 0,
                "food_eaten": 0,
                "accepted_moves": 7,
                "rejected_moves": 0,
                "won": False,
                "termination_reason": "wall_collision",
                "log_path": str(self.tmp_path / "bench-v1-42.jsonl"),
            }
        ]
        with open(self.tmp_path / "baseline_v1.json", "w", encoding="utf-8") as f:
            json.dump(bench_json, f)

        # Create bench-v1-42_final.json
        final_json = {
            "session_id": "bench-v1-42",
            "game": "snake",
            "agent_name": "ZENITH",
            "done": True,
            "won": False,
            "score": 0,
            "state": {"foodEaten": 0},
            "message": "wall_collision",
        }
        with open(self.tmp_path / "bench-v1-42_final.json", "w", encoding="utf-8") as f:
            json.dump(final_json, f)

        records = discover_and_aggregate_runs([self.tmp_path], check_hash=True)
        self.assertEqual(len(records), 1)
        r = records[0]

        self.assertEqual(r["session_id"], "bench-v1-42")
        self.assertEqual(r["run_type"], "local_simulator")
        self.assertEqual(r["agent_name"], "ZENITH")
        self.assertEqual(r["model_id"], "convaiinnovations/laya")
        self.assertEqual(r["prompt_version"], "v1")
        self.assertEqual(r["seed"], 42)
        self.assertEqual(r["score"], 0)
        self.assertEqual(r["steps"], 7)
        self.assertFalse(r["won"])
        self.assertEqual(r["termination_reason"], "wall_collision")
        self.assertTrue(r["hash_chain_valid"])

    def test_markdown_report_generation(self):
        """Markdown report contains attribution audit, run history, and non-equivalence notice."""
        records = [
            {
                "session_id": "f240cb86-0d3d-4445-9708-79989ecff36e",
                "game": "snake",
                "run_type": "live_arena",
                "agent_name": None,
                "model_id": None,
                "prompt_version": "v2",
                "seed": None,
                "score": 1000,
                "steps": 152,
                "foods_eaten": 15,
                "won": True,
                "done": True,
                "termination_reason": "Solved in 152 steps!",
                "applied_moves": 152,
                "rejected_moves": 0,
                "fallback_moves": 0,
                "avg_decision_ms": 99.49,
                "total_duration_s": 103.0,
                "hash_chain_valid": True,
                "log_path": "logs/f240cb86-0d3d-4445-9708-79989ecff36e.jsonl",
                "run_timestamp": "2026-10-16T19:04:32Z",
                "aggregated_at": "2026-10-17T00:00:00Z",
            }
        ]

        md_path = self.tmp_path / "benchmark_report.md"
        generate_benchmark_report_md(records, md_path)

        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("# Team ZENITH - Run History and Benchmark Report", content)
        self.assertIn("Official Live Arena Session", content)
        self.assertIn("f240cb86-0d3d-4445-9708-79989ecff36e", content)
        self.assertIn("Leaderboard Attribution Audit Findings", content)
        self.assertIn("Simulator Equivalence Disclaimer", content)
        self.assertIn("Cryptographic Hash Chain Audit Status", content)

    def test_cli_runner_execution(self):
        """run_aggregator_cli executes cleanly with custom directories."""
        self._create_synthetic_jsonl_session("sess-cli-test", num_moves=1)
        out_dir = self.tmp_path / "output"

        code = run_aggregator_cli([
            "--log-dirs", str(self.tmp_path),
            "--output-dir", str(out_dir),
            "--no-hash-check",
        ])
        self.assertEqual(code, 0)
        self.assertTrue((out_dir / "run_history.jsonl").is_file())
        self.assertTrue((out_dir / "run_history.csv").is_file())
        self.assertTrue((out_dir / "benchmark_report.md").is_file())


if __name__ == "__main__":
    unittest.main()
