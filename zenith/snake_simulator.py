"""Deterministic local Snake simulator for testing and benchmarking.

This module provides a reproducible, zero-network Snake environment adhering
strictly to the official TopGameAI Arena rules documented in Track2_PS2_support.pdf:
- 12x12 board by default.
- Win by eating 15 foods.
- 180-degree immediate reversal into neck is rejected (does not count as accepted move).
- Wall or self collision ends the game.
- Move cap of 300 accepted moves.
- Score formula: foods_eaten * 60 + (100 if won else 0), capped at 1000.
- Deterministic pseudo-random food generation seeded via Python's standard random module.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Mapping, Optional, Tuple

TEAM_NAME = "ZENITH"
VALID_DIRECTIONS = ("up", "down", "left", "right")
OPPOSITE_DIRECTIONS = {
    "up": "down",
    "down": "up",
    "left": "right",
    "right": "left",
}
DIRECTION_OFFSETS = {
    "up": (0, -1),
    "down": (0, 1),
    "left": (-1, 0),
    "right": (1, 0),
}


class DeterministicSnakeSimulator:
    """Deterministic local Arena-compatible Snake simulator."""

    def __init__(
        self,
        seed: int = 42,
        width: int = 12,
        height: int = 12,
        max_moves: int = 300,
        target_food: int = 15,
        session_id_prefix: str = "sim-snake",
        initial_snake: Optional[List[Dict[str, int]]] = None,
        initial_direction: str = "up",
    ) -> None:
        self._seed = seed
        self._width = width
        self._height = height
        self._max_moves = max_moves
        self._target_food = target_food
        self._session_id = f"{session_id_prefix}-{seed}"
        self._agent_name = TEAM_NAME

        self._initial_snake = (
            [dict(c) for c in initial_snake]
            if initial_snake is not None
            else [
                {"x": 6, "y": 6},
                {"x": 6, "y": 7},
                {"x": 6, "y": 8},
            ]
        )
        self._initial_direction = initial_direction

        # Internal state
        self._rng = random.Random(seed)
        self._snake: List[Dict[str, int]] = []
        self._direction: str = initial_direction
        self._food: Dict[str, int] = {"x": 0, "y": 0}
        self._food_eaten: int = 0
        self._accepted_moves: int = 0
        self._rejected_moves: int = 0
        self._done: bool = False
        self._won: Optional[bool] = None
        self._score: int = 0
        self._termination_reason: Optional[str] = None
        self._food_history: List[Dict[str, int]] = []

        self._reset()

    def _reset(self) -> None:
        """Reset the simulator to initial state using the configured seed."""
        self._rng = random.Random(self._seed)
        self._snake = [dict(c) for c in self._initial_snake]
        self._direction = self._initial_direction
        self._food_eaten = 0
        self._accepted_moves = 0
        self._rejected_moves = 0
        self._done = False
        self._won = None
        self._score = 0
        self._termination_reason = None
        self._food_history = []

        self._spawn_food()

    def _spawn_food(self) -> None:
        """Spawn a new food item at an unoccupied cell."""
        occupied = {(seg["x"], seg["y"]) for seg in self._snake}
        available: List[Tuple[int, int]] = [
            (x, y)
            for y in range(self._height)
            for x in range(self._width)
            if (x, y) not in occupied
        ]
        if not available:
            # Entire board filled
            self._done = True
            self._won = True
            self._termination_reason = "board_full"
            self._calculate_score()
            return

        fx, fy = self._rng.choice(available)
        self._food = {"x": fx, "y": fy}
        self._food_history.append(dict(self._food))

    def _calculate_score(self) -> None:
        """Calculate score according to official rules: foods * 60 + 100 if won."""
        base = self._food_eaten * 60
        bonus = 100 if (self._won is True) else 0
        self._score = min(1000, base + bonus)

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def seed(self) -> int:
        return self._seed

    @property
    def food_eaten(self) -> int:
        return self._food_eaten

    @property
    def accepted_moves(self) -> int:
        return self._accepted_moves

    @property
    def rejected_moves(self) -> int:
        return self._rejected_moves

    @property
    def score(self) -> int:
        return self._score

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
        """Build standard Arena API response dictionary."""
        return {
            "session_id": self._session_id,
            "game": "snake",
            "agent_name": self._agent_name,
            "state": {
                "width": self._width,
                "height": self._height,
                "snake": [dict(c) for c in self._snake],
                "food": dict(self._food),
                "direction": self._direction,
                "foodEaten": self._food_eaten,
            },
            "done": self._done,
            "score": self._score,
            "won": self._won,
            "result": result,
        }

    # ── ArenaAdapter Protocol ──────────────────────────────────────────

    def create_session(self, game: str, agent_name: str) -> Dict[str, Any]:
        """Create a session (conforms to ArenaAdapter protocol)."""
        self._agent_name = agent_name or TEAM_NAME
        self._reset()
        return self._build_response(result="applied")

    def get_session(self, session_id: str) -> Dict[str, Any]:
        """Retrieve current session state (conforms to ArenaAdapter protocol)."""
        return self._build_response(result="applied")

    def submit_action(self, session_id: str, action: str) -> Dict[str, Any]:
        """Submit a move action and update state.

        Rules:
        - If already done, returns current state with result 'applied'.
        - If action not in ('up', 'down', 'left', 'right'), rejected.
        - If action is 180-degree reversal of current direction (when snake > 1), rejected.
        - Moving into wall or body ends game (done=True, won=False).
        - Eating food increments foodEaten, snake grows, score updates, new food placed.
        - Winning when foodEaten >= target_food (15).
        - Max accepted moves limit (300).
        """
        if self._done:
            return self._build_response(result="applied")

        action_clean = str(action).strip().lower()

        # Check valid direction
        if action_clean not in VALID_DIRECTIONS:
            self._rejected_moves += 1
            return self._build_response(result="rejected")

        # Check 180-degree immediate reversal into neck
        if len(self._snake) > 1 and action_clean == OPPOSITE_DIRECTIONS.get(self._direction):
            self._rejected_moves += 1
            return self._build_response(result="rejected")

        # Move accepted
        self._accepted_moves += 1
        self._direction = action_clean

        head = self._snake[0]
        dx, dy = DIRECTION_OFFSETS[action_clean]
        new_head = {"x": head["x"] + dx, "y": head["y"] + dy}

        # Check wall collision
        if (
            new_head["x"] < 0
            or new_head["x"] >= self._width
            or new_head["y"] < 0
            or new_head["y"] >= self._height
        ):
            self._done = True
            self._won = False
            self._termination_reason = "wall_collision"
            self._calculate_score()
            return self._build_response(result="applied")

        # Check food eating
        eats_food = (new_head["x"] == self._food["x"] and new_head["y"] == self._food["y"])

        # Check body collision:
        # If food eaten, tail does not pop; if food not eaten, tail pops.
        body_to_check = self._snake if eats_food else self._snake[:-1]
        for seg in body_to_check:
            if seg["x"] == new_head["x"] and seg["y"] == new_head["y"]:
                self._done = True
                self._won = False
                self._termination_reason = "self_collision"
                self._calculate_score()
                return self._build_response(result="applied")

        # Advance snake
        self._snake.insert(0, new_head)
        if eats_food:
            self._food_eaten += 1
            if self._food_eaten >= self._target_food:
                self._done = True
                self._won = True
                self._termination_reason = "target_food_reached"
                self._calculate_score()
                return self._build_response(result="applied")
            else:
                self._calculate_score()
                self._spawn_food()
        else:
            self._snake.pop()
            self._calculate_score()

        # Check move limit
        if self._accepted_moves >= self._max_moves and not self._done:
            self._done = True
            self._won = self._food_eaten >= self._target_food
            self._termination_reason = "max_moves_reached"
            self._calculate_score()

        return self._build_response(result="applied")
