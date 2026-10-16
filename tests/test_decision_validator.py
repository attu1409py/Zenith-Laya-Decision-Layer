"""Unit tests for zenith/decision_validator.py.

Validates competition decision rules:
- Questions list validation
- Probability distribution constraints ([0, 1], sum in [0.98, 1.02], exactly 4 keys)
- Rejection of boolean values and non-finite numbers (NaN/Inf)
- Action and chosen match
- Confidence equals probabilities[chosen]
- Permitted source ('laya' or 'fallback')
- Fallback budget tracker (<= 10% limit)
- No silent action substitution on invalid decision
"""

import math
import unittest

from zenith.decision_validator import (
    DecisionValidationError,
    FallbackTracker,
    validate_decision,
)


class TestDecisionValidator(unittest.TestCase):
    """Test suite for validate_decision function."""

    def _get_valid_decision(self):
        return {
            "questions": ["What is the next best move for Snake at (6,6)?"],
            "probabilities": {
                "up": 0.61,
                "down": 0.04,
                "left": 0.22,
                "right": 0.13,
            },
            "chosen": "up",
            "confidence": 0.61,
            "source": "laya",
        }

    def test_valid_laya_decision(self):
        """A properly formatted decision must pass validation unchanged."""
        decision = self._get_valid_decision()
        validated = validate_decision(decision, action="up")

        self.assertEqual(validated["chosen"], "up")
        self.assertEqual(validated["confidence"], 0.61)
        self.assertEqual(validated["source"], "laya")
        self.assertEqual(validated["questions"], decision["questions"])
        self.assertEqual(validated["probabilities"], decision["probabilities"])

    def test_valid_fallback_decision(self):
        """A valid safety fallback decision must pass validation."""
        decision = self._get_valid_decision()
        decision["source"] = "fallback"
        validated = validate_decision(decision, action="up")
        self.assertEqual(validated["source"], "fallback")

    def test_non_dict_decision_rejected(self):
        """Non-dictionary decision must be rejected."""
        with self.assertRaises(DecisionValidationError):
            validate_decision(["not", "a", "dict"], action="up")  # type: ignore

    def test_missing_questions_field(self):
        """Missing 'questions' field must be rejected."""
        decision = self._get_valid_decision()
        del decision["questions"]
        with self.assertRaises(DecisionValidationError):
            validate_decision(decision, action="up")

    def test_empty_questions_list(self):
        """Empty 'questions' list must be rejected."""
        decision = self._get_valid_decision()
        decision["questions"] = []
        with self.assertRaises(DecisionValidationError):
            validate_decision(decision, action="up")

    def test_empty_question_string(self):
        """Empty or blank string inside 'questions' list must be rejected."""
        decision = self._get_valid_decision()
        decision["questions"] = ["   "]
        with self.assertRaises(DecisionValidationError):
            validate_decision(decision, action="up")

    def test_missing_probabilities_field(self):
        """Missing 'probabilities' field must be rejected."""
        decision = self._get_valid_decision()
        del decision["probabilities"]
        with self.assertRaises(DecisionValidationError):
            validate_decision(decision, action="up")

    def test_missing_probability_key(self):
        """Missing one of the four required direction keys must be rejected."""
        decision = self._get_valid_decision()
        del decision["probabilities"]["right"]
        with self.assertRaises(DecisionValidationError):
            validate_decision(decision, action="up")

    def test_extra_probability_key(self):
        """Additional direction keys must be rejected."""
        decision = self._get_valid_decision()
        decision["probabilities"]["none"] = 0.0
        with self.assertRaises(DecisionValidationError):
            validate_decision(decision, action="up")

    def test_boolean_probability_rejected(self):
        """Boolean values (True/False) must not be accepted as numeric probabilities."""
        decision = self._get_valid_decision()
        decision["probabilities"]["up"] = True
        with self.assertRaises(DecisionValidationError):
            validate_decision(decision, action="up")

    def test_probability_out_of_bounds_negative(self):
        """Negative probability value must be rejected."""
        decision = self._get_valid_decision()
        decision["probabilities"]["down"] = -0.05
        with self.assertRaises(DecisionValidationError):
            validate_decision(decision, action="up")

    def test_probability_out_of_bounds_greater_than_one(self):
        """Probability value greater than 1 must be rejected."""
        decision = self._get_valid_decision()
        decision["probabilities"]["up"] = 1.05
        with self.assertRaises(DecisionValidationError):
            validate_decision(decision, action="up")

    def test_probability_nan_rejected(self):
        """NaN probability must be rejected."""
        decision = self._get_valid_decision()
        decision["probabilities"]["up"] = float("nan")
        with self.assertRaises(DecisionValidationError):
            validate_decision(decision, action="up")

    def test_probability_infinity_rejected(self):
        """Infinity probability must be rejected."""
        decision = self._get_valid_decision()
        decision["probabilities"]["up"] = float("inf")
        with self.assertRaises(DecisionValidationError):
            validate_decision(decision, action="up")

    def test_probability_sum_too_low(self):
        """Sum < 0.98 must be rejected."""
        decision = self._get_valid_decision()
        # Sum = 0.95
        decision["probabilities"] = {"up": 0.60, "down": 0.10, "left": 0.15, "right": 0.10}
        decision["confidence"] = 0.60
        with self.assertRaises(DecisionValidationError):
            validate_decision(decision, action="up")

    def test_probability_sum_too_high(self):
        """Sum > 1.02 must be rejected."""
        decision = self._get_valid_decision()
        # Sum = 1.06
        decision["probabilities"] = {"up": 0.60, "down": 0.16, "left": 0.15, "right": 0.15}
        decision["confidence"] = 0.60
        with self.assertRaises(DecisionValidationError):
            validate_decision(decision, action="up")

    def test_probability_sum_boundary_values(self):
        """Sum exactly 0.98 and 1.02 must pass validation."""
        decision = self._get_valid_decision()
        # Exactly 0.98
        decision["probabilities"] = {"up": 0.50, "down": 0.18, "left": 0.15, "right": 0.15}
        decision["confidence"] = 0.50
        self.assertAlmostEqual(sum(decision["probabilities"].values()), 0.98)
        self.assertEqual(validate_decision(decision, action="up")["confidence"], 0.50)

        # Exactly 1.02
        decision["probabilities"] = {"up": 0.52, "down": 0.20, "left": 0.15, "right": 0.15}
        decision["confidence"] = 0.52
        self.assertAlmostEqual(sum(decision["probabilities"].values()), 1.02)
        self.assertEqual(validate_decision(decision, action="up")["confidence"], 0.52)

    def test_invalid_chosen_direction(self):
        """Chosen direction not in (up, down, left, right) must be rejected."""
        decision = self._get_valid_decision()
        decision["chosen"] = "forward"
        with self.assertRaises(DecisionValidationError):
            validate_decision(decision, action="forward")

    def test_chosen_mismatch_with_action(self):
        """Chosen action must equal submitted action; mismatch must be rejected."""
        decision = self._get_valid_decision()
        decision["chosen"] = "up"
        with self.assertRaises(DecisionValidationError):
            validate_decision(decision, action="down")

    def test_confidence_not_matching_probabilities(self):
        """Confidence must equal probabilities[chosen]."""
        decision = self._get_valid_decision()
        decision["confidence"] = 0.50  # probabilities['up'] is 0.61
        with self.assertRaises(DecisionValidationError):
            validate_decision(decision, action="up")

    def test_boolean_confidence_rejected(self):
        """Boolean values for confidence must be rejected."""
        decision = self._get_valid_decision()
        decision["confidence"] = True
        with self.assertRaises(DecisionValidationError):
            validate_decision(decision, action="up")

    def test_invalid_source_rejected(self):
        """Sources other than 'laya' or 'fallback' must be rejected."""
        decision = self._get_valid_decision()
        decision["source"] = "gpt-4"
        with self.assertRaises(DecisionValidationError):
            validate_decision(decision, action="up")

        decision["source"] = "heuristic_search"
        with self.assertRaises(DecisionValidationError):
            validate_decision(decision, action="up")

    def test_no_silent_action_substitution(self):
        """Invalid decision must raise exception, never substitute an action."""
        bad_decision = self._get_valid_decision()
        bad_decision["probabilities"]["up"] = -1.0  # Invalid!
        with self.assertRaises(DecisionValidationError):
            validate_decision(bad_decision, action="up")


class TestFallbackTracker(unittest.TestCase):
    """Test suite for session-level fallback move budget tracking."""

    def test_empty_session_is_within_limit(self):
        """A new tracker with 0 moves is within limit."""
        tracker = FallbackTracker(max_ratio=0.10)
        self.assertEqual(tracker.total_moves, 0)
        self.assertEqual(tracker.fallback_moves, 0)
        self.assertEqual(tracker.fallback_percentage, 0.0)
        self.assertTrue(tracker.is_within_limit())
        is_valid, msg = tracker.validate_session()
        self.assertTrue(is_valid)
        self.assertIsNone(msg)

    def test_fallback_within_10_percent_limit(self):
        """1 fallback in 10 moves (10.0%) is compliant."""
        tracker = FallbackTracker(max_ratio=0.10)
        tracker.record_move("fallback")
        for _ in range(9):
            tracker.record_move("laya")

        self.assertEqual(tracker.total_moves, 10)
        self.assertEqual(tracker.fallback_moves, 1)
        self.assertEqual(tracker.laya_moves, 9)
        self.assertAlmostEqual(tracker.fallback_percentage, 10.0)
        self.assertTrue(tracker.is_within_limit())

        is_valid, msg = tracker.validate_session()
        self.assertTrue(is_valid)
        self.assertIsNone(msg)

    def test_fallback_exceeds_10_percent_limit(self):
        """2 fallbacks in 10 moves (20.0%) violates the 10% limit."""
        tracker = FallbackTracker(max_ratio=0.10)
        tracker.record_move("fallback")
        tracker.record_move("fallback")
        for _ in range(8):
            tracker.record_move("laya")

        self.assertEqual(tracker.total_moves, 10)
        self.assertEqual(tracker.fallback_moves, 2)
        self.assertAlmostEqual(tracker.fallback_percentage, 20.0)
        self.assertFalse(tracker.is_within_limit())

        is_valid, msg = tracker.validate_session()
        self.assertFalse(is_valid)
        self.assertIn("exceed", msg.lower())
        self.assertIn("20.00%", msg)

    def test_unknown_source_raises_value_error(self):
        """Recording an unknown source must raise ValueError."""
        tracker = FallbackTracker()
        with self.assertRaises(ValueError):
            tracker.record_move("unknown_agent")


if __name__ == "__main__":
    unittest.main()
