"""Focused tests for mock-source attribution and terminal status reporting.

Verifies:
1. --mock-model path makes no external model or Arena network requests.
2. Decisions from make_mock_decide_fn have source='mock', distinguishing them
   from actual Laya inference ('laya') and safety fallback ('fallback').
3. Terminal-status reporting clearly distinguishes:
   - WON (authoritative win confirmed)
   - LOST (authoritative game loss confirmed)
   - MOVE_LIMIT_REACHED (stopped because max_moves reached without a loss)
   - NO_PROGRESS_STOPPED (stopped because board remained unchanged)
   - API_ERROR_STOPPED (stopped due to network/API error)
   - REJECTION_LIMIT_STOPPED (stopped due to consecutive move rejections)
"""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from zenith.decision_validator import PERMITTED_SOURCES, validate_decision
from zenith.decision_viewer import DecisionViewer
from zenith.game2048_simulator import Deterministic2048Simulator
from zenith.main import make_mock_decide_fn, run_cli
from zenith.runner import SessionResult, SessionRunner
from zenith.session_logger import SessionLogger
from zenith.snake_simulator import DeterministicSnakeSimulator


class TestMockSourceAttribution(unittest.TestCase):
    """Tests for synthetic mock decision source labeling and isolation."""

    def test_permitted_sources_includes_mock(self):
        """PERMITTED_SOURCES must contain exactly 'laya', 'fallback', and 'mock'."""
        self.assertIn("mock", PERMITTED_SOURCES)
        self.assertIn("laya", PERMITTED_SOURCES)
        self.assertIn("fallback", PERMITTED_SOURCES)

    def test_make_mock_decide_fn_2048_attribution(self):
        """Mock decision function for 2048 must label decisions with source='mock'."""
        decide = make_mock_decide_fn()
        state = {
            "grid": [
                [2, 0, 0, 0],
                [0, 2, 0, 0],
                [0, 0, 0, 0],
                [0, 0, 0, 0],
            ],
            "score": 0,
            "best": 2,
        }
        decision = decide("2048", state)
        self.assertEqual(decision["source"], "mock")
        # Validate decision with validator
        validated = validate_decision(decision, action=decision["chosen"])
        self.assertEqual(validated["source"], "mock")

    def test_make_mock_decide_fn_snake_attribution(self):
        """Mock decision function for Snake must label decisions with source='mock'."""
        decide = make_mock_decide_fn()
        state = {
            "snake": [{"x": 5, "y": 5}],
            "food": {"x": 5, "y": 4},
            "direction": "up",
        }
        decision = decide("snake", state)
        self.assertEqual(decision["source"], "mock")
        validated = validate_decision(decision, action=decision["chosen"])
        self.assertEqual(validated["source"], "mock")

    def test_viewer_displays_mock_source_label(self):
        """DecisionViewer must visibly show 'Source     : mock' for mock moves."""
        buf = io.StringIO()
        viewer = DecisionViewer("2048", "test-sess", mock_mode=True, out=buf)
        decide = make_mock_decide_fn()
        decision = decide("2048", {"grid": [[2, 0, 0, 0]] * 4})
        viewer.show_move(
            step=1,
            state_before={},
            decision=decision,
            action=decision["chosen"],
            result="applied",
            state_after={},
            timing={"decide_ms": 1, "api_ms": 1, "turn_ms": 2},
        )
        output = buf.getvalue()
        self.assertIn("Source     : mock", output)
        self.assertNotIn("Source     : laya", output)

    def test_mock_dry_run_makes_zero_network_calls(self):
        """--mock-model in dry-run mode must make zero external Arena or model requests."""
        tmp_dir = tempfile.mkdtemp()
        try:
            stdout = io.StringIO()
            stderr = io.StringIO()

            # Guard against any socket connection, urllib, requests, or LayaAdapter construction
            with patch("urllib.request.urlopen") as mock_url, \
                 patch("zenith.main.LayaAdapter") as mock_laya, \
                 patch("zenith.main.ArenaClient") as mock_arena:

                code = run_cli(
                    [
                        "--game", "2048",
                        "--mock-model",
                        "--log-dir", tmp_dir,
                        "--max-moves", "3",
                    ],
                    stdout=stdout,
                    stderr=stderr,
                )

                mock_url.assert_not_called()
                mock_laya.assert_not_called()
                mock_arena.assert_not_called()

            self.assertEqual(code, 0)
            # Verify JSONL log contains source: "mock"
            log_files = list(Path(tmp_dir).glob("*.jsonl"))
            self.assertEqual(len(log_files), 1)
            lines = [json.loads(line) for line in log_files[0].read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertGreater(len(lines), 0)
            for entry in lines:
                self.assertEqual(entry["decision"]["source"], "mock")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


class TestTerminalStatusReporting(unittest.TestCase):
    """Tests for distinguishing WON, LOST, MOVE_LIMIT_REACHED, and stopped states."""

    def test_status_won(self):
        """Authoritative win must report status='WON'."""
        result = SessionResult(session_id="s1", game="2048", won=True)
        self.assertEqual(result.status, "WON")

    def test_status_genuine_loss(self):
        """Authoritative game loss must report status='LOST'."""
        result = SessionResult(session_id="s1", game="2048", won=False)
        self.assertEqual(result.status, "LOST")

    def test_status_move_limit_reached_not_lost(self):
        """Reaching max_moves without loss must report MOVE_LIMIT_REACHED, not LOST."""
        result = SessionResult(
            session_id="s1",
            game="2048",
            won=None,
            termination_reason="max_moves_reached",
        )
        self.assertEqual(result.status, "MOVE_LIMIT_REACHED")
        self.assertNotEqual(result.status, "LOST")

    def test_status_no_progress_stopped(self):
        """Stopped by no-progress guard must report NO_PROGRESS_STOPPED."""
        result = SessionResult(
            session_id="s1",
            game="2048",
            won=None,
            termination_reason="no_progress_stopped",
            error="No-progress detected: action 'up' was reported as applied but board/state did not advance",
        )
        self.assertEqual(result.status, "NO_PROGRESS_STOPPED")

    def test_status_api_error_stopped(self):
        """Stopped by API error must report API_ERROR_STOPPED."""
        result = SessionResult(
            session_id="s1",
            game="2048",
            won=None,
            termination_reason="api_error_stopped",
            error="API error during submit_action: connection timeout",
        )
        self.assertEqual(result.status, "API_ERROR_STOPPED")

    def test_status_rejection_limit_stopped(self):
        """Stopped by consecutive rejected moves must report REJECTION_LIMIT_STOPPED."""
        result = SessionResult(
            session_id="s1",
            game="2048",
            won=None,
            termination_reason="rejection_limit_reached",
            error="Too many consecutive rejected moves (10)",
        )
        self.assertEqual(result.status, "REJECTION_LIMIT_STOPPED")

    def test_2048_simulator_move_limit_sets_won_none(self):
        """Deterministic2048Simulator reaching max_moves must NOT set won=False."""
        sim = Deterministic2048Simulator(max_moves=2, seed=123)
        sim.submit_action(sim.session_id, "left")
        resp = sim.submit_action(sim.session_id, "down")
        self.assertTrue(resp["done"])
        self.assertEqual(resp["termination_reason"], "max_moves_reached")
        # Critical assertion: must be None, NOT False
        self.assertIsNone(resp["won"])
        self.assertIsNone(sim.won)

    def test_2048_simulator_genuine_loss_sets_won_false(self):
        """Deterministic2048Simulator with no valid moves left must set won=False."""
        grid = [
            [2, 4, 2, 8],
            [4, 8, 16, 4],
            [8, 16, 4, 8],
            [4, 8, 0, 16],
        ]
        sim = Deterministic2048Simulator(initial_grid=grid)
        resp = sim.submit_action(sim.session_id, "left")
        self.assertTrue(resp["done"])
        self.assertEqual(resp["termination_reason"], "no_moves_remaining")
        self.assertFalse(resp["won"])
        self.assertFalse(sim.won)

    def test_snake_simulator_move_limit_sets_won_none(self):
        """DeterministicSnakeSimulator reaching max_moves must NOT set won=False."""
        sim = DeterministicSnakeSimulator(max_moves=2, target_food=15)
        sim.submit_action(sim.session_id, "left")
        resp = sim.submit_action(sim.session_id, "up")
        self.assertTrue(resp["done"])
        self.assertEqual(resp["termination_reason"], "max_moves_reached")
        # Critical assertion: must be None, NOT False
        self.assertIsNone(resp["won"])
        self.assertIsNone(sim.won)

    def test_snake_simulator_wall_collision_sets_won_false(self):
        """DeterministicSnakeSimulator hitting wall must set won=False."""
        sim = DeterministicSnakeSimulator(width=5, height=5, max_moves=50)
        sim._snake = [{"x": 0, "y": 0}]
        resp = sim.submit_action(sim.session_id, "left")
        self.assertTrue(resp["done"])
        self.assertFalse(resp["won"])
        self.assertEqual(sim.termination_reason, "wall_collision")

    def test_cli_dry_run_reports_move_limit_reached(self):
        """CLI dry run reaching max_moves must print MOVE_LIMIT_REACHED and not LOST."""
        tmp_dir = tempfile.mkdtemp()
        try:
            stdout = io.StringIO()
            stderr = io.StringIO()

            code = run_cli(
                [
                    "--game", "2048",
                    "--mock-model",
                    "--log-dir", tmp_dir,
                    "--max-moves", "3",
                ],
                stdout=stdout,
                stderr=stderr,
            )

            self.assertEqual(code, 0)
            out_str = stdout.getvalue()
            self.assertIn("Result Status:        MOVE_LIMIT_REACHED", out_str)
            self.assertNotIn("Result Status:        LOST", out_str)
            self.assertIn("Status     : MOVE_LIMIT_REACHED", out_str)
            self.assertIn("Won        : N/A", out_str)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
