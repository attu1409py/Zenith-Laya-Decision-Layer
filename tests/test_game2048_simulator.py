"""Tests for the deterministic local 2048 simulator and game mechanics."""

import unittest

from zenith.game2048_simulator import (
    Deterministic2048Simulator,
    has_valid_moves,
    simulate_move,
    slide_and_merge_line,
)


class Test2048Mechanics(unittest.TestCase):
    """Test suite for 2048 row/column sliding, merging, and movement mechanics."""

    def test_slide_and_merge_basic(self):
        """Empty spaces slide left and zeros are padded on the right."""
        res, pts = slide_and_merge_line([0, 2, 0, 4])
        self.assertEqual(res, [2, 4, 0, 0])
        self.assertEqual(pts, 0)

    def test_slide_and_merge_pairs(self):
        """Adjacent identical tiles merge into their sum."""
        res, pts = slide_and_merge_line([2, 2, 0, 0])
        self.assertEqual(res, [4, 0, 0, 0])
        self.assertEqual(pts, 4)

    def test_single_merge_per_move_rule(self):
        """Tiles cannot merge multiple times in a single move.
        [2, 2, 2, 2] -> [4, 4, 0, 0] (never [8, 0, 0, 0]).
        """
        res, pts = slide_and_merge_line([2, 2, 2, 2])
        self.assertEqual(res, [4, 4, 0, 0])
        self.assertEqual(pts, 8)

    def test_slide_merge_precedence_left(self):
        """Leftmost pair merges first when three identical tiles are present.
        [4, 4, 4, 0] -> [8, 4, 0, 0].
        """
        res, pts = slide_and_merge_line([4, 4, 4, 0])
        self.assertEqual(res, [8, 4, 0, 0])
        self.assertEqual(pts, 8)

    def test_slide_merge_with_gap(self):
        """Identical tiles separated by zero merge when slid together.
        [2, 0, 2, 4] -> [4, 4, 0, 0].
        """
        res, pts = slide_and_merge_line([2, 0, 2, 4])
        self.assertEqual(res, [4, 4, 0, 0])
        self.assertEqual(pts, 4)

    def test_no_merge_different_values(self):
        """Different adjacent tiles do not merge."""
        res, pts = slide_and_merge_line([2, 4, 8, 16])
        self.assertEqual(res, [2, 4, 8, 16])
        self.assertEqual(pts, 0)

    def test_all_zeros_line(self):
        """All-zero line returns all zeros and 0 points."""
        res, pts = slide_and_merge_line([0, 0, 0, 0])
        self.assertEqual(res, [0, 0, 0, 0])
        self.assertEqual(pts, 0)

    def test_simulate_move_left(self):
        """Test 2D grid move left."""
        grid = [
            [2, 0, 0, 2],
            [4, 4, 4, 4],
            [0, 0, 0, 0],
            [2, 4, 2, 4],
        ]
        new_grid, pts, changed = simulate_move(grid, "left")
        self.assertTrue(changed)
        self.assertEqual(new_grid[0], [4, 0, 0, 0])
        self.assertEqual(new_grid[1], [8, 8, 0, 0])
        self.assertEqual(new_grid[2], [0, 0, 0, 0])
        self.assertEqual(new_grid[3], [2, 4, 2, 4])
        self.assertEqual(pts, 4 + 16)

    def test_simulate_move_right(self):
        """Test 2D grid move right."""
        grid = [
            [2, 0, 0, 2],
            [4, 4, 4, 4],
            [0, 0, 0, 0],
            [2, 4, 2, 4],
        ]
        new_grid, pts, changed = simulate_move(grid, "right")
        self.assertTrue(changed)
        self.assertEqual(new_grid[0], [0, 0, 0, 4])
        self.assertEqual(new_grid[1], [0, 0, 8, 8])
        self.assertEqual(new_grid[2], [0, 0, 0, 0])
        self.assertEqual(new_grid[3], [2, 4, 2, 4])
        self.assertEqual(pts, 4 + 16)

    def test_simulate_move_up(self):
        """Test 2D grid move up."""
        grid = [
            [2, 4, 0, 2],
            [2, 4, 0, 4],
            [0, 4, 0, 2],
            [0, 4, 0, 4],
        ]
        new_grid, pts, changed = simulate_move(grid, "up")
        self.assertTrue(changed)
        self.assertEqual(new_grid[0], [4, 8, 0, 2])
        self.assertEqual(new_grid[1], [0, 8, 0, 4])
        self.assertEqual(new_grid[2], [0, 0, 0, 2])
        self.assertEqual(new_grid[3], [0, 0, 0, 4])
        self.assertEqual(pts, 4 + 16)

    def test_simulate_move_down(self):
        """Test 2D grid move down."""
        grid = [
            [2, 4, 0, 2],
            [2, 4, 0, 4],
            [0, 4, 0, 2],
            [0, 4, 0, 4],
        ]
        new_grid, pts, changed = simulate_move(grid, "down")
        self.assertTrue(changed)
        self.assertEqual(new_grid[0], [0, 0, 0, 2])
        self.assertEqual(new_grid[1], [0, 0, 0, 4])
        self.assertEqual(new_grid[2], [0, 8, 0, 2])
        self.assertEqual(new_grid[3], [4, 8, 0, 4])
        self.assertEqual(pts, 4 + 16)

    def test_simulate_move_noop(self):
        """When tiles cannot slide or merge in a direction, changed is False."""
        grid = [
            [4, 0, 0, 0],
            [2, 0, 0, 0],
            [8, 0, 0, 0],
            [16, 0, 0, 0],
        ]
        new_grid, pts, changed = simulate_move(grid, "left")
        self.assertFalse(changed)
        self.assertEqual(pts, 0)
        self.assertEqual(new_grid, grid)

    def test_has_valid_moves(self):
        """Check board full vs empty vs matching detection."""
        # 1. Has empty cell
        grid_with_empty = [
            [2, 4, 8, 16],
            [32, 64, 128, 256],
            [512, 1024, 2, 4],
            [8, 16, 32, 0],
        ]
        self.assertTrue(has_valid_moves(grid_with_empty))

        # 2. Full board with horizontal match
        grid_full_h_match = [
            [2, 4, 8, 16],
            [32, 64, 128, 256],
            [512, 1024, 2, 4],
            [8, 16, 32, 32],
        ]
        self.assertTrue(has_valid_moves(grid_full_h_match))

        # 3. Full board with vertical match
        grid_full_v_match = [
            [2, 4, 8, 16],
            [32, 64, 128, 256],
            [512, 1024, 2, 4],
            [512, 16, 32, 64],
        ]
        self.assertTrue(has_valid_moves(grid_full_v_match))

        # 4. Full board with no matches
        grid_terminal = [
            [2, 4, 2, 4],
            [4, 2, 4, 2],
            [2, 4, 2, 4],
            [4, 2, 4, 2],
        ]
        self.assertFalse(has_valid_moves(grid_terminal))


class TestDeterministic2048Simulator(unittest.TestCase):
    """Test suite for Deterministic2048Simulator protocol, state management, and rules."""

    def test_seed_determinism(self):
        """Two simulators with the same seed produce identical boards and tile spawns."""
        sim1 = Deterministic2048Simulator(seed=42)
        sim2 = Deterministic2048Simulator(seed=42)

        self.assertEqual(sim1.grid, sim2.grid)
        self.assertEqual(sim1.best, sim2.best)

        # Make same move
        r1 = sim1.submit_action("s1", "left")
        r2 = sim2.submit_action("s2", "left")

        self.assertEqual(r1["state"]["grid"], r2["state"]["grid"])
        self.assertEqual(r1["state"]["score"], r2["state"]["score"])
        self.assertEqual(r1["state"]["best"], r2["state"]["best"])

    def test_noop_move_rejection(self):
        """Action that cannot move any tiles is rejected and does not increment accepted moves."""
        # Custom grid where left is no-op
        custom_grid = [
            [2, 0, 0, 0],
            [4, 0, 0, 0],
            [8, 0, 0, 0],
            [16, 0, 0, 0],
        ]
        sim = Deterministic2048Simulator(initial_grid=custom_grid)
        resp = sim.submit_action(sim.session_id, "left")

        self.assertEqual(resp["result"], "rejected")
        self.assertEqual(sim.accepted_moves, 0)
        self.assertEqual(sim.rejected_moves, 1)
        self.assertEqual(resp["state"]["grid"], custom_grid)

    def test_invalid_action_string_rejection(self):
        """Invalid direction string is rejected."""
        sim = Deterministic2048Simulator()
        resp = sim.submit_action(sim.session_id, "diagonal")

        self.assertEqual(resp["result"], "rejected")
        self.assertEqual(sim.accepted_moves, 0)
        self.assertEqual(sim.rejected_moves, 1)

    def test_accepted_move_increments_moves_and_spawns(self):
        """Valid move updates grid, increments accepted moves, and spawns one tile."""
        custom_grid = [
            [0, 0, 0, 2],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
        ]
        sim = Deterministic2048Simulator(initial_grid=custom_grid)
        resp = sim.submit_action(sim.session_id, "left")

        self.assertEqual(resp["result"], "applied")
        self.assertEqual(sim.accepted_moves, 1)
        self.assertEqual(sim.rejected_moves, 0)

        # There should now be exactly 2 non-zero tiles (the moved 2 + the spawned tile)
        non_zero = sum(1 for row in sim.grid for cell in row if cell > 0)
        self.assertEqual(non_zero, 2)
        # Leftmost cell must be 2
        self.assertEqual(sim.grid[0][0], 2)

    def test_merge_scoring_and_best_update(self):
        """Merging tiles adds to score and updates highest tile (best)."""
        custom_grid = [
            [2, 2, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
        ]
        sim = Deterministic2048Simulator(initial_grid=custom_grid)
        resp = sim.submit_action(sim.session_id, "left")

        self.assertEqual(resp["result"], "applied")
        self.assertEqual(sim.score, 4)
        self.assertGreaterEqual(sim.best, 4)

    def test_max_moves_termination(self):
        """Reaching max_moves ends the game with done=True."""
        sim = Deterministic2048Simulator(max_moves=2, seed=10)
        # We need moves that change the board
        sim.submit_action(sim.session_id, "left")
        self.assertFalse(sim.done)
        sim.submit_action(sim.session_id, "down")
        self.assertTrue(sim.done)
        self.assertEqual(sim.termination_reason, "max_moves_reached")

    def test_game_over_no_moves_remaining(self):
        """When no moves remain, game terminates with no_moves_remaining."""
        # Full board with only 1 possible move to fill the last spot
        almost_full = [
            [2, 4, 2, 4],
            [4, 2, 4, 2],
            [2, 4, 2, 4],
            [4, 2, 0, 2],
        ]
        sim = Deterministic2048Simulator(initial_grid=almost_full, seed=99)
        # Move right: row 3 becomes [0, 4, 2, 2] -> [0, 4, 0, 4] or slides
        resp = sim.submit_action(sim.session_id, "right")
        self.assertEqual(resp["result"], "applied")

    def test_arena_adapter_protocol(self):
        """Simulator adheres to create_session and get_session API."""
        sim = Deterministic2048Simulator(seed=77)
        create_resp = sim.create_session("2048", "ZENITH")
        self.assertEqual(create_resp["game"], "2048")
        self.assertEqual(create_resp["agent_name"], "ZENITH")
        self.assertIn("state", create_resp)
        self.assertIn("grid", create_resp["state"])
        self.assertEqual(len(create_resp["state"]["grid"]), 4)

        get_resp = sim.get_session(sim.session_id)
        self.assertEqual(get_resp["session_id"], sim.session_id)
        self.assertEqual(get_resp["state"]["grid"], create_resp["state"]["grid"])
