"""Unit tests for the benchmark suite and optimization helpers."""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock

from zenith.benchmark import (
    Benchmark2048RunResult,
    BenchmarkRunResult,
    format_2048_results_markdown,
    format_comparison_markdown,
    format_results_markdown,
    load_benchmark_json,
    run_2048_benchmark_suite,
    run_benchmark_suite,
    run_single_2048_benchmark,
    run_single_benchmark,
    save_2048_benchmark_json,
    save_benchmark_json,
)
from zenith.decision_viewer import DecisionViewer
from zenith.game2048_simulator import Deterministic2048Simulator
from zenith.laya_adapter import build_snake_criteria, format_snake_state
from zenith.runner import SessionRunner
from zenith.session_logger import SessionLogger
from zenith.snake_simulator import DeterministicSnakeSimulator



class TestBenchmarkFormattingAndSerialization(unittest.TestCase):
    """Test suite for benchmark dataclass, JSON serialization, and Markdown formatting."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def test_save_and_load_benchmark_json(self):
        res1 = BenchmarkRunResult(
            seed=42,
            prompt_version="v2",
            model_id="convaiinnovations/laya",
            score=1000,
            food_eaten=15,
            accepted_moves=105,
            rejected_moves=0,
            fallback_moves=0,
            won=True,
            termination_reason="target_food_reached",
            avg_inference_ms=45.2,
            min_inference_ms=39.0,
            max_inference_ms=88.5,
            total_time_s=4.75,
            hash_chain_valid=True,
            log_path="logs/test/bench-v2-42.jsonl",
            failure_details=None,
        )

        out_path = os.path.join(self._tmp_dir, "test_bench.json")
        save_benchmark_json([res1], out_path)

        loaded = load_benchmark_json(out_path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].seed, 42)
        self.assertEqual(loaded[0].score, 1000)
        self.assertEqual(loaded[0].food_eaten, 15)
        self.assertTrue(loaded[0].won)
        self.assertTrue(loaded[0].hash_chain_valid)

    def test_format_results_markdown(self):
        res = [
            BenchmarkRunResult(
                seed=42,
                prompt_version="v2",
                model_id="convaiinnovations/laya",
                score=1000,
                food_eaten=15,
                accepted_moves=105,
                rejected_moves=0,
                fallback_moves=0,
                won=True,
                termination_reason="target_food_reached",
                avg_inference_ms=45.2,
                min_inference_ms=39.0,
                max_inference_ms=88.5,
                total_time_s=4.75,
                hash_chain_valid=True,
                log_path="logs/bench.jsonl",
            )
        ]
        md = format_results_markdown(res, title="Test Benchmark")
        self.assertIn("### Test Benchmark", md)
        self.assertIn("1000", md)
        self.assertIn("target_food_reached", md)
        self.assertIn("Win Rate: 100.0%", md)

    def test_format_comparison_markdown(self):
        b = [
            BenchmarkRunResult(
                seed=42,
                prompt_version="v1",
                model_id="convaiinnovations/laya",
                score=0,
                food_eaten=0,
                accepted_moves=7,
                rejected_moves=0,
                fallback_moves=0,
                won=False,
                termination_reason="wall_collision",
                avg_inference_ms=41.0,
                min_inference_ms=40.0,
                max_inference_ms=43.0,
                total_time_s=0.3,
                hash_chain_valid=True,
                log_path="logs/b42.jsonl",
            )
        ]
        r = [
            BenchmarkRunResult(
                seed=42,
                prompt_version="v2",
                model_id="convaiinnovations/laya",
                score=1000,
                food_eaten=15,
                accepted_moves=105,
                rejected_moves=0,
                fallback_moves=0,
                won=True,
                termination_reason="target_food_reached",
                avg_inference_ms=45.0,
                min_inference_ms=40.0,
                max_inference_ms=80.0,
                total_time_s=4.5,
                hash_chain_valid=True,
                log_path="logs/r42.jsonl",
            )
        ]
        comp_md = format_comparison_markdown(b, r)
        self.assertIn("### Benchmark Baseline (v1) vs Revised (v2) Comparison", comp_md)
        self.assertIn("wall_collision", comp_md)
        self.assertIn("target_food_reached", comp_md)
        self.assertIn("Baseline (v1):** Total Food = 0", comp_md)
        self.assertIn("Revised (v2):** Total Food = 15", comp_md)


class TestBenchmarkExecutionWithMock(unittest.TestCase):
    """Test suite for benchmark runners using simulated decisions."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def test_run_single_benchmark_with_mock_adapter(self):
        mock_adapter = MagicMock()
        mock_adapter.model_id = "mock-model"
        mock_adapter.prompt_version = "v2"

        # Mock decide function that cycles through left, up, right, down safely
        def mock_decide(game, state):
            return {
                "questions": ["Which way?"],
                "probabilities": {"up": 0.25, "down": 0.25, "left": 0.25, "right": 0.25},
                "chosen": "up",
                "confidence": 0.25,
                "source": "laya",
            }

        mock_adapter.decide = mock_decide

        res = run_single_benchmark(
            seed=42,
            adapter=mock_adapter,
            prompt_version="v2",
            log_dir=self._tmp_dir,
            quiet=True,
            max_moves=5,
        )

        self.assertEqual(res.seed, 42)
        self.assertEqual(res.prompt_version, "v2")
        self.assertTrue(res.hash_chain_valid)
        self.assertTrue(os.path.exists(res.log_path))

    def test_run_benchmark_suite_with_mock_adapter(self):
        mock_adapter = MagicMock()
        mock_adapter.model_id = "mock-model"
        mock_adapter.prompt_version = "v2"

        def mock_decide(game, state):
            return {
                "questions": ["Move?"],
                "probabilities": {"up": 0.7, "down": 0.1, "left": 0.1, "right": 0.1},
                "chosen": "up",
                "confidence": 0.7,
                "source": "laya",
            }

        mock_adapter.decide = mock_decide

        results = run_benchmark_suite(
            seeds=[1, 2],
            prompt_version="v2",
            log_dir=self._tmp_dir,
            quiet=True,
            adapter=mock_adapter,
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].seed, 1)
        self.assertEqual(results[1].seed, 2)


class TestRunnerRejectionGuard(unittest.TestCase):
    """Test suite for SessionRunner rejection loop protection."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def test_runner_stops_after_consecutive_rejections(self):
        sim = DeterministicSnakeSimulator(initial_direction="up")
        logger = SessionLogger(session_id="test-rej-guard", game="snake", log_dir=self._tmp_dir)
        import io
        viewer = DecisionViewer(game="snake", session_id="test-rej-guard", out=io.StringIO())

        # decide_fn that always proposes "down" (illegal reversal into neck)
        def stubborn_decide(game, state):
            return {
                "questions": ["Move?"],
                "probabilities": {"up": 0.1, "down": 0.7, "left": 0.1, "right": 0.1},
                "chosen": "down",
                "confidence": 0.7,
                "source": "laya",
            }

        runner = SessionRunner(
            arena=sim,
            decide_fn=stubborn_decide,
            logger=logger,
            viewer=viewer,
            max_consecutive_rejections=3,
        )

        result = runner.run()

        self.assertIn("Too many consecutive rejected moves", str(result.error))
        self.assertEqual(result.rejected_moves, 3)
        self.assertEqual(result.applied_moves, 0)
        self.assertTrue(result.hash_chain_valid)


class TestPromptV2Logic(unittest.TestCase):
    """Test suite for revised v2 prompt formatting and criteria generation."""

    def test_v2_prompt_wall_and_food_navigation(self):
        state = {
            "width": 12,
            "height": 12,
            "snake": [{"x": 11, "y": 2}, {"x": 10, "y": 2}, {"x": 9, "y": 2}],
            "food": {"x": 4, "y": 2},
            "direction": "right",
            "foodEaten": 0,
        }

        prompt_state, question_text = format_snake_state(state, prompt_version="v2")
        criteria = build_snake_criteria(state, prompt_version="v2")

        self.assertIn("Moving left or right causes fatal collision or illegal reversal.", question_text)
        self.assertIn("Which safe direction should the snake choose to avoid collision and stay alive?", question_text)

        self.assertIn("deadly collision into wall", criteria["right"])
        self.assertIn("forbidden reversal into snake body", criteria["left"])
        self.assertIn("Safe move: safely avoids collision", criteria["up"])
        self.assertIn("Safe move: safely avoids collision", criteria["down"])

    def test_v2_prompt_food_ahead(self):
        state = {
            "width": 12,
            "height": 12,
            "snake": [{"x": 6, "y": 6}, {"x": 6, "y": 7}, {"x": 6, "y": 8}],
            "food": {"x": 6, "y": 3},
            "direction": "up",
            "foodEaten": 1,
        }

        prompt_state, question_text = format_snake_state(state, prompt_version="v2")
        criteria = build_snake_criteria(state, prompt_version="v2")

        self.assertIn("Moving up safely advances toward the food.", question_text)
        self.assertIn("Which safe direction should the snake choose to advance toward the food?", question_text)
        self.assertIn("Best move: advances toward the food", criteria["up"])
        self.assertIn("forbidden reversal into snake body", criteria["down"])


class Test2048BenchmarkSuite(unittest.TestCase):
    """Test suite for 2048 benchmark functions."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def test_2048_benchmark_dataclass_and_json(self):
        res = Benchmark2048RunResult(
            seed=42,
            prompt_version="v2",
            model_id="convaiinnovations/laya",
            highest_tile=512,
            score=4520,
            tournament_score=433,
            accepted_moves=250,
            rejected_moves=5,
            fallback_moves=0,
            won=False,
            termination_reason="no_moves_remaining",
            avg_inference_ms=45.0,
            min_inference_ms=40.0,
            max_inference_ms=60.0,
            total_time_s=11.25,
            hash_chain_valid=True,
            log_path="logs/bench-2048.jsonl",
            final_grid=[[512, 256, 128, 64], [32, 16, 8, 4], [2, 0, 0, 0], [0, 0, 0, 0]],
        )
        out_p = os.path.join(self._tmp_dir, "test_2048.json")
        save_2048_benchmark_json([res], out_p)
        self.assertTrue(os.path.isfile(out_p))

        md = format_2048_results_markdown([res], title="Test 2048")
        self.assertIn("Test 2048", md)
        self.assertIn("512", md)
        self.assertIn("Runs Reaching >= 512:** 1/1", md)

    def test_run_single_2048_benchmark_with_mock_adapter(self):
        mock_adapter = MagicMock()
        mock_adapter.model_id = "convaiinnovations/laya"
        mock_adapter.prompt_version = "v2"

        # Mock decide cycling directions
        dirs = ["left", "down", "right", "up"]
        idx = [0]
        def _mock_decide(game, state):
            chosen = dirs[idx[0] % len(dirs)]
            idx[0] += 1
            return {
                "questions": ["Slide tiles?"],
                "probabilities": {d: (0.7 if d == chosen else 0.1) for d in ("up", "down", "left", "right")},
                "chosen": chosen,
                "confidence": 0.7,
                "source": "laya",
            }
        mock_adapter.decide = _mock_decide

        res = run_single_2048_benchmark(
            seed=42,
            adapter=mock_adapter,
            prompt_version="v2",
            log_dir=self._tmp_dir,
            quiet=True,
            max_moves=10,
        )

        self.assertEqual(res.seed, 42)
        self.assertEqual(res.prompt_version, "v2")
        self.assertGreater(res.accepted_moves, 0)
        self.assertTrue(res.hash_chain_valid)
        self.assertTrue(os.path.isfile(res.log_path))

    def test_generate_2048_benchmark_from_logs(self):
        """generate_2048_benchmark_from_logs derives metrics directly from verified JSONL logs."""
        mock_adapter = MagicMock()
        mock_adapter.model_id = "convaiinnovations/laya"
        mock_adapter.prompt_version = "v3"

        dirs = ["left", "down", "right", "up"]
        idx = [0]
        def _mock_decide(game, state):
            chosen = dirs[idx[0] % len(dirs)]
            idx[0] += 1
            return {
                "questions": ["Slide tiles v3?"],
                "probabilities": {d: (0.7 if d == chosen else 0.1) for d in ("up", "down", "left", "right")},
                "chosen": chosen,
                "confidence": 0.7,
                "source": "laya",
            }
        mock_adapter.decide = _mock_decide

        run_single_2048_benchmark(
            seed=42,
            adapter=mock_adapter,
            prompt_version="v3",
            log_dir=self._tmp_dir,
            quiet=True,
            max_moves=15,
        )

        from zenith.benchmark import generate_2048_benchmark_from_logs
        derived_results = generate_2048_benchmark_from_logs(
            seeds=[42],
            prompt_version="v3",
            log_dir=self._tmp_dir,
        )

        self.assertEqual(len(derived_results), 1)
        r = derived_results[0]
        self.assertEqual(r.seed, 42)
        self.assertEqual(r.prompt_version, "v3")
        self.assertGreater(r.accepted_moves, 0)
        self.assertGreater(r.highest_tile, 0)
        self.assertTrue(r.hash_chain_valid)
        self.assertEqual(r.termination_reason, "no_moves_remaining")


if __name__ == "__main__":
    unittest.main()

