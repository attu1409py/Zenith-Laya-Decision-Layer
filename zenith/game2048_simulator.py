"""Deterministic local 2048 simulator for testing and benchmarking.

This module provides a reproducible, zero-network 2048 environment adhering
strictly to the official TopGameAI Arena rules:
- 4x4 board grid.
- Initial board starts with 2 randomly spawned tiles.
- Tile values are powers of 2 (0 represents an empty cell).
- Permitted actions: "up", "down", "left", "right".
- Tiles slide as far as possible in the chosen direction.
- Two adjacent identical tiles merge into one tile of their sum.
- Single-merge-per-move: each tile merges at most once per turn
  (e.g., [2, 2, 2, 2] moving left becomes [4, 4, 0, 0], not [8, 0, 0, 0]).
- Each merge adds the merged tile value to in-game score.
- If a move produces no change on the board, it is rejected (result: "rejected"),
  does not spawn a new tile, and does not increment accepted moves.
- On each accepted move, exactly one new tile spawns at a uniformly random
  empty cell (90% chance of 2, 10% chance of 4).
- Game ends when no valid moves exist (board is full and no adjacent tiles match)
  or maximum accepted moves is reached.
- Win condition: achieving tile 2048 or higher.
- Qualification criterion: reaching tile 512 or higher.
- Seeded pseudo-random generator via Python's standard random module for determinism.
"""

from __future__ import annotations

import copy
import math
import random
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

TEAM_NAME = "ZENITH"
VALID_DIRECTIONS = ("up", "down", "left", "right")


def slide_and_merge_line(line: Sequence[int]) -> Tuple[List[int], int]:
    """Slide and merge a single 1D row or column to the left.

    Semantics:
    1. Filter out zeros (empty cells).
    2. Merge identical adjacent pairs from left to right.
       Each tile participates in at most one merge per turn.
    3. Add the value of each newly created merged tile to points gained.
    4. Pad the resulting line with zeros on the right to match original length.

    Args:
        line: Sequence of integers representing tile values.

    Returns:
        A tuple of (new_line, points_gained).
    """
    length = len(line)
    non_zeros = [int(v) for v in line if int(v) > 0]
    merged: List[int] = []
    points = 0
    skip = False

    for i in range(len(non_zeros)):
        if skip:
            skip = False
            continue
        if i + 1 < len(non_zeros) and non_zeros[i] == non_zeros[i + 1]:
            val = non_zeros[i] * 2
            merged.append(val)
            points += val
            skip = True
        else:
            merged.append(non_zeros[i])

    # Pad remaining space with zeros
    merged.extend([0] * (length - len(merged)))
    return merged, points


def simulate_move(
    grid: Sequence[Sequence[int]],
    action: str,
) -> Tuple[List[List[int]], int, bool]:
    """Simulate a directional slide and merge on a 2D grid.

    Args:
        grid: 4x4 matrix of integers.
        action: One of 'up', 'down', 'left', 'right'.

    Returns:
        A tuple of (new_grid, points_gained, changed_flag).
    """
    action_clean = str(action).strip().lower()
    if action_clean not in VALID_DIRECTIONS:
        return [list(r) for r in grid], 0, False

    height = len(grid)
    width = len(grid[0]) if height > 0 else 0
    new_grid: List[List[int]] = [[0] * width for _ in range(height)]
    total_points = 0

    if action_clean == "left":
        for r in range(height):
            merged_row, pts = slide_and_merge_line(grid[r])
            new_grid[r] = merged_row
            total_points += pts

    elif action_clean == "right":
        for r in range(height):
            reversed_row = list(reversed(grid[r]))
            merged_row, pts = slide_and_merge_line(reversed_row)
            new_grid[r] = list(reversed(merged_row))
            total_points += pts

    elif action_clean == "up":
        for c in range(width):
            col = [grid[r][c] for r in range(height)]
            merged_col, pts = slide_and_merge_line(col)
            for r in range(height):
                new_grid[r][c] = merged_col[r]
            total_points += pts

    elif action_clean == "down":
        for c in range(width):
            col = [grid[r][c] for r in range(height)]
            reversed_col = list(reversed(col))
            merged_col, pts = slide_and_merge_line(reversed_col)
            unreversed_col = list(reversed(merged_col))
            for r in range(height):
                new_grid[r][c] = unreversed_col[r]
            total_points += pts

    changed = False
    for r in range(height):
        for c in range(width):
            if new_grid[r][c] != grid[r][c]:
                changed = True
                break
        if changed:
            break

    return new_grid, total_points, changed


def has_valid_moves(grid: Sequence[Sequence[int]]) -> bool:
    """Check if any legal move can change the current board."""
    height = len(grid)
    width = len(grid[0]) if height > 0 else 0

    # 1. Any empty cell means at least one direction can slide or spawn
    for r in range(height):
        for c in range(width):
            if grid[r][c] == 0:
                return True

    # 2. Check for adjacent horizontal matches
    for r in range(height):
        for c in range(width - 1):
            if grid[r][c] == grid[r][c + 1]:
                return True

    # 3. Check for adjacent vertical matches
    for r in range(height - 1):
        for c in range(width):
            if grid[r][c] == grid[r + 1][c]:
                return True

    return False


class Deterministic2048Simulator:
    """Deterministic local Arena-compatible 2048 simulator.

    Conforms to the ArenaAdapter protocol:
        create_session(game: str, agent_name: str) -> Dict[str, Any]
        get_session(session_id: str) -> Dict[str, Any]
        submit_action(session_id: str, action: str) -> Dict[str, Any]
    """

    def __init__(
        self,
        seed: int = 42,
        width: int = 4,
        height: int = 4,
        max_moves: int = 2000,
        session_id_prefix: str = "sim-2048",
        initial_grid: Optional[Sequence[Sequence[int]]] = None,
    ) -> None:
        """Initialize the 2048 simulator.

        Args:
            seed: Deterministic random seed for tile spawns.
            width: Board width (default: 4).
            height: Board height (default: 4).
            max_moves: Maximum accepted moves cap (default: 2000).
            session_id_prefix: Prefix for generated session ID.
            initial_grid: Optional predetermined starting board (for testing).
        """
        self._seed = seed
        self._width = width
        self._height = height
        self._max_moves = max_moves
        self._session_id = f"{session_id_prefix}-{seed}"
        self._agent_name = TEAM_NAME
        self._custom_initial_grid = (
            [list(row) for row in initial_grid] if initial_grid is not None else None
        )

        # Internal state
        self._rng = random.Random(seed)
        self._grid: List[List[int]] = [[0] * width for _ in range(height)]
        self._score: int = 0
        self._best: int = 0
        self._accepted_moves: int = 0
        self._rejected_moves: int = 0
        self._done: bool = False
        self._won: Optional[bool] = None
        self._termination_reason: Optional[str] = None

        self._reset()

    def _reset(self) -> None:
        """Reset the simulator to initial state using configured seed."""
        self._rng = random.Random(self._seed)
        self._score = 0
        self._accepted_moves = 0
        self._rejected_moves = 0
        self._done = False
        self._won = None
        self._termination_reason = None

        if self._custom_initial_grid is not None:
            self._grid = [list(r) for r in self._custom_initial_grid]
        else:
            self._grid = [[0] * self._width for _ in range(self._height)]
            # Spawn 2 initial tiles
            self._spawn_tile()
            self._spawn_tile()

        self._update_best()

    def _spawn_tile(self) -> bool:
        """Spawn a tile in a randomly chosen empty cell.

        Tile is 2 with 90% probability, 4 with 10% probability.

        Returns:
            True if a tile was spawned, False if board is full.
        """
        empty_cells: List[Tuple[int, int]] = [
            (r, c)
            for r in range(self._height)
            for c in range(self._width)
            if self._grid[r][c] == 0
        ]
        if not empty_cells:
            return False

        r, c = self._rng.choice(empty_cells)
        # 90% chance of 2, 10% chance of 4
        val = 2 if self._rng.random() < 0.9 else 4
        self._grid[r][c] = val
        return True

    def _update_best(self) -> None:
        """Update highest tile value on board."""
        max_val = 0
        for r in range(self._height):
            for c in range(self._width):
                if self._grid[r][c] > max_val:
                    max_val = self._grid[r][c]
        self._best = max_val
        if self._best >= 2048 and self._won is None:
            self._won = True

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def seed(self) -> int:
        return self._seed

    @property
    def grid(self) -> List[List[int]]:
        return [list(r) for r in self._grid]

    @property
    def score(self) -> int:
        """In-game merge score."""
        return self._score

    @property
    def tournament_score(self) -> int:
        """Arena tournament score formula:
        min(1000, floor(log2(best) - 6) * 143 + score/1000) for best >= 128.
        """
        if self._best < 128:
            return min(1000, self._score)
        factor = int(math.floor(math.log2(self._best) - 6))
        calc = int(factor * 143 + (self._score / 1000.0))
        return min(1000, max(0, calc))

    @property
    def best(self) -> int:
        """Highest tile value reached."""
        return self._best

    @property
    def accepted_moves(self) -> int:
        return self._accepted_moves

    @property
    def rejected_moves(self) -> int:
        return self._rejected_moves

    @property
    def done(self) -> bool:
        return self._done

    @property
    def won(self) -> Optional[bool]:
        return self._won

    @property
    def termination_reason(self) -> Optional[str]:
        return self._termination_reason

    def _build_response(self, result: str = "applied") -> Dict[str, Any]:
        """Build standard Arena API response dictionary for 2048."""
        resp = {
            "session_id": self._session_id,
            "game": "2048",
            "agent_name": self._agent_name,
            "state": {
                "grid": [list(r) for r in self._grid],
                "score": self._score,
                "best": self._best,
            },
            "done": self._done,
            "score": self._score,
            "won": self._won,
            "steps": self._accepted_moves,
            "result": result,
        }
        if self._termination_reason:
            resp["termination_reason"] = self._termination_reason
        return resp

    # ── ArenaAdapter Protocol ──────────────────────────────────────────

    def create_session(self, game: str, agent_name: str) -> Dict[str, Any]:
        """Create a new session conforming to the ArenaAdapter protocol."""
        self._agent_name = agent_name or TEAM_NAME
        self._reset()
        return self._build_response(result="applied")

    def get_session(self, session_id: str) -> Dict[str, Any]:
        """Retrieve current session state conforming to ArenaAdapter protocol."""
        return self._build_response(result="applied")

    def submit_action(self, session_id: str, action: str) -> Dict[str, Any]:
        """Submit a move action and update state.

        Rules:
        - If already done, returns current state with result 'applied'.
        - If action not in ('up', 'down', 'left', 'right'), rejected.
        - If move produces no board change, rejected (result: 'rejected'),
          does not spawn tile, does not increment accepted moves.
        - If move changes board:
          - Increment accepted_moves.
          - Add merge points to score.
          - Update best tile.
          - Check win condition (best >= 2048).
          - Spawn one new tile (90% 2, 10% 4).
          - Check terminal condition (no valid moves remain).
          - Check max moves limit.
        """
        if self._done:
            return self._build_response(result="applied")

        action_clean = str(action).strip().lower()

        # Check valid direction
        if action_clean not in VALID_DIRECTIONS:
            self._rejected_moves += 1
            return self._build_response(result="rejected")

        # Simulate move
        new_grid, points_gained, changed = simulate_move(self._grid, action_clean)

        if not changed:
            # No-op action: move is rejected
            self._rejected_moves += 1
            return self._build_response(result="rejected")

        # Accepted move
        self._accepted_moves += 1
        self._grid = new_grid
        self._score += points_gained
        self._update_best()

        # Spawn new tile
        self._spawn_tile()
        self._update_best()

        # Check terminal condition: no valid moves left
        if not has_valid_moves(self._grid):
            self._done = True
            if self._won is None:
                self._won = self._best >= 2048
            self._termination_reason = "no_moves_remaining"

        # Check move limit
        elif self._accepted_moves >= self._max_moves:
            self._done = True
            if self._won is None:
                self._won = True if self._best >= 2048 else None
            self._termination_reason = "max_moves_reached"

        return self._build_response(result="applied")
