"""Unit tests for zenith/main.py CLI and orchestration.

Validates CLI argument handling, dry-run vs. live separation, operator confirmation
safeguards, exit codes, hash-chain verification, and final response persistence.
No live Arena network calls are made.
"""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

from zenith.arena_client import ArenaClient, ArenaHttpError
from zenith.hash_chain import verify_jsonl_file
from zenith.session_logger import SessionLogger
from zenith.main import (
    TEAM_NAME,
    MockSnakeArena,
    confirm_live_session,
    make_mock_decide_fn,
    run_cli,
)


class TestMockSnakeArena(unittest.TestCase):
    """Tests for MockSnakeArena simulation used in dry runs."""

    def test_mock_snake_initial_state(self):
        arena = MockSnakeArena(session_id="mock-123")
        state = arena.create_session("snake", TEAM_NAME)
        self.assertEqual(state["session_id"], "mock-123")
        self.assertEqual(state["game"], "snake")
        self.assertFalse(state["done"])
        self.assertEqual(state["score"], 0)
        snake_state = state["state"]
        self.assertEqual(len(snake_state["snake"]), 3)
        self.assertEqual(snake_state["direction"], "up")

    def test_mock_snake_movement_and_food_eaten(self):
        # Head starts at (6,6), food at (6,3), moves up to food
        arena = MockSnakeArena(session_id="mock-move", max_moves=5)
        arena.create_session("snake", TEAM_NAME)

        # Move 1: (6, 5)
        resp1 = arena.submit_action("mock-move", "up")
        self.assertEqual(resp1["state"]["snake"][0], {"x": 6, "y": 5})
        self.assertEqual(resp1["score"], 0)

        # Move 2: (6, 4)
        resp2 = arena.submit_action("mock-move", "up")
        self.assertEqual(resp2["state"]["snake"][0], {"x": 6, "y": 4})
        self.assertEqual(resp2["score"], 0)

        # Move 3: (6, 3) -> Reaches food!
        resp3 = arena.submit_action("mock-move", "up")
        self.assertEqual(resp3["state"]["snake"][0], {"x": 6, "y": 3})
        self.assertEqual(resp3["score"], 100)
        self.assertEqual(resp3["state"]["foodEaten"], 1)

    def test_mock_snake_wall_collision(self):
        arena = MockSnakeArena(session_id="mock-wall", width=5, height=5, max_moves=10)
        arena._snake = [{"x": 0, "y": 0}]
        arena._food = {"x": 4, "y": 4}
        # Moving up from (0,0) hits top wall
        resp = arena.submit_action("mock-wall", "up")
        self.assertTrue(resp["done"])
        self.assertFalse(resp["won"])


class TestLiveConfirmation(unittest.TestCase):
    """Tests for operator confirmation safeguard before live sessions."""

    def test_confirm_yes(self):
        buf = io.StringIO()
        res = confirm_live_session(
            "snake", TEAM_NAME, "https://topgameai.com/api/arena", "convaiinnovations/laya",
            input_fn=lambda _: "YES",
            out=buf,
        )
        self.assertTrue(res)
        self.assertIn("LIVE COMPETITION RUN CONFIRMATION", buf.getvalue())
        self.assertIn("authorized by operator", buf.getvalue())

    def test_confirm_no(self):
        buf = io.StringIO()
        res = confirm_live_session(
            "snake", TEAM_NAME, "https://topgameai.com/api/arena", "convaiinnovations/laya",
            input_fn=lambda _: "no",
            out=buf,
        )
        self.assertFalse(res)
        self.assertIn("declined", buf.getvalue())

    def test_confirm_eof_error(self):
        def raise_eof(_):
            raise EOFError("stdin closed")

        buf = io.StringIO()
        res = confirm_live_session(
            "snake", TEAM_NAME, "https://topgameai.com/api/arena", "convaiinnovations/laya",
            input_fn=raise_eof,
            out=buf,
        )
        self.assertFalse(res)
        self.assertIn("unavailable", buf.getvalue())


class TestCliExecution(unittest.TestCase):
    """Tests for CLI arguments, execution paths, and error handling."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def test_default_mode_is_dry_run(self):
        """No mode specified must default to dry run and make zero network calls."""
        stdout = io.StringIO()
        stderr = io.StringIO()

        # Patch urllib.request to guarantee no network transport is accessed
        with patch("urllib.request.urlopen") as mock_urlopen:
            code = run_cli(
                ["--mock-model", "--log-dir", self._tmp_dir, "--max-moves", "3"],
                stdout=stdout,
                stderr=stderr,
            )
            mock_urlopen.assert_not_called()

        self.assertEqual(code, 0)
        out = stdout.getvalue()
        self.assertIn("DRY-RUN (Simulated Arena)", out)
        self.assertIn("VERIFIED VALID", out)

        # Verify log file on disk
        log_files = list(Path(self._tmp_dir).glob("*.jsonl"))
        self.assertEqual(len(log_files), 1)
        verification = verify_jsonl_file(log_files[0])
        self.assertTrue(verification.is_valid)

        # Verify final response file
        resp_files = list(Path(self._tmp_dir).glob("*_final.json"))
        self.assertEqual(len(resp_files), 1)

    def test_dry_run_explicit_flag(self):
        """Explicit --dry-run flag functions identically to default."""
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch("urllib.request.urlopen") as mock_urlopen:
            code = run_cli(
                ["--dry-run", "--mock-model", "--log-dir", self._tmp_dir, "--max-moves", "3"],
                stdout=stdout,
                stderr=stderr,
            )
            mock_urlopen.assert_not_called()

        self.assertEqual(code, 0)
        self.assertIn("DRY-RUN", stdout.getvalue())

    def test_locked_game_rejected(self):
        """Games other than 'snake' must be rejected with exit code 2."""
        stdout = io.StringIO()
        stderr = io.StringIO()

        code = run_cli(
            ["--game", "2048", "--mock-model"],
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(code, 2)
        self.assertIn("locked", stderr.getvalue())

    def test_live_declined_confirmation_prevents_network(self):
        """Declining live confirmation must abort with exit code 2 and make no requests."""
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch("zenith.arena_client.ArenaClient.create_session") as mock_create:
            code = run_cli(
                ["--live", "--mock-model", "--log-dir", self._tmp_dir],
                input_fn=lambda _: "n",
                stdout=stdout,
                stderr=stderr,
            )
            mock_create.assert_not_called()

        self.assertEqual(code, 2)
        # Verify no log directory files created
        self.assertEqual(len(list(Path(self._tmp_dir).glob("*.jsonl"))), 0)

    def test_live_missing_stdin_aborts_safely(self):
        """Missing stdin during live mode must abort with exit code 2."""
        def raise_eof(_):
            raise EOFError()

        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch("zenith.arena_client.ArenaClient.create_session") as mock_create:
            code = run_cli(
                ["--live", "--mock-model", "--log-dir", self._tmp_dir],
                input_fn=raise_eof,
                stdout=stdout,
                stderr=stderr,
            )
            mock_create.assert_not_called()

        self.assertEqual(code, 2)

    def test_live_confirmed_executes_session(self):
        """Affirmative confirmation proceeds with ArenaClient session creation and run."""
        stdout = io.StringIO()
        stderr = io.StringIO()

        # Mock ArenaClient calls
        mock_initial = {
            "session_id": "live-session-123",
            "game": "snake",
            "state": {"snake": [{"x": 5, "y": 5}], "food": {"x": 5, "y": 4}, "direction": "up"},
            "done": False,
            "score": 0,
        }
        mock_move_resp = {
            "session_id": "live-session-123",
            "game": "snake",
            "state": {"snake": [{"x": 5, "y": 4}], "food": {"x": 5, "y": 4}, "direction": "up"},
            "done": True,
            "score": 100,
            "won": True,
            "result": "applied",
        }

        with patch.object(ArenaClient, "create_session", return_value=mock_initial) as mock_create, \
             patch.object(ArenaClient, "submit_action", return_value=mock_move_resp) as mock_submit:

            code = run_cli(
                ["--live", "--mock-model", "--log-dir", self._tmp_dir],
                input_fn=lambda _: "YES",
                stdout=stdout,
                stderr=stderr,
            )

            mock_create.assert_called_once_with(game="snake", agent_name="ZENITH")
            mock_submit.assert_called_once()

        self.assertEqual(code, 0)
        out = stdout.getvalue()
        self.assertIn("LIVE (Official Arena)", out)
        self.assertIn("live-session-123", out)
        self.assertIn("VERIFIED VALID", out)

    def test_cli_explicit_agent_name_zenith_passed_to_create_session(self):
        """CLI with explicit --agent-name ZENITH must pass agent_name='ZENITH' to create_session."""
        mock_initial = {
            "session_id": "live-zenith-1",
            "game": "snake",
            "state": {"snake": [{"x": 6, "y": 6}], "food": {"x": 6, "y": 5}, "direction": "up"},
            "done": False,
            "score": 0,
        }
        mock_move_resp = {
            "session_id": "live-zenith-1",
            "game": "snake",
            "state": {"snake": [{"x": 6, "y": 5}], "food": {"x": 6, "y": 5}, "direction": "up"},
            "done": True,
            "score": 100,
            "won": True,
            "result": "applied",
        }
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.object(ArenaClient, "create_session", return_value=mock_initial) as mock_create, \
             patch.object(ArenaClient, "submit_action", return_value=mock_move_resp) as mock_submit:
            code = run_cli(
                ["--live", "--mock-model", "--agent-name", "ZENITH", "--log-dir", self._tmp_dir],
                input_fn=lambda _: "YES",
                stdout=stdout,
                stderr=stderr,
            )
            mock_create.assert_called_once_with(game="snake", agent_name="ZENITH")
            mock_submit.assert_called_once()
        self.assertEqual(code, 0)

    def test_cli_custom_agent_name_passed_to_create_session(self):
        """CLI with custom --agent-name must pass that exact name to create_session."""
        mock_initial = {
            "session_id": "live-custom-1",
            "game": "snake",
            "state": {"snake": [{"x": 6, "y": 6}], "food": {"x": 6, "y": 5}, "direction": "up"},
            "done": False,
            "score": 0,
        }
        mock_move_resp = {
            "session_id": "live-custom-1",
            "game": "snake",
            "state": {"snake": [{"x": 6, "y": 5}], "food": {"x": 6, "y": 5}, "direction": "up"},
            "done": True,
            "score": 100,
            "won": True,
            "result": "applied",
        }
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.object(ArenaClient, "create_session", return_value=mock_initial) as mock_create, \
             patch.object(ArenaClient, "submit_action", return_value=mock_move_resp) as mock_submit:
            code = run_cli(
                ["--live", "--mock-model", "--agent-name", "TEST_TEAM_ALPHA", "--log-dir", self._tmp_dir],
                input_fn=lambda _: "YES",
                stdout=stdout,
                stderr=stderr,
            )
            mock_create.assert_called_once_with(game="snake", agent_name="TEST_TEAM_ALPHA")
            mock_submit.assert_called_once()
        self.assertEqual(code, 0)

    def test_cli_end_to_end_post_payload_exact_agent_name_field(self):
        """End-to-end: CLI --agent-name ZENITH must serialize into POST body with exact field agent_name='ZENITH'."""
        mock_resp_create = {
            "session_id": "live-e2e-zenith",
            "game": "snake",
            "state": {"snake": [{"x": 6, "y": 6}], "food": {"x": 6, "y": 5}, "direction": "up"},
            "done": False,
            "score": 0,
        }
        mock_resp_action = {
            "session_id": "live-e2e-zenith",
            "game": "snake",
            "state": {"snake": [{"x": 6, "y": 5}], "food": {"x": 6, "y": 5}, "direction": "up"},
            "done": True,
            "score": 100,
            "won": True,
            "result": "applied",
        }

        def mock_urlopen_router(req: urllib.request.Request, timeout=None):
            resp = MagicMock()
            resp.status = 200
            resp.__enter__.return_value = resp
            resp.__exit__.return_value = False
            if req.full_url.endswith("/sessions"):
                resp.read.return_value = json.dumps(mock_resp_create).encode("utf-8")
            else:
                resp.read.return_value = json.dumps(mock_resp_action).encode("utf-8")
            return resp

        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch("urllib.request.urlopen", side_effect=mock_urlopen_router) as mock_urlopen:
            code = run_cli(
                ["--live", "--mock-model", "--agent-name", "ZENITH", "--log-dir", self._tmp_dir],
                input_fn=lambda _: "YES",
                stdout=stdout,
                stderr=stderr,
            )

            mock_urlopen.assert_called()
            # Inspect first request which is create_session (POST /sessions)
            first_req: urllib.request.Request = mock_urlopen.call_args_list[0][0][0]
            self.assertEqual(first_req.get_method(), "POST")
            self.assertTrue(first_req.full_url.endswith("/sessions"))
            post_body = json.loads(first_req.data.decode("utf-8"))
            self.assertEqual(post_body, {"game": "snake", "agent_name": "ZENITH"})
            self.assertIn("agent_name", post_body)
            self.assertEqual(post_body["agent_name"], "ZENITH")
            self.assertNotIn("agentName", post_body)

        self.assertEqual(code, 0)

    def test_cli_preserves_session_metadata_file(self):
        """CLI must preserve creation response and attribution metadata in {session_id}_meta.json."""
        stdout = io.StringIO()
        stderr = io.StringIO()

        code = run_cli(
            ["--dry-run", "--mock-model", "--log-dir", self._tmp_dir, "--max-moves", "2"],
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(code, 0)

        meta_files = list(Path(self._tmp_dir).glob("*_meta.json"))
        self.assertEqual(len(meta_files), 1)
        with open(meta_files[0], "r", encoding="utf-8") as f:
            meta = json.load(f)

        self.assertEqual(meta["agent_name"], "ZENITH")
        self.assertEqual(meta["game"], "snake")
        self.assertEqual(meta["mode"], "dry_run")
        self.assertIn("initial_response", meta)
        self.assertIn("session_id", meta)

    def test_live_creation_error_exits_with_code_1(self):
        """Network error during live session creation returns exit code 1."""
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.object(ArenaClient, "create_session", side_effect=ArenaHttpError("Server error", 500)):
            code = run_cli(
                ["--live", "--mock-model", "--log-dir", self._tmp_dir],
                input_fn=lambda _: "YES",
                stdout=stdout,
                stderr=stderr,
            )

        self.assertEqual(code, 1)
        self.assertIn("Arena session creation failed", stderr.getvalue())

    def test_invalid_decision_never_submits_action(self):
        """Invalid decisions must be stopped by the validator and never submitted to Arena."""
        stdout = io.StringIO()
        stderr = io.StringIO()

        # Decision with invalid probability sum
        bad_decision = {
            "questions": ["Which way?"],
            "probabilities": {"up": 0.5, "down": 0.1, "left": 0.1, "right": 0.1},  # Sum = 0.8 (invalid!)
            "chosen": "up",
            "confidence": 0.5,
            "source": "laya",
        }

        with patch("zenith.main.make_mock_decide_fn", return_value=lambda g, s: bad_decision), \
             patch.object(MockSnakeArena, "submit_action") as mock_submit:

            code = run_cli(
                ["--mock-model", "--log-dir", self._tmp_dir, "--max-consecutive-errors", "2"],
                stdout=stdout,
                stderr=stderr,
            )
            # Submit action must never have been called with the bad decision
            mock_submit.assert_not_called()

        self.assertEqual(code, 1)
        self.assertIn("validation errors", stderr.getvalue().lower())

    def test_hash_chain_failure_exits_with_code_3(self):
        """If log verification fails after run, CLI must exit with code 3."""
        stdout = io.StringIO()
        stderr = io.StringIO()

        from zenith.hash_chain import VerificationResult

        with patch.object(
            SessionLogger,
            "verify_log",
            return_value=VerificationResult(is_valid=False, error_message="Hash mismatch at line 2"),
        ):
            code = run_cli(
                ["--mock-model", "--log-dir", self._tmp_dir, "--max-moves", "2"],
                stdout=stdout,
                stderr=stderr,
            )

        self.assertEqual(code, 3)
        self.assertIn("hash chain verification failed", stderr.getvalue().lower())

    def test_live_model_init_failure_prevents_arena_requests(self):
        """Failure during LayaAdapter initialization must abort immediately with code 1 and make no Arena requests."""
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch("zenith.main.LayaAdapter", side_effect=TypeError("LayaAdapter.__init__() got an unexpected keyword argument 'model_name'")), \
             patch.object(ArenaClient, "create_session") as mock_create:

            code = run_cli(
                ["--live", "--log-dir", self._tmp_dir],
                stdout=stdout,
                stderr=stderr,
            )
            mock_create.assert_not_called()

        self.assertEqual(code, 1)
        self.assertIn("Failed to initialize Laya adapter", stderr.getvalue())

    def test_live_model_initialized_with_correct_model_id(self):
        """Verify that CLI constructs LayaAdapter using model_id=APPROVED_MODEL_ID."""
        stdout = io.StringIO()
        stderr = io.StringIO()

        mock_initial = {
            "session_id": "live-session-456",
            "game": "snake",
            "state": {"snake": [{"x": 5, "y": 5}], "food": {"x": 5, "y": 4}, "direction": "up"},
            "done": False,
            "score": 0,
        }
        mock_move_resp = {
            "session_id": "live-session-456",
            "game": "snake",
            "state": {"snake": [{"x": 5, "y": 4}], "food": {"x": 5, "y": 4}, "direction": "up"},
            "done": True,
            "score": 100,
            "won": True,
            "result": "applied",
        }

        mock_adapter_instance = MagicMock()
        mock_adapter_instance.decide = MagicMock(return_value={
            "questions": ["Which way?"],
            "probabilities": {"up": 0.7, "down": 0.1, "left": 0.1, "right": 0.1},
            "chosen": "up",
            "confidence": 0.7,
            "source": "laya",
        })

        from zenith.laya_adapter import APPROVED_MODEL_ID

        with patch("zenith.main.LayaAdapter", return_value=mock_adapter_instance) as mock_adapter_cls, \
             patch.object(ArenaClient, "create_session", return_value=mock_initial) as mock_create, \
             patch.object(ArenaClient, "submit_action", return_value=mock_move_resp) as mock_submit:

            code = run_cli(
                ["--live", "--log-dir", self._tmp_dir],
                input_fn=lambda _: "YES",
                stdout=stdout,
                stderr=stderr,
            )
            mock_adapter_cls.assert_called_once_with(model_id=APPROVED_MODEL_ID)
            mock_create.assert_called_once()
            mock_submit.assert_called_once()

        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()


