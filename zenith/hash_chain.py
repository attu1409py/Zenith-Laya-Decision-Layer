"""Canonical JSON serialization and SHA-256 hash-chain audit engine.

This module implements the SHA-256 hash-chain specification mandated by Section 3.3
of the competition participant guide (Track2_PS2_support.pdf) and CONTEXT.md.

Audit rules:
1. Every record contains 'prev_hash' and 'hash'.
2. The first record uses 'GENESIS-<session_id>' as 'prev_hash'.
3. The hash input is: prev_hash + "|" + canonical_json(record_without_hash)
4. Canonical JSON uses keys sorted alphabetically at all levels, compact separators
   without whitespace (',' and ':'), UTF-8 encoding, and strictly no NaN or Infinity.
5. Each subsequent record must use the immediately preceding record's calculated hash
   as its 'prev_hash'.
6. Verification detects modified fields, broken links, missing hashes, non-finite
   numbers, and malformed JSONL records.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Union


@dataclass(frozen=True)
class VerificationResult:
    """Outcome of verifying a sequence or file of JSONL hash-chain records."""

    is_valid: bool
    record_count: int = 0
    error_message: Optional[str] = None
    error_line_index: Optional[int] = None  # 1-indexed line number where failure occurred
    session_id: Optional[str] = None


def canonical_json(obj: Any) -> str:
    """Serialize a Python object to canonical JSON string.

    Specifications:
    - Keys sorted alphabetically at all dictionary nesting levels (`sort_keys=True`).
    - Compact separators without whitespace (`separators=(',', ':')`).
    - Preserves non-ASCII characters (`ensure_ascii=False`) for UTF-8 compatibility.
    - Explicitly forbids non-compliant floats such as NaN and +/- Infinity (`allow_nan=False`).

    Raises:
        ValueError: If data contains NaN, Infinity, or cannot be serialized.
        TypeError: If an unsupported object type is encountered.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def get_genesis_prev_hash(session_id: str) -> str:
    """Compute the initial prev_hash string for line 1 of a session."""
    if not session_id or not isinstance(session_id, str):
        raise ValueError("session_id must be a non-empty string.")
    return f"GENESIS-{session_id}"


def calculate_record_hash(prev_hash: str, record_without_hash: Mapping[str, Any]) -> str:
    """Calculate the SHA-256 hash of a record given its prev_hash and payload.

    Hash input string:
        prev_hash + "|" + canonical_json(record_without_hash)

    Args:
        prev_hash: The link string ('GENESIS-<session_id>' or previous line's hash).
        record_without_hash: The dictionary of record fields excluding 'hash'.

    Returns:
        Hex-encoded SHA-256 digest string (64 characters lowercase).

    Raises:
        ValueError: If 'hash' key is present in record_without_hash, or non-finite numbers exist.
    """
    if "hash" in record_without_hash:
        raise ValueError(
            "record_without_hash must not contain the 'hash' key. "
            "Pass the record stripped of its 'hash' field."
        )
    if not isinstance(prev_hash, str) or not prev_hash:
        raise ValueError("prev_hash must be a non-empty string.")

    canonical_payload = canonical_json(record_without_hash)
    hash_input = f"{prev_hash}|{canonical_payload}"
    return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()


def create_chained_record(
    record_data: Mapping[str, Any],
    prev_hash: str,
) -> Dict[str, Any]:
    """Create a new dictionary containing all fields, prev_hash, and the computed hash.

    Args:
        record_data: Mapping containing the record's fields (excluding 'hash').
        prev_hash: The previous record's hash, or 'GENESIS-<session_id>' for line 1.

    Returns:
        A new Dict containing all input fields, 'prev_hash', and 'hash'.
    """
    new_record = {k: v for k, v in record_data.items() if k != "hash"}
    new_record["prev_hash"] = prev_hash
    computed_hash = calculate_record_hash(prev_hash, new_record)
    new_record["hash"] = computed_hash
    return new_record


def serialize_record_to_jsonl(record: Mapping[str, Any]) -> str:
    """Serialize a complete chained record (including prev_hash and hash) to a JSON string.

    Does not append a trailing newline.
    """
    if "prev_hash" not in record or "hash" not in record:
        raise ValueError("Record must contain both 'prev_hash' and 'hash' before serialization.")
    return canonical_json(record)


def read_jsonl_records(lines: Iterable[str]) -> List[Dict[str, Any]]:
    """Parse JSONL lines into a list of record dictionaries.

    Raises:
        ValueError: On empty lines between records, non-object JSON, or malformed JSON.
    """
    records: List[Dict[str, Any]] = []
    line_number = 0

    for raw_line in lines:
        line_number += 1
        stripped = raw_line.rstrip("\r\n")

        # Allow empty line only if it's whitespace-only at EOF after records, but flag blank lines in between
        if not stripped.strip():
            raise ValueError(f"Line {line_number}: Blank or empty line encountered in JSONL.")

        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Line {line_number}: Malformed JSON: {exc.msg} at pos {exc.pos}."
            ) from exc

        if not isinstance(parsed, dict):
            raise ValueError(
                f"Line {line_number}: Record must be a JSON object, got {type(parsed).__name__}."
            )

        records.append(parsed)

    return records


def verify_records(records: Sequence[Mapping[str, Any]]) -> VerificationResult:
    """Verify an in-memory sequence of records for strict hash-chain integrity.

    Checks performed:
    1. Sequence is non-empty.
    2. Every record has 'prev_hash' and 'hash' (strings).
    3. Line 1 has 'prev_hash' == 'GENESIS-<session_id>'.
    4. Line N has 'prev_hash' == record[N-1]['hash'].
    5. 'session_id' is consistent across all records.
    6. Recomputed SHA-256 hash matches the recorded 'hash' exactly.
    7. All values conform to canonical JSON requirements (no NaN/Infinity).

    Note:
        This verifies the cryptographic hash chain only. It does not validate
        the game-specific schema (action choices, probability sums, timing fields),
        which is handled by dedicated decision validation.
    """
    if not records:
        return VerificationResult(
            is_valid=False,
            record_count=0,
            error_message="Log contains no records.",
            error_line_index=None,
            session_id=None,
        )

    expected_prev_hash: Optional[str] = None
    session_id: Optional[str] = None

    for idx, record in enumerate(records):
        line_number = idx + 1

        if not isinstance(record, dict):
            return VerificationResult(
                is_valid=False,
                record_count=idx,
                error_message=f"Line {line_number}: Record must be a JSON object.",
                error_line_index=line_number,
                session_id=session_id,
            )

        # Check for session_id
        current_session_id = record.get("session_id")
        if not current_session_id or not isinstance(current_session_id, str):
            return VerificationResult(
                is_valid=False,
                record_count=idx,
                error_message=f"Line {line_number}: Missing or non-string 'session_id'.",
                error_line_index=line_number,
                session_id=session_id,
            )

        if idx == 0:
            session_id = current_session_id
            expected_prev_hash = get_genesis_prev_hash(session_id)
        elif current_session_id != session_id:
            return VerificationResult(
                is_valid=False,
                record_count=idx,
                error_message=(
                    f"Line {line_number}: session_id changed from '{session_id}' "
                    f"to '{current_session_id}'."
                ),
                error_line_index=line_number,
                session_id=session_id,
            )

        # Verify prev_hash presence and link integrity
        prev_hash = record.get("prev_hash")
        if not prev_hash or not isinstance(prev_hash, str):
            return VerificationResult(
                is_valid=False,
                record_count=idx,
                error_message=f"Line {line_number}: Missing or non-string 'prev_hash'.",
                error_line_index=line_number,
                session_id=session_id,
            )

        if prev_hash != expected_prev_hash:
            return VerificationResult(
                is_valid=False,
                record_count=idx,
                error_message=(
                    f"Line {line_number}: Broken hash chain. prev_hash was '{prev_hash}', "
                    f"expected '{expected_prev_hash}'."
                ),
                error_line_index=line_number,
                session_id=session_id,
            )

        # Verify recorded hash presence
        recorded_hash = record.get("hash")
        if not recorded_hash or not isinstance(recorded_hash, str):
            return VerificationResult(
                is_valid=False,
                record_count=idx,
                error_message=f"Line {line_number}: Missing or non-string 'hash'.",
                error_line_index=line_number,
                session_id=session_id,
            )

        # Recompute hash
        record_without_hash = {k: v for k, v in record.items() if k != "hash"}
        try:
            calculated_hash = calculate_record_hash(prev_hash, record_without_hash)
        except ValueError as exc:
            return VerificationResult(
                is_valid=False,
                record_count=idx,
                error_message=f"Line {line_number}: Canonical serialization failed: {exc}",
                error_line_index=line_number,
                session_id=session_id,
            )

        if calculated_hash != recorded_hash:
            return VerificationResult(
                is_valid=False,
                record_count=idx,
                error_message=(
                    f"Line {line_number}: Hash mismatch (tampered record or invalid hash). "
                    f"Recorded: '{recorded_hash}', Calculated: '{calculated_hash}'."
                ),
                error_line_index=line_number,
                session_id=session_id,
            )

        # Advance chain
        expected_prev_hash = recorded_hash

    return VerificationResult(
        is_valid=True,
        record_count=len(records),
        error_message=None,
        error_line_index=None,
        session_id=session_id,
    )


def verify_jsonl_lines(lines: Iterable[str]) -> VerificationResult:
    """Verify an iterable of JSONL line strings.

    Catches parsing and decoding errors and returns a VerificationResult.
    """
    try:
        # Filter trailing empty strings (common when splitting on \n)
        raw_list = list(lines)
        while raw_list and not raw_list[-1].strip():
            raw_list.pop()

        if not raw_list:
            return VerificationResult(
                is_valid=False,
                record_count=0,
                error_message="Log contains no records.",
                error_line_index=None,
                session_id=None,
            )

        records = read_jsonl_records(raw_list)
    except ValueError as exc:
        # Extract line number if present
        error_str = str(exc)
        line_idx: Optional[int] = None
        if error_str.startswith("Line "):
            try:
                line_idx = int(error_str.split(":")[0].replace("Line ", "").strip())
            except ValueError:
                line_idx = None
        return VerificationResult(
            is_valid=False,
            record_count=0,
            error_message=error_str,
            error_line_index=line_idx,
            session_id=None,
        )

    return verify_records(records)


def verify_jsonl_file(file_path: Union[str, Path]) -> VerificationResult:
    """Read a JSONL file from disk and verify its SHA-256 hash chain."""
    path = Path(file_path)
    if not path.is_file():
        return VerificationResult(
            is_valid=False,
            record_count=0,
            error_message=f"File does not exist: {path}",
            error_line_index=None,
            session_id=None,
        )

    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as exc:
        return VerificationResult(
            is_valid=False,
            record_count=0,
            error_message=f"Failed to read file: {exc}",
            error_line_index=None,
            session_id=None,
        )

    return verify_jsonl_lines(lines)
