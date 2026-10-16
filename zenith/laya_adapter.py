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

APPROVED_MODEL_ID: str = "convaiinnovations/laya"
QUESTION_KEY: str = "direction"
CRITERIA: Dict[str, str] = {
    "up": "Move up",
    "down": "Move down",
    "left": "Move left",
    "right": "Move right",
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
        if not isinstance(game, str) or game.lower() != "snake":
            raise ValueError(
                f"LayaAdapter currently only supports 'snake', got '{game}'."
            )

        # 1. Format state and question instructions
        prompt_state, question_text = format_snake_state(state, prompt_version=self.prompt_version)
        criteria = build_snake_criteria(state, prompt_version=self.prompt_version)
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
