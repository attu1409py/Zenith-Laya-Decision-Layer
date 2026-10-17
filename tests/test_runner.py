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
from zenith.runner import (
    SessionRunner,
    SessionResult,
    _extract_state,
    check_state_progress,
    normalize_2048_grid,
)
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


class Mock2048ScriptArena:
    """Deterministic mock arena for 2048 tests that records actions."""

    def __init__(
        self,
        session_id: str,
        script: List[Dict[str, Any]],
        initial_state: Optional[Dict[str, Any]] = None,
    ):
        self._session_id = session_id
        self._script = list(script)
        self._index = 0
        self.actions_received: List[str] = []
        self._initial_state = initial_state or {
            "session_id": session_id,
            "game": "2048",
            "state": {
                "grid": [
                    [0, 0, 2, 0],
                    [0, 0, 0, 0],
                    [0, 0, 0, 0],
                    [0, 0, 0, 0],
                ],
                "score": 0,
                "best": 2,
            },
            "done": False,
            "score": 0,
        }

    def create_session(self, game: str, agent_name: str) -> Dict[str, Any]:
        return dict(self._initial_state)

    def get_session(self, session_id: str) -> Dict[str, Any]:
        return dict(self._initial_state)

    def submit_action(self, session_id: str, action: str) -> Dict[str, Any]:
        self.actions_received.append(action)
        if self._index >= len(self._script):
            return {
                "session_id": session_id,
                "done": True,
                "score": 0,
                "result": "applied",
            }
        resp = dict(self._script[self._index])
        self._index += 1
        resp.setdefault("session_id", session_id)
        return resp


class TestSessionRunnerNoProgressGuard(unittest.TestCase):
    """M7 Hotfix tests: Guard against 2048 no-progress loops, duplicate retries, and malformed states."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()

    def _make_2048_runner(
        self,
        script: List[Dict[str, Any]],
        initial_state: Optional[Dict[str, Any]] = None,
        decide_fn=None,
        session_id: str = "test-2048-np-001",
        max_consecutive_no_progress: int = 1,
    ):
        arena = Mock2048ScriptArena(session_id, script, initial_state=initial_state)
        buf = io.StringIO()
        logger = SessionLogger(session_id, "2048", log_dir=self._tmp_dir)
        viewer = DecisionViewer("2048", session_id, mock_mode=True, log_path=str(logger.log_path), out=buf)
        runner = SessionRunner(
            arena=arena,
            decide_fn=decide_fn or _laya_decision,
            logger=logger,
            viewer=viewer,
            max_consecutive_no_progress=max_consecutive_no_progress,
        )
        return runner, arena, logger, buf

    def test_applied_action_with_changed_board(self):
        """1. An applied action with a changed board must be recorded as applied and continue."""
        initial_state = {
            "session_id": "test-np-1",
            "game": "2048",
            "state": {"grid": [[0, 0, 2, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]], "score": 0, "best": 2},
            "done": False,
            "score": 0,
        }
        script = [
            {
                "state": {"grid": [[2, 0, 0, 2], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]], "score": 0, "best": 2},
                "done": True,
                "score": 0,
                "result": "applied",
            }
        ]
        runner, arena, logger, buf = self._make_2048_runner(script, initial_state=initial_state, session_id="test-np-1")
        result = runner.run()

        self.assertEqual(result.applied_moves, 1)
        self.assertEqual(result.no_progress_moves, 0)
        self.assertEqual(result.rejected_moves, 0)
        self.assertEqual(result.moves[0].result, "applied")
        self.assertIsNone(result.error)
        self.assertTrue(result.hash_chain_valid)

    def test_applied_action_with_unchanged_board(self):
        """2. An applied action with an unchanged board must be detected as no_progress."""
        frozen_grid = [
            [8, 4, 32, 4],
            [16, 128, 16, 16],
            [2, 256, 4, 2],
            [0, 0, 2, 8],
        ]
        initial_state = {
            "session_id": "test-np-2",
            "game": "2048",
            "state": {"grid": frozen_grid, "score": 2772, "best": 256},
            "done": False,
            "score": 2772,
        }
        # Server falsely returns result='applied' with unchanged grid and score
        script = [
            {
                "state": {"grid": frozen_grid, "score": 2772, "best": 256},
                "done": False,
                "score": 2772,
                "result": "applied",
            }
        ]
        runner, arena, logger, buf = self._make_2048_runner(
            script, initial_state=initial_state, session_id="test-np-2", max_consecutive_no_progress=1
        )
        result = runner.run()

        self.assertEqual(result.applied_moves, 0)
        self.assertEqual(result.no_progress_moves, 1)
        self.assertEqual(result.moves[0].result, "no_progress")
        self.assertIsNotNone(result.error)
        self.assertIn("No-progress detected", result.error)
        self.assertTrue(result.hash_chain_valid)

        # Verify JSONL log on disk records result as 'no_progress'
        with open(result.log_path, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["result"], "no_progress")
        self.assertEqual(lines[0]["action"], "up")

    def test_explicitly_rejected_action(self):
        """3. An explicitly rejected action must be preserved and distinguished from applied/no-progress."""
        grid_a = [[0, 0, 2, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
        grid_b = [[2, 0, 0, 2], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
        initial_state = {
            "session_id": "test-np-3",
            "game": "2048",
            "state": {"grid": grid_a, "score": 0, "best": 2},
            "done": False,
            "score": 0,
        }
        script = [
            {
                "state": {"grid": grid_a, "score": 0, "best": 2},
                "done": False,
                "score": 0,
                "result": "rejected",
            },
            {
                "state": {"grid": grid_b, "score": 0, "best": 2},
                "done": True,
                "score": 0,
                "result": "applied",
            },
        ]
        runner, arena, logger, buf = self._make_2048_runner(script, initial_state=initial_state, session_id="test-np-3")
        result = runner.run()

        self.assertEqual(result.rejected_moves, 1)
        self.assertEqual(result.applied_moves, 1)
        self.assertEqual(result.no_progress_moves, 0)
        self.assertEqual(result.moves[0].result, "rejected")
        self.assertEqual(result.moves[1].result, "applied")
        self.assertIsNone(result.error)

    def test_repeated_identical_board_stops_at_threshold(self):
        """4. Repeated identical boards must stop submissions when threshold is reached."""
        frozen_grid = [
            [8, 4, 32, 4],
            [16, 128, 16, 16],
            [2, 256, 4, 2],
            [0, 0, 2, 8],
        ]
        initial_state = {
            "session_id": "test-np-4",
            "game": "2048",
            "state": {"grid": frozen_grid, "score": 2772, "best": 256},
            "done": False,
            "score": 2772,
        }
        # Provide 5 identical responses; runner configured with threshold 2
        script = [
            {"state": {"grid": frozen_grid, "score": 2772, "best": 256}, "done": False, "score": 2772, "result": "applied"}
            for _ in range(5)
        ]
        runner, arena, logger, buf = self._make_2048_runner(
            script, initial_state=initial_state, session_id="test-np-4", max_consecutive_no_progress=2
        )
        result = runner.run()

        # Must have stopped after exactly 2 actions
        self.assertEqual(len(arena.actions_received), 2)
        self.assertEqual(result.no_progress_moves, 2)
        self.assertEqual(result.applied_moves, 0)
        self.assertIn("2 no-progress move(s)", result.error)
        self.assertTrue(result.hash_chain_valid)

    def test_missing_or_malformed_post_action_state(self):
        """5. Missing or malformed post-action state must trigger safe termination."""
        initial_state = {
            "session_id": "test-np-5",
            "game": "2048",
            "state": {"grid": [[0, 0, 2, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]], "score": 0, "best": 2},
            "done": False,
            "score": 0,
        }
        # Response with malformed 2x2 grid instead of 4x4
        script = [
            {
                "state": {"grid": [[1, 2], [3, 4]], "score": 0},
                "done": False,
                "score": 0,
                "result": "applied",
            }
        ]
        runner, arena, logger, buf = self._make_2048_runner(script, initial_state=initial_state, session_id="test-np-5")
        result = runner.run()

        self.assertEqual(result.no_progress_moves, 1)
        self.assertEqual(result.applied_moves, 0)
        self.assertIsNotNone(result.error)
        self.assertIn("malformed 4x4 grid", result.error)

    def test_terminal_response(self):
        """6. A terminal response (done=True) must be treated as game completion, not an error."""
        frozen_grid = [
            [8, 4, 32, 4],
            [16, 128, 16, 16],
            [2, 256, 4, 2],
            [0, 0, 2, 8],
        ]
        initial_state = {
            "session_id": "test-np-6",
            "game": "2048",
            "state": {"grid": frozen_grid, "score": 2772, "best": 256},
            "done": False,
            "score": 2772,
        }
        # Terminal response: board unchanged because game is over (loss)
        script = [
            {
                "state": {"grid": frozen_grid, "score": 2772, "best": 256},
                "done": True,
                "won": False,
                "score": 2772,
                "result": "applied",
            }
        ]
        runner, arena, logger, buf = self._make_2048_runner(script, initial_state=initial_state, session_id="test-np-6")
        result = runner.run()

        self.assertIsNone(result.error)
        self.assertEqual(result.applied_moves, 1)
        self.assertEqual(result.no_progress_moves, 0)
        self.assertFalse(result.won)
        self.assertTrue(result.hash_chain_valid)

    def test_timeout_with_no_automatic_action_retry(self):
        """7. A timeout during action submission must NOT be retried."""
        class TimeoutArena:
            def __init__(self):
                self.calls = 0

            def create_session(self, g, a):
                return {}

            def get_session(self, s):
                return {
                    "session_id": s,
                    "game": "2048",
                    "state": {"grid": [[0] * 4 for _ in range(4)], "score": 0},
                    "done": False,
                    "score": 0,
                }

            def submit_action(self, s, a):
                self.calls += 1
                raise TimeoutError("Arena HTTP connection timed out after 10.0s")

        arena = TimeoutArena()
        buf = io.StringIO()
        logger = SessionLogger("test-np-7", "2048", log_dir=self._tmp_dir)
        viewer = DecisionViewer("2048", "test-np-7", mock_mode=True, out=buf)
        runner = SessionRunner(
            arena=arena,
            decide_fn=_laya_decision,
            logger=logger,
            viewer=viewer,
            max_consecutive_errors=5,
        )
        result = runner.run()

        # Critical assertion: called EXACTLY once. ZERO retries.
        self.assertEqual(arena.calls, 1)
        self.assertIsNotNone(result.error)
        self.assertIn("API error during submit_action", result.error)
        self.assertIn("prevent duplicate action submission", result.error)

    def test_no_progress_guard_stops_without_inventing_or_substituting_action(self):
        """8. When stopped by no-progress guard, no substitution or action invention occurs."""
        decisions_made = []

        def recorded_decide(game, state):
            decisions_made.append("up")
            return {
                "questions": ["Next 2048 move?"],
                "probabilities": {"up": 0.40, "down": 0.20, "left": 0.20, "right": 0.20},
                "chosen": "up",
                "confidence": 0.40,
                "source": "laya",
            }

        frozen_grid = [
            [8, 4, 32, 4],
            [16, 128, 16, 16],
            [2, 256, 4, 2],
            [0, 0, 2, 8],
        ]
        initial_state = {
            "session_id": "test-np-8",
            "game": "2048",
            "state": {"grid": frozen_grid, "score": 2772, "best": 256},
            "done": False,
            "score": 2772,
        }
        script = [
            {
                "state": {"grid": frozen_grid, "score": 2772, "best": 256},
                "done": False,
                "score": 2772,
                "result": "applied",
            }
        ]
        runner, arena, logger, buf = self._make_2048_runner(
            script,
            initial_state=initial_state,
            decide_fn=recorded_decide,
            session_id="test-np-8",
            max_consecutive_no_progress=1,
        )
        result = runner.run()

        # Exactly 1 decision requested from Laya
        self.assertEqual(decisions_made, ["up"])
        # Exactly 1 action submitted to arena
        self.assertEqual(arena.actions_received, ["up"])
        # No fallback moves substituted
        self.assertEqual(result.fallback_moves, 0)
        self.assertEqual(result.moves[0].decision["source"], "laya")
        self.assertEqual(result.moves[0].action, "up")
        self.assertIn("No-progress detected", result.error)


class TestStateProgressHelpers(unittest.TestCase):
    """Direct unit tests for normalize_2048_grid and check_state_progress."""

    def test_normalize_valid_grid(self):
        valid = [[2, 0, 0, 0], [0, 4, 0, 0], [0, 0, 8, 0], [0, 0, 0, 16]]
        self.assertEqual(normalize_2048_grid(valid), valid)

    def test_normalize_invalid_structures(self):
        self.assertIsNone(normalize_2048_grid(None))
        self.assertIsNone(normalize_2048_grid("not a grid"))
        self.assertIsNone(normalize_2048_grid([[1, 2], [3, 4]]))  # 2x2
        self.assertIsNone(normalize_2048_grid([[1, 2, 3, 4]] * 3))  # 3 rows
        self.assertIsNone(normalize_2048_grid([[1, 2, 3, 4]] * 5))  # 5 rows
        # Row with 3 elements
        self.assertIsNone(normalize_2048_grid([[1, 2, 3], [1, 2, 3, 4], [1, 2, 3, 4], [1, 2, 3, 4]]))
        # Non-numeric elements (string, None, bool)
        self.assertIsNone(normalize_2048_grid([[1, "2", 3, 4]] + [[0]*4]*3))
        self.assertIsNone(normalize_2048_grid([[1, None, 3, 4]] + [[0]*4]*3))
        self.assertIsNone(normalize_2048_grid([[True, 2, 3, 4]] + [[0]*4]*3))

    def test_check_2048_progress_detection(self):
        g1 = [[2, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
        g2 = [[0, 2, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]

        # Grid changed -> progress True
        ok, reason = check_state_progress("2048", {"grid": g1, "score": 0}, {"grid": g2, "score": 0})
        self.assertTrue(ok)
        self.assertEqual(reason, "progress confirmed")

        # Grid identical, score identical -> progress False
        ok, reason = check_state_progress("2048", {"grid": g1, "score": 0}, {"grid": g1, "score": 0})
        self.assertFalse(ok)
        self.assertEqual(reason, "grid and score unchanged")

        # Grid identical, but score changed -> progress True
        ok, reason = check_state_progress("2048", {"grid": g1, "score": 0}, {"grid": g1, "score": 4})
        self.assertTrue(ok)

        # Malformed state_after
        ok, reason = check_state_progress("2048", {"grid": g1}, "not a dict")
        self.assertFalse(ok)
        self.assertEqual(reason, "state_after is not a dictionary")

        # Missing grid
        ok, reason = check_state_progress("2048", {"grid": g1}, {"score": 10})
        self.assertFalse(ok)
        self.assertIn("missing or malformed 4x4 grid", reason)

    def test_check_snake_progress_detection(self):
        s1 = {"snake": [[5, 5], [5, 6]], "score": 0, "foodEaten": 0}
        s2 = {"snake": [[5, 4], [5, 5]], "score": 0, "foodEaten": 0}

        # Snake moved -> progress True
        ok, reason = check_state_progress("snake", s1, s2)
        self.assertTrue(ok)

        # Snake stationary and score unchanged -> progress False
        ok, reason = check_state_progress("snake", s1, s1)
        self.assertFalse(ok)
        self.assertEqual(reason, "snake coordinates and score unchanged")


if __name__ == "__main__":
    unittest.main()
