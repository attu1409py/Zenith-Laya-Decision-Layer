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
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Sequence

from zenith.decision_validator import (
    DecisionValidationError,
    FallbackTracker,
    validate_decision,
)
from zenith.decision_viewer import DecisionViewer
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
    result: str  # 'applied' or 'rejected'
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
    total_moves: int = 0
    applied_moves: int = 0
    rejected_moves: int = 0
    fallback_moves: int = 0
    hash_chain_valid: Optional[bool] = None
    total_time_ms: Optional[int] = None
    log_path: Optional[str] = None
    moves: List[MoveRecord] = field(default_factory=list)
    error: Optional[str] = None


# ── Runner class ───────────────────────────────────────────────────────

class SessionRunner:
    """Orchestrates a complete game session from start to finish.

    The runner:
    1. Creates a session via the arena adapter.
    2. Enters a loop: get state -> call decide_fn -> validate -> submit action.
    3. Logs every move (applied and rejected) via SessionLogger.
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
        on_step: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_complete: Optional[Callable[[SessionResult], None]] = None,
    ):
        """Initialize the session runner.

        Args:
            arena: Arena API adapter (or mock).
            decide_fn: Callable that produces decisions from game state.
            logger: SessionLogger for JSONL output.
            viewer: DecisionViewer for terminal display.
            fallback_tracker: FallbackTracker instance (created if None).
            max_consecutive_errors: Stop after this many consecutive errors.
            max_consecutive_rejections: Stop after this many consecutive rejected moves.
            on_step: Optional callback called after each move record is logged.
            on_complete: Optional callback called when session completes.
        """
        self._arena = arena
        self._decide_fn = decide_fn
        self._logger = logger
        self._viewer = viewer
        self._fallback = fallback_tracker or FallbackTracker()
        self._max_consecutive_errors = max_consecutive_errors
        self._max_consecutive_rejections = max_consecutive_rejections
        self._on_step = on_step
        self._on_complete = on_complete
        self._stop_requested: bool = False

    def stop(self) -> None:
        """Signal the runner to halt cleanly after current step."""
        self._stop_requested = True

    def run(self, initial_session_data: Optional[Dict[str, Any]] = None) -> SessionResult:
        """Execute the game session loop and return the result.

        Args:
            initial_session_data: Optional initial session dict from create_session.
                If provided, avoids an immediate duplicate get_session network call.

        Returns:
            SessionResult with full session outcome.
        """
        session_watch = MonotonicStopwatch()
        game = self._logger.game
        session_id = self._logger.session_id
        result = SessionResult(session_id=session_id, game=game)
        result.log_path = str(self._logger.log_path)

        self._viewer.show_header()

        step = 0          # accepted-step counter
        consecutive_errors = 0
        consecutive_rejections = 0
        done = False

        # Get initial state
        if initial_session_data is not None:
            session_data = dict(initial_session_data)
        else:
            try:
                session_data = self._arena.get_session(session_id)
            except Exception as exc:
                result.error = f"Failed to get initial session state: {exc}"
                return result

        while not done:
            if self._stop_requested:
                result.error = "Session stopped by operator."
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
                    break
                continue

            # ── Submit action ──
            api_watch = MonotonicStopwatch()
            try:
                response = self._arena.submit_action(session_id, action)
            except Exception as exc:
                consecutive_errors += 1
                if consecutive_errors >= self._max_consecutive_errors:
                    result.error = (
                        f"Too many consecutive API errors "
                        f"({consecutive_errors}): {exc}"
                    )
                    break
                continue
            api_ms = api_watch.elapsed_ms()

            consecutive_errors = 0  # reset on success

            # ── Determine result ──
            state_after = _extract_state(response)
            move_result = response.get("result", "applied")
            done = response.get("done", False)
            won = response.get("won")
            new_score = response.get("score", score)

            if move_result == "applied":
                step += 1
                result.applied_moves += 1
                consecutive_rejections = 0
            else:
                result.rejected_moves += 1
                consecutive_rejections += 1
                if consecutive_rejections >= self._max_consecutive_rejections:
                    result.error = (
                        f"Too many consecutive rejected moves "
                        f"({consecutive_rejections}): session stopped to avoid infinite loop."
                    )
                    break

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

            # ── Log ──
            log_step = step if move_result == "applied" else step + 1
            # Note: The step value for rejected moves is ambiguous per the
            # guide. We use step+1 tentatively; the logger accepts whatever
            # caller supplies. This is an unresolved blocker per PROJECT_STATE.
            logged_record: Dict[str, Any] = {}
            try:
                logged_record = self._logger.log_move(
                    step=log_step if move_result == "rejected" else step,
                    state_before=dict(state_before),
                    action=action,
                    state_after=dict(state_after),
                    result=move_result,
                    decision=validated_decision,
                    timing=timing,
                )
            except Exception as exc:
                result.error = f"Failed to log move at step {step}: {exc}"
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

        # ── Session complete ──
        result.final_score = session_data.get("score")
        result.won = session_data.get("won")
        result.total_time_ms = session_watch.elapsed_ms()

        # Save final response
        try:
            self._logger.save_final_response(session_data)
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
        )

        if self._on_complete is not None:
            try:
                self._on_complete(result)
            except Exception:
                pass

        return result


def _extract_state(session_data: Mapping[str, Any]) -> Dict[str, Any]:
    """Extract the game state sub-dict from a session response.

    The Arena API may return state at top level or nested under a 'state' key.
    This helper handles both formats.
    """
    if "state" in session_data and isinstance(session_data["state"], dict):
        return dict(session_data["state"])
    # If no nested 'state', return a copy of the full response as the state
    # (excluding metadata fields)
    excluded = {"session_id", "done", "won", "result", "score", "game", "agent_name"}
    return {k: v for k, v in session_data.items() if k not in excluded}
