# Team ZENITH - Run History and Benchmark Report

**Generated:** 2026-10-16 19:32:55 UTC\
**Team / Agent Name:** `ZENITH`\
**Total Discovered Runs:** 12 (`1` live arena, `10` local simulator, `1` mock)

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
| `bench-v2-42` | `local_simulator` | v2 | 42 | 1000 | 105 | 15 | YES | 114 | 3340 | 0 | 43.24 ms | **PASS** |
| `bench-v2-100` | `local_simulator` | v2 | 100 | 1000 | 151 | 15 | YES | 151 | 0 | 0 | 49.15 ms | **PASS** |
| `bench-v2-2026` | `local_simulator` | v2 | 2026 | 1000 | 113 | 15 | YES | 113 | 0 | 0 | 49.22 ms | **PASS** |
| `bench-v2-7` | `local_simulator` | v2 | 7 | 660 | 114 | 11 | NO | 114 | 0 | 0 | 49.65 ms | **PASS** |
| `bench-v2-13` | `local_simulator` | v2 | 13 | 660 | 64 | 11 | NO | 64 | 0 | 0 | 48.33 ms | **PASS** |
| `mock-snake-1792177345472` | `mock` | - | - | 100 | 3 | 1 | YES | 3 | 0 | 0 | 0.0 ms | **PASS** |

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
| 42 | 0 | **1000** | 0 | **15** | 7 | 105 | NO | **YES** | `wall_collision` | `target_food_reached` |
| 100 | 0 | **1000** | 0 | **15** | 7 | 151 | NO | **YES** | `wall_collision` | `target_food_reached` |
| 2026 | 60 | **1000** | 1 | **15** | 7 | 113 | NO | **YES** | `wall_collision` | `target_food_reached` |

- **Baseline (v1):** Avg Score = 24.0 | Win Rate = 0/5 (0.0%) | 100% crashed at step 7 due to momentum bias.
- **Revised (v2):** Avg Score = **864.0** | Win Rate = **3/5 (60.0%)** | 100% achieved >= 600 qualifying points (3 perfect 1000-pt wins).
- **Score Improvement:** **36.0x** increase in average score.

---

## 4. Cryptographic Hash Chain Audit Status

All original `.jsonl` audit log files were independently verified using the competition SHA-256 hash-chain engine (`verify_jsonl_file`).

- **Logs Verified Valid:** **12 / 12** (100.0% integrity across all records).
- **Genesis Linkage:** Every log begins with `GENESIS-<session_id>`.
- **Canonical Serialization:** All hashes computed over `prev_hash + '|' + canonical_json(record_without_hash)`.
- **Tamper Protection:** No altered, deleted, or fabricated records detected.
