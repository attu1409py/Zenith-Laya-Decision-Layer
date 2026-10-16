"""Validation for TopGameAI Arena competition decisions.

This module validates that a decision dictionary conforms strictly to Section 3.2
and 4.3 of the Track 2 PS02 participant guide (Track2_PS2_support.pdf) and CONTEXT.md.

Rules:
1. 'questions': Array containing the exact text question(s) asked to Laya.
2. 'probabilities': Exactly the four keys 'up', 'down', 'left', 'right'.
   Values must be numbers in [0, 1] and sum to between 0.98 and 1.02 inclusive.
   Booleans are strictly forbidden as numbers.
3. 'chosen': Must be a valid direction and must equal the submitted action.
4. 'confidence': Must equal probabilities[chosen].
5. 'source': Must be 'laya' or 'fallback'.
6. Fallback limit: At most 10% of moves in a session may have source 'fallback'.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

VALID_DIRECTIONS: Tuple[str, ...] = ("up", "down", "left", "right")
PERMITTED_SOURCES: Tuple[str, ...] = ("laya", "fallback")
MIN_PROBABILITY_SUM: float = 0.98
MAX_PROBABILITY_SUM: float = 1.02
MAX_FALLBACK_RATIO: float = 0.10


class DecisionValidationError(ValueError):
    """Raised when a decision dictionary fails competition validation."""
    pass


def validate_decision(
    decision: Mapping[str, Any],
    action: str,
) -> Dict[str, Any]:
    """Validate a decision block against the submitted action and competition rules.

    Args:
        decision: The decision dictionary returned or prepared for logging.
        action: The move action submitted to the game Arena ('up', 'down', 'left', 'right').

    Returns:
        A validated copy of the decision dictionary.

    Raises:
        DecisionValidationError: If any rule is violated.
    """
    if not isinstance(decision, dict):
        raise DecisionValidationError(
            f"Decision must be a JSON dictionary object, got {type(decision).__name__}."
        )

    # 1. Validate 'questions'
    if "questions" not in decision:
        raise DecisionValidationError("Decision is missing required 'questions' field.")
    questions = decision["questions"]
    if not isinstance(questions, list) or len(questions) == 0:
        raise DecisionValidationError(
            "'questions' must be a non-empty list of question strings."
        )
    for idx, q in enumerate(questions):
        if not isinstance(q, str) or not q.strip():
            raise DecisionValidationError(
                f"'questions[{idx}]' must be a non-empty string."
            )

    # 2. Validate 'probabilities'
    if "probabilities" not in decision:
        raise DecisionValidationError("Decision is missing required 'probabilities' field.")
    probabilities = decision["probabilities"]
    if not isinstance(probabilities, dict):
        raise DecisionValidationError(
            f"'probabilities' must be a dictionary, got {type(probabilities).__name__}."
        )

    expected_keys = set(VALID_DIRECTIONS)
    actual_keys = set(probabilities.keys())

    missing_keys = expected_keys - actual_keys
    if missing_keys:
        raise DecisionValidationError(
            f"'probabilities' is missing required keys: {sorted(missing_keys)}."
        )

    extra_keys = actual_keys - expected_keys
    if extra_keys:
        raise DecisionValidationError(
            f"'probabilities' contains illegal extra keys: {sorted(extra_keys)}. "
            f"Allowed keys are exactly: {list(VALID_DIRECTIONS)}."
        )

    prob_sum = 0.0
    for direction in VALID_DIRECTIONS:
        val = probabilities[direction]
        # In Python, isinstance(True, int) is True, so reject bool explicitly
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise DecisionValidationError(
                f"Probability for '{direction}' must be a numeric float, got {type(val).__name__} ({val!r})."
            )
        if not math.isfinite(val):
            raise DecisionValidationError(
                f"Probability for '{direction}' must be a finite number, got {val}."
            )
        if val < 0.0 or val > 1.0:
            raise DecisionValidationError(
                f"Probability for '{direction}' must be between 0 and 1 inclusive, got {val}."
            )
        prob_sum += float(val)

    if prob_sum < MIN_PROBABILITY_SUM or prob_sum > MAX_PROBABILITY_SUM:
        raise DecisionValidationError(
            f"Probability sum must be between {MIN_PROBABILITY_SUM} and {MAX_PROBABILITY_SUM} inclusive, "
            f"got {prob_sum:.6f}."
        )

    # 3. Validate 'chosen'
    if "chosen" not in decision:
        raise DecisionValidationError("Decision is missing required 'chosen' field.")
    chosen = decision["chosen"]
    if chosen not in VALID_DIRECTIONS:
        raise DecisionValidationError(
            f"'chosen' must be one of {VALID_DIRECTIONS}, got {chosen!r}."
        )

    # 4. Cross-check 'chosen' with submitted 'action'
    if not isinstance(action, str) or not action.strip():
        raise DecisionValidationError("Submitted 'action' must be a non-empty string.")
    if chosen != action:
        raise DecisionValidationError(
            f"'chosen' action '{chosen}' does not match submitted action '{action}'."
        )

    # 5. Validate 'confidence'
    if "confidence" not in decision:
        raise DecisionValidationError("Decision is missing required 'confidence' field.")
    confidence = decision["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise DecisionValidationError(
            f"'confidence' must be a numeric float, got {type(confidence).__name__} ({confidence!r})."
        )
    if not math.isfinite(confidence):
        raise DecisionValidationError(
            f"'confidence' must be a finite number, got {confidence}."
        )

    expected_confidence = probabilities[chosen]
    if not math.isclose(float(confidence), float(expected_confidence), rel_tol=1e-7, abs_tol=1e-7):
        raise DecisionValidationError(
            f"'confidence' ({confidence}) does not equal probabilities['{chosen}'] ({expected_confidence})."
        )

    # 6. Validate 'source'
    if "source" not in decision:
        raise DecisionValidationError("Decision is missing required 'source' field.")
    source = decision["source"]
    if source not in PERMITTED_SOURCES:
        raise DecisionValidationError(
            f"'source' must be one of {PERMITTED_SOURCES}, got {source!r}."
        )

    # Return deep copy / sanitized dictionary without silent mutation
    return {
        "questions": list(questions),
        "probabilities": {k: float(probabilities[k]) for k in VALID_DIRECTIONS},
        "chosen": str(chosen),
        "confidence": float(confidence),
        "source": str(source),
    }


class FallbackTracker:
    """Tracks and validates session-level fallback move compliance.

    Competition rule:
    Fallback moves must be at most 10% of a session's moves.

    Note on runtime vs session-end policy:
    At the start of a session (e.g. step 1), a single fallback yields a 100% ratio
    which would exceed 10% if evaluated eagerly without knowing session length.
    Therefore, session-level validation assesses the complete finished session.
    Runtime guards should only restrict fallback usage based on explicit session
    budget strategies rather than guessing.
    """

    def __init__(self, max_ratio: float = MAX_FALLBACK_RATIO):
        self.max_ratio = max_ratio
        self.total_moves: int = 0
        self.fallback_moves: int = 0
        self.laya_moves: int = 0

    def record_move(self, source: str) -> None:
        """Record the source of a move decision ('laya' or 'fallback')."""
        if source == "fallback":
            self.fallback_moves += 1
            self.total_moves += 1
        elif source == "laya":
            self.laya_moves += 1
            self.total_moves += 1
        else:
            raise ValueError(f"Unknown decision source: {source!r}")

    @property
    def fallback_ratio(self) -> float:
        """Ratio of fallback moves to total moves [0.0, 1.0]."""
        if self.total_moves == 0:
            return 0.0
        return self.fallback_moves / self.total_moves

    @property
    def fallback_percentage(self) -> float:
        """Percentage of fallback moves [0.0, 100.0]."""
        return self.fallback_ratio * 100.0

    def is_within_limit(self) -> bool:
        """Return True if the current fallback ratio does not exceed the limit."""
        return self.fallback_ratio <= (self.max_ratio + 1e-9)

    def validate_session(self) -> Tuple[bool, Optional[str]]:
        """Validate whether the finished session satisfies the 10% fallback rule.

        Returns:
            (True, None) if compliant.
            (False, error_message) if fallback limit was exceeded.
        """
        if not self.is_within_limit():
            return (
                False,
                f"Fallback moves exceed {self.max_ratio * 100:.1f}% limit: "
                f"{self.fallback_moves}/{self.total_moves} ({self.fallback_percentage:.2f}%).",
            )
        return (True, None)
