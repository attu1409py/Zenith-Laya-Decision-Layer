# Team ZENITH - Run History and Benchmark Report

**Generated:** 2026-10-16 21:05:02 UTC  
**Team / Agent Name:** `ZENITH`  
**Total Discovered Runs:** 31 (`1` live arena, `28` local simulator, `2` mock)

---

## 1. Executive Summary & Attribution Audit

### Official Live Arena Session
- **Session ID:** `f240cb86-0d3d-4445-9708-79989ecff36e`
- **Game:** `snake` | **Result:** Score **1000**, Won: **True** in **152** accepted moves
- **Food Eaten:** 15 / 15 target foods (100% completed)
- **Fallback Usage:** 0 fallback moves (0.0% of accepted moves; strictly <= 10% limit)
- **Audit Hash Chain:** `VERIFIED VALID (100% SHA-256 intact)`
- **Run Timestamp:** `2026-10-16T19:04:32Z`
- **Audit Log Path:** [`logs/f240cb86-0d3d-4445-9708-79989ecff36e.jsonl`](logs/f240cb86-0d3d-4445-9708-79989ecff36e.jsonl)

### Leaderboard Attribution Audit Findings

1. **Client POST Body Verification:**
   - The CLI `--agent-name` parameter defaults to `ZENITH`.
   - `ArenaClient.create_session(game='snake', agent_name='ZENITH')` strictly serializes `{"game": "snake", "agent_name": "ZENITH"}` into the HTTP POST body.
   - Regression tests verify that `agent_name` is transmitted without modification.

2. **Leaderboard Endpoint Behavior (`GET /leaderboard/snake`):**
   - A read-only query to `https://topgameai.com/api/arena/leaderboard/snake` returned exactly 20 entries.
   - All 20 entries have `score: 1000` and are strictly ordered chronologically ascending by `timestamp` (`ORDER BY timestamp ASC LIMIT 20`).
   - The rank 20 cutoff timestamp is `1792161489372`.
   - ZENITH's official run `f240cb86-0d3d-4445-9708-79989ecff36e` completed at timestamp `1792177472000` (~4.4 hours later).
   - Consequently, ZENITH's completed run is positioned outside the server-side 20-row response window.

3. **Server Session Echo Limitation:**
   - The TopGameAI Arena `GET /sessions/:id` and action endpoints do not echo an `agent_name` field in the session object.
   - The competition server does not expose an endpoint to re-attribute or query rankings beyond rank 20.
   - The local SHA-256 JSONL audit log remains the authoritative cryptographic proof of the run.

---

## 2. Consolidated Run History

| Session ID | Run Type | Prompt | Seed | Score | Steps | Food | Won | Applied | Rejected | Fallback | Avg Latency | Hash Valid |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `f240cb86-0d3d-4445-97...` | `live_arena` | v2 | - | 1000 | 152 | 15 | YES | 152 | 0 | 0 | 99.49 ms | **PASS** |
| `bench-v1-100` | `local_simulator` | v1 | 100 | 0 | 7 | 0 | NO | 7 | 0 | 0 | 41.14 ms | **PASS** |
| `bench-v1-2026` | `local_simulator` | v1 | 2026 | 60 | 7 | 1 | NO | 7 | 0 | 0 | 42.0 ms | **PASS** |
| `bench-v1-42` | `local_simulator` | v1 | 42 | 0 | 7 | 0 | NO | 7 | 0 | 0 | 81.29 ms | **PASS** |
| `bench-v1-13` | `local_simulator` | v1 | 13 | 60 | 7 | 1 | NO | 7 | 0 | 0 | 42.43 ms | **PASS** |
| `bench-v1-7` | `local_simulator` | v1 | 7 | 0 | 7 | 0 | NO | 7 | 0 | 0 | 41.86 ms | **PASS** |
| `bench-v2-42` | `local_simulator` | v2 | 42 | 1000 | 114 | 15 | YES | 114 | 3340 | 0 | 43.24 ms | **PASS** |
| `bench-v2-100` | `local_simulator` | v2 | 100 | 1000 | 151 | 15 | YES | 151 | 0 | 0 | 49.15 ms | **PASS** |
| `bench-v2-2026` | `local_simulator` | v2 | 2026 | 1000 | 113 | 15 | YES | 113 | 0 | 0 | 49.22 ms | **PASS** |
| `bench-v2-7` | `local_simulator` | v2 | 7 | 660 | 114 | 11 | NO | 114 | 0 | 0 | 49.65 ms | **PASS** |
| `bench-v2-13` | `local_simulator` | v2 | 13 | 660 | 64 | 11 | NO | 64 | 0 | 0 | 48.33 ms | **PASS** |
| `bench-2048-v2-42` | `local_simulator` | v2 | 42 | 1316 | 272 | - | NO | 272 | 0 | 0 | 61.13 ms | **PASS** |
| `bench-2048-v1-42` | `local_simulator` | v1 | 42 | 20 | 6 | - | NO | 6 | 9 | 0 | 107.4 ms | **PASS** |
| `bench-2048-v1-100` | `local_simulator` | v1 | 100 | 16 | 4 | - | NO | 4 | 9 | 0 | 77.77 ms | **PASS** |
| `bench-2048-v1-2026` | `local_simulator` | v1 | 2026 | 12 | 7 | - | NO | 7 | 9 | 0 | 65.88 ms | **PASS** |
| `bench-2048-v1-7` | `local_simulator` | v1 | 7 | 12 | 3 | - | NO | 3 | 9 | 0 | 53.58 ms | **PASS** |
| `bench-2048-v1-13` | `local_simulator` | v1 | 13 | 16 | 6 | - | NO | 6 | 9 | 0 | 65.2 ms | **PASS** |
| `bench-2048-v2-100` | `local_simulator` | v2 | 100 | 1392 | 145 | - | NO | 145 | 0 | 0 | 59.8 ms | **PASS** |
| `bench-2048-v2-2026` | `local_simulator` | v2 | 2026 | 3472 | 292 | - | NO | 292 | 0 | 0 | 59.39 ms | **PASS** |
| `bench-2048-v2-7` | `local_simulator` | v2 | 7 | 1716 | 170 | - | NO | 170 | 0 | 0 | 61.01 ms | **PASS** |
| `bench-2048-v2-13` | `local_simulator` | v2 | 13 | 616 | 85 | - | NO | 85 | 0 | 0 | 58.53 ms | **PASS** |
| `bench-2048-v3-42` | `local_simulator` | v3 | 42 | 3320 | 409 | - | NO | 409 | 9 | 0 | 54.67 ms | **PASS** |
| `bench-2048-v3-100` | `local_simulator` | v3 | 100 | 600 | 162 | - | NO | 162 | 9 | 0 | 55.82 ms | **PASS** |
| `bench-2048-v3-2026` | `local_simulator` | v3 | 2026 | 2844 | 254 | - | NO | 254 | 9 | 0 | 51.17 ms | **PASS** |
| `bench-2048-v3-7` | `local_simulator` | v3 | 7 | 4588 | 391 | - | NO | 391 | 9 | 0 | 51.57 ms | **PASS** |
| `bench-2048-v3-13` | `local_simulator` | v3 | 13 | 1960 | 247 | - | NO | 247 | 18 | 0 | 50.74 ms | **PASS** |
| `bench-2048-v3-99` | `local_simulator` | v3 | 99 | 5812 | 413 | - | NO | 413 | 0 | 0 | 52.51 ms | **PASS** |
| `bench-2048-v3-123` | `local_simulator` | v3 | 123 | 1536 | 164 | - | NO | 164 | 0 | 0 | 50.14 ms | **PASS** |
| `bench-2048-v3-777` | `local_simulator` | v3 | 777 | 2792 | 241 | - | NO | 241 | 0 | 0 | 50.02 ms | **PASS** |
| `mock-snake-1792177345472` | `mock` | - | - | 100 | 3 | 1 | YES | 3 | 0 | 0 | 0.0 ms | **PASS** |
| `mock-2048-42` | `mock` | v1 | - | 4 | 2 | - | NO | 2 | 9 | 0 | 0.0 ms | **PASS** |

---

## 3. Local Simulator Benchmark Evaluation

> [!IMPORTANT]
> **Simulator Equivalence Disclaimer:**
> While `DeterministicSnakeSimulator` faithfully implements the documented rules (12x12 grid, 180-degree reversals, food scoring), **local simulator performance does not guarantee identical Arena server food sequences**. The server's internal pseudo-random food placement differs from local PRNG sequences. Local simulator scores are benchmark indicators and are strictly distinguished from official competition runs.

### Baseline (v1) vs Revised (v2) Prompt Comparison

| Seed | v1 Score | v2 Score | v1 Food | v2 Food | v1 Moves | v2 Moves | v1 Won | v2 Won | v1 Reason | v2 Reason |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 7 | 0 | **660** | 0 | **11** | 7 | 114 | NO | **NO** | `wall_collision` | `self_collision` |
| 13 | 60 | **660** | 1 | **11** | 7 | 64 | NO | **NO** | `wall_collision` | `self_collision` |
| 42 | 0 | **1000** | 0 | **15** | 7 | 114 | NO | **YES** | `wall_collision` | `target_food_reached` |
| 100 | 0 | **1000** | 0 | **15** | 7 | 151 | NO | **YES** | `wall_collision` | `target_food_reached` |
| 2026 | 60 | **1000** | 1 | **15** | 7 | 113 | NO | **YES** | `wall_collision` | `target_food_reached` |

- **Baseline (v1):** Avg Score = 24.0 | Win Rate = 0/5 (0.0%) | 100% crashed at step 7 due to momentum bias.
- **Revised (v2):** Avg Score = **864.0** | Win Rate = **3/5 (60.0%)** | 100% achieved >= 600 qualifying points (3 perfect 1000-pt wins).
- **Score Improvement:** **36.0x** increase in average score.

---

## 4. Local 2048 Benchmark Evaluation

> [!IMPORTANT]
> **2048 Simulator Equivalence & Qualification Scope:**
> `Deterministic2048Simulator` implements the official TopGameAI 4x4 mechanics, single-merge-per-move rules, 90/10 tile spawning, and no-op move rejection. Local simulation results are reproducible benchmark baselines and do NOT substitute for an official Arena qualifying run.

| Seed | Prompt | Best Tile | Merge Score | Steps | Rejections | Won | Reason | Avg Latency | Chain Valid |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 42 | v2 | **128** | 1316 | 272 | 0 | NO | `no_moves_remaining` | 61.13 ms | **PASS** |
| 42 | v1 | **8** | 20 | 6 | 9 | NO | `unknown` | 107.4 ms | **PASS** |
| 100 | v1 | **8** | 16 | 4 | 9 | NO | `unknown` | 77.77 ms | **PASS** |
| 2026 | v1 | **4** | 12 | 7 | 9 | NO | `unknown` | 65.88 ms | **PASS** |
| 7 | v1 | **8** | 12 | 3 | 9 | NO | `unknown` | 53.58 ms | **PASS** |
| 13 | v1 | **8** | 16 | 6 | 9 | NO | `unknown` | 65.2 ms | **PASS** |
| 100 | v2 | **128** | 1392 | 145 | 0 | NO | `no_moves_remaining` | 59.8 ms | **PASS** |
| 2026 | v2 | **256** | 3472 | 292 | 0 | NO | `no_moves_remaining` | 59.39 ms | **PASS** |
| 7 | v2 | **128** | 1716 | 170 | 0 | NO | `no_moves_remaining` | 61.01 ms | **PASS** |
| 13 | v2 | **64** | 616 | 85 | 0 | NO | `no_moves_remaining` | 58.53 ms | **PASS** |
| 42 | v3 | **256** | 3320 | 409 | 9 | NO | `no_moves_remaining` | 54.67 ms | **PASS** |
| 100 | v3 | **64** | 600 | 162 | 9 | NO | `no_moves_remaining` | 55.82 ms | **PASS** |
| 2026 | v3 | **256** | 2844 | 254 | 9 | NO | `no_moves_remaining` | 51.17 ms | **PASS** |
| 7 | v3 | **512** | 4588 | 391 | 9 | NO | `no_moves_remaining` | 51.57 ms | **PASS** |
| 13 | v3 | **256** | 1960 | 247 | 18 | NO | `no_moves_remaining` | 50.74 ms | **PASS** |
| 99 | v3 | **512** | 5812 | 413 | 0 | NO | `no_moves_remaining` | 52.51 ms | **PASS** |
| 123 | v3 | **128** | 1536 | 164 | 0 | NO | `no_moves_remaining` | 50.14 ms | **PASS** |
| 777 | v3 | **256** | 2792 | 241 | 0 | NO | `no_moves_remaining` | 50.02 ms | **PASS** |
| - | v1 | **4** | 4 | 2 | 9 | NO | `-` | 0.0 ms | **PASS** |

- **Max Tile Reached:** **512**
- **Average Highest Tile:** **157.1**
- **Runs Reaching >= 512:** **2 / 19** (10.5%)

### 2048 Prompt Comparison (v1 vs v2 vs v3)

| Seed | v1 Best | v2 Best | v3 Best | v1 Score | v2 Score | v3 Score | v1 Moves | v2 Moves | v3 Moves | v3 Rej | v3 Reason |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 7 | 8 | 128 | **512** | 12 | 1716 | **4588** | 3 | 170 | 391 | 9 | `no_moves_remaining` |
| 13 | 8 | 64 | **256** | 16 | 616 | **1960** | 6 | 85 | 247 | 18 | `no_moves_remaining` |
| 42 | 8 | 128 | **256** | 20 | 1316 | **3320** | 6 | 272 | 409 | 9 | `no_moves_remaining` |
| 99 | - | - | **512** | - | - | **5812** | - | - | 413 | 0 | `no_moves_remaining` |
| 100 | 8 | 128 | **64** | 16 | 1392 | **600** | 4 | 145 | 162 | 9 | `no_moves_remaining` |
| 123 | - | - | **128** | - | - | **1536** | - | - | 164 | 0 | `no_moves_remaining` |
| 777 | - | - | **256** | - | - | **2792** | - | - | 241 | 0 | `no_moves_remaining` |
| 2026 | 4 | 256 | **256** | 12 | 3472 | **2844** | 7 | 292 | 254 | 9 | `no_moves_remaining` |

---

## 5. Cryptographic Hash Chain Audit Status

All original `.jsonl` audit log files were independently verified using the competition SHA-256 hash-chain engine (`verify_jsonl_file`).

- **Logs Verified Valid:** **31 / 31** (100.0% integrity across all records).
- **Genesis Linkage:** Every log begins with `GENESIS-<session_id>`.
- **Canonical Serialization:** All hashes computed over `prev_hash + '|' + canonical_json(record_without_hash)`.
- **Tamper Protection:** No altered, deleted, or fabricated records detected.

