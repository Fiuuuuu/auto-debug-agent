"""
evals/runner.py
---------------
Execution layer for the eval harness.

It copies each buggy sample to a temp file, runs the real auto-debug pipeline,
scores the result, and writes the evidence needed by reviewer/proposal agents.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

from .artifacts import (
    build_case_artifact,
    build_run_payload,
    make_run_id,
    write_json,
)
from .golden_dataset import GOLDEN
from .reporting import C_BOLD, C_CYAN, C_RESET, print_case_header, print_summary
from .scorer import DebugScore, compute_score


PROJECT_ROOT = Path(__file__).parent.parent.resolve()


def _display_path(path: Path) -> str:
    """Display project-relative paths when possible."""
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _load_pipeline():
    """
    Import the production pipeline lazily.

    This keeps `python evals/run_evals.py --help` usable even before MODEL_ID is
    configured.  The model is only required when the user actually runs cases.
    """
    from main import run_debug_pipeline

    return run_debug_pipeline


def select_cases(ids: list[str]) -> list[dict[str, Any]]:
    """Return requested golden cases, preserving GOLDEN order."""
    if not ids:
        return GOLDEN
    return [entry for entry in GOLDEN if entry["id"] in ids]


def run_single(entry: dict[str, Any], tmpdir: Path) -> tuple[DebugScore, dict[str, Any], Path | None, Path]:
    """Run the pipeline on one golden entry and return score plus raw evidence."""
    run_debug_pipeline = _load_pipeline()
    original = PROJECT_ROOT / entry["file"]
    case_root = tmpdir / entry["id"]
    shutil.copytree(PROJECT_ROOT / "sample_bugs", case_root / "sample_bugs")
    tmp_copy = case_root / entry["file"]

    print_case_header(entry)
    result = run_debug_pipeline(
        str(tmp_copy),
        max_fix_attempts=4,
        auto_approve=True,
    )

    fixed_file = None
    if result["sandbox"] is not None:
        fixed_file = result["sandbox"].sandbox_file
    elif result["status"] == "no_bug":
        fixed_file = tmp_copy

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
    return score, result, fixed_file, original


def run_eval_suite(
    *,
    ids: list[str],
    output: str | None = None,
    runs_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Run selected eval cases and persist a reviewable results bundle.

    Returns the top-level results payload so callers/tests do not need to read
    JSON back from disk.
    """
    cases = select_cases(ids)
    if ids and not cases:
        raise ValueError(f"No matching cases for ids: {ids}")

    run_id = make_run_id()
    started_at = time.time()
    runs_root = runs_dir or (PROJECT_ROOT / "evals" / "runs")
    run_dir = runs_root / run_id
    cases_dir = run_dir / "cases"
    case_artifacts: list[dict[str, Any]] = []
    summary: list[tuple[str, DebugScore]] = []

    print(f"\n{C_CYAN}Auto-Debug Agent — Evaluation Suite{C_RESET}")
    print(f"Run id: {run_id}")
    print(f"Running {len(cases)} case(s) ...\n")

    eval_work = PROJECT_ROOT / ".debug" / "eval_work" / run_id
    shutil.rmtree(eval_work, ignore_errors=True)
    eval_work.mkdir(parents=True, exist_ok=True)

    for entry in cases:
        score, result, fixed_file, original = run_single(entry, eval_work)
        print(f"\n{C_BOLD}Score for [{entry['id']}]{C_RESET}")
        print(score.pretty())

        case_path = cases_dir / f"{entry['id']}.json"
        artifact = build_case_artifact(
            entry=entry,
            result=result,
            score=score,
            original_file=original,
            fixed_file=fixed_file,
            project_root=PROJECT_ROOT,
            case_path=case_path,
        )
        write_json(case_path, artifact)
        case_artifacts.append(artifact)
        summary.append((entry["id"], score))

    results_payload = build_run_payload(
        run_id=run_id,
        project_root=PROJECT_ROOT,
        cases=case_artifacts,
        started_at=started_at,
    )
    results_path = run_dir / "results.json"
    write_json(results_path, results_payload)
    print_summary(summary)
    print(f"\n  Results saved -> {_display_path(results_path)}")

    if output:
        out_path = Path(output)
        if not out_path.is_absolute():
            out_path = PROJECT_ROOT / out_path
        write_json(out_path, results_payload)
        print(f"  Compatibility copy -> {_display_path(out_path)}")

    return results_payload
