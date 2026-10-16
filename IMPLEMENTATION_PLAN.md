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
| M2 (Task 02) | Arena API client | Mid-tier coding model; use stronger model for ambiguous parsing/error handling | Create session, get state, send action, capture final response; mocked unit tests pass (18/18 tests pass) | Completed (2026-10-16) |
| M3 (Task 03) | Decision validation and logger | Strong reasoning/coding model | Probability/action/confidence validation passes tests; JSONL schema complete; SHA-256 chain integrated | Completed (2026-10-16) |
| M4 (Task 04) | Visible decision viewer + mock runner | Mid/high coding model | Viewer stays visible; runner loop tested with mocks; no unverified live submission (22+14 = 36 new tests, 116 total) | Completed (2026-10-16) |
| M5 | Verified Snake run | Strong reasoning for failure analysis | Final response matches last log record; hash chain intact; fallback <=10%; score >=600; session qualifies as verified | Not started |
| M6 | 2048 client and prompt | Mid/high coding model | Stage unlock confirmed; 2048 runs logged and independently verified | Locked until M5 success |
| M7 | Three best 2048 runs | Strong reasoning for log/scoring verification | Three qualifying run logs preserved; median points computed per guide; qualifying 512 tile hit if seeking optional Stage 3 | Locked until M6 is ready |
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

1. The approved Laya model/runtime/API interface and credentials have not been confirmed in the project materials available so far.
2. The `step` field interpretation when rejected moves must be logged should be confirmed with the organizer if examples do not make it unambiguous.
3. Optional Stage 3 availability and interface need confirmation.
