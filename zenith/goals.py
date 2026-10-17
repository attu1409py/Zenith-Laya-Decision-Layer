"""Per-stage goal configuration and evaluation for Team ZENITH Decision Layer.

Provides a unified, easily extensible goal configuration system:
- Snake: GOAL = eat 15 food
- 2048: GOAL = reach the 2048 tile
- Extensible to any future stage by registering in STAGE_GOALS.
- Fallback: "No goal defined" when a stage has no registered goal.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Optional, Tuple


def _snake_metric(state: Mapping[str, Any]) -> Tuple[int, str]:
    """Calculate food eaten for Snake state."""
    food_eaten = state.get("foodEaten")
    if food_eaten is None:
        snake = state.get("snake")
        if isinstance(snake, list) and len(snake) >= 3:
            food_eaten = len(snake) - 3
        else:
            score = state.get("score", 0)
            food_eaten = int(score) // 100 if isinstance(score, (int, float)) else 0
    val = max(0, int(food_eaten or 0))
    return val, f"{val} / 15 food"


def _snake_check(state: Mapping[str, Any]) -> bool:
    """Check if Snake goal is reached (>= 15 food)."""
    val, _ = _snake_metric(state)
    return val >= 15


def _2048_metric(state: Mapping[str, Any]) -> Tuple[int, str]:
    """Calculate highest tile for 2048 state."""
    grid = state.get("grid")
    max_tile = 0
    if isinstance(grid, list):
        for row in grid:
            if isinstance(row, list):
                for val in row:
                    if isinstance(val, (int, float)) and val > max_tile:
                        max_tile = int(val)
    return max_tile, f"{max_tile} / 2048 tile"


def _2048_check(state: Mapping[str, Any]) -> bool:
    """Check if 2048 goal is reached (>= 2048 tile)."""
    max_tile, _ = _2048_metric(state)
    return max_tile >= 2048


# Extensible goal registry
STAGE_GOALS: Dict[str, Dict[str, Any]] = {
    "snake": {
        "label": "FOOD",
        "target": 15,
        "unit": "food",
        "metric_fn": _snake_metric,
        "check_fn": _snake_check,
    },
    "2048": {
        "label": "TILE",
        "target": 2048,
        "unit": "tile",
        "metric_fn": _2048_metric,
        "check_fn": _2048_check,
    },
}


def register_stage_goal(
    stage_name: str,
    label: str,
    target: int,
    unit: str,
    metric_fn: Callable[[Mapping[str, Any]], Tuple[int, str]],
    check_fn: Callable[[Mapping[str, Any]], bool],
) -> None:
    """Register or override a goal configuration for a game stage."""
    STAGE_GOALS[str(stage_name).strip().lower()] = {
        "label": label,
        "target": target,
        "unit": unit,
        "metric_fn": metric_fn,
        "check_fn": check_fn,
    }


def get_stage_goal(game: str) -> Optional[Dict[str, Any]]:
    """Retrieve goal configuration for given game name."""
    if not game:
        return None
    return STAGE_GOALS.get(str(game).strip().lower())


def evaluate_stage_goal(game: str, state: Mapping[str, Any]) -> Dict[str, Any]:
    """Evaluate current state against the stage goal.

    Returns:
        dict with keys:
            - has_goal (bool)
            - label (str, e.g. 'FOOD', 'TILE', 'NO GOAL')
            - unit (str, e.g. 'food', 'tile')
            - current_value (int)
            - target_value (int)
            - progress_text (str, e.g. '7 / 15 food' or 'No goal defined')
            - pct (float 0.0 to 100.0)
            - reached (bool)
    """
    config = get_stage_goal(game)
    if not config:
        return {
            "has_goal": False,
            "label": "NO GOAL",
            "unit": "",
            "current_value": 0,
            "target_value": 0,
            "progress_text": "No goal defined",
            "pct": 0.0,
            "reached": False,
        }

    current_val, text = config["metric_fn"](state)
    target = config["target"]
    reached = config["check_fn"](state)
    pct = min(100.0, max(0.0, (current_val / target * 100.0) if target > 0 else 0.0))

    return {
        "has_goal": True,
        "label": config["label"],
        "unit": config.get("unit", ""),
        "current_value": current_val,
        "target_value": target,
        "progress_text": text,
        "pct": round(pct, 1),
        "reached": bool(reached),
    }
