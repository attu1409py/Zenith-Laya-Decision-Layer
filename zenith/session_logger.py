"""Append-only JSONL session logger with integrated SHA-256 hash chaining.

This module writes audit-compliant JSONL logs for TopGameAI Arena game sessions,
strictly adhering to the schema and verification rules in Section 3 and 4 of
Track2_PS2_support.pdf and CONTEXT.md.

Key guarantees:
1. Every move (both 'applied' and 'rejected') is logged as a separate JSONL record.
2. Every record contains 'prev_hash' and 'hash', cryptographically chained using
   canonical JSON serialization and SHA-256 hashing.
3. Raw state objects (state_before, state_after) are preserved without alteration.
4. Timings (decide_ms, api_ms, turn_ms) are validated as non-negative integers
   measured using monotonic clocks.
5. All file writes are flushed immediately to prevent data loss in user buffers.
6. The final Arena response can be persisted immediately upon game conclusion.
7. Caller-supplied 'step' values are preserved without synthetic modification.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Union

from zenith.decision_validator import validate_decision
from zenith.hash_chain import (
    VerificationResult,
    create_chained_record,
    get_genesis_prev_hash,
    read_jsonl_records,
    serialize_record_to_jsonl,
    verify_jsonl_file,
)

VALID_RESULTS = ("applied", "rejected", "no_progress")
VALID_GAMES = ("snake", "2048")


class SessionLoggerError(ValueError):
    """Raised when record creation or logging fails validation."""
    pass


class MonotonicStopwatch:
    """Monotonic stopwatch for accurate integer millisecond timing.

    Uses time.monotonic_ns() to avoid wall-clock shifts, timezone changes,
    or leap second drift.
    """

    def __init__(self):
        self._start_ns: int = time.monotonic_ns()

    def elapsed_ms(self) -> int:
        """Return elapsed time in integer milliseconds since stopwatch instantiation."""
        return (time.monotonic_ns() - self._start_ns) // 1_000_000

    def reset(self) -> None:
        """Reset the stopwatch start time to now."""
        self._start_ns = time.monotonic_ns()


class SessionLogger:
    """Manages an append-only, SHA-256 hash-chained JSONL log file for a game session."""

    def __init__(
        self,
        session_id: str,
        game: str,
        log_dir: Union[str, Path] = "logs",
        filename: Optional[str] = None,
    ):
        """Initialize the session logger.

        Args:
            session_id: The unique Arena session ID.
            game: Game name ('snake' or '2048').
            log_dir: Directory where logs should be stored (defaults to 'logs').
            filename: Custom filename (defaults to '{session_id}.jsonl').
        """
        if not session_id or not isinstance(session_id, str) or not session_id.strip():
            raise SessionLoggerError("session_id must be a non-empty string.")
        if not game or not isinstance(game, str) or game.strip() not in VALID_GAMES:
            raise SessionLoggerError(f"game must be one of {VALID_GAMES}, got {game!r}.")

        self.session_id = session_id.strip()
        self.game = game.strip()
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.log_path = self.log_dir / (filename or f"{self.session_id}.jsonl")
        self.last_hash: Optional[str] = None
        self.record_count: int = 0

        # If file already exists with data, verify and resume chain
        if self.log_path.exists() and self.log_path.stat().st_size > 0:
            verification = verify_jsonl_file(self.log_path)
            if not verification.is_valid:
                raise SessionLoggerError(
                    f"Existing log file {self.log_path} fails hash-chain verification: "
                    f"{verification.error_message}"
                )
            with open(self.log_path, "r", encoding="utf-8") as f:
                records = read_jsonl_records(f.readlines())
            self.record_count = len(records)
            self.last_hash = records[-1]["hash"]

    def _validate_timing(self, timing: Mapping[str, Any]) -> Dict[str, int]:
        """Validate timing dictionary containing decide_ms, api_ms, turn_ms."""
        if not isinstance(timing, dict):
            raise SessionLoggerError(f"'timing' must be a dictionary, got {type(timing).__name__}.")

        required_keys = ("decide_ms", "api_ms", "turn_ms")
        validated_timing: Dict[str, int] = {}

        for k in required_keys:
            if k not in timing:
                raise SessionLoggerError(f"'timing' missing required field: '{k}'.")
            v = timing[k]
            # Exclude booleans explicitly
            if isinstance(v, bool) or not isinstance(v, int):
                raise SessionLoggerError(
                    f"'timing.{k}' must be an integer millisecond count, got {type(v).__name__} ({v!r})."
                )
            if v < 0:
                raise SessionLoggerError(f"'timing.{k}' cannot be negative, got {v}.")
            validated_timing[k] = v

        return validated_timing

    def _format_utc_timestamp(self, ts: Optional[str] = None) -> str:
        """Ensure timestamp is formatted as UTC ISO-8601 (ending in 'Z')."""
        if ts is not None:
            if not isinstance(ts, str) or not ts.strip():
                raise SessionLoggerError("Caller-provided 'ts' must be a non-empty string.")
            return ts.strip()
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def log_move(
        self,
        step: int,
        state_before: Mapping[str, Any],
        action: str,
        state_after: Mapping[str, Any],
        result: str,
        decision: Mapping[str, Any],
        timing: Mapping[str, Any],
        ts: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate and append a move record to the session JSONL file.

        Args:
            step: Move step number (caller-supplied integer).
            state_before: Raw game state returned by the Arena before this move.
            action: Move string ('up', 'down', 'left', 'right').
            state_after: Raw game state returned by the Arena after this move.
            result: Result string ('applied' or 'rejected').
            decision: Decision block dictionary.
            timing: Dict with decide_ms, api_ms, turn_ms integers.
            ts: Optional UTC ISO-8601 timestamp string (generated if omitted).

        Returns:
            The complete chained record with prev_hash and hash.
        """
        # 1. Validate step
        if isinstance(step, bool) or not isinstance(step, int) or step < 1:
            raise SessionLoggerError(
                f"'step' must be a positive integer starting at 1, got {type(step).__name__} ({step!r})."
            )

        # 2. Validate states
        if not isinstance(state_before, dict):
            raise SessionLoggerError(
                f"'state_before' must be a dictionary, got {type(state_before).__name__}."
            )
        if not isinstance(state_after, dict):
            raise SessionLoggerError(
                f"'state_after' must be a dictionary, got {type(state_after).__name__}."
            )

        # 3. Validate result
        if not isinstance(result, str) or result not in VALID_RESULTS:
            raise SessionLoggerError(
                f"'result' must be one of {VALID_RESULTS}, got {result!r}."
            )

        # 4. Validate decision and action match
        validated_decision = validate_decision(decision, action)

        # 5. Validate timings
        validated_timing = self._validate_timing(timing)

        # 6. Format timestamp
        iso_ts = self._format_utc_timestamp(ts)

        # 7. Determine prev_hash
        if self.last_hash is None:
            prev_hash = get_genesis_prev_hash(self.session_id)
        else:
            prev_hash = self.last_hash

        # 8. Assemble record without hash
        raw_record = {
            "session_id": self.session_id,
            "game": self.game,
            "step": step,
            "state_before": state_before,
            "action": action,
            "state_after": state_after,
            "result": result,
            "decision": validated_decision,
            "timing": validated_timing,
            "ts": iso_ts,
        }

        # 9. Compute chained record (adds prev_hash and hash)
        chained_record = create_chained_record(raw_record, prev_hash)

        # 10. Write to JSONL file and flush immediately
        jsonl_line = serialize_record_to_jsonl(chained_record) + "\n"
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(jsonl_line)
            f.flush()

        # 11. Advance chain state
        self.last_hash = chained_record["hash"]
        self.record_count += 1

        return chained_record

    def save_final_response(
        self,
        final_response: Mapping[str, Any],
        filename: Optional[str] = None,
    ) -> Path:
        """Persist the Arena's final game response immediately upon game completion.

        Args:
            final_response: The final response payload dictionary from the Arena API.
            filename: Optional custom filename (defaults to '{session_id}_final.json').

        Returns:
            The Path to the saved final response file.
        """
        if not isinstance(final_response, dict):
            raise SessionLoggerError(
                f"final_response must be a dictionary, got {type(final_response).__name__}."
            )

        target_file = self.log_dir / (filename or f"{self.session_id}_final.json")
        with open(target_file, "w", encoding="utf-8") as f:
            json.dump(final_response, f, indent=2, ensure_ascii=False)
            f.flush()

        return target_file

    def save_metadata(
        self,
        metadata: Mapping[str, Any],
        filename: Optional[str] = None,
    ) -> Path:
        """Persist session attribution metadata and creation response locally.

        Args:
            metadata: Dictionary containing session creation metadata, agent_name,
                model_id, prompt_version, initial_response, etc.
            filename: Optional custom filename (defaults to '{session_id}_meta.json').

        Returns:
            The Path to the saved metadata file.
        """
        if not isinstance(metadata, (dict, Mapping)):
            raise SessionLoggerError(
                f"metadata must be a dictionary, got {type(metadata).__name__}."
            )

        target_file = self.log_dir / (filename or f"{self.session_id}_meta.json")
        with open(target_file, "w", encoding="utf-8") as f:
            json.dump(dict(metadata), f, indent=2, ensure_ascii=False)
            f.flush()

        return target_file

    def verify_log(self) -> VerificationResult:
        """Verify the cryptographic hash-chain integrity of this session's log file."""
        return verify_jsonl_file(self.log_path)
