# Team ZENITH - Beat the Bot Decision Layer

**Last updated:** 2026-10-16  
**Team/agent name for arena:** `ZENITH`  
**Primary source:** `Track2_PS2_support.pdf` (Participant Guide: Logs, Rules, Stages) supplied by the team.

## 1. Purpose and scope

Build the compliant decision layer for Team ZENITH's PS 02 entry, **"Beat the Bot: Teach Laya to Play"**. The decision layer reads the official TopGameAI Arena game state, asks the specified Laya decision model a structured question, validates the returned decision, submits the chosen move to the official Arena API, and writes an auditable JSONL record for every applied and rejected move.

This project is **not** the game-library product. The existing public Game Library is a separate showcase/portfolio project:

- Existing reference repository: https://github.com/attu1409py/Zen-Proto
- Existing live library: https://zen-proto-five.vercel.app/#/

Keep `Zen-Proto` intact. Recommended competition repository/workspace: `zenith-laya-decision-layer` (create a separate local folder and GitHub repository). This keeps the static game-library code, assets, and licenses separate from the competition bot and its audit logs.

## 2. Competition scope from the supplied participant guide

The participant guide identifies these stages:

1. **Stage 1: Snake** - the starting stage.
2. **Stage 2: 2048** - unlocked by one verified Snake run scoring at least 600 points (ten foods or more per the guide).
3. **Stage 3: Full Doom-style game** - optional; unlocked by one verified 2048 run reaching a tile of 512 or higher.

The exact Stage 3 environment, if pursued, needs organizer confirmation. The guide does not make Hamster Hit, Flappy Bird, Pac-Man, Chess, or Space Shooter part of the required competition stages. Do not spend competition implementation time on those games unless organizers explicitly update the requirements. They may remain in the separate Game Library showcase.

Official game pages:
- Snake: https://topgameai.com/arena/snake
- 2048: https://topgameai.com/arena/2048
- Arena API documentation: https://topgameai.com/arena/docs

The live API reference currently documents `POST https://topgameai.com/api/arena/sessions`, `GET /sessions/:id`, and `POST /sessions/:id/action`, but always verify actual response bodies against the current official docs and live responses before relying on exact schemas. Arena sessions are documented as expiring after 24 hours. Do not assume a session remains available after it ends; save the final response and logs immediately.

## 3. Non-negotiable rules

The supplied guide states that every move must come from a logged Laya decision. The decision layer must not use another AI model, a search algorithm, lookahead planning, or a reinforcement-learning agent to choose moves. A simple rule-based fallback is permitted only as a safety measure (for example, to prevent a clearly illegal move), must be explicitly marked `source: "fallback"`, and may not exceed 10% of a session's moves.

Other prohibited behavior in the guide includes browser extensions, macros, or automation that plays the game outside the visible decision layer. During judging, the decision viewer must remain visible while the bot runs.

**Do not follow earlier generic RL setup suggestions for this competition bot.** Do not install Stable-Baselines3, Gymnasium, or PyTorch for the Arena decision layer unless organizers explicitly change the rules. The permitted Laya runtime/API and its credentials are not yet confirmed in this project context.

## 4. Required per-move log

Write newline-delimited JSON: one JSON object per line in a `.jsonl` file. Log every applied move and every rejected move; do not hide or delete failed/abandoned sessions. Persist the game's final response immediately when a session ends.

Required top-level fields from the guide:

- `session_id`: string returned by the game
- `game`: `snake` or `2048`
- `step`: integer move number, starting at 1 with no gaps, interpreted according to the organizer's move/rejection semantics
- `state_before`: game state exactly as returned before the move
- `action`: submitted move string
- `state_after`: game state exactly as returned after the move
- `result`: `applied` or `rejected`
- `decision`: required decision object
- `timing`: `decide_ms`, `api_ms`, `turn_ms`, integer milliseconds
- `ts`: UTC ISO-8601 timestamp, e.g. `2026-11-07T09:30:12Z`
- `prev_hash`: previous line's hash, or `GENESIS-<session_id>` for the first line
- `hash`: SHA-256 hash defined below

The `decision` object must contain:

```json
{
  "questions": ["<exact question text sent to Laya>"],
  "probabilities": {"up": 0.61, "down": 0.04, "left": 0.22, "right": 0.13},
  "chosen": "up",
  "confidence": 0.61,
  "source": "laya"
}
```

Decision validation rules:
- Probability keys must be exactly `up`, `down`, `left`, `right`.
- Values must be numbers in `[0, 1]` and sum to a value from `0.98` through `1.02` inclusive.
- `chosen` must equal `action`.
- `confidence` must equal `probabilities[chosen]`.
- `source` is `laya`, except an allowed, explicitly flagged safety fallback.
- Fallback moves must be no more than 10% of a session's moves.

Hash rule from the guide: compute SHA-256 over the UTF-8 text `prev_hash + "|" + canonical_json(line_without_hash)`. Canonical JSON uses keys sorted alphabetically, no spaces, UTF-8, and no NaN/Infinity. Validate hash-chain integrity with a separate verification command/test.

**Ambiguity to resolve, do not silently guess:** the guide requires a log line for rejected moves, requires `step` to have no gaps, and says rejected moves do not count as accepted steps. Confirm how `step` is expected to behave for rejected actions from the organizers or test an official example. If useful, record an extra monotonic `log_index` without changing required fields. Never invent a format that risks invalidating the run.

## 5. Game rules and progression

### Snake

- Win by eating 15 foods.
- Cannot reverse direction in a single move.
- Hitting a wall or the snake's own body ends the game.
- Cap: 300 accepted moves; rejected moves do not count as accepted steps.
- Score: `foods_eaten * 60 + 100 if won`, capped at 1000.
- Food positions are random.
- Target one **verified** run of at least 600 points before starting Stage 2, as specified by the guide.

### 2048

- Moves are `up`, `down`, `left`, `right`.
- Equal neighbouring tiles merge once per move; after a board-changing move, a random new tile appears (usually 2, occasionally 4).
- A move that does not change the board is rejected and does not count as an accepted step.
- Cap: 2000 accepted moves.
- Use the official game's current scoring/rules; the participant guide says to follow the game pages if information differs and tell organizers. Do not assume an independently calculated score is authoritative over the final Arena response.
- Judging uses the median points of the team's three best verified runs.
- Optional Stage 3 unlocks after a verified 2048 run reaches tile 512 or higher.

## 6. Required visible decision viewer

During judging, keep a visible decision viewer while the bot runs. At minimum it should show:

- Team/agent name `ZENITH`, selected game, session ID, and session status.
- Latest state (or a useful, compact view of it).
- Exact question sent to Laya.
- Laya probability distribution, chosen action, confidence, and source.
- Move result (applied/rejected) and current score/step count.
- `decide_ms`, `api_ms`, `turn_ms`.
- Fallback count/percentage and log file location/status.
- Final game result and whether the log/hash chain validated.

A clear local terminal/console viewer is acceptable as a first implementation unless organizers specify a different UI requirement. It must remain visible during the judging run.

## 7. Architecture and implementation boundaries

Recommended first implementation: a Python decision-layer CLI/viewer using Python's standard-library HTTP, JSON, time, hashlib, datetime, filesystem utilities, and tests. Keep the code modular enough to change the Laya client without rewriting Arena integration or logging.

Suggested logical components:

- `arena_client`: create sessions, get state, submit actions, capture raw responses.
- `laya_client`: call the organizer-approved Laya model/runtime; never hardcode unverified endpoints or response schemas.
- `decision_validator`: normalize/validate the approved Laya output into the competition's required four-way probabilities and consistent action fields, without fabricating probabilities.
- `runner`: orchestrate state -> Laya -> validation -> action -> result -> log.
- `jsonl_logger`: append-only JSONL writing and SHA-256 chaining.
- `log_verifier`: validate required fields, probability rules, step/attempt semantics, and hash chain.
- `decision_viewer`: keep a live, readable decision/status panel visible during play.
- `tests`: unit tests for schema validation, probability sums, rejection handling, canonical JSON/hashes, and integration tests with safe/mock responses (mocks may test transport only, not pretend to be the real Laya model for competition runs).

A mock Laya adapter may be used for unit tests, but never submit mock decisions as competition results. Every actual competition move must be selected by the real approved Laya model and correctly logged.

## 8. Secrets, dependencies, and repository hygiene

- Use team name `ZENITH`; never use a personal name for leaderboard agent identity.
- Do not commit API keys, tokens, local `.env` files, browser profiles, or personal data.
- Store credentials in local environment variables or a gitignored `.env` file. Provide `.env.example` with placeholder names only after the actual interface is confirmed.
- Do not commit virtual environments, caches, generated logs from unrelated experiments, or large artifacts unnecessarily.
- Keep run logs as required submission artifacts and preserve failed/abandoned attempts.
- Prefer Python standard library for Arena HTTP/log/hash code; add dependencies only for the actual approved Laya runtime or viewer requirement.
- If using a new repository, preserve `Zen-Proto` unchanged. Do not copy custom game implementations into the decision-layer repo as if they were the official competition games.

## 9. Source of truth and references

Priority order:
1. Organizer-supplied `Track2_PS2_support.pdf` for competition-specific stages, restrictions, log schema, and verification requirements.
2. The official game page and official Arena API docs for live request/response formats; the guide explicitly says to follow the game pages if they differ and tell organizers.
3. Confirmed instructions from organizers about the Laya model/runtime and judging environment.
4. This file and `agent.md` for project decisions.

Never guess a request body or infer the Laya endpoint from a similarly named third-party API. Verify actual docs and a real response first.

## 10. Current status (as of 2026-10-16)

- Existing Game Library: public at https://zen-proto-five.vercel.app/#/ and hosted in https://github.com/attu1409py/Zen-Proto.
- The user has **not run** any RL setup commands from earlier planning.
- No PS-specific decision-layer implementation is confirmed as started.
- The participant guide has now narrowed the immediate work to Snake and 2048 on the official Arena, with Laya decisions and auditable logs.
- Next milestone: collect/confirm the Laya runtime/API details, establish a clean decision-layer repo, inspect current API docs/responses, and implement a single verified Snake run.

## 11. Changelog

- **2026-10-16:** Read the supplied Track 2 PS02 participant guide. Replaced the earlier generic multi-game RL plan for this competition with a rules-compliant Laya decision-layer plan. Recommended a separate `zenith-laya-decision-layer` repository to keep the existing Game Library separate. Explicitly scoped competition work to Snake, 2048, and optional Doom-style Stage 3 unless organizers change the requirements.
- **2026-10-16:** Added required JSONL schema, decision constraints, timing fields, SHA-256 hash chain, fallback cap, stage unlock conditions, visible decision viewer, and no-secrets guidance.
