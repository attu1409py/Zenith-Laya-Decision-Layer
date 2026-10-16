"""Visible terminal decision viewer for the ZENITH competition decision layer.

Displays a clean, readable status panel during game sessions as required by
Section 6 of CONTEXT.md and the participant guide. The viewer must remain
visible during judging runs.

Required display elements (from CONTEXT.md):
- Team/agent name ZENITH, selected game, session ID, and session status.
- Latest game state (compact view).
- Exact question sent to Laya.
- Laya probability distribution, chosen action, confidence, and source.
- Move result (applied/rejected) and current score/step count.
- decide_ms, api_ms, turn_ms.
- Fallback count/percentage and log file location/status.
- Final game result and whether the log/hash chain validated.
"""

from __future__ import annotations

import io
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Sequence, TextIO

TEAM_NAME = "ZENITH"
SEPARATOR = "=" * 72
THIN_SEP = "-" * 72
DIRECTIONS = ("up", "down", "left", "right")


class DecisionViewer:
    """Renders a terminal decision panel for a ZENITH game session.

    All output goes through self._out, which defaults to sys.stdout
    but can be replaced with a StringIO for testing.
    """

    def __init__(
        self,
        game: str,
        session_id: str,
        *,
        mock_mode: bool = False,
        log_path: Optional[str] = None,
        out: Optional[TextIO] = None,
    ):
        """Initialize the viewer.

        Args:
            game: Game identifier ('snake' or '2048').
            session_id: Arena session ID string.
            mock_mode: If True, display a prominent MOCK MODE indicator.
            log_path: Path to the JSONL log file.
            out: Output stream (defaults to sys.stdout).
        """
        self._game = game
        self._session_id = session_id
        self._mock_mode = mock_mode
        self._log_path = log_path or "(not set)"
        self._out: TextIO = out if out is not None else sys.stdout

        # Session-level counters
        self._applied_count: int = 0
        self._rejected_count: int = 0
        self._fallback_count: int = 0
        self._total_moves: int = 0
        self._last_score: Optional[int] = None
        self._session_status: str = "INITIALISING"

    def _write(self, text: str = "") -> None:
        """Write a line to the output stream."""
        self._out.write(text + "\n")

    # ── Header ──────────────────────────────────────────────────────────

    def show_header(self) -> None:
        """Display the session header with team name and mode indicator."""
        self._write(SEPARATOR)
        mode_tag = "  *** MOCK MODE ***" if self._mock_mode else ""
        self._write(f"  {TEAM_NAME} Decision Layer{mode_tag}")
        self._write(SEPARATOR)
        self._write(f"  Game       : {self._game}")
        self._write(f"  Session    : {self._session_id}")
        self._write(f"  Log file   : {self._log_path}")
        self._write(f"  Status     : {self._session_status}")
        self._write(SEPARATOR)

    # ── Per-move display ────────────────────────────────────────────────

    def show_move(
        self,
        step: int,
        state_before: Mapping[str, Any],
        decision: Mapping[str, Any],
        action: str,
        result: str,
        state_after: Mapping[str, Any],
        timing: Mapping[str, int],
        score: Optional[int] = None,
        done: bool = False,
        won: Optional[bool] = None,
    ) -> None:
        """Display a single move's full decision panel.

        Args:
            step: Current step number.
            state_before: Game state before the move.
            decision: The validated decision dictionary.
            action: Submitted action string.
            result: 'applied' or 'rejected'.
            state_after: Game state after the move.
            timing: Dict with decide_ms, api_ms, turn_ms.
            score: Current game score (if available).
            done: Whether the game has ended.
            won: Whether the game was won (if known).
        """
        # Update internal counters
        self._total_moves += 1
        source = decision.get("source", "unknown")
        if result == "applied":
            self._applied_count += 1
        elif result == "rejected":
            self._rejected_count += 1
        if source == "fallback":
            self._fallback_count += 1
        if score is not None:
            self._last_score = score

        self._write()
        self._write(THIN_SEP)
        self._write(f"  Step {step}  |  Result: {result.upper()}")
        self._write(THIN_SEP)

        # Question text
        questions = decision.get("questions", [])
        if questions:
            self._write(f"  Question   : {questions[0]}")
            for extra_q in questions[1:]:
                self._write(f"               {extra_q}")
        else:
            self._write("  Question   : (none)")

        # Probability distribution
        probs = decision.get("probabilities", {})
        prob_parts = []
        for d in DIRECTIONS:
            val = probs.get(d, 0.0)
            prob_parts.append(f"{d}={val:.4f}")
        self._write(f"  Probs      : {' | '.join(prob_parts)}")

        # Chosen action, confidence, source
        chosen = decision.get("chosen", "?")
        confidence = decision.get("confidence", 0.0)
        self._write(f"  Chosen     : {chosen}  (confidence: {confidence:.4f})")
        self._write(f"  Source     : {source}")
        self._write(f"  Action     : {action}")

        # Compact state view
        self._write(f"  State (before): {_compact_state(state_before)}")
        self._write(f"  State (after) : {_compact_state(state_after)}")

        # Timing
        decide_ms = timing.get("decide_ms", 0)
        api_ms = timing.get("api_ms", 0)
        turn_ms = timing.get("turn_ms", 0)
        self._write(f"  Timing     : decide={decide_ms}ms  api={api_ms}ms  turn={turn_ms}ms")

        # Score and session stats
        score_str = str(score) if score is not None else "N/A"
        self._write(f"  Score      : {score_str}")
        self._write(
            f"  Moves      : {self._applied_count} applied, "
            f"{self._rejected_count} rejected, "
            f"{self._total_moves} total"
        )

        # Fallback stats
        fb_pct = (self._fallback_count / self._total_moves * 100.0) if self._total_moves > 0 else 0.0
        self._write(
            f"  Fallback   : {self._fallback_count}/{self._total_moves} "
            f"({fb_pct:.1f}%)"
        )

        if done:
            self._session_status = "FINISHED"
            won_str = "YES" if won else ("NO" if won is not None else "UNKNOWN")
            self._write(f"  Game Over  : won={won_str}")

        self._write(THIN_SEP)

    # ── Session summary ─────────────────────────────────────────────────

    def show_summary(
        self,
        final_score: Optional[int] = None,
        won: Optional[bool] = None,
        hash_chain_valid: Optional[bool] = None,
        total_time_ms: Optional[int] = None,
    ) -> None:
        """Display the end-of-session summary panel.

        Args:
            final_score: The final game score.
            won: Whether the game was won.
            hash_chain_valid: Whether the log's hash chain verified.
            total_time_ms: Total session wall-clock time in ms.
        """
        self._write()
        self._write(SEPARATOR)
        self._write("  SESSION SUMMARY")
        self._write(SEPARATOR)
        if self._mock_mode:
            self._write("  Mode       : *** MOCK MODE ***")
        self._write(f"  Game       : {self._game}")
        self._write(f"  Session    : {self._session_id}")

        score_str = str(final_score) if final_score is not None else "N/A"
        self._write(f"  Final Score: {score_str}")

        won_str = "YES" if won else ("NO" if won is not None else "UNKNOWN")
        self._write(f"  Won        : {won_str}")

        self._write(f"  Applied    : {self._applied_count}")
        self._write(f"  Rejected   : {self._rejected_count}")
        self._write(f"  Total Moves: {self._total_moves}")

        fb_pct = (self._fallback_count / self._total_moves * 100.0) if self._total_moves > 0 else 0.0
        limit_ok = "OK" if fb_pct <= 10.0 + 1e-9 else "EXCEEDED"
        self._write(
            f"  Fallback   : {self._fallback_count}/{self._total_moves} "
            f"({fb_pct:.1f}%) [{limit_ok}]"
        )

        if total_time_ms is not None:
            self._write(f"  Total Time : {total_time_ms}ms")

        if hash_chain_valid is not None:
            chain_str = "VALID" if hash_chain_valid else "INVALID"
            self._write(f"  Hash Chain : {chain_str}")

        self._write(f"  Log File   : {self._log_path}")
        self._write(SEPARATOR)


def _compact_state(state: Mapping[str, Any], max_len: int = 120) -> str:
    """Produce a compact, single-line summary of a game state dict.

    If the full repr exceeds max_len, it is truncated with '...'.
    """
    if not state:
        return "{}"
    # Build a short summary showing key fields
    parts = []
    for key in sorted(state.keys()):
        val = state[key]
        val_str = repr(val)
        if len(val_str) > 40:
            val_str = val_str[:37] + "..."
        parts.append(f"{key}={val_str}")
    result = ", ".join(parts)
    if len(result) > max_len:
        result = result[: max_len - 3] + "..."
    return result
