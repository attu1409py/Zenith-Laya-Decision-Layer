"""Unit tests for zenith.decision_viewer.

Validates terminal output, counter tracking, mock mode indicators,
compact state rendering, and summary formatting.
"""

from __future__ import annotations

import io
import unittest
from typing import Any, Dict, Mapping

from zenith.decision_viewer import DecisionViewer, _compact_state, TEAM_NAME


def _sample_decision(**overrides: Any) -> Dict[str, Any]:
    """Build a valid decision dict with optional overrides."""
    d = {
        "questions": ["Given the snake game state, which direction should I move?"],
        "probabilities": {"up": 0.61, "down": 0.04, "left": 0.22, "right": 0.13},
        "chosen": "up",
        "confidence": 0.61,
        "source": "laya",
    }
    d.update(overrides)
    return d


def _sample_timing(**overrides: Any) -> Dict[str, int]:
    """Build a timing dict with optional overrides."""
    t = {"decide_ms": 12, "api_ms": 45, "turn_ms": 60}
    t.update(overrides)
    return t


class TestDecisionViewerHeader(unittest.TestCase):
    """Tests for the session header display."""

    def test_header_contains_team_name(self):
        """The header must display ZENITH as the team name."""
        buf = io.StringIO()
        viewer = DecisionViewer("snake", "sess-001", out=buf)
        viewer.show_header()
        output = buf.getvalue()
        self.assertIn(TEAM_NAME, output)

    def test_header_contains_game_and_session(self):
        """The header must display the game and session ID."""
        buf = io.StringIO()
        viewer = DecisionViewer("2048", "sess-xyz", out=buf)
        viewer.show_header()
        output = buf.getvalue()
        self.assertIn("2048", output)
        self.assertIn("sess-xyz", output)

    def test_header_mock_mode_indicator(self):
        """When mock_mode=True, the header must display MOCK MODE prominently."""
        buf = io.StringIO()
        viewer = DecisionViewer("snake", "sess-001", mock_mode=True, out=buf)
        viewer.show_header()
        output = buf.getvalue()
        self.assertIn("MOCK MODE", output)

    def test_header_no_mock_indicator_by_default(self):
        """When mock_mode=False (default), MOCK MODE must not appear in header."""
        buf = io.StringIO()
        viewer = DecisionViewer("snake", "sess-001", out=buf)
        viewer.show_header()
        output = buf.getvalue()
        self.assertNotIn("MOCK MODE", output)

    def test_header_log_path_display(self):
        """The header must display the log file path."""
        buf = io.StringIO()
        viewer = DecisionViewer(
            "snake", "sess-001", log_path="logs/sess-001.jsonl", out=buf
        )
        viewer.show_header()
        output = buf.getvalue()
        self.assertIn("logs/sess-001.jsonl", output)


class TestDecisionViewerMoveDisplay(unittest.TestCase):
    """Tests for per-move display."""

    def _make_viewer(self, **kwargs) -> tuple:
        buf = io.StringIO()
        kwargs.setdefault("out", buf)
        viewer = DecisionViewer("snake", "test-session", **kwargs)
        return viewer, buf

    def test_move_shows_step_and_result(self):
        """The move display must include step number and result."""
        viewer, buf = self._make_viewer()
        viewer.show_move(
            step=1,
            state_before={"snake": [[1, 1]], "food": [5, 5]},
            decision=_sample_decision(),
            action="up",
            result="applied",
            state_after={"snake": [[1, 0]], "food": [5, 5]},
            timing=_sample_timing(),
            score=60,
        )
        output = buf.getvalue()
        self.assertIn("Step 1", output)
        self.assertIn("APPLIED", output)

    def test_move_shows_probabilities(self):
        """The move display must include all four probability values."""
        viewer, buf = self._make_viewer()
        viewer.show_move(
            step=1,
            state_before={},
            decision=_sample_decision(),
            action="up",
            result="applied",
            state_after={},
            timing=_sample_timing(),
        )
        output = buf.getvalue()
        self.assertIn("up=0.6100", output)
        self.assertIn("down=0.0400", output)
        self.assertIn("left=0.2200", output)
        self.assertIn("right=0.1300", output)

    def test_move_shows_question(self):
        """The move display must show the exact question text sent to Laya."""
        viewer, buf = self._make_viewer()
        question = "What direction should the snake move?"
        viewer.show_move(
            step=1,
            state_before={},
            decision=_sample_decision(questions=[question]),
            action="up",
            result="applied",
            state_after={},
            timing=_sample_timing(),
        )
        output = buf.getvalue()
        self.assertIn(question, output)

    def test_move_shows_timing(self):
        """The move display must show decide_ms, api_ms, turn_ms."""
        viewer, buf = self._make_viewer()
        viewer.show_move(
            step=1,
            state_before={},
            decision=_sample_decision(),
            action="up",
            result="applied",
            state_after={},
            timing=_sample_timing(decide_ms=15, api_ms=200, turn_ms=220),
        )
        output = buf.getvalue()
        self.assertIn("decide=15ms", output)
        self.assertIn("api=200ms", output)
        self.assertIn("turn=220ms", output)

    def test_move_shows_source(self):
        """The move display must show the decision source."""
        viewer, buf = self._make_viewer()
        viewer.show_move(
            step=1,
            state_before={},
            decision=_sample_decision(source="fallback"),
            action="up",
            result="applied",
            state_after={},
            timing=_sample_timing(),
        )
        output = buf.getvalue()
        self.assertIn("fallback", output)

    def test_move_shows_score(self):
        """The move display must show the current score."""
        viewer, buf = self._make_viewer()
        viewer.show_move(
            step=1,
            state_before={},
            decision=_sample_decision(),
            action="up",
            result="applied",
            state_after={},
            timing=_sample_timing(),
            score=180,
        )
        output = buf.getvalue()
        self.assertIn("180", output)

    def test_move_game_over_display(self):
        """When done=True, the move display must show game-over info."""
        viewer, buf = self._make_viewer()
        viewer.show_move(
            step=10,
            state_before={},
            decision=_sample_decision(),
            action="up",
            result="applied",
            state_after={},
            timing=_sample_timing(),
            score=600,
            done=True,
            won=True,
        )
        output = buf.getvalue()
        self.assertIn("Game Over", output)
        self.assertIn("YES", output)

    def test_rejected_move_display(self):
        """A rejected move must display REJECTED in the output."""
        viewer, buf = self._make_viewer()
        viewer.show_move(
            step=3,
            state_before={},
            decision=_sample_decision(),
            action="up",
            result="rejected",
            state_after={},
            timing=_sample_timing(),
        )
        output = buf.getvalue()
        self.assertIn("REJECTED", output)


class TestDecisionViewerCounters(unittest.TestCase):
    """Tests for internal counter tracking."""

    def test_counters_track_applied_and_rejected(self):
        """Counters must correctly track applied and rejected moves."""
        buf = io.StringIO()
        viewer = DecisionViewer("snake", "sess-cnt", out=buf)
        decision = _sample_decision()
        timing = _sample_timing()
        state = {}

        # 3 applied
        for i in range(3):
            viewer.show_move(i + 1, state, decision, "up", "applied", state, timing)
        # 2 rejected
        for i in range(2):
            viewer.show_move(4, state, decision, "up", "rejected", state, timing)

        self.assertEqual(viewer._applied_count, 3)
        self.assertEqual(viewer._rejected_count, 2)
        self.assertEqual(viewer._total_moves, 5)

    def test_fallback_counter(self):
        """Fallback counter must increment when source is 'fallback'."""
        buf = io.StringIO()
        viewer = DecisionViewer("snake", "sess-fb", out=buf)
        timing = _sample_timing()
        state = {}

        viewer.show_move(1, state, _sample_decision(source="laya"), "up", "applied", state, timing)
        viewer.show_move(2, state, _sample_decision(source="fallback"), "up", "applied", state, timing)
        viewer.show_move(3, state, _sample_decision(source="laya"), "up", "applied", state, timing)

        self.assertEqual(viewer._fallback_count, 1)
        self.assertEqual(viewer._total_moves, 3)


class TestDecisionViewerSummary(unittest.TestCase):
    """Tests for the session summary panel."""

    def test_summary_shows_final_score(self):
        """Summary must display the final score."""
        buf = io.StringIO()
        viewer = DecisionViewer("snake", "sess-sum", out=buf)
        viewer.show_summary(final_score=720, won=True, hash_chain_valid=True)
        output = buf.getvalue()
        self.assertIn("720", output)
        self.assertIn("YES", output)
        self.assertIn("VALID", output)

    def test_summary_shows_invalid_hash_chain(self):
        """Summary must display INVALID when hash chain fails."""
        buf = io.StringIO()
        viewer = DecisionViewer("snake", "sess-bad", out=buf)
        viewer.show_summary(hash_chain_valid=False)
        output = buf.getvalue()
        self.assertIn("INVALID", output)

    def test_summary_mock_mode_indicator(self):
        """Summary must display MOCK MODE in mock_mode."""
        buf = io.StringIO()
        viewer = DecisionViewer("snake", "sess-m", mock_mode=True, out=buf)
        viewer.show_summary()
        output = buf.getvalue()
        self.assertIn("MOCK MODE", output)

    def test_summary_total_time(self):
        """Summary must display the total session time."""
        buf = io.StringIO()
        viewer = DecisionViewer("snake", "sess-t", out=buf)
        viewer.show_summary(total_time_ms=12345)
        output = buf.getvalue()
        self.assertIn("12345", output)

    def test_summary_fallback_exceeded(self):
        """Summary must flag when fallback proportion exceeds 10%."""
        buf = io.StringIO()
        viewer = DecisionViewer("snake", "sess-fb-x", out=buf)
        timing = _sample_timing()
        state = {}
        # 5 fallback out of 10 = 50%
        for i in range(5):
            viewer.show_move(i + 1, state, _sample_decision(source="fallback"), "up", "applied", state, timing)
        for i in range(5):
            viewer.show_move(i + 6, state, _sample_decision(source="laya"), "up", "applied", state, timing)
        viewer.show_summary()
        output = buf.getvalue()
        self.assertIn("EXCEEDED", output)


class TestCompactState(unittest.TestCase):
    """Tests for the _compact_state helper."""

    def test_empty_state(self):
        """Empty dict must render as '{}'."""
        self.assertEqual(_compact_state({}), "{}")

    def test_simple_state(self):
        """Simple state must include key=value pairs."""
        result = _compact_state({"score": 100, "food": [3, 5]})
        self.assertIn("food=", result)
        self.assertIn("score=", result)

    def test_truncation(self):
        """Long state must be truncated with '...'."""
        big_state = {f"key_{i}": f"value_{i}" * 10 for i in range(20)}
        result = _compact_state(big_state, max_len=60)
        self.assertTrue(len(result) <= 60)
        self.assertTrue(result.endswith("..."))


if __name__ == "__main__":
    unittest.main()
