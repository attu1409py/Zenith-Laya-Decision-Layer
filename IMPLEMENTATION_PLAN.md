# Team ZENITH - Implementation Plan and Antigravity Input Checklist

**Plan date:** 2026-10-16  
**Current status:** Planning only; no competition-bot setup commands have been run.

## Decision: use a separate repository

Recommended repository: `zenith-laya-decision-layer`.

Keep https://github.com/attu1409py/Zen-Proto unchanged as the original Game Library showcase. The participant guide says the official games run on TopGameAI Arena and that the team builds a decision layer rather than its own games. A separate repository avoids mixing static frontend assets and custom games with competition sessions, model integration, and required audit logs.

The new repo should not copy the custom game engines just to satisfy the competition. It can link back to the existing Game Library in its README as a separate showcase.

## What to give Antigravity before implementation

### Must provide before Milestone 0 can be completed

- [x] This starter pack: `CONTEXT.md`, `agent.md`/`AGENT.md`, `PROJECT_STATE.md`, and this file. (Verified present in workspace)
- [x] The original participant guide PDF, saved locally in the workspace as `docs/Track2_PS2_support.pdf`. (Verified present and read)
- [x] Workspace path confirmed: `c:\Users\Atharva\OneDrive\Desktop\Zenith-Decision-Layer` (dedicated, separate from `Zen-Proto`).
- [ ] Confirmed Laya integration instructions from organizers: official package/runtime or API endpoint, model/checkpoint identifier, request/response schema, auth method, quota/rate limits, and any required launch command. If the organizers gave a zip, repository, notebook, or README, provide it too.
- [ ] Team's deadline and any judging-run rules beyond the PDF.

### Useful references to provide

- Snake: https://topgameai.com/arena/snake
- 2048: https://topgameai.com/arena/2048
- Arena API docs: https://topgameai.com/arena/docs
- Existing project reference only: https://github.com/attu1409py/Zen-Proto
- Existing live showcase only: https://zen-proto-five.vercel.app/#/
- Team/leaderboard agent name: `ZENITH`.
- Environment notes: Windows, NVIDIA GPU, 16 GB RAM. Do not start an RL stack; these details are not needed to choose competition moves under the supplied rules.

### Credentials and secret handling

- Never place real API keys or tokens in a prompt, markdown file, Git commit, or log.
- Give Antigravity the **name of the environment variable** and the interface docs; add the actual secret locally to an ignored `.env` or environment variable only after the actual interface is confirmed.
- If no approved Laya credentials/runtime have been provided, stop and ask for them rather than guessing or using a third-party service with a similar name.

## Milestone chart

| ID | Workstream | Model selection guidance in Antigravity | Acceptance criteria | Status |
|---|---|---|---|---|
| M0 | Repository and source preflight | Fast/low-cost model is sufficient | Dedicated repo confirmed; guide and docs read; Laya interface gaps identified; `PROJECT_STATE.md` updated | Completed (2026-10-16) |
| Task 01 | Scaffolding & SHA-256 audit engine | Standard model | Git repo initialized, .gitignore configured, canonical JSON & SHA-256 hash-chain verified (24/24 tests pass) | Completed (2026-10-16) |
| M1 (Task 05A) | Confirm & install Laya runtime | Strong reasoning model if schema/docs are ambiguous | Official package laya==0.4.8 & convaiinnovations/laya loaded on GPU; single forward pass verified (334 ms); contract valid | Completed (2026-10-16) |
| Task 05B | Laya decision adapter integration | Strong coding model | LayaAdapter implemented; Snake state parsing; 4-way choice question; contract validation; runner integration (24 new tests, 140 total) | Completed (2026-10-16) |
| Task 05C | Laya SDK schema verification | Strong coding model | Verified instructions/criteria schema in installed laya==0.4.8; synthetic GPU inference validated; regression test added (141 total tests) | Completed (2026-10-16) |
| M2 (Task 02) | Arena API client | Mid-tier coding model; use stronger model for ambiguous parsing/error handling | Create session, get state, send action, capture final response; mocked unit tests pass (18/18 tests pass) | Completed (2026-10-16) |
| M3 (Task 03) | Decision validation and logger | Strong reasoning/coding model | Probability/action/confidence validation passes tests; JSONL schema complete; SHA-256 chain integrated | Completed (2026-10-16) |
| M4 (Task 04) | Visible decision viewer + mock runner | Mid/high coding model | Viewer stays visible; runner loop tested with mocks; no unverified live submission (22+14 = 36 new tests, 116 total) | Completed (2026-10-16) |
| Task 06 | Executable CLI & end-to-end runner | Mid/high coding model | zenith/main.py, run_session.py, MockSnakeArena, live confirmation guard, 15 tests in test_cli.py (156 total tests) | Completed (2026-10-16) |
| Task 06B | Local Laya Snake benchmark & prompt optimization | Strong coding model | DeterministicSnakeSimulator, benchmark suite, v2 prompt/criteria optimization (36x score improvement, 100% runs >= 600 pts, 179 total tests pass) | Completed (2026-10-17) |
| Task 07A | Run history aggregator & attribution audit | Strong coding/reasoning model | Consolidated run_history.jsonl, CSV, benchmark_report.md; verified 12/12 hash chains; audited official run f240cb86...; leaderboard FIFO limit 20 findings; 18 new tests (197 total tests pass) | Completed (2026-10-17) |
| M5 | Verified Snake run | Strong reasoning for failure analysis | Final response matches last log record; hash chain intact; fallback <=10%; score >=600; session qualifies as verified | Completed (f240cb86: 1000 pts, won, 152 steps, hash chain valid) |
| M6 | 2048 adapter, simulator & qualification benchmark | Mid/high coding model | Verified official contract; Deterministic2048Simulator; 2048 Laya adapter (v1 & v2 criteria); local GPU benchmark (5 seeds, max tile 256, 1,702 avg merge score, 0 rejections); aggregator updated (23 runs verified); 228/228 tests pass | Completed (2026-10-17) |
| Task M6B | 2048 Strategic Prompt Optimization (v3) | Strong coding/reasoning model | v2 trace analysis; v3 prompt & criteria with corner-anchor preservation; standard 5 seeds (Seed 7 reaches 512, 80% >= 256); holdout 3 seeds (Seed 99 reaches 512, 5812 pts); 4 new tests (232 total pass); 31/31 hash chains valid | Completed (2026-10-17) |
| Task M6C | 2048 v3 Benchmark Integrity Audit | Strong coding/reasoning model | Reconciled seed 13 (raw log 18 rejections; removed hardcoded 10); continuous log multi-segment reconciliation; generate_2048_benchmark_from_logs; regenerated summaries; 233/233 tests pass | Completed (2026-10-17) |
| Task M6D | Final Benchmark Segment Integrity Check | Strong coding/reasoning model | Disentangled whole source-log metrics from evaluated game segments; split_records_into_segments; explicit record_scope; benchmark_2048_v3.json tied to evaluated segment; 4 new regression tests (237/237 tests pass); 31/31 hash chains valid | Completed (2026-10-17) |
| M7 | Controlled Live 2048 Qualifying Run(s) | Strong reasoning for log/scoring verification | Three qualifying run logs preserved; median points computed per guide; qualifying 512 tile hit if seeking optional Stage 3 | Next Milestone (Ready for operator review & approval) |

| M8 | Optional Doom-style stage | Decide only after organizer confirms environment | Exact official environment/interface known; earlier run evidence retained | Optional / unknown |

## Task-by-task model budget policy

The user selects the Antigravity model in the UI before each task; a prompt cannot be assumed to change that selector automatically.

- Use a fast/low-cost model for reading files, inventory, documentation updates, simple test scaffolding, and straightforward text/code edits.
- Use the strongest available reasoning/coding model for: Laya schema interpretation, probability normalization/validation, fallback semantics, canonical JSON and hash chaining, rejection/step semantics, and debugging a failed verified run.
- Make one narrow request per task. Have the agent report the intended change and tests before doing consequential operations.
- Do not submit public Arena moves, spend paid model credits, or start a long run without the user approving the run configuration.

## Run and submission discipline

- Use `ZENITH` as the public agent name.
- Keep all run logs, including rejected and abandoned attempts. Never remove a failed run to improve the record.
- Save the final API response immediately when a game ends.
- Never mark a run verified until every requirement in `CONTEXT.md` is checked.
- Migrate no code from the Game Library unless it is genuinely reusable and does not violate the requirement to use the official Arena games.

## Main unresolved blockers

1. **RESOLVED (Task 05A/05B):** Approved Laya runtime confirmed as local `laya==0.4.8` with `convaiinnovations/laya` running on CUDA.
2. The `step` field interpretation when rejected moves must be logged should be confirmed with the organizer if examples do not make it unambiguous.
3. Optional Stage 3 availability and interface need confirmation.

