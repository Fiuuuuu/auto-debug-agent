#!/usr/bin/env python3
"""
evals/run_evals.py
------------------
Batch evaluation runner for the Auto-Debug Agent.

Usage
-----
    # Run all cases
    python evals/run_evals.py

    # Run specific cases by id
    python evals/run_evals.py bug1 bug3

    # Save results to JSON
    python evals/run_evals.py --output evals/results.json

How it works
------------
1. For each golden dataset entry, copy the original bug file to a temp path
   so the source is never modified.
2. Call run_debug_pipeline() with auto_approve=True (no human interaction).
3. Score the result with compute_score().
4. Print a per-case report and a final summary table.
"""

from __future__ import annotations
import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

# ── Make sure project root is on sys.path ─────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from main import run_debug_pipeline
from evals.golden_dataset import GOLDEN
from evals.scorer import compute_score, DebugScore


# ── Colours ───────────────────────────────────────────────────────────────────
C_RESET  = "\033[0m"
C_CYAN   = "\033[36m"
C_GREEN  = "\033[32m"
C_RED    = "\033[31m"
C_YELLOW = "\033[33m"
C_BOLD   = "\033[1m"


def grade_colour(grade: str) -> str:
    return {
        "A": C_GREEN,
        "B": C_GREEN,
        "C": C_YELLOW,
        "D": C_YELLOW,
        "F": C_RED,
    }.get(grade, C_RESET)


def run_single(entry: dict, tmpdir: Path) -> tuple[DebugScore, dict]:
    """Run the pipeline on one golden entry and return (score, raw_result)."""
    original = PROJECT_ROOT / entry["file"]
    # Work on a temp copy so the source file is never touched
    tmp_copy = tmpdir / original.name
    shutil.copy2(original, tmp_copy)

    print(f"\n{C_CYAN}{'━'*60}{C_RESET}")
    print(f"{C_BOLD}  [{entry['id']}]  {entry['file']}{C_RESET}")
    print(f"  Tags: {', '.join(entry['tags'])}   Bugs: {entry['bug_count']}")
    print(f"{C_CYAN}{'━'*60}{C_RESET}")

    result = run_debug_pipeline(
        str(tmp_copy),
        max_fix_attempts=2,
        auto_approve=True,
    )

    # Determine which file to score against
    fixed_file = None
    if result["sandbox"] is not None:
        fixed_file = result["sandbox"].sandbox_file
    elif result["status"] == "no_bug":
        fixed_file = tmp_copy  # original was already clean

    score = compute_score(
        pipeline_status=result["status"],
        fixed_file=fixed_file,
        original_file=original,
        checkers=entry["checkers"],
        bug_count=entry["bug_count"],
        retry_count=result.get("retry_count", 0),
        wall_time=result.get("wall_time", 0.0),
        timeout=entry.get("timeout", 30),
    )

    return score, result


def print_summary(results: list[tuple[str, DebugScore]]) -> None:
    print(f"\n{C_BOLD}{'━'*60}")
    print("  EVALUATION SUMMARY")
    print(f"{'━'*60}{C_RESET}")

    header = f"  {'ID':<10} {'Grade':>5} {'Total':>7} {'Correct':>9} {'Bugs':>8} {'Minimal':>9} {'Effic':>7}"
    print(header)
    print(f"  {'-'*57}")

    totals = []
    for eid, s in results:
        gc = grade_colour(s.grade)
        print(
            f"  {eid:<10} "
            f"{gc}{s.grade:>5}{C_RESET} "
            f"{s.total:>7.1f} "
            f"{s.fix_correctness:>9.1f} "
            f"{s.bug_completeness:>8.1f} "
            f"{s.patch_minimality:>9.1f} "
            f"{s.efficiency:>7.1f}"
        )
        totals.append(s.total)

    print(f"  {'-'*57}")
    avg = sum(totals) / len(totals) if totals else 0
    fix_rate = sum(1 for _, s in results if s.fix_correctness == 50.0) / max(len(results), 1)
    print(f"\n  Cases run   : {len(results)}")
    print(f"  Avg score   : {avg:.1f}/100")
    print(f"  Fix rate    : {fix_rate*100:.0f}%  "
          f"({sum(1 for _, s in results if s.fix_correctness==50.0)}/{len(results)} files ran clean)")
    print(f"  Total bugs  : {sum(s.bugs_total for _, s in results)}   "
          f"Fixed: {sum(s.bugs_fixed for _, s in results)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Auto-Debug Agent evaluations")
    parser.add_argument("ids", nargs="*", help="Case ids to run (default: all)")
    parser.add_argument("--output", "-o", help="Save raw results to this JSON file")
    args = parser.parse_args()

    cases = GOLDEN
    if args.ids:
        cases = [e for e in GOLDEN if e["id"] in args.ids]
        if not cases:
            print(f"No matching cases for ids: {args.ids}")
            sys.exit(1)

    print(f"\n{C_CYAN}Auto-Debug Agent — Evaluation Suite{C_RESET}")
    print(f"Running {len(cases)} case(s) …\n")

    summary: list[tuple[str, DebugScore]] = []
    raw_output: list[dict] = []

    with tempfile.TemporaryDirectory(prefix="autdebug_eval_") as tmpdir:
        for entry in cases:
            score, result = run_single(entry, Path(tmpdir))
            print(f"\n{C_BOLD}Score for [{entry['id']}]{C_RESET}")
            print(score.pretty())
            summary.append((entry["id"], score))
            raw_output.append({
                "id": entry["id"],
                "file": entry["file"],
                "tags": entry["tags"],
                "status": result["status"],
                "total": score.total,
                "grade": score.grade,
                "fix_correctness": score.fix_correctness,
                "bug_completeness": score.bug_completeness,
                "patch_minimality": score.patch_minimality,
                "efficiency": score.efficiency,
                "bugs_fixed": score.bugs_fixed,
                "bugs_total": score.bugs_total,
                "lines_changed": score.lines_changed,
                "retry_count": score.retry_count,
                "wall_time": round(score.wall_time, 2),
                "notes": score.notes,
            })

    print_summary(summary)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(raw_output, indent=2, ensure_ascii=False))
        print(f"\n  Results saved → {args.output}")


if __name__ == "__main__":
    main()
