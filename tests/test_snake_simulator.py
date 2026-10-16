"""Tests for the deterministic local Snake simulator."""

import os
import shutil
import tempfile
import unittest

from zenith.decision_viewer import DecisionViewer
from zenith.runner import SessionRunner
from zenith.session_logger import SessionLogger
from zenith.snake_simulator import DeterministicSnakeSimulator


class TestDeterministicSnakeSimulator(unittest.TestCase):
    """Test suite for DeterministicSnakeSimulator mechanics and Arena protocol."""

    def test_seed_determinism(self):
        """Two simulators with the same seed must yield identical food positions."""
        sim1 = DeterministicSnakeSimulator(seed=123)
        sim2 = DeterministicSnakeSimulator(seed=123)

        self.assertEqual(sim1.get_session("sim1")["state"]["food"], sim2.get_session("sim2")["state"]["food"])

        # Execute identical sequence
        sim1.submit_action("sim1", "left")
        sim2.submit_action("sim2", "left")

        self.assertEqual(sim1.get_session("sim1")["state"]["snake"], sim2.get_session("sim2")["state"]["snake"])

    def test_reversal_rejection(self):
        """Moving opposite to current direction with length > 1 must be rejected."""
        sim = DeterministicSnakeSimulator(initial_direction="up")
        resp = sim.submit_action(sim.session_id, "down")

        self.assertEqual(resp["result"], "rejected")
        self.assertEqual(sim.accepted_moves, 0)
        self.assertEqual(sim.rejected_moves, 1)
        self.assertFalse(sim.done)

    def test_invalid_action_rejection(self):
        """Invalid action string must be rejected."""
        sim = DeterministicSnakeSimulator()
        resp = sim.submit_action(sim.session_id, "jump")

        self.assertEqual(resp["result"], "rejected")
        self.assertEqual(sim.accepted_moves, 0)
        self.assertEqual(sim.rejected_moves, 1)
        self.assertFalse(sim.done)

    def test_wall_collision(self):
        """Hitting a boundary wall must terminate the game with done=True and won=False."""
        # Initial head at (6, 6) moving up.
        # Moving up 7 times reaches y=-1.
        sim = DeterministicSnakeSimulator()
        for i in range(6):
            resp = sim.submit_action(sim.session_id, "up")
            self.assertFalse(resp["done"], f"Step {i} unexpectedly ended game")

        resp = sim.submit_action(sim.session_id, "up")
        self.assertTrue(resp["done"])
        self.assertFalse(resp["won"])
        self.assertEqual(sim.termination_reason, "wall_collision")

    def test_self_collision(self):
        """Turning into one's own body must terminate the game."""
        # Setup snake with custom body
        custom_snake = [
            {"x": 5, "y": 5},
            {"x": 4, "y": 5},
            {"x": 4, "y": 4},
            {"x": 5, "y": 4},
            {"x": 6, "y": 4},
        ]
        sim = DeterministicSnakeSimulator(
            initial_snake=custom_snake,
            initial_direction="right",
        )
        # Turn up into (5, 4) which is part of body
        resp = sim.submit_action(sim.session_id, "up")
        self.assertTrue(resp["done"])
        self.assertFalse(resp["won"])
        self.assertEqual(sim.termination_reason, "self_collision")

    def test_food_consumption_growth_and_scoring(self):
        """Eating food increases length, food_eaten count, and score."""
        sim = DeterministicSnakeSimulator()
        # Force food position right in front of head at (6, 5)
        sim._food = {"x": 6, "y": 5}
        initial_len = len(sim.get_session(sim.session_id)["state"]["snake"])

        resp = sim.submit_action(sim.session_id, "up")
        self.assertEqual(sim.food_eaten, 1)
        self.assertEqual(sim.score, 60)  # 1 * 60 + 0
        new_len = len(resp["state"]["snake"])
        self.assertEqual(new_len, initial_len + 1)

    def test_win_condition_at_15_foods(self):
        """Reaching 15 foods immediately triggers win with 1000 points."""
        sim = DeterministicSnakeSimulator(target_food=2)
        # First food
        sim._food = {"x": 6, "y": 5}
        sim.submit_action(sim.session_id, "up")
        self.assertFalse(sim.done)

        # Second food
        sim._food = {"x": 6, "y": 4}
        resp = sim.submit_action(sim.session_id, "up")
        self.assertTrue(resp["done"])
        self.assertTrue(resp["won"])
        self.assertEqual(sim.termination_reason, "target_food_reached")
        self.assertEqual(sim.score, 2 * 60 + 100)

    def test_max_moves_reached(self):
        """Reaching max_moves ends the game."""
        sim = DeterministicSnakeSimulator(max_moves=2)
        sim.submit_action(sim.session_id, "left")
        self.assertFalse(sim.done)
        resp = sim.submit_action(sim.session_id, "up")
        self.assertTrue(resp["done"])
        self.assertEqual(sim.termination_reason, "max_moves_reached")

    def test_integration_with_session_runner(self):
        """The simulator must work seamlessly with SessionRunner and SessionLogger."""
        temp_dir = tempfile.mkdtemp()
        try:
            sim = DeterministicSnakeSimulator(max_moves=5, seed=99)
            logger = SessionLogger(session_id=sim.session_id, game="snake", log_dir=temp_dir)
            import io
            viewer = DecisionViewer(game="snake", session_id=sim.session_id, out=io.StringIO())

            def mock_decide(game, state):
                # Always turn left or up safely
                cur_dir = state.get("direction", "up")
                act = "left" if cur_dir == "up" else "up"
                return {
                    "questions": ["Next move?"],
                    "probabilities": {"up": 0.5, "down": 0.0, "left": 0.5, "right": 0.0},
                    "chosen": act,
                    "confidence": 0.5,
                    "source": "laya",
                }

            runner = SessionRunner(
                arena=sim,
                decide_fn=mock_decide,
                logger=logger,
                viewer=viewer,
            )
            result = runner.run()

            self.assertGreater(result.total_moves, 0)
            self.assertTrue(result.hash_chain_valid)
            self.assertTrue(os.path.exists(result.log_path))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
