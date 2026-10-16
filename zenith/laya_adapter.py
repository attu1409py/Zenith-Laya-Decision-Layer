"""Laya decision adapter for TopGameAI Arena competition.

This module provides the LayaAdapter class, connecting the verified local
Laya runtime (convaiinnovations/laya) to the ZENITH decision pipeline.

Responsibilities:
1. Parse Arena Snake game state dictionaries into structured state observations.
2. Build typed choice questions with precisely the options: up, down, left, right.
3. Call the installed Laya SDK through its documented predict interface.
4. Extract the selected choice and probability distribution without altering probabilities.
5. Strictly validate the returned structure against competition rules.
6. Set confidence = probabilities[chosen] for the competition record (distinguishing
   it from Laya's internal normalized-entropy confidence metric).
7. Preserve inference diagnostics and metadata separately from the required decision block.
8. Duck-type as a DecideFn callable for direct injection into SessionRunner.
"""

from __future__ import annotations

import math
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from zenith.decision_validator import (
    MAX_PROBABILITY_SUM,
    MIN_PROBABILITY_SUM,
    VALID_DIRECTIONS,
    DecisionValidationError,
    validate_decision,
)
from zenith.game2048_simulator import simulate_move

APPROVED_MODEL_ID: str = "convaiinnovations/laya"
QUESTION_KEY: str = "direction"
CRITERIA: Dict[str, str] = {
    "up": "Move up",
    "down": "Move down",
    "left": "Move left",
    "right": "Move right",
}
CRITERIA_2048: Dict[str, str] = {
    "up": "Slide tiles up",
    "down": "Slide tiles down",
    "left": "Slide tiles left",
    "right": "Slide tiles right",
}



class LayaInferenceError(RuntimeError):
    """Raised when Laya inference fails or returns invalid/malformed data."""
    pass


class LayaResponseContractError(LayaInferenceError, DecisionValidationError):
    """Raised when Laya output violates competition decision requirements."""
    pass


def _parse_coord(pt: Any) -> Optional[Tuple[int, int]]:
    """Parse coordinate from either a dict ({'x': 1, 'y': 2}) or a list/tuple ([1, 2])."""
    if isinstance(pt, dict) and "x" in pt and "y" in pt:
        try:
            return (int(pt["x"]), int(pt["y"]))
        except (ValueError, TypeError):
            return None
    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
        try:
            return (int(pt[0]), int(pt[1]))
        except (ValueError, TypeError):
            return None
    return None


def format_snake_state(
    state: Mapping[str, Any],
    prompt_version: str = "v1",
) -> Tuple[Dict[str, Any], str]:
    """Format an Arena Snake state mapping into a prompt state and question instruction.

    Args:
        state: Raw state dictionary returned by TopGameAI Arena API.
        prompt_version: Prompt strategy version ('v1' baseline or 'v2' revised).

    Returns:
        A tuple of (prompt_state_dict, question_instruction_text).
    """
    if not isinstance(state, (dict, Mapping)):
        state = {}

    grid = state.get("grid")
    width = state.get("width")
    height = state.get("height")

    # Determine width and height
    if width is None and isinstance(grid, list) and len(grid) > 0 and isinstance(grid[0], list):
        width = len(grid[0])
    if height is None and isinstance(grid, list):
        height = len(grid)
    width = int(width) if width is not None else 12
    height = int(height) if height is not None else 12

    # Parse snake body
    raw_snake = state.get("snake")
    snake_cells: List[Tuple[int, int]] = []
    if isinstance(raw_snake, list):
        for s in raw_snake:
            parsed = _parse_coord(s)
            if parsed is not None:
                snake_cells.append(parsed)

    # If snake not in state but grid available, scan grid (3=head, 1=body)
    if not snake_cells and isinstance(grid, list):
        head_from_grid = None
        body_from_grid = []
        for r_idx, row in enumerate(grid):
            if isinstance(row, list):
                for c_idx, cell in enumerate(row):
                    if cell == 3:
                        head_from_grid = (c_idx, r_idx)
                    elif cell == 1:
                        body_from_grid.append((c_idx, r_idx))
        if head_from_grid:
            snake_cells = [head_from_grid] + body_from_grid

    # Default head and body if missing
    if snake_cells:
        head = snake_cells[0]
        body = snake_cells[1:]
    else:
        head = (width // 2, height // 2)
        body = []

    # Parse food
    raw_food = state.get("food")
    food = _parse_coord(raw_food)
    if food is None and isinstance(grid, list):
        for r_idx, row in enumerate(grid):
            if isinstance(row, list):
                for c_idx, cell in enumerate(row):
                    if cell == 2:
                        food = (c_idx, r_idx)
                        break
                if food is not None:
                    break
    if food is None:
        food = (0, 0)

    # Direction and foodEaten
    direction = str(state.get("direction", "unknown")).strip().lower()
    food_eaten = int(state.get("foodEaten", 0)) if state.get("foodEaten") is not None else 0

    prompt_state = {
        "game": "snake",
        "board": {"width": width, "height": height},
        "snake_head": list(head),
        "snake_body": [list(c) for c in body],
        "current_direction": direction,
        "food": list(food),
        "food_eaten": food_eaten,
    }

    if prompt_version == "v2":
        hx, hy = head
        fx, fy = food
        offsets = {
            "up": (0, -1),
            "down": (0, 1),
            "left": (-1, 0),
            "right": (1, 0),
        }
        body_coords = set(body)
        neck = body[0] if body else None
        dist_cur = abs(hx - fx) + abs(hy - fy)

        lethal: List[str] = []
        closer: List[str] = []
        other_safe: List[str] = []

        for d in VALID_DIRECTIONS:
            dx, dy = offsets[d]
            nx, ny = hx + dx, hy + dy
            if nx < 0 or nx >= width or ny < 0 or ny >= height:
                lethal.append(d)
            elif neck and (nx, ny) == neck:
                lethal.append(d)
            elif (nx, ny) in body_coords:
                lethal.append(d)
            else:
                d_new = abs(nx - fx) + abs(ny - fy)
                if d_new < dist_cur:
                    closer.append(d)
                else:
                    other_safe.append(d)

        parts = [f"The snake head is at ({hx}, {hy}) on a {width}x{height} grid. Food is at ({fx}, {fy})."]
        if lethal:
            lethal_str = " or ".join(lethal)
            parts.append(f"Moving {lethal_str} causes fatal collision or illegal reversal.")
        if closer:
            closer_str = " or ".join(closer)
            parts.append(f"Moving {closer_str} safely advances toward the food.")
            parts.append("Which safe direction should the snake choose to advance toward the food?")
        else:
            safe_str = " or ".join(other_safe) if other_safe else "none"
            parts.append(f"Moving {safe_str} stays safely on the board.")
            parts.append("Which safe direction should the snake choose to avoid collision and stay alive?")
        question_text = " ".join(parts)

        prompt_state = {
            "game": "snake",
            "grid_size": f"{width}x{height}",
            "head": list(head),
            "food": list(food),
            "food_eaten": food_eaten,
            "safe_moves": closer + other_safe,
        }
    else:
        question_text = (
            f"In this Snake game on a {width}x{height} board (columns x: 0-{width - 1}, rows y: 0-{height - 1}), "
            f"the snake head is at {list(head)}, body length is {len(snake_cells) if snake_cells else 1}, "
            f"current direction is {direction}, and food is at {list(food)}. "
            "Which direction (up, down, left, right) should the snake move next to avoid collisions "
            "and advance toward the food?"
        )

    return prompt_state, question_text


def build_snake_criteria(
    state: Mapping[str, Any],
    prompt_version: str = "v1",
) -> Dict[str, str]:
    """Build the criteria dictionary for Laya choice options.

    For 'v1', returns the static default criteria.
    For 'v2', generates context-aware criteria detailing survival outcomes
    and relative food proximity for each candidate direction.
    """
    if prompt_version != "v2":
        return dict(CRITERIA)

    if not isinstance(state, (dict, Mapping)):
        state = {}

    width = int(state.get("width", 12)) if state.get("width") is not None else 12
    height = int(state.get("height", 12)) if state.get("height") is not None else 12

    raw_snake = state.get("snake")
    snake_cells: List[Tuple[int, int]] = []
    if isinstance(raw_snake, list):
        for s in raw_snake:
            parsed = _parse_coord(s)
            if parsed is not None:
                snake_cells.append(parsed)

    head = snake_cells[0] if snake_cells else (width // 2, height // 2)
    body = snake_cells[1:] if len(snake_cells) > 1 else []
    raw_food = state.get("food")
    food = _parse_coord(raw_food) or (0, 0)

    hx, hy = head
    fx, fy = food
    offsets = {
        "up": (0, -1),
        "down": (0, 1),
        "left": (-1, 0),
        "right": (1, 0),
    }
    body_coords = set(body)
    neck = body[0] if body else None
    dist_cur = abs(hx - fx) + abs(hy - fy)

    criteria: Dict[str, str] = {}
    for d in VALID_DIRECTIONS:
        dx, dy = offsets[d]
        nx, ny = hx + dx, hy + dy
        if nx < 0 or nx >= width or ny < 0 or ny >= height:
            criteria[d] = "Do not choose: deadly collision into wall"
        elif neck and (nx, ny) == neck:
            criteria[d] = "Do not choose: forbidden reversal into snake body"
        elif (nx, ny) in body_coords:
            criteria[d] = "Do not choose: deadly collision into snake body"
        else:
            d_new = abs(nx - fx) + abs(ny - fy)
            if d_new < dist_cur:
                criteria[d] = "Best move: advances toward the food, safe from collision"
            else:
                criteria[d] = "Safe move: safely avoids collision and stays on the board"

    return criteria


def _describe_2048_tile_position(
    grid: Sequence[Sequence[int]],
    target_val: int,
) -> Tuple[Optional[Tuple[int, int]], str, str]:
    """Locate the target tile on a 4x4 grid and describe its location.

    Returns:
        ((row, col), location_type, location_name)
        location_type is one of: 'corner', 'outer wall', 'inner center'
        location_name e.g.: 'bottom-left', 'top wall', 'inner center'
    """
    for r in range(4):
        for c in range(4):
            if grid[r][c] == target_val:
                is_corner = (r, c) in ((0, 0), (0, 3), (3, 0), (3, 3))
                is_edge = (r in (0, 3) or c in (0, 3)) and not is_corner
                loc_type = "corner" if is_corner else ("outer wall" if is_edge else "inner center")
                r_name = "top" if r == 0 else ("bottom" if r == 3 else f"row {r}")
                c_name = "left" if c == 0 else ("right" if c == 3 else f"col {c}")
                name = f"{r_name}-{c_name}" if (is_corner or is_edge) else "inner center"
                return (r, c), loc_type, name
    return None, "unknown", "unknown"


def format_2048_grid_ascii(grid: Sequence[Sequence[int]]) -> str:
    """Format a 4x4 2048 board into a clean, legible ASCII grid."""
    lines = ["+------+------+------+------+"]
    for row in grid:
        cells = []
        for val in row:
            v_int = int(val) if val is not None else 0
            cells.append(f"{v_int:>5} " if v_int > 0 else "      ")
        lines.append("|" + "|".join(cells) + "|")
        lines.append("+------+------+------+------+")
    return "\n".join(lines)


def format_2048_state(
    state: Mapping[str, Any],
    prompt_version: str = "v1",
) -> Tuple[Dict[str, Any], str]:
    """Format an Arena 2048 state mapping into a prompt state and question instruction.

    Args:
        state: Raw state dictionary returned by TopGameAI Arena API or simulator.
        prompt_version: Prompt strategy version ('v1', 'v2', or 'v3').

    Returns:
        A tuple of (prompt_state_dict, question_instruction_text).
    """
    if not isinstance(state, (dict, Mapping)):
        state = {}

    raw_grid = state.get("grid")
    grid: List[List[int]] = []
    if isinstance(raw_grid, list) and len(raw_grid) == 4:
        for row in raw_grid:
            if isinstance(row, list) and len(row) == 4:
                grid.append([int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0 for v in row])
            else:
                grid.append([0, 0, 0, 0])
    else:
        grid = [[0] * 4 for _ in range(4)]

    # Extract score and best
    raw_score = state.get("score")
    score = int(raw_score) if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool) else 0

    raw_best = state.get("best")
    if isinstance(raw_best, (int, float)) and not isinstance(raw_best, bool) and int(raw_best) > 0:
        best = int(raw_best)
    else:
        best = max((max(row) for row in grid), default=0)

    empty_count = sum(1 for row in grid for cell in row if cell == 0)
    grid_ascii = format_2048_grid_ascii(grid)

    if prompt_version == "v3":
        cur_pos, cur_type, cur_loc = _describe_2048_tile_position(grid, best)
        merging_dirs: List[str] = []
        slide_dirs: List[str] = []
        noop_dirs: List[str] = []

        for d in VALID_DIRECTIONS:
            new_g, pts, changed = simulate_move(grid, d)
            if not changed:
                noop_dirs.append(d)
            elif pts > 0:
                merging_dirs.append(d)
            else:
                slide_dirs.append(d)

        parts = [
            f"The current 2048 board (highest tile: {best} in {cur_loc} [{cur_type}], score: {score}, empty cells: {empty_count}) is:\n{grid_ascii}",
            f"Strategic priority: Keep your highest tile ({best}) anchored in a corner or outer wall, and merge matching numbers to free space.",
        ]
        if noop_dirs:
            noop_str = " or ".join(noop_dirs)
            parts.append(f"Moving {noop_str} is forbidden because no tiles can move or merge.")
        if merging_dirs:
            merge_str = " or ".join(merging_dirs)
            parts.append(f"Moving {merge_str} merges matching tiles to gain points and free space.")
        if slide_dirs:
            slide_str = " or ".join(slide_dirs)
            parts.append(f"Moving {slide_str} slides tiles safely without merging.")
        parts.append("Which valid direction (up, down, left, right) should you choose to preserve your anchor, merge numbers, and build toward tile 512?")
        question_text = "\n".join(parts)

        prompt_state = {
            "game": "2048",
            "grid": grid,
            "highest_tile": best,
            "score": score,
            "empty_cells": empty_count,
            "valid_moves": merging_dirs + slide_dirs,
        }
    elif prompt_version == "v2":
        merging_dirs = []
        slide_dirs = []
        noop_dirs = []

        for d in VALID_DIRECTIONS:
            new_g, pts, changed = simulate_move(grid, d)
            if not changed:
                noop_dirs.append(d)
            elif pts > 0:
                merging_dirs.append(d)
            else:
                slide_dirs.append(d)

        parts = [
            f"The current 2048 board (highest tile: {best}, score: {score}, empty cells: {empty_count}) is:\n{grid_ascii}"
        ]
        if noop_dirs:
            noop_str = " or ".join(noop_dirs)
            parts.append(f"Moving {noop_str} has no effect because no tiles can move or merge.")
        if merging_dirs:
            merge_str = " or ".join(merging_dirs)
            parts.append(f"Moving {merge_str} merges matching tiles to gain points and free space.")
        if slide_dirs:
            slide_str = " or ".join(slide_dirs)
            parts.append(f"Moving {slide_str} slides tiles safely without merging.")
        parts.append("Which direction should you slide the tiles next to merge numbers and build toward tile 512?")
        question_text = "\n".join(parts)

        prompt_state = {
            "game": "2048",
            "grid": grid,
            "highest_tile": best,
            "score": score,
            "empty_cells": empty_count,
            "valid_moves": merging_dirs + slide_dirs,
        }
    else:
        question_text = (
            f"In this 2048 game on a 4x4 grid (highest tile: {best}, score: {score}), "
            f"the current board is:\n{grid_ascii}\n"
            "Which direction (up, down, left, right) should you slide the tiles next "
            "to merge matching numbers and reach higher tiles?"
        )
        prompt_state = {
            "game": "2048",
            "grid": grid,
            "highest_tile": best,
            "score": score,
            "empty_cells": empty_count,
        }

    return prompt_state, question_text


def build_2048_criteria(
    state: Mapping[str, Any],
    prompt_version: str = "v1",
) -> Dict[str, str]:
    """Build the criteria dictionary for 2048 choice options.

    For 'v1', returns static directional slide criteria.
    For 'v2', generates context-aware criteria indicating merge points and
    no-op warnings for each direction.
    For 'v3', adds corner anchor tracking, space management, and verifiable
    strategic outcomes for each direction.
    """
    if prompt_version not in ("v2", "v3"):
        return dict(CRITERIA_2048)

    if not isinstance(state, (dict, Mapping)):
        state = {}

    raw_grid = state.get("grid")
    grid: List[List[int]] = []
    if isinstance(raw_grid, list) and len(raw_grid) == 4:
        for row in raw_grid:
            if isinstance(row, list) and len(row) == 4:
                grid.append([int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0 for v in row])
            else:
                grid.append([0, 0, 0, 0])
    else:
        grid = [[0] * 4 for _ in range(4)]

    raw_best = state.get("best")
    if isinstance(raw_best, (int, float)) and not isinstance(raw_best, bool) and int(raw_best) > 0:
        best = int(raw_best)
    else:
        best = max((max(row) for row in grid), default=0)

    if prompt_version == "v2":
        criteria: Dict[str, str] = {}
        for d in VALID_DIRECTIONS:
            new_g, pts, changed = simulate_move(grid, d)
            if not changed:
                criteria[d] = "Do not choose: no tiles can move or merge in this direction (invalid no-op move)"
            elif pts > 0:
                criteria[d] = f"Merges matching tiles for +{pts} points and frees space"
            else:
                criteria[d] = "Safe slide: shifts tiles without merging"
        return criteria

    # prompt_version == 'v3'
    cur_pos, cur_type, cur_loc = _describe_2048_tile_position(grid, best)
    criteria_v3: Dict[str, str] = {}
    for d in VALID_DIRECTIONS:
        new_g, pts, changed = simulate_move(grid, d)
        if not changed:
            criteria_v3[d] = "Do not choose: forbidden no-op move with zero movement"
            continue

        new_empty = sum(1 for row in new_g for cell in row if cell == 0)
        new_best = max((max(row) for row in new_g), default=best)
        new_pos, new_type, new_loc = _describe_2048_tile_position(new_g, new_best)

        anchor_clause = ""
        if new_best > best:
            anchor_clause = f" (creates NEW highest tile {new_best} in {new_loc})"
        elif cur_type == "corner":
            if new_type == "corner":
                anchor_clause = f" (preserves highest tile in {new_loc} corner)"
            else:
                anchor_clause = f" (caution: pulls highest tile away from corner)"
        elif cur_type == "outer wall":
            if new_type in ("corner", "outer wall"):
                anchor_clause = f" (keeps highest tile on {new_loc})"
            else:
                anchor_clause = f" (caution: pushes highest tile into inner center)"
        else:  # cur was inner center
            if new_type in ("corner", "outer wall"):
                anchor_clause = f" (moves highest tile outward to {new_loc})"

        if pts > 0:
            criteria_v3[d] = f"Best move: merges matching tiles for +{pts} points and frees space{anchor_clause}"
        else:
            criteria_v3[d] = f"Safe move: shifts tiles safely without merging{anchor_clause}"

    return criteria_v3



def build_laya_questions(
    question_text: str,
    criteria: Optional[Dict[str, str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Build the typed choice question dictionary required by Laya SDK."""
    return {
        QUESTION_KEY: {
            "type": "choice",
            "instructions": question_text,
            "criteria": dict(criteria) if criteria is not None else dict(CRITERIA),
        }
    }


def extract_and_validate_choice_response(
    raw_result: Any,
    question_key: str,
    question_text: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Extract and validate the Laya response against competition decision rules.

    Args:
        raw_result: The raw object returned by agent.predict().
        question_key: The question key expected in answers (default: 'direction').
        question_text: The exact question instruction supplied to Laya.

    Returns:
        A tuple of (competition_decision_dict, diagnostics_dict).

    Raises:
        LayaInferenceError: If raw response is not a dict or missing answers.
        LayaResponseContractError: If choice, probabilities, or confidence violate rules.
    """
    if not isinstance(raw_result, dict):
        raise LayaInferenceError(
            f"Laya predict returned non-dict object: {type(raw_result).__name__} ({raw_result!r})"
        )

    answers = raw_result.get("answers")
    if not isinstance(answers, dict):
        raise LayaInferenceError(
            f"Laya response missing 'answers' dictionary, got: {type(answers).__name__}"
        )

    if question_key not in answers:
        raise LayaInferenceError(
            f"Laya response missing question key '{question_key}'. Available keys: {list(answers.keys())}"
        )

    ans = answers[question_key]
    if not isinstance(ans, dict):
        raise LayaInferenceError(
            f"Answer for '{question_key}' is not a dictionary: {type(ans).__name__}"
        )

    # 1. Validate choice
    chosen = ans.get("choice")
    if not isinstance(chosen, str) or chosen not in VALID_DIRECTIONS:
        raise LayaResponseContractError(
            f"Laya selected invalid or missing choice {chosen!r}. "
            f"Expected one of: {list(VALID_DIRECTIONS)}"
        )

    # 2. Validate probabilities
    probs = ans.get("probabilities")
    if not isinstance(probs, dict):
        raise LayaResponseContractError(
            f"Laya answer missing 'probabilities' dictionary, got: {type(probs).__name__}"
        )

    expected_keys = set(VALID_DIRECTIONS)
    actual_keys = set(probs.keys())

    missing_keys = expected_keys - actual_keys
    if missing_keys:
        raise LayaResponseContractError(
            f"Laya probabilities missing required direction keys: {sorted(missing_keys)}"
        )

    extra_keys = actual_keys - expected_keys
    if extra_keys:
        raise LayaResponseContractError(
            f"Laya probabilities contain unexpected extra keys: {sorted(extra_keys)}"
        )

    prob_sum = 0.0
    sanitized_probs: Dict[str, float] = {}
    for d in VALID_DIRECTIONS:
        val = probs[d]
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise LayaResponseContractError(
                f"Probability for '{d}' is not numeric: {type(val).__name__} ({val!r})"
            )
        if not math.isfinite(val):
            raise LayaResponseContractError(
                f"Probability for '{d}' is non-finite: {val}"
            )
        float_val = float(val)
        if float_val < 0.0 or float_val > 1.0:
            raise LayaResponseContractError(
                f"Probability for '{d}' outside [0, 1]: {float_val}"
            )
        sanitized_probs[d] = float_val
        prob_sum += float_val

    if prob_sum < MIN_PROBABILITY_SUM or prob_sum > MAX_PROBABILITY_SUM:
        raise LayaResponseContractError(
            f"Probability sum {prob_sum:.6f} outside permitted range "
            f"[{MIN_PROBABILITY_SUM}, {MAX_PROBABILITY_SUM}]"
        )

    # 3. Determine competition confidence
    # The participant guide requires confidence == probabilities[chosen].
    # In Laya, ans['confidence'] is normalized entropy, while ans['answer_confidence']
    # is the calibrated max probability. We strictly bind confidence to probabilities[chosen].
    competition_confidence = sanitized_probs[chosen]

    # 4. Construct competition decision
    competition_decision = {
        "questions": [question_text],
        "probabilities": sanitized_probs,
        "chosen": chosen,
        "confidence": competition_confidence,
        "source": "laya",
    }

    # Verify through official validator
    validated = validate_decision(competition_decision, chosen)

    # 5. Extract diagnostic metadata
    diagnostics = {
        "raw_laya_confidence": ans.get("confidence"),
        "raw_answer_confidence": ans.get("answer_confidence"),
        "action_metadata": ans.get("action"),
        "token_usage": raw_result.get("usage"),
        "model_name": raw_result.get("model"),
    }

    return validated, diagnostics


class LayaAdapter:
    """Decision adapter connecting the local Laya model to the Zenith runner.

    Conforms to the DecideFn signature:
        (game: str, state: Mapping[str, Any]) -> Dict[str, Any]
    """

    def __init__(
        self,
        agent: Optional[Any] = None,
        model_id: str = APPROVED_MODEL_ID,
        device: Optional[str] = None,
        prompt_version: str = "v1",
    ) -> None:
        """Initialize LayaAdapter.

        Args:
            agent: Optional pre-loaded Laya agent or test double. If None,
                convaiinnovations/laya will be loaded via laya.load().
            model_id: Checkpoint identifier (must be convaiinnovations/laya).
            device: Optional runtime device override ('cuda', 'cpu', etc.).
            prompt_version: Prompt strategy version ('v1' or 'v2').
        """
        self.model_id = model_id
        self.device = device
        self.prompt_version = prompt_version
        self.last_metadata: Optional[Dict[str, Any]] = None

        if agent is not None:
            self.agent = agent
        else:
            if model_id != APPROVED_MODEL_ID:
                raise ValueError(
                    f"Unauthorized model '{model_id}'. Only '{APPROVED_MODEL_ID}' is permitted."
                )
            self.agent = self._load_agent(model_id, device)

    @staticmethod
    def _load_agent(model_id: str, device: Optional[str]) -> Any:
        """Load the official Laya agent using the installed laya package."""
        try:
            import laya
        except ImportError as exc:
            raise LayaInferenceError(
                "The 'laya' package is not installed. Run in the configured .venv."
            ) from exc

        return laya.load(model_id, device=device)

    def decide(self, game: str, state: Mapping[str, Any]) -> Dict[str, Any]:
        """Make a decision for a game state using Laya.

        Conforms strictly to the runner DecideFn signature:
            (game: str, state: Mapping[str, Any]) -> Dict[str, Any]

        Args:
            game: Game identifier ('snake').
            state: Raw game state mapping from the Arena.

        Returns:
            A competition decision dictionary with questions, probabilities,
            chosen, confidence, and source='laya'.

        Raises:
            ValueError: If game is not 'snake'.
            LayaInferenceError: If model inference or parsing fails.
        """
        game_clean = str(game).strip().lower() if isinstance(game, str) else ""
        if game_clean not in ("snake", "2048"):
            raise ValueError(
                f"LayaAdapter only supports 'snake' and '2048', got '{game}'."
            )

        # 1. Format state and question instructions
        if game_clean == "snake":
            prompt_state, question_text = format_snake_state(state, prompt_version=self.prompt_version)
            criteria = build_snake_criteria(state, prompt_version=self.prompt_version)
        else:
            prompt_state, question_text = format_2048_state(state, prompt_version=self.prompt_version)
            criteria = build_2048_criteria(state, prompt_version=self.prompt_version)

        questions = build_laya_questions(question_text, criteria=criteria)

        # 2. Execute genuine inference
        t0 = time.perf_counter()
        try:
            raw_result = self.agent.predict(prompt_state, questions)
        except Exception as exc:
            raise LayaInferenceError(
                f"Laya predict() failed during inference: {exc}"
            ) from exc
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        # 3. Extract, validate, and construct competition decision
        decision, diagnostics = extract_and_validate_choice_response(
            raw_result, QUESTION_KEY, question_text
        )

        # 4. Store diagnostic metadata for caller inspection
        self.last_metadata = {
            "game": game,
            "model_id": self.model_id,
            "device": self.device,
            "inference_ms": elapsed_ms,
            "question_text": question_text,
            "prompt_state": prompt_state,
            **diagnostics,
        }

        return decision

    def get_last_metadata(self) -> Optional[Dict[str, Any]]:
        """Return the diagnostic metadata from the most recent decision."""
        if self.last_metadata is None:
            return None
        return dict(self.last_metadata)
