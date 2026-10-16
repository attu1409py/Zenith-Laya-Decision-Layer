"""Unit tests for zenith.runner using mock adapters.

Validates the SessionRunner orchestration loop using deterministic mock
arena, mock decision function, and real SessionLogger/DecisionViewer
instances. No live network calls are made.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from zenith.decision_validator import FallbackTracker
from zenith.decision_viewer import DecisionViewer
from zenith.runner import SessionRunner, SessionResult, _extract_state
from zenith.session_logger import SessionLogger


# ── Mock Arena Adapter ─────────────────────────────────────────────────

class MockArena:
    """Deterministic mock arena that replays a scripted game.

    Each call to submit_action consumes the next response from the script.
    """

    def __init__(self, session_id: str, script: List[Dict[str, Any]]):
        """Initialize with a scripted sequence of submit_action responses.

        Args:
            session_id: The session ID to return.
            script: Ordered list of response dicts that submit_action returns.
                    Each must include at minimum: state, done, score.
        """
        self._session_id = session_id
        self._script = list(script)
        self._index = 0
        self._initial_state: Dict[str, Any] = {
            "session_id": session_id,
            "game": "snake",
            "state": {"snake": [[5, 5]], "food": [3, 3], "direction": "right"},
            "done": False,
            "score": 0,
        }

    def create_session(self, game: str, agent_name: str) -> Dict[str, Any]:
        return dict(self._initial_state)

    def get_session(self, session_id: str) -> Dict[str, Any]:
        return dict(self._initial_state)

    def submit_action(self, session_id: str, action: str) -> Dict[str, Any]:
        if self._index >= len(self._script):
            # Game over if script exhausted
            return {
                "session_id": session_id,
                "state": {"snake": [[5, 5]], "food": [3, 3]},
                "done": True,
                "score": 0,
                "won": False,
                "result": "applied",
            }
        resp = self._script[self._index]
        self._index += 1
        resp.setdefault("session_id", session_id)
        resp.setdefault("result", "applied")
        return resp


def _laya_decision(game: str, state: Mapping[str, Any]) -> Dict[str, Any]:
    """Mock Laya decision function that always chooses 'up'."""
    return {
        "questions": [f"Given the {game} state, which direction?"],
        "probabilities": {"up": 0.70, "down": 0.10, "left": 0.10, "right": 0.10},
        "chosen": "up",
        "confidence": 0.70,
        "source": "laya",
    }


def _fallback_decision(game: str, state: Mapping[str, Any]) -> Dict[str, Any]:
    """Mock fallback decision function."""
    return {
        "questions": [f"Fallback for {game}"],
        "probabilities": {"up": 0.25, "down": 0.25, "left": 0.25, "right": 0.25},
        "chosen": "up",
        "confidence": 0.25,
        "source": "fallback",
    }


def _build_script(n_moves: int, final_score: int = 120, won: bool = False) -> List[Dict[str, Any]]:
    """Build a simple n-move script ending the game on the last move."""
    script = []
    for i in range(n_moves):
        is_last = i == n_moves - 1
        script.append({
            "state": {"snake": [[5, 5 - i]], "food": [3, 3]},
            "done": is_last,
            "score": final_score if is_last else (i + 1) * 10,
            "won": won if is_last else None,
        })
    return script


class TestSessionRunnerBasic(unittest.TestCase):
    """Basic runner loop tests."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()

    def _make_runner(
        self,
        script: List[Dict[str, Any]],
        decide_fn=None,
        session_id: str = "test-run-001",
    ) -> tuple:
        """Build a runner with mocks and return (runner, buf)."""
        arena = MockArena(session_id, script)
        buf = io.StringIO()
        logger = SessionLogger(session_id, "snake", log_dir=self._tmp_dir)
        viewer = DecisionViewer(
            "snake", session_id,
            mock_mode=True,
            log_path=str(logger.log_path),
            out=buf,
        )
        tracker = FallbackTracker()
        runner = SessionRunner(
            arena=arena,
            decide_fn=decide_fn or _laya_decision,
            logger=logger,
            viewer=viewer,
            fallback_tracker=tracker,
        )
        return runner, buf

    def test_simple_3_move_game(self):
        """A 3-move scripted game must complete with correct counts."""
        script = _build_script(3, final_score=180)
        runner, buf = self._make_runner(script)
        result = runner.run()

        self.assertEqual(result.session_id, "test-run-001")
        self.assertEqual(result.game, "snake")
        self.assertEqual(result.total_moves, 3)
        self.assertEqual(result.applied_moves, 3)
        self.assertEqual(result.rejected_moves, 0)
        self.assertEqual(result.final_score, 180)
        self.assertIsNone(result.error)

    def test_hash_chain_valid_after_run(self):
        """After a clean run, the hash chain must verify as valid."""
        script = _build_script(3)
        runner, buf = self._make_runner(script)
        result = runner.run()
        self.assertTrue(result.hash_chain_valid)

    def test_viewer_output_present(self):
        """The viewer must produce output during the run."""
        script = _build_script(2)
        runner, buf = self._make_runner(script)
        runner.run()
        output = buf.getvalue()
        self.assertIn("ZENITH", output)
        self.assertIn("MOCK MODE", output)
        self.assertIn("SESSION SUMMARY", output)

    def test_log_file_created(self):
        """A JSONL log file must be created for the session."""
        script = _build_script(2)
        runner, buf = self._make_runner(script)
        result = runner.run()
        self.assertTrue(Path(result.log_path).exists())
        with open(result.log_path, "r") as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 2)

    def test_final_response_saved(self):
        """The final Arena response must be persisted as a JSON file."""
        script = _build_script(2, final_score=120)
        runner, buf = self._make_runner(script)
        result = runner.run()
        final_path = Path(self._tmp_dir) / "test-run-001_final.json"
        self.assertTrue(final_path.exists())

    def test_single_move_game(self):
        """A 1-move game (immediate done) must work correctly."""
        script = _build_script(1, final_score=60, won=False)
        runner, buf = self._make_runner(script)
        result = runner.run()
        self.assertEqual(result.total_moves, 1)
        self.assertEqual(result.applied_moves, 1)
        self.assertEqual(result.final_score, 60)
        self.assertFalse(result.won)


class TestSessionRunnerRejectedMoves(unittest.TestCase):
    """Tests for handling rejected moves."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()

    def test_rejected_moves_counted(self):
        """Rejected moves must be counted separately from applied."""
        script = [
            {
                "state": {"snake": [[5, 4]]},
                "done": False,
                "score": 0,
                "result": "rejected",
            },
            {
                "state": {"snake": [[5, 3]]},
                "done": True,
                "score": 60,
                "result": "applied",
            },
        ]
        arena = MockArena("test-rej-001", script)
        buf = io.StringIO()
        logger = SessionLogger("test-rej-001", "snake", log_dir=self._tmp_dir)
        viewer = DecisionViewer("snake", "test-rej-001", mock_mode=True, out=buf)
        runner = SessionRunner(
            arena=arena,
            decide_fn=_laya_decision,
            logger=logger,
            viewer=viewer,
        )
        result = runner.run()
        self.assertEqual(result.applied_moves, 1)
        self.assertEqual(result.rejected_moves, 1)
        self.assertEqual(result.total_moves, 2)


class TestSessionRunnerFallback(unittest.TestCase):
    """Tests for fallback tracking during a run."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()

    def test_fallback_moves_tracked(self):
        """Fallback moves must be counted by the runner."""
        script = _build_script(3, final_score=180)
        arena = MockArena("test-fb-001", script)
        buf = io.StringIO()
        logger = SessionLogger("test-fb-001", "snake", log_dir=self._tmp_dir)
        viewer = DecisionViewer("snake", "test-fb-001", mock_mode=True, out=buf)
        runner = SessionRunner(
            arena=arena,
            decide_fn=_fallback_decision,
            logger=logger,
            viewer=viewer,
        )
        result = runner.run()
        self.assertEqual(result.fallback_moves, 3)
        self.assertEqual(result.total_moves, 3)


class TestSessionRunnerErrorHandling(unittest.TestCase):
    """Tests for error handling and consecutive error limits."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()

    def test_decision_errors_cause_stop_after_limit(self):
        """Too many consecutive decision errors must stop the run."""
        call_count = 0

        def bad_decide(game, state):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("Mock decision failure")

        # Long script that won't complete due to errors
        script = _build_script(20)
        arena = MockArena("test-err-001", script)
        buf = io.StringIO()
        logger = SessionLogger("test-err-001", "snake", log_dir=self._tmp_dir)
        viewer = DecisionViewer("snake", "test-err-001", mock_mode=True, out=buf)
        runner = SessionRunner(
            arena=arena,
            decide_fn=bad_decide,
            logger=logger,
            viewer=viewer,
            max_consecutive_errors=3,
        )
        result = runner.run()
        self.assertIsNotNone(result.error)
        self.assertIn("decision errors", result.error)
        self.assertEqual(call_count, 3)

    def test_api_errors_cause_stop_after_limit(self):
        """Too many consecutive API errors must stop the run."""
        class FailingArena:
            def create_session(self, g, a): return {}
            def get_session(self, s):
                return {
                    "state": {"snake": [[5, 5]]},
                    "done": False,
                    "score": 0,
                }
            def submit_action(self, s, a):
                raise ConnectionError("Mock network failure")

        buf = io.StringIO()
        logger = SessionLogger("test-api-err", "snake", log_dir=self._tmp_dir)
        viewer = DecisionViewer("snake", "test-api-err", mock_mode=True, out=buf)
        runner = SessionRunner(
            arena=FailingArena(),
            decide_fn=_laya_decision,
            logger=logger,
            viewer=viewer,
            max_consecutive_errors=2,
        )
        result = runner.run()
        self.assertIsNotNone(result.error)
        self.assertIn("API errors", result.error)


class TestExtractState(unittest.TestCase):
    """Tests for the _extract_state helper."""

    def test_nested_state_key(self):
        """When 'state' key exists, it should be extracted."""
        data = {"session_id": "s1", "state": {"board": [1, 2, 3]}, "done": False}
        state = _extract_state(data)
        self.assertEqual(state, {"board": [1, 2, 3]})

    def test_flat_response(self):
        """When no 'state' key exists, metadata fields should be excluded."""
        data = {"session_id": "s1", "done": False, "score": 0, "board": [[0, 0]], "food": [3, 3]}
        state = _extract_state(data)
        self.assertIn("board", state)
        self.assertIn("food", state)
        self.assertNotIn("session_id", state)
        self.assertNotIn("done", state)
        self.assertNotIn("score", state)


class TestSessionRunnerWonGame(unittest.TestCase):
    """Tests for a game that ends with a win."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()

    def test_won_game(self):
        """A winning game must report won=True in the result."""
        script = _build_script(5, final_score=1000, won=True)
        arena = MockArena("test-win-001", script)
        buf = io.StringIO()
        logger = SessionLogger("test-win-001", "snake", log_dir=self._tmp_dir)
        viewer = DecisionViewer("snake", "test-win-001", mock_mode=True, out=buf)
        runner = SessionRunner(
            arena=arena,
            decide_fn=_laya_decision,
            logger=logger,
            viewer=viewer,
        )
        result = runner.run()
        self.assertTrue(result.won)
        self.assertEqual(result.final_score, 1000)
        self.assertTrue(result.hash_chain_valid)


if __name__ == "__main__":
    unittest.main()
