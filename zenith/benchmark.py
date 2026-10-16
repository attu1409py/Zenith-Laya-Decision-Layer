"""Benchmark runner for local deterministic Snake simulation with Laya.

Runs controlled batches of seeds against the local Laya model without any
network calls or live Arena sessions, recording full metrics, decision logs,
and hash chains.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from zenith.decision_viewer import DecisionViewer
from zenith.laya_adapter import APPROVED_MODEL_ID, LayaAdapter
from zenith.runner import SessionRunner
from zenith.session_logger import SessionLogger
from zenith.snake_simulator import DeterministicSnakeSimulator

BENCHMARK_LOG_DIR = os.path.join("logs", "benchmarks")


@dataclass
class BenchmarkRunResult:
    seed: int
    prompt_version: str
    model_id: str
    score: int
    food_eaten: int
    accepted_moves: int
    rejected_moves: int
    fallback_moves: int
    won: bool
    termination_reason: str
    avg_inference_ms: float
    min_inference_ms: float
    max_inference_ms: float
    total_time_s: float
    hash_chain_valid: bool
    log_path: str
    failure_details: Optional[Dict[str, Any]] = None


def run_single_benchmark(
    seed: int,
    adapter: LayaAdapter,
    prompt_version: str = "v1",
    log_dir: str = BENCHMARK_LOG_DIR,
    quiet: bool = True,
    max_moves: int = 300,
    target_food: int = 15,
) -> BenchmarkRunResult:
    """Run a single deterministic benchmark session for one seed."""
    sim = DeterministicSnakeSimulator(
        seed=seed,
        max_moves=max_moves,
        target_food=target_food,
        session_id_prefix=f"bench-{prompt_version}",
    )
    session_id = sim.session_id

    os.makedirs(log_dir, exist_ok=True)
    logger = SessionLogger(
        session_id=session_id,
        game="snake",
        log_dir=log_dir,
    )

    out_stream = io.StringIO() if quiet else sys.stdout
    viewer = DecisionViewer(
        game="snake",
        session_id=session_id,
        mock_mode=False,
        log_path=logger.log_path,
        out=out_stream,
    )

    runner = SessionRunner(
        arena=sim,
        decide_fn=adapter.decide,
        logger=logger,
        viewer=viewer,
    )

    adapter.prompt_version = prompt_version

    start_time = time.monotonic()
    result = runner.run()
    elapsed_s = time.monotonic() - start_time

    # Collect inference times from move records
    inference_times = [
        m.timing.get("decide_ms", 0) for m in result.moves if m.timing
    ]
    avg_inf = (
        sum(inference_times) / len(inference_times) if inference_times else 0.0
    )
    min_inf = min(inference_times) if inference_times else 0.0
    max_inf = max(inference_times) if inference_times else 0.0

    # Collect failure details if game ended in loss
    failure_details = None
    if not sim.won and result.moves:
        last_move = result.moves[-1]
        failure_details = {
            "termination_reason": sim.termination_reason,
            "last_step": last_move.step,
            "last_action": last_move.action,
            "last_decision": last_move.decision,
            "snake_final": sim._snake,
            "food_final": sim._food,
        }

    return BenchmarkRunResult(
        seed=seed,
        prompt_version=prompt_version,
        model_id=adapter.model_id,
        score=sim.score,
        food_eaten=sim.food_eaten,
        accepted_moves=sim.accepted_moves,
        rejected_moves=sim.rejected_moves,
        fallback_moves=result.fallback_moves,
        won=bool(sim.won),
        termination_reason=sim.termination_reason or "unknown",
        avg_inference_ms=round(avg_inf, 2),
        min_inference_ms=round(min_inf, 2),
        max_inference_ms=round(max_inf, 2),
        total_time_s=round(elapsed_s, 2),
        hash_chain_valid=bool(result.hash_chain_valid),
        log_path=result.log_path or logger.log_path,
        failure_details=failure_details,
    )


def run_benchmark_suite(
    seeds: List[int],
    prompt_version: str = "v1",
    model_id: str = APPROVED_MODEL_ID,
    log_dir: str = BENCHMARK_LOG_DIR,
    quiet: bool = True,
    adapter: Optional[LayaAdapter] = None,
) -> List[BenchmarkRunResult]:
    """Execute a batch of benchmark runs on given seeds."""
    if adapter is None:
        print(f"Loading Laya model '{model_id}' (prompt_version={prompt_version})...")
        adapter = LayaAdapter(model_id=model_id, prompt_version=prompt_version)

    results: List[BenchmarkRunResult] = []
    for idx, seed in enumerate(seeds, 1):
        print(f"[{idx}/{len(seeds)}] Running seed {seed} (prompt={prompt_version})...", flush=True)
        res = run_single_benchmark(
            seed=seed,
            adapter=adapter,
            prompt_version=prompt_version,
            log_dir=log_dir,
            quiet=quiet,
        )
        results.append(res)
        print(
            f"  -> Score: {res.score} | Food: {res.food_eaten} | Moves: {res.accepted_moves} "
            f"| Rej: {res.rejected_moves} | Term: {res.termination_reason} "
            f"| Inf: {res.avg_inference_ms}ms | Time: {res.total_time_s}s",
            flush=True,
        )

    return results


def format_results_markdown(
    results: List[BenchmarkRunResult],
    title: str = "Benchmark Results",
) -> str:
    """Format benchmark results as a Markdown table."""
    lines = [
        f"### {title}",
        "",
        "| Seed | Prompt | Score | Food | Accepted Moves | Rejections | Won | Reason | Avg Latency (ms) | Time (s) | Chain Valid |",
        "|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
    ]
    for r in results:
        lines.append(
            f"| {r.seed} | {r.prompt_version} | {r.score} | {r.food_eaten} | "
            f"{r.accepted_moves} | {r.rejected_moves} | {'YES' if r.won else 'NO'} | "
            f"`{r.termination_reason}` | {r.avg_inference_ms} | {r.total_time_s} | "
            f"{'VALID' if r.hash_chain_valid else 'INVALID'} |"
        )

    total_food = sum(r.food_eaten for r in results)
    avg_score = sum(r.score for r in results) / len(results) if results else 0
    wins = sum(1 for r in results if r.won)
    win_rate = (wins / len(results)) * 100 if results else 0

    lines.extend([
        "",
        f"**Summary:** Total Food Eaten: {total_food} | Avg Score: {avg_score:.1f} | Win Rate: {win_rate:.1f}% ({wins}/{len(results)})",
        "",
    ])
    return "\n".join(lines)


def format_comparison_markdown(
    baseline: List[BenchmarkRunResult],
    revised: List[BenchmarkRunResult],
) -> str:
    """Format side-by-side comparison between baseline and revised versions."""
    base_map = {r.seed: r for r in baseline}
    rev_map = {r.seed: r for r in revised}
    all_seeds = sorted(set(base_map.keys()) | set(rev_map.keys()))

    lines = [
        "### Benchmark Baseline (v1) vs Revised (v2) Comparison",
        "",
        "| Seed | Base Score | Rev Score | Base Food | Rev Food | Base Moves | Rev Moves | Base Won | Rev Won | Base Reason | Rev Reason |",
        "|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
    ]

    for s in all_seeds:
        b = base_map.get(s)
        r = rev_map.get(s)
        b_score = str(b.score) if b else "N/A"
        r_score = str(r.score) if r else "N/A"
        b_food = str(b.food_eaten) if b else "N/A"
        r_food = str(r.food_eaten) if r else "N/A"
        b_moves = str(b.accepted_moves) if b else "N/A"
        r_moves = str(r.accepted_moves) if r else "N/A"
        b_won = ("YES" if b.won else "NO") if b else "N/A"
        r_won = ("YES" if r.won else "NO") if r else "N/A"
        b_reason = f"`{b.termination_reason}`" if b else "N/A"
        r_reason = f"`{r.termination_reason}`" if r else "N/A"

        lines.append(
            f"| {s} | {b_score} | {r_score} | {b_food} | {r_food} | "
            f"{b_moves} | {r_moves} | {b_won} | {r_won} | {b_reason} | {r_reason} |"
        )

    base_avg_score = sum(b.score for b in baseline) / len(baseline) if baseline else 0
    rev_avg_score = sum(r.score for r in revised) / len(revised) if revised else 0
    base_food = sum(b.food_eaten for b in baseline)
    rev_food = sum(r.food_eaten for r in revised)
    base_wins = sum(1 for b in baseline if b.won)
    rev_wins = sum(1 for r in revised if r.won)

    lines.extend([
        "",
        f"- **Baseline (v1):** Total Food = {base_food}, Avg Score = {base_avg_score:.1f}, Wins = {base_wins}/{len(baseline)}",
        f"- **Revised (v2):** Total Food = {rev_food}, Avg Score = {rev_avg_score:.1f}, Wins = {rev_wins}/{len(revised)}",
        "",
    ])
    return "\n".join(lines)


def save_benchmark_json(
    results: List[BenchmarkRunResult],
    output_path: str,
) -> None:
    """Save benchmark results to a JSON file for persistent comparison."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in results], f, indent=2)


def load_benchmark_json(input_path: str) -> List[BenchmarkRunResult]:
    """Load benchmark results from a JSON file."""
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    results = []
    for item in data:
        results.append(BenchmarkRunResult(**item))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Zenith Local Laya Snake Benchmark")
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 100, 2026, 7, 13], help="Seeds to test")
    parser.add_argument("--prompt-version", default="v2", choices=["v1", "v2"], help="Prompt version (default: v2)")
    parser.add_argument("--output", default=None, help="Output JSON path")
    parser.add_argument("--compare", default=None, help="Path to baseline JSON to compare against")
    parser.add_argument("--verbose", action="store_true", help="Print viewer panels")
    args = parser.parse_args()

    results = run_benchmark_suite(
        seeds=args.seeds,
        prompt_version=args.prompt_version,
        quiet=not args.verbose,
    )

    md = format_results_markdown(results, title=f"Snake Benchmark (Prompt {args.prompt_version})")
    print("\n" + md)

    if args.output:
        save_benchmark_json(results, args.output)
        print(f"Results saved to {args.output}")

    if args.compare and os.path.exists(args.compare):
        baseline = load_benchmark_json(args.compare)
        comp_md = format_comparison_markdown(baseline, results)
        print("\n" + comp_md)


if __name__ == "__main__":
    main()
