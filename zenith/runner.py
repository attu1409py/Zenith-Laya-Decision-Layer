"""Game session runner orchestrating state -> decide -> validate -> act -> log -> view.

This module provides the SessionRunner class that ties together all ZENITH
decision-layer components with dependency injection, so the runner can be
exercised with mock adapters in tests without contacting live services.

Components injected at construction:
- arena_adapter: provides create_session, get_session, submit_action
- decide_fn: callable that receives game state and returns a decision dict
- session_logger: SessionLogger instance for JSONL/hash-chain logging
- decision_viewer: DecisionViewer instance for terminal display
- fallback_tracker: FallbackTracker instance for session compliance

Architecture note:
    The real ArenaClient and Laya client are NOT imported here.
    Any object satisfying the duck-typed interface will work, which is
    the key to testability without mocking external services.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

from zenith.decision_validator import (
    DecisionValidationError,
    FallbackTracker,
    validate_decision,
)
from zenith.decision_viewer import DecisionViewer
from zenith.goals import evaluate_stage_goal
from zenith.session_logger import MonotonicStopwatch, SessionLogger


# ── Protocol for the arena adapter ─────────────────────────────────────

class ArenaAdapter(Protocol):
    """Duck-typed interface for an arena API adapter."""

    def create_session(self, game: str, agent_name: str) -> Dict[str, Any]:
        """Create a new game session. Returns raw session dict."""
        ...

    def get_session(self, session_id: str) -> Dict[str, Any]:
        """Retrieve the current state of a session."""
        ...

    def submit_action(self, session_id: str, action: str) -> Dict[str, Any]:
        """Submit an action and return the updated session dict."""
        ...


# Type alias for the decision function
DecideFn = Callable[[str, Mapping[str, Any]], Dict[str, Any]]
"""Signature: (game: str, state: Mapping) -> decision dict.

The decision dict must conform to the competition schema:
    questions, probabilities, chosen, confidence, source.
"""


# ── Data classes for results ───────────────────────────────────────────

@dataclass
class MoveRecord:
    """A single move's outcome within a session."""
    step: int
    action: str
    result: str  # 'applied', 'rejected', or 'no_progress'
    decision: Dict[str, Any]
    timing: Dict[str, int]
    score: Optional[int] = None
    done: bool = False
    won: Optional[bool] = None


@dataclass
class SessionResult:
    """Final outcome of a complete session run."""
    session_id: str
    game: str
    final_score: Optional[int] = None
    won: Optional[bool] = None
    outcome: Optional[str] = None
    goal_reached: Optional[bool] = None
    goal_progress: Optional[str] = None
    completion_reason: Optional[str] = None
    total_moves: int = 0
    applied_moves: int = 0
    rejected_moves: int = 0
    no_progress_moves: int = 0
    fallback_moves: int = 0
    hash_chain_valid: Optional[bool] = None
    total_time_ms: Optional[int] = None
    log_path: Optional[str] = None
    moves: List[MoveRecord] = field(default_factory=list)
    error: Optional[str] = None
    termination_reason: Optional[str] = None

    @property
    def status(self) -> str:
        """Terminal session status distinguishing all termination modes."""
        if self.won is True:
            return "WON"
        if self.termination_reason == "no_progress_stopped" or (self.error and "No-progress detected" in self.error):
            return "NO_PROGRESS_STOPPED"
        if self.termination_reason == "api_error_stopped" or (self.error and "API error" in self.error):
            return "API_ERROR_STOPPED"
        if self.termination_reason == "rejection_limit_reached" or (self.error and "consecutive rejected moves" in self.error):
            return "REJECTION_LIMIT_STOPPED"
        if self.termination_reason == "decision_error_stopped" or (self.error and "decision errors" in self.error):
            return "DECISION_ERROR_STOPPED"
        if self.termination_reason == "validation_error_stopped" or (self.error and "validation errors" in self.error):
            return "VALIDATION_ERROR_STOPPED"
        if self.error:
            return "ERROR"
        if self.termination_reason == "max_moves_reached":
            return "MOVE_LIMIT_REACHED"
        if self.won is False:
            return "LOST"
        return "COMPLETE"


# ── Runner class ───────────────────────────────────────────────────────

class SessionRunner:
    """Orchestrates a complete game session from start to finish.

    The runner:
    1. Creates a session via the arena adapter.
    2. Enters a loop: get state -> call decide_fn -> validate -> submit action.
    3. Logs every move (applied, rejected, no_progress) via SessionLogger.
    4. Updates the DecisionViewer after each move.
    5. Tracks fallback compliance via FallbackTracker.
    6. Saves the final response and verifies the hash chain on completion.
    """

    def __init__(
        self,
        arena: ArenaAdapter,
        decide_fn: DecideFn,
        logger: SessionLogger,
        viewer: DecisionViewer,
        fallback_tracker: Optional[FallbackTracker] = None,
        *,
        max_consecutive_errors: int = 5,
        max_consecutive_rejections: int = 10,
        max_consecutive_no_progress: int = 1,
        max_moves: Optional[int] = None,
        on_step: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_complete: Optional[Callable[[SessionResult], None]] = None,
    ):
        self._arena = arena
        self._decide_fn = decide_fn
        self._logger = logger
        self._viewer = viewer
        self._fallback = fallback_tracker or FallbackTracker()
        self._max_consecutive_errors = max_consecutive_errors
        self._max_consecutive_rejections = max_consecutive_rejections
        self._max_consecutive_no_progress = max_consecutive_no_progress
        self._max_moves = max_moves
        self._on_step = on_step
        self._on_complete = on_complete
        self._stop_requested = False

    def stop(self) -> None:
        """Signal the session runner loop to stop gracefully after current step."""
        self._stop_requested = True

    def run(self, initial_session_data: Optional[Dict[str, Any]] = None) -> SessionResult:
        """Run the full session loop until the game concludes or stops."""
        session_watch = MonotonicStopwatch()

        game = self._logger.game
        session_id = self._logger.session_id
        result = SessionResult(session_id=session_id, game=game)
        result.log_path = str(self._logger.log_path)

        self._viewer.show_header()

        step = 0          # accepted-step counter
        consecutive_errors = 0
        consecutive_rejections = 0
        consecutive_no_progress = 0
        done = False

        # Get initial state
        if initial_session_data is not None:
            session_data = dict(initial_session_data)
        else:
            try:
                session_data = self._arena.get_session(session_id)
            except Exception as exc:
                result.error = f"Failed to get initial session state: {exc}"
                result.termination_reason = "api_error_stopped"
                return result

        last_progress_str = ""

        while not done:
            if self._stop_requested:
                if not result.termination_reason:
                    result.termination_reason = "stopped_by_user"
                break

            turn_watch = MonotonicStopwatch()

            # Extract current state from session data
            state_before = _extract_state(session_data)
            done = session_data.get("done", False)
            if done:
                break

            score = session_data.get("score")

            # ── Decide ──
            decide_watch = MonotonicStopwatch()
            try:
                decision = self._decide_fn(game, state_before)
            except Exception as exc:
                consecutive_errors += 1
                if consecutive_errors >= self._max_consecutive_errors:
                    result.error = (
                        f"Too many consecutive decision errors "
                        f"({consecutive_errors}): {exc}"
                    )
                    result.termination_reason = "decision_error_stopped"
                    break
                continue
            decide_ms = decide_watch.elapsed_ms()

            # ── Validate ──
            action = decision.get("chosen", "")
            try:
                validated_decision = validate_decision(decision, action)
            except DecisionValidationError as exc:
                consecutive_errors += 1
                if consecutive_errors >= self._max_consecutive_errors:
                    result.error = (
                        f"Too many consecutive validation errors "
                        f"({consecutive_errors}): {exc}"
                    )
                    result.termination_reason = "validation_error_stopped"
                    break
                continue

            # ── Submit action ──
            api_watch = MonotonicStopwatch()
            try:
                response = self._arena.submit_action(session_id, action)
            except Exception as exc:
                result.error = (
                    f"API error during submit_action (action '{action}'): {exc}. "
                    "Session stopped to prevent duplicate action submission (consecutive API errors limit)."
                )
                result.termination_reason = "api_error_stopped"
                break
            api_ms = api_watch.elapsed_ms()

            consecutive_errors = 0  # reset on success

            # ── Determine result ──
            state_after = _extract_state(response)
            raw_result = response.get("result", "applied")
            done = response.get("done", False)
            won = response.get("won")
            new_score = response.get("score", score)

            stop_after_logging = False

            if done:
                # Terminal state reached
                if raw_result == "rejected":
                    move_result = "rejected"
                    result.rejected_moves += 1
                else:
                    move_result = "applied"
                    step += 1
                    result.applied_moves += 1
            elif raw_result == "rejected":
                # Explicitly rejected move
                move_result = "rejected"
                result.rejected_moves += 1
                consecutive_rejections += 1
                consecutive_no_progress = 0
                if consecutive_rejections >= self._max_consecutive_rejections:
                    result.error = (
                        f"Too many consecutive rejected moves "
                        f"({consecutive_rejections}): session stopped to avoid infinite loop."
                    )
                    result.termination_reason = "rejection_limit_reached"
                    stop_after_logging = True
            else:
                # Action reported as applied (or non-rejected); check authoritative state progress
                is_progress, progress_reason = check_state_progress(
                    game=game,
                    state_before=state_before,
                    state_after=state_after,
                    score_before=score,
                    score_after=new_score,
                )
                if is_progress:
                    move_result = "applied"
                    step += 1
                    result.applied_moves += 1
                    consecutive_rejections = 0
                    consecutive_no_progress = 0
                else:
                    # Action reported as applied, but board/state did not advance
                    move_result = "no_progress"
                    result.no_progress_moves += 1
                    consecutive_no_progress += 1
                    if consecutive_no_progress >= self._max_consecutive_no_progress:
                        result.error = (
                            f"No-progress detected: action '{action}' was reported as applied "
                            f"but board/state did not advance ({progress_reason}). "
                            f"Session stopped after {consecutive_no_progress} no-progress move(s) "
                            "to prevent infinite loop."
                        )
                        result.termination_reason = "no_progress_stopped"
                        stop_after_logging = True

            result.total_moves += 1
            turn_ms = turn_watch.elapsed_ms()

            timing = {
                "decide_ms": decide_ms,
                "api_ms": api_ms,
                "turn_ms": turn_ms,
            }

            # ── Track fallback ──
            source = validated_decision.get("source", "laya")
            self._fallback.record_move(source)
            if source == "fallback":
                result.fallback_moves += 1

            # ── Goal check ──
            goal_eval = evaluate_stage_goal(game, state_after)
            goal_reached = goal_eval["reached"]
            goal_prog_str = goal_eval["progress_text"]
            last_progress_str = goal_prog_str
            if goal_reached:
                done = True
                won = True
                if not result.termination_reason:
                    result.termination_reason = "goal_reached"
                stop_after_logging = True

            # ── Log ──
            log_step = step if move_result == "applied" else step + 1
            logged_record: Dict[str, Any] = {}
            try:
                logged_record = self._logger.log_move(
                    step=log_step,
                    state_before=dict(state_before),
                    action=action,
                    state_after=dict(state_after),
                    result=move_result,
                    decision=validated_decision,
                    timing=timing,
                )
            except Exception as exc:
                result.error = f"Failed to log move at step {step}: {exc}"
                result.termination_reason = "log_error_stopped"
                break

            # ── Display ──
            move_record = MoveRecord(
                step=step,
                action=action,
                result=move_result,
                decision=validated_decision,
                timing=timing,
                score=new_score,
                done=done,
                won=won,
            )
            result.moves.append(move_record)

            self._viewer.show_move(
                step=step,
                state_before=state_before,
                decision=validated_decision,
                action=action,
                result=move_result,
                state_after=state_after,
                timing=timing,
                score=new_score,
                done=done,
                won=won,
            )

            # ── Broadcast UI step callback ──
            if self._on_step is not None:
                try:
                    self._on_step({
                        "session_id": session_id,
                        "game": game,
                        "step": step,
                        "action": action,
                        "result": move_result,
                        "state_before": dict(state_before),
                        "state_after": dict(state_after),
                        "decision": dict(validated_decision),
                        "timing": dict(timing),
                        "score": new_score,
                        "done": done,
                        "won": won,
                        "hash": logged_record.get("hash"),
                        "prev_hash": logged_record.get("prev_hash"),
                        "ts": logged_record.get("ts"),
                        "total_moves": result.total_moves,
                        "applied_moves": result.applied_moves,
                        "rejected_moves": result.rejected_moves,
                        "fallback_moves": result.fallback_moves,
                        "fallback_pct": (result.fallback_moves / result.total_moves * 100.0) if result.total_moves > 0 else 0.0,
                    })
                except Exception:
                    pass

            # Update session_data for next iteration
            session_data = response

            if self._max_moves is not None and result.applied_moves >= self._max_moves:
                if not result.termination_reason:
                    result.termination_reason = "max_moves_reached"
                stop_after_logging = True

            if stop_after_logging:
                break

        # ── Session complete ──
        result.final_score = session_data.get("score")
        if result.termination_reason == "goal_reached":
            result.won = True
        elif result.termination_reason == "max_moves_reached":
            result.won = session_data.get("won")
            if result.won is not True:
                result.won = None
        else:
            result.won = session_data.get("won")

        result.total_time_ms = session_watch.elapsed_ms()
        if not result.termination_reason and "termination_reason" in session_data:
            result.termination_reason = session_data.get("termination_reason")

        # Determine authoritative outcome and goal status
        if result.termination_reason == "goal_reached" or result.won is True:
            result.outcome = "GOAL REACHED"
            result.goal_reached = True
            result.completion_reason = f"STAGE COMPLETE // GOAL REACHED ({last_progress_str})"
        elif result.termination_reason == "max_moves_reached":
            result.outcome = "MAX MOVES REACHED"
            result.goal_reached = False
            result.completion_reason = f"Max moves limit ({self._max_moves}) reached before goal ({last_progress_str})"
        elif result.termination_reason == "stopped_by_user":
            result.outcome = "STOPPED BY USER"
            result.goal_reached = False
            result.completion_reason = f"Session stopped by operator ({last_progress_str})"
        elif result.won is False or done:
            result.outcome = "GAME OVER"
            result.goal_reached = False
            result.completion_reason = f"Game over ({last_progress_str})"
        else:
            result.outcome = result.status
            result.goal_reached = False
            result.completion_reason = f"Session completed ({last_progress_str})"
        result.goal_progress = last_progress_str

        # Save final response with outcome metadata (separate from per-move JSONL log)
        try:
            final_payload = dict(session_data)
            final_payload["outcome"] = result.outcome
            final_payload["goal_reached"] = result.goal_reached
            final_payload["goal_progress"] = result.goal_progress
            final_payload["completion_reason"] = result.completion_reason
            final_payload["status"] = result.status
            self._logger.save_final_response(final_payload)
        except Exception:
            pass  # Best-effort; the JSONL log is the primary artifact

        # Verify hash chain
        try:
            verification = self._logger.verify_log()
            result.hash_chain_valid = verification.is_valid
        except Exception:
            result.hash_chain_valid = None

        # Show summary
        self._viewer.show_summary(
            final_score=result.final_score,
            won=result.won,
            hash_chain_valid=result.hash_chain_valid,
            total_time_ms=result.total_time_ms,
            status=result.status,
        )

        if self._on_complete is not None:
            try:
                self._on_complete(result)
            except Exception:
                pass

        return result


def _extract_state(session_data: Mapping[str, Any]) -> Dict[str, Any]:
    """Extract game state dictionary from raw arena session response."""
    # TopGameAI Arena returns game state nested under 'state'
    if "state" in session_data and isinstance(session_data["state"], dict):
        return dict(session_data["state"])

    # If already a flat state dict, return all game-related keys
    # (excluding metadata fields)
    excluded = {"session_id", "done", "won", "result", "score", "game", "agent_name", "termination_reason"}
    return {k: v for k, v in session_data.items() if k not in excluded}


def normalize_2048_grid(raw_grid: Any) -> Optional[List[List[int]]]:
    """Normalize a 2048 grid into a 4x4 list of lists of integers.

    Returns None if raw_grid is missing, not a 4x4 structure, or contains
    invalid/non-numeric cells (booleans are strictly excluded).
    """
    if not isinstance(raw_grid, (list, tuple)) or len(raw_grid) != 4:
        return None
    grid: List[List[int]] = []
    for row in raw_grid:
        if not isinstance(row, (list, tuple)) or len(row) != 4:
            return None
        row_ints: List[int] = []
        for cell in row:
            if isinstance(cell, bool):
                return None
            if not isinstance(cell, (int, float)):
                return None
            row_ints.append(int(cell))
        grid.append(row_ints)
    return grid


def check_state_progress(
    game: str,
    state_before: Mapping[str, Any],
    state_after: Mapping[str, Any],
    score_before: Optional[int] = None,
    score_after: Optional[int] = None,
) -> Tuple[bool, str]:
    """Determine whether post-action state demonstrates verified game progress.

    Args:
        game: Game identifier ('2048' or 'snake').
        state_before: Pre-action authoritative state dict.
        state_after: Post-action authoritative state dict.
        score_before: Pre-action score (if available).
        score_after: Post-action score (if available).

    Returns:
        A tuple of (is_progress, detail_reason).
    """
    if not isinstance(state_after, (dict, Mapping)):
        return False, "state_after is not a dictionary"

    game_clean = (game or "").strip().lower()

    if game_clean == "2048":
        grid_after = normalize_2048_grid(state_after.get("grid"))
        if grid_after is None:
            return False, "state_after missing or malformed 4x4 grid"

        grid_before = (
            normalize_2048_grid(state_before.get("grid"))
            if isinstance(state_before, (dict, Mapping))
            else None
        )

        grid_changed = (grid_before != grid_after) if grid_before is not None else True

        # Extract numeric scores for comparison
        s_before = state_before.get("score") if isinstance(state_before, (dict, Mapping)) else None
        if s_before is None:
            s_before = score_before
        s_after = state_after.get("score") if isinstance(state_after, (dict, Mapping)) else None
        if s_after is None:
            s_after = score_after

        score_changed = False
        if s_before is not None and s_after is not None:
            score_changed = (s_before != s_after)

        if not grid_changed and not score_changed:
            return False, "grid and score unchanged"

        return True, "progress confirmed"

    elif game_clean == "snake":
        snake_before = state_before.get("snake") if isinstance(state_before, (dict, Mapping)) else None
        snake_after = state_after.get("snake")

        if snake_after is None:
            return False, "state_after missing snake coordinates"

        s_before = state_before.get("score") if isinstance(state_before, (dict, Mapping)) else None
        if s_before is None:
            s_before = score_before
        s_after = state_after.get("score") if isinstance(state_after, (dict, Mapping)) else None
        if s_after is None:
            s_after = score_after

        food_b = state_before.get("foodEaten") if isinstance(state_before, (dict, Mapping)) else None
        food_a = state_after.get("foodEaten")

        if snake_before is not None:
            snake_changed = (snake_before != snake_after)
            score_changed = (s_before is not None and s_after is not None and s_before != s_after)
            food_changed = (food_b is not None and food_a is not None and food_b != food_a)
            if not snake_changed and not score_changed and not food_changed:
                return False, "snake coordinates and score unchanged"

        return True, "progress confirmed"

    # Default fallback for unrecognized games:
    if state_before == state_after and score_before == score_after:
        return False, "state unchanged"
    return True, "progress confirmed"
