"""Unit tests for zenith/laya_adapter.py."""

from __future__ import annotations

import io
import math
import shutil
import tempfile
import unittest
from typing import Any, Dict, List, Mapping
from unittest.mock import MagicMock, patch

from zenith.decision_validator import DecisionValidationError
from zenith.laya_adapter import (
    APPROVED_MODEL_ID,
    CRITERIA,
    QUESTION_KEY,
    LayaAdapter,
    LayaInferenceError,
    LayaResponseContractError,
    _parse_coord,
    build_laya_questions,
    extract_and_validate_choice_response,
    format_snake_state,
)
from zenith.decision_viewer import DecisionViewer
from zenith.runner import SessionRunner
from zenith.session_logger import SessionLogger


class MockLayaAgent:
    """Mock Laya agent returning configurable predictions."""

    def __init__(self, canned_response: Any = None) -> None:
        if canned_response is not None:
            self.canned_response = canned_response
        else:
            self.canned_response = {
                "model": "laya-rl-agent",
                "answers": {
                    QUESTION_KEY: {
                        "type": "choice",
                        "choice": "right",
                        "probabilities": {
                            "up": 0.0607,
                            "down": 0.0334,
                            "left": 0.0386,
                            "right": 0.8673,
                        },
                        "confidence": 0.6157,
                        "answer_confidence": 0.8673,
                        "action": {"act_probability": 1.0},
                    }
                },
                "usage": {
                    "input_tokens": 180,
                    "output_tokens": 0,
                    "state_tokens": 129,
                    "state_tokens_dropped": 0,
                    "truncated": False,
                    "truncated_questions": [],
                },
            }
        self.last_state = None
        self.last_questions = None
        self.call_count = 0

    def predict(self, state: Any, questions: Any) -> Any:
        self.last_state = state
        self.last_questions = questions
        self.call_count += 1
        if isinstance(self.canned_response, Exception):
            raise self.canned_response
        return self.canned_response


class MockArenaClient:
    """Mock Arena API client for runner integration."""

    def __init__(self, states: List[Dict[str, Any]]) -> None:
        self.states = states
        self.index = 0
        self.actions_received: List[str] = []

    def create_session(self, game: str, agent_name: str) -> Dict[str, Any]:
        return {
            "session_id": "test-sess-laya",
            "game": game,
            "state": self.states[0],
            "done": False,
            "score": 0,
        }

    def get_session(self, session_id: str) -> Dict[str, Any]:
        st = self.states[min(self.index, len(self.states) - 1)]
        is_done = self.index >= len(self.states) - 1
        return {
            "session_id": session_id,
            "game": "snake",
            "state": st,
            "done": is_done,
            "score": self.index * 60,
        }

    def submit_action(self, session_id: str, action: str) -> Dict[str, Any]:
        self.actions_received.append(action)
        self.index += 1
        is_done = self.index >= len(self.states) - 1
        return {
            "session_id": session_id,
            "game": "snake",
            "state": self.states[min(self.index, len(self.states) - 1)],
            "done": is_done,
            "score": self.index * 60,
            "won": is_done,
        }


class TestParseCoord(unittest.TestCase):
    """Tests for _parse_coord helper."""

    def test_parse_dict_coord(self):
        self.assertEqual(_parse_coord({"x": 5, "y": 10}), (5, 10))
        self.assertEqual(_parse_coord({"x": "3", "y": "4"}), (3, 4))
        self.assertIsNone(_parse_coord({"x": "abc", "y": 4}))
        self.assertIsNone(_parse_coord({"x": 5}))

    def test_parse_list_coord(self):
        self.assertEqual(_parse_coord([5, 10]), (5, 10))
        self.assertEqual(_parse_coord((7, 8)), (7, 8))
        self.assertEqual(_parse_coord(["2", "9"]), (2, 9))
        self.assertIsNone(_parse_coord([1]))
        self.assertIsNone(_parse_coord("invalid"))


class TestFormatSnakeState(unittest.TestCase):
    """Tests for format_snake_state."""

    def test_standard_arena_state(self):
        state = {
            "width": 12,
            "height": 12,
            "snake": [{"x": 6, "y": 6}, {"x": 6, "y": 7}],
            "food": {"x": 3, "y": 2},
            "direction": "up",
            "foodEaten": 1,
        }
        prompt_state, question_text = format_snake_state(state)

        self.assertEqual(prompt_state["game"], "snake")
        self.assertEqual(prompt_state["board"], {"width": 12, "height": 12})
        self.assertEqual(prompt_state["snake_head"], [6, 6])
        self.assertEqual(prompt_state["snake_body"], [[6, 7]])
        self.assertEqual(prompt_state["current_direction"], "up")
        self.assertEqual(prompt_state["food"], [3, 2])
        self.assertEqual(prompt_state["food_eaten"], 1)

        self.assertIn("12x12 board", question_text)
        self.assertIn("[6, 6]", question_text)
        self.assertIn("current direction is up", question_text)
        self.assertIn("[3, 2]", question_text)

    def test_list_coordinates(self):
        state = {
            "width": 10,
            "height": 10,
            "snake": [[4, 4], [4, 5]],
            "food": [8, 8],
            "direction": "LEFT",
        }
        prompt_state, question_text = format_snake_state(state)
        self.assertEqual(prompt_state["snake_head"], [4, 4])
        self.assertEqual(prompt_state["snake_body"], [[4, 5]])
        self.assertEqual(prompt_state["food"], [8, 8])
        self.assertEqual(prompt_state["current_direction"], "left")

    def test_grid_scanning_fallback(self):
        # 3x3 grid: (1,1) is head (3), (1,2) is body (1), (0,0) is food (2)
        grid = [
            [2, 0, 0],
            [0, 3, 0],
            [0, 1, 0],
        ]
        state = {"grid": grid}
        prompt_state, question_text = format_snake_state(state)
        self.assertEqual(prompt_state["board"], {"width": 3, "height": 3})
        self.assertEqual(prompt_state["snake_head"], [1, 1])
        self.assertEqual(prompt_state["snake_body"], [[1, 2]])
        self.assertEqual(prompt_state["food"], [0, 0])

    def test_empty_or_malformed_state(self):
        prompt_state, question_text = format_snake_state({})
        self.assertEqual(prompt_state["board"], {"width": 12, "height": 12})
        self.assertEqual(prompt_state["snake_head"], [6, 6])
        self.assertEqual(prompt_state["snake_body"], [])
        self.assertEqual(prompt_state["food"], [0, 0])
        self.assertTrue(len(question_text) > 0)


class TestBuildLayaQuestions(unittest.TestCase):
    """Tests for build_laya_questions and SDK question schema compliance."""

    def test_question_structure(self):
        """Assert build_laya_questions strictly uses instructions and criteria."""
        q = build_laya_questions("Which way to move?")
        self.assertIn(QUESTION_KEY, q)
        q_def = q[QUESTION_KEY]
        # Must have exactly type, instructions, criteria - NOT text or options
        self.assertEqual(set(q_def.keys()), {"type", "instructions", "criteria"})
        self.assertEqual(q_def["type"], "choice")
        self.assertEqual(q_def["instructions"], "Which way to move?")
        self.assertNotIn("text", q_def)
        self.assertNotIn("options", q_def)
        self.assertEqual(set(q_def["criteria"].keys()), {"up", "down", "left", "right"})

    def test_laya_sdk_schema_rejection_of_text_and_options(self):
        """Verify installed Laya SDK rejects text/options and accepts instructions/criteria."""
        try:
            from laya.agent import Agent
        except ImportError:
            self.skipTest("laya package not installed in environment")

        q = build_laya_questions("Which direction should the snake move?")
        # Must pass Laya SDK's Agent._check_question validation without error
        Agent._check_question(QUESTION_KEY, q[QUESTION_KEY])

        # Passing legacy text/options schema must be rejected by Laya SDK
        legacy_def = {
            "type": "choice",
            "text": "Which direction should the snake move?",
            "options": {"up": "Move up", "down": "Move down", "left": "Move left", "right": "Move right"},
        }
        with self.assertRaises(ValueError) as ctx:
            Agent._check_question(QUESTION_KEY, legacy_def)
        self.assertIn("instructions", str(ctx.exception).lower())



class TestExtractAndValidateChoiceResponse(unittest.TestCase):
    """Tests for extract_and_validate_choice_response."""

    def setUp(self):
        self.valid_raw = {
            "model": "laya-rl-agent",
            "answers": {
                QUESTION_KEY: {
                    "type": "choice",
                    "choice": "right",
                    "probabilities": {
                        "up": 0.0607,
                        "down": 0.0334,
                        "left": 0.0386,
                        "right": 0.8673,
                    },
                    "confidence": 0.6157,  # entropy-based
                    "answer_confidence": 0.8673,  # calibrated max prob
                    "action": {"act_probability": 1.0},
                }
            },
            "usage": {"input_tokens": 150},
        }
        self.q_text = "What is the next move?"

    def test_valid_response_mapping(self):
        dec, diag = extract_and_validate_choice_response(
            self.valid_raw, QUESTION_KEY, self.q_text
        )
        self.assertEqual(dec["chosen"], "right")
        self.assertEqual(dec["source"], "laya")
        self.assertEqual(dec["questions"], [self.q_text])
        # Competition confidence strictly matches probabilities[chosen]
        self.assertAlmostEqual(dec["confidence"], 0.8673)
        self.assertEqual(set(dec["probabilities"].keys()), {"up", "down", "left", "right"})
        self.assertAlmostEqual(sum(dec["probabilities"].values()), 1.0, places=4)

        # Diagnostics preserved separately
        self.assertAlmostEqual(diag["raw_laya_confidence"], 0.6157)
        self.assertAlmostEqual(diag["raw_answer_confidence"], 0.8673)
        self.assertEqual(diag["token_usage"], {"input_tokens": 150})
        self.assertEqual(diag["model_name"], "laya-rl-agent")

    def test_non_dict_raw_result(self):
        with self.assertRaises(LayaInferenceError):
            extract_and_validate_choice_response("invalid", QUESTION_KEY, self.q_text)

    def test_missing_answers_key(self):
        with self.assertRaises(LayaInferenceError):
            extract_and_validate_choice_response({"output": {}}, QUESTION_KEY, self.q_text)

    def test_missing_question_key(self):
        with self.assertRaises(LayaInferenceError):
            extract_and_validate_choice_response(
                {"answers": {"other_q": {}}}, QUESTION_KEY, self.q_text
            )

    def test_invalid_choice_direction(self):
        raw = {
            "answers": {
                QUESTION_KEY: {
                    "choice": "forward",
                    "probabilities": {"up": 0.25, "down": 0.25, "left": 0.25, "right": 0.25},
                }
            }
        }
        with self.assertRaises(LayaResponseContractError):
            extract_and_validate_choice_response(raw, QUESTION_KEY, self.q_text)

    def test_missing_probability_keys(self):
        raw = {
            "answers": {
                QUESTION_KEY: {
                    "choice": "up",
                    "probabilities": {"up": 0.5, "down": 0.5},
                }
            }
        }
        with self.assertRaises(LayaResponseContractError):
            extract_and_validate_choice_response(raw, QUESTION_KEY, self.q_text)

    def test_extra_probability_keys(self):
        raw = {
            "answers": {
                QUESTION_KEY: {
                    "choice": "up",
                    "probabilities": {
                        "up": 0.25,
                        "down": 0.25,
                        "left": 0.25,
                        "right": 0.25,
                        "stay": 0.0,
                    },
                }
            }
        }
        with self.assertRaises(LayaResponseContractError):
            extract_and_validate_choice_response(raw, QUESTION_KEY, self.q_text)

    def test_boolean_probability_rejected(self):
        raw = {
            "answers": {
                QUESTION_KEY: {
                    "choice": "up",
                    "probabilities": {"up": True, "down": 0.0, "left": 0.0, "right": 0.0},
                }
            }
        }
        with self.assertRaises(LayaResponseContractError):
            extract_and_validate_choice_response(raw, QUESTION_KEY, self.q_text)

    def test_non_finite_probability_rejected(self):
        raw = {
            "answers": {
                QUESTION_KEY: {
                    "choice": "up",
                    "probabilities": {"up": float("nan"), "down": 0.33, "left": 0.33, "right": 0.34},
                }
            }
        }
        with self.assertRaises(LayaResponseContractError):
            extract_and_validate_choice_response(raw, QUESTION_KEY, self.q_text)

    def test_probability_out_of_range(self):
        raw = {
            "answers": {
                QUESTION_KEY: {
                    "choice": "up",
                    "probabilities": {"up": -0.1, "down": 0.5, "left": 0.3, "right": 0.3},
                }
            }
        }
        with self.assertRaises(LayaResponseContractError):
            extract_and_validate_choice_response(raw, QUESTION_KEY, self.q_text)

    def test_probability_sum_out_of_range(self):
        # Sum = 0.5 (< 0.98)
        raw = {
            "answers": {
                QUESTION_KEY: {
                    "choice": "up",
                    "probabilities": {"up": 0.2, "down": 0.1, "left": 0.1, "right": 0.1},
                }
            }
        }
        with self.assertRaises(LayaResponseContractError):
            extract_and_validate_choice_response(raw, QUESTION_KEY, self.q_text)

        # Sum = 1.3 (> 1.02)
        raw["answers"][QUESTION_KEY]["probabilities"] = {
            "up": 0.5,
            "down": 0.3,
            "left": 0.3,
            "right": 0.2,
        }
        with self.assertRaises(LayaResponseContractError):
            extract_and_validate_choice_response(raw, QUESTION_KEY, self.q_text)


class TestLayaAdapter(unittest.TestCase):
    """Tests for LayaAdapter class."""

    def test_init_with_mock_agent(self):
        agent = MockLayaAgent()
        adapter = LayaAdapter(agent=agent)
        self.assertIs(adapter.agent, agent)
        self.assertEqual(adapter.model_id, APPROVED_MODEL_ID)
        self.assertIsNone(adapter.get_last_metadata())

    def test_init_rejects_unapproved_model_without_agent(self):
        with self.assertRaises(ValueError):
            LayaAdapter(model_id="unapproved/fake-model")

    def test_init_signature_model_id_and_rejects_model_name(self):
        """Verify that LayaAdapter accepts model_id and rejects the erroneous model_name argument."""
        agent = MockLayaAgent()
        # model_id as keyword argument must succeed
        adapter = LayaAdapter(agent=agent, model_id=APPROVED_MODEL_ID)
        self.assertEqual(adapter.model_id, APPROVED_MODEL_ID)

        # Invalid keyword argument model_name must raise TypeError
        with self.assertRaises(TypeError) as ctx:
            LayaAdapter(agent=agent, model_name=APPROVED_MODEL_ID)  # type: ignore[call-arg]
        self.assertIn("unexpected keyword argument 'model_name'", str(ctx.exception))

    def test_decide_snake_success(self):
        agent = MockLayaAgent()
        adapter = LayaAdapter(agent=agent)

        state = {
            "width": 12,
            "height": 12,
            "snake": [{"x": 6, "y": 6}],
            "food": {"x": 3, "y": 3},
            "direction": "up",
        }
        decision = adapter.decide("snake", state)

        self.assertEqual(decision["chosen"], "right")
        self.assertEqual(decision["source"], "laya")
        self.assertAlmostEqual(decision["confidence"], 0.8673)
        self.assertEqual(set(decision["probabilities"].keys()), {"up", "down", "left", "right"})
        self.assertTrue(len(decision["questions"]) == 1)

        # Verify metadata
        meta = adapter.get_last_metadata()
        self.assertIsNotNone(meta)
        self.assertIn("inference_ms", meta)
        self.assertGreater(meta["inference_ms"], 0.0)
        self.assertEqual(meta["model_id"], APPROVED_MODEL_ID)
        self.assertAlmostEqual(meta["raw_laya_confidence"], 0.6157)
        self.assertAlmostEqual(meta["raw_answer_confidence"], 0.8673)

    def test_decide_rejects_unsupported_game(self):
        agent = MockLayaAgent()
        adapter = LayaAdapter(agent=agent)
        with self.assertRaises(ValueError):
            adapter.decide("2048", {})
        with self.assertRaises(ValueError):
            adapter.decide("chess", {})

    def test_decide_handles_agent_exception(self):
        agent = MockLayaAgent(canned_response=RuntimeError("CUDA OOM error"))
        adapter = LayaAdapter(agent=agent)
        with self.assertRaises(LayaInferenceError) as ctx:
            adapter.decide("snake", {})
        self.assertIn("Laya predict() failed", str(ctx.exception))


class TestLayaAdapterRunnerIntegration(unittest.TestCase):
    """End-to-end integration test of LayaAdapter with SessionRunner."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def test_runner_with_laya_adapter(self):
        # 3-move scripted Snake game
        states = [
            {"width": 10, "height": 10, "snake": [[5, 5]], "food": [5, 6], "direction": "right"},
            {"width": 10, "height": 10, "snake": [[5, 6]], "food": [5, 7], "direction": "right"},
            {"width": 10, "height": 10, "snake": [[5, 7]], "food": [5, 8], "direction": "right"},
            {"width": 10, "height": 10, "snake": [[5, 8]], "food": [5, 9], "direction": "right"},
        ]
        arena_client = MockArenaClient(states)
        agent = MockLayaAgent()
        adapter = LayaAdapter(agent=agent)

        session_id = "test-laya-runner-sess"
        logger = SessionLogger(session_id, "snake", log_dir=self._tmp_dir)
        buf = io.StringIO()
        viewer = DecisionViewer("snake", session_id, mock_mode=True, out=buf)

        runner = SessionRunner(
            arena=arena_client,
            decide_fn=adapter.decide,
            logger=logger,
            viewer=viewer,
        )

        result = runner.run()

        self.assertIsNone(result.error)
        self.assertEqual(result.total_moves, 3)
        self.assertEqual(result.applied_moves, 3)
        self.assertEqual(result.fallback_moves, 0)
        self.assertTrue(result.hash_chain_valid)

        # Check log file verification on disk
        self.assertTrue(logger.verify_log())

        # Verify agent was called 3 times
        self.assertEqual(agent.call_count, 3)
        self.assertEqual(arena_client.actions_received, ["right", "right", "right"])


if __name__ == "__main__":
    unittest.main()
