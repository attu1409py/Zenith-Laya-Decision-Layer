"""Command-line interface and end-to-end session runner for Team ZENITH.

This module provides the main entry point to run game sessions in either:
1. Dry-run mode (default): Uses a simulated local Arena adapter and mock or
   local Laya model. Absolutely zero network calls are made.
2. Live mode: Requires explicit `--live` and affirmative interactive
   confirmation before creating any session on the official TopGameAI Arena.

All game sessions enforce:
- Team name 'ZENITH'
- Pure model decisions (no RL policy, no lookahead planner, no strategic fallback)
- Strict probability validation ([0, 1], sum in [0.98, 1.02], confidence = probabilities[chosen])
- Complete JSONL logging with SHA-256 hash chaining
- Immediate final response persistence
- Live terminal decision viewer
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, TextIO

from zenith.arena_client import ArenaClient, ArenaError
from zenith.decision_validator import VALID_DIRECTIONS
from zenith.decision_viewer import DecisionViewer
from zenith.game2048_simulator import Deterministic2048Simulator
from zenith.laya_adapter import APPROVED_MODEL_ID, LayaAdapter
from zenith.runner import ArenaAdapter, DecideFn, SessionResult, SessionRunner
from zenith.session_logger import SessionLogger

Mock2048Arena = Deterministic2048Simulator


TEAM_NAME: str = "ZENITH"
DEFAULT_GAME: str = "snake"
DEFAULT_LOG_DIR: str = "logs"
DEFAULT_TIMEOUT: float = 10.0


# ── Simulated Arena Adapter for Dry-Run ────────────────────────────────


class MockSnakeArena:
    """Deterministic simulated Arena adapter for Snake dry runs.

    Implements the ArenaAdapter protocol without making any network calls.
    Simulates snake movement on a 12x12 grid, food consumption, and termination.
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        *,
        width: int = 12,
        height: int = 12,
        max_moves: int = 10,
    ) -> None:
        self._session_id = session_id or f"mock-snake-{int(time.time() * 1000)}"
        self._width = width
        self._height = height
        self._max_moves = max_moves
        self._move_count = 0
        self._score = 0
        self._done = False
        self._won: Optional[bool] = None

        # Initial snake state: 3 segments moving up
        self._snake: List[Dict[str, int]] = [
            {"x": 6, "y": 6},
            {"x": 6, "y": 7},
            {"x": 6, "y": 8},
        ]
        self._food: Dict[str, int] = {"x": 6, "y": 3}
        self._direction = "up"
        self._food_eaten = 0

    @property
    def session_id(self) -> str:
        return self._session_id

    def _build_state(self) -> Dict[str, Any]:
        return {
            "session_id": self._session_id,
            "game": "snake",
            "agent_name": TEAM_NAME,
            "state": {
                "width": self._width,
                "height": self._height,
                "snake": [dict(c) for c in self._snake],
                "food": dict(self._food),
                "direction": self._direction,
                "foodEaten": self._food_eaten,
            },
            "done": self._done,
            "score": self._score,
            "won": self._won,
        }

    def create_session(self, game: str, agent_name: str) -> Dict[str, Any]:
        """Create mock session."""
        return self._build_state()

    def get_session(self, session_id: str) -> Dict[str, Any]:
        """Retrieve current mock session."""
        return self._build_state()

    def submit_action(self, session_id: str, action: str) -> Dict[str, Any]:
        """Advance the mock snake game state by one action."""
        if self._done:
            resp = self._build_state()
            resp["result"] = "applied"
            return resp

        self._move_count += 1
        action_clean = str(action).strip().lower()
        if action_clean not in VALID_DIRECTIONS:
            # Reject invalid action
            resp = self._build_state()
            resp["result"] = "rejected"
            return resp

        self._direction = action_clean
        head = self._snake[0]
        dx, dy = 0, 0
        if action_clean == "up":
            dy = -1
        elif action_clean == "down":
            dy = 1
        elif action_clean == "left":
            dx = -1
        elif action_clean == "right":
            dx = 1

        new_head = {"x": head["x"] + dx, "y": head["y"] + dy}

        # Check wall collision
        if (
            new_head["x"] < 0
            or new_head["x"] >= self._width
            or new_head["y"] < 0
            or new_head["y"] >= self._height
        ):
            self._done = True
            self._won = False
            resp = self._build_state()
            resp["result"] = "applied"
            return resp

        # Check self collision
        for seg in self._snake[:-1]:
            if seg["x"] == new_head["x"] and seg["y"] == new_head["y"]:
                self._done = True
                self._won = False
                resp = self._build_state()
                resp["result"] = "applied"
                return resp

        # Move snake
        self._snake.insert(0, new_head)
        if new_head["x"] == self._food["x"] and new_head["y"] == self._food["y"]:
            # Food eaten
            self._food_eaten += 1
            self._score += 100
            # Relocate food deterministically
            self._food = {
                "x": (self._food["x"] + 3) % self._width,
                "y": (self._food["y"] + 3) % self._height,
            }
        else:
            self._snake.pop()

        if self._move_count >= self._max_moves:
            self._done = True
            self._won = self._score > 0

        resp = self._build_state()
        resp["result"] = "applied"
        return resp


# ── Synthetic Mock Decision Function ──────────────────────────────────


def make_mock_decide_fn() -> DecideFn:
    """Create a synthetic decision function for fast testing without GPU weights."""

    def _mock_decide(game: str, state: Mapping[str, Any]) -> Dict[str, Any]:
        game_clean = str(game).strip().lower()
        if game_clean == "2048":
            q_text = "Which direction (up, down, left, right) should you slide the tiles next to merge numbers?"
            grid = state.get("grid")
            chosen = "left"
            if isinstance(grid, list):
                from zenith.game2048_simulator import simulate_move
                for d in ("left", "down", "right", "up"):
                    _, _, changed = simulate_move(grid, d)
                    if changed:
                        chosen = d
                        break
        else:
            q_text = (
                f"Given {game} state with head at {state.get('snake', [{}])[0] if isinstance(state.get('snake'), list) and state.get('snake') else 'unknown'}, "
                "which direction should the snake move?"
            )
            direction = str(state.get("direction", "up")).lower()
            chosen = direction if direction in VALID_DIRECTIONS else "up"

        probs = {d: 0.05 for d in VALID_DIRECTIONS}
        probs[chosen] = 0.85
        return {
            "questions": [q_text],
            "probabilities": probs,
            "chosen": chosen,
            "confidence": probs[chosen],
            "source": "laya",
        }

    return _mock_decide




# ── Live Confirmation Safeguard ───────────────────────────────────────


def confirm_live_session(
    game: str,
    agent_name: str,
    base_url: str,
    model_name: str,
    *,
    input_fn: Callable[[str], str] = input,
    out: TextIO = sys.stdout,
) -> bool:
    """Prompt the operator for explicit confirmation before creating a live Arena session.

    Args:
        game: Game identifier ('snake').
        agent_name: Public agent name ('ZENITH').
        base_url: Target Arena API base URL.
        model_name: Checkpoint identifier.
        input_fn: Function to read input (defaults to builtin input).
        out: Stream to write prompt text.

    Returns:
        True if the user confirmed by typing exactly 'YES', False otherwise.
    """
    banner = (
        "\n"
        "======================================================================\n"
        "                   LIVE COMPETITION RUN CONFIRMATION                  \n"
        "======================================================================\n"
        f" Team / Agent Name: {agent_name}\n"
        f" Game:              {game}\n"
        f" Arena Endpoint:    {base_url}\n"
        f" Model Checkpoint:  {model_name}\n"
        " Mode:              LIVE (Real network calls to TopGameAI Arena)\n"
        "======================================================================\n"
        " WARNING: This operation creates an official, judged Arena session.\n"
        " Every move will be submitted to the competition servers.\n"
        " Type 'YES' to proceed, or anything else to abort: "
    )
    out.write(banner)
    out.flush()

    try:
        user_input = input_fn("").strip()
    except (EOFError, OSError):
        out.write("\n[ABORTED] Standard input is unavailable. Cannot confirm live session.\n")
        out.flush()
        return False

    if user_input != "YES":
        out.write(f"\n[ABORTED] Confirmation declined (received '{user_input}'). No session created.\n")
        out.flush()
        return False

    out.write("\n[CONFIRMED] Live session creation authorized by operator.\n\n")
    out.flush()
    return True


# ── Argument Parser ────────────────────────────────────────────────────


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct argument parser with helpful documentation."""
    parser = argparse.ArgumentParser(
        prog="zenith",
        description="Team ZENITH TopGameAI Arena Competition Decision Runner",
    )
    parser.add_argument(
        "--game",
        default=DEFAULT_GAME,
        choices=["snake", "2048"],
        help=f"Game to play (default: {DEFAULT_GAME}). Note: 2048 unlocks after verified Snake run.",
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Execute simulated dry run without contacting Arena API (default mode).",
    )
    mode_group.add_argument(
        "--live",
        action="store_true",
        help="Execute live session against TopGameAI Arena (requires operator confirmation).",
    )

    parser.add_argument(
        "--mock-model",
        action="store_true",
        help="Use synthetic mock decisions instead of loading local Laya GPU model.",
    )
    parser.add_argument(
        "--log-dir",
        default=DEFAULT_LOG_DIR,
        help=f"Directory to save session JSONL logs and final responses (default: '{DEFAULT_LOG_DIR}').",
    )
    parser.add_argument(
        "--agent-name",
        default=TEAM_NAME,
        help=f"Agent / team name for the Arena session (default: '{TEAM_NAME}').",
    )
    parser.add_argument(
        "--base-url",
        default=ArenaClient.DEFAULT_BASE_URL,
        help=f"Base URL for Arena API (default: '{ArenaClient.DEFAULT_BASE_URL}').",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"Arena HTTP request timeout in seconds (default: {DEFAULT_TIMEOUT}).",
    )
    parser.add_argument(
        "--max-moves",
        type=int,
        default=None,
        help="Optional maximum moves to execute in dry-run mode.",
    )
    parser.add_argument(
        "--max-consecutive-errors",
        type=int,
        default=5,
        help="Stop after this many consecutive errors (default: 5).",
    )
    parser.add_argument(
        "--prompt-version",
        default="v1",
        choices=["v1", "v2", "v3"],
        help="Prompt strategy version ('v1' baseline, 'v2' revised, 'v3' strategic; default: 'v1').",
    )
    return parser


# ── CLI Runner Logic ───────────────────────────────────────────────────


def run_cli(
    argv: Optional[Sequence[str]] = None,
    *,
    input_fn: Callable[[str], str] = input,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Execute the CLI with specified arguments and streams.

    Returns:
        0 on successful session completion.
        1 on session error during execution.
        2 on validation / confirmation abort before session start.
        3 on post-run hash-chain verification failure.
    """
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    is_live = bool(args.live)
    game = args.game.strip().lower()

    if game not in ("snake", "2048"):
        stderr.write(
            f"Error: Game '{game}' is not supported. "
            "Valid choices are: 'snake', '2048'.\n"
        )
        return 2

    # ── Step 1: Initialize Decision Provider ──
    if args.mock_model:
        model_display = "mock-synthetic-model"
        decide_fn = make_mock_decide_fn()
    else:
        model_display = APPROVED_MODEL_ID
        stdout.write(f"Initializing Laya decision adapter with checkpoint '{APPROVED_MODEL_ID}'...\n")
        stdout.flush()
        try:
            adapter_kwargs = {"model_id": APPROVED_MODEL_ID}
            if hasattr(args, "prompt_version") and args.prompt_version != "v1":
                adapter_kwargs["prompt_version"] = args.prompt_version
            adapter = LayaAdapter(**adapter_kwargs)
            decide_fn = adapter.decide
        except Exception as exc:
            stderr.write(f"Failed to initialize Laya adapter: {exc}\n")
            return 1

    # ── Step 2: Configure Arena Adapter ──
    arena: ArenaAdapter
    if is_live:
        confirmed = confirm_live_session(
            game=game,
            agent_name=args.agent_name,
            base_url=args.base_url,
            model_name=model_display,
            input_fn=input_fn,
            out=stdout,
        )
        if not confirmed:
            return 2

        try:
            client = ArenaClient(
                base_url=args.base_url,
                timeout=args.timeout,
                default_agent_name=args.agent_name,
            )
            stdout.write(f"Creating live Arena session on {args.base_url} for team '{args.agent_name}'...\n")
            stdout.flush()
            session_resp = client.create_session(game=game, agent_name=args.agent_name)
            arena = client
        except ArenaError as exc:
            stderr.write(f"Arena session creation failed: {exc}\n")
            return 1
        except Exception as exc:
            stderr.write(f"Unexpected error during session creation: {exc}\n")
            return 1
    else:
        # Dry-run mode: explicitly simulated Arena adapter
        max_moves = args.max_moves if args.max_moves is not None else 10
        if game == "snake":
            mock_arena = MockSnakeArena(max_moves=max_moves)
        else:
            mock_arena = Deterministic2048Simulator(max_moves=max_moves, session_id_prefix="mock-2048")
        session_resp = mock_arena.create_session(game=game, agent_name=args.agent_name)
        arena = mock_arena


    session_id = str(session_resp.get("session_id", "")).strip()
    if not session_id:
        stderr.write("Arena response missing valid 'session_id'. Aborting.\n")
        return 1

    # ── Step 3: Configure Logger, Viewer, and Runner ──
    log_dir = Path(args.log_dir)
    logger = SessionLogger(session_id=session_id, game=game, log_dir=log_dir)

    # Preserve session creation response and attribution metadata locally
    try:
        logger.save_metadata({
            "session_id": session_id,
            "game": game,
            "agent_name": args.agent_name,
            "model_id": model_display,
            "prompt_version": getattr(args, "prompt_version", "v1"),
            "mode": "live" if is_live else "dry_run",
            "initial_response": session_resp,
        })
    except Exception:
        pass

    viewer = DecisionViewer(
        game=game,
        session_id=session_id,
        mock_mode=(not is_live),
        log_path=str(logger.log_path),
        out=stdout,
    )

    runner = SessionRunner(
        arena=arena,
        decide_fn=decide_fn,
        logger=logger,
        viewer=viewer,
        max_consecutive_errors=args.max_consecutive_errors,
    )

    # ── Step 4: Execute Session Loop ──
    stdout.write(f"Starting session loop for {session_id}...\n")
    stdout.flush()
    result: SessionResult = runner.run(initial_session_data=session_resp)

    # ── Step 5: Evaluate Result and Exit Code ──
    if result.error:
        stderr.write(f"\n[SESSION ERROR] {result.error}\n")
        return 1

    if result.hash_chain_valid is False:
        stderr.write("\n[CRITICAL AUDIT FAILURE] Log file hash chain verification failed!\n")
        return 3

    # Display clear summary banner
    stdout.write(
        "\n"
        "======================================================================\n"
        "                        ZENITH SESSION COMPLETE                       \n"
        "======================================================================\n"
        f" Session ID:           {result.session_id}\n"
        f" Game:                 {result.game}\n"
        f" Mode:                 {'LIVE (Official Arena)' if is_live else 'DRY-RUN (Simulated Arena)'}\n"
        f" Model / Identity:     {model_display}\n"
        f" Final Score:          {result.final_score}\n"
        f" Result Status:        {'WON' if result.won else ('LOST' if result.won is False else 'COMPLETE')}\n"
        f" Total Moves:          {result.total_moves}\n"
        f" Applied Moves:        {result.applied_moves}\n"
        f" Rejected Moves:       {result.rejected_moves}\n"
        f" Fallback Moves:       {result.fallback_moves}\n"
        f" Session Duration:     {result.total_time_ms} ms\n"
        f" Output JSONL Log:     {result.log_path}\n"
        f" SHA-256 Hash Chain:   {'VERIFIED VALID' if result.hash_chain_valid else 'UNKNOWN'}\n"
        "======================================================================\n"
    )
    stdout.flush()
    return 0


def main() -> int:
    """Main program entry point."""
    return run_cli(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
