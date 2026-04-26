"""
evals/artifacts.py
------------------
Small helpers for writing evaluation evidence to disk.

The scorer answers "how well did it do?".  Artifacts answer "what happened?".
Keeping those separate makes the eval harness easier to review and harder to
accidentally game.
"""

from __future__ import annotations

import difflib
import json
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


def make_run_id() -> str:
    """Return a sortable id for one eval run."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def relpath(path: Path, root: Path) -> str:
    """Return a stable relative path when possible."""
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def safe_truncate(text: str | None, limit: int = 8000) -> str:
    """Keep JSON artifacts readable without hiding that text was trimmed."""
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[truncated: {len(text) - limit} chars omitted]"


def protocol_summary(msg: Any) -> dict[str, Any]:
    """Convert a TeamProtocol-like object into a compact review payload."""
    if msg is None:
        return {}
    data = asdict(msg) if is_dataclass(msg) else dict(msg)
    return {
        "phase": data.get("phase", ""),
        "status": data.get("status", ""),
        "target_file": data.get("target_file", ""),
        "error_info": safe_truncate(data.get("error_info", ""), 4000),
        "root_cause": safe_truncate(data.get("root_cause", ""), 5000),
        "issues": data.get("issues", []),
        "fix_plan": safe_truncate(data.get("fix_plan", ""), 3000),
        "patch_desc": safe_truncate(data.get("patch_desc", ""), 5000),
        "test_result": safe_truncate(data.get("test_result", ""), 5000),
        "retry_count": data.get("retry_count", 0),
        "notes": safe_truncate(data.get("notes", ""), 2000),
    }


def sandbox_diff_summary(original_file: Path, fixed_file: Path | None) -> dict[str, Any]:
    """Return a unified diff summary between the original and sandbox copy."""
    if fixed_file is None or not fixed_file.exists():
        return {
            "available": False,
            "lines_changed": 0,
            "diff": "",
            "reason": "No sandbox file was returned by the pipeline.",
        }
    try:
        original_lines = original_file.read_text(errors="replace").splitlines()
        fixed_lines = fixed_file.read_text(errors="replace").splitlines()
    except Exception as exc:
        return {
            "available": False,
            "lines_changed": 0,
            "diff": "",
            "reason": f"Could not read files: {exc}",
        }

    diff_lines = list(
        difflib.unified_diff(
            original_lines,
            fixed_lines,
            fromfile=str(original_file),
            tofile=str(fixed_file),
            lineterm="",
        )
    )
    changed = sum(
        1
        for line in diff_lines
        if (line.startswith("+") or line.startswith("-"))
        and not line.startswith("+++")
        and not line.startswith("---")
    )
    return {
        "available": True,
        "lines_changed": changed,
        "diff": safe_truncate("\n".join(diff_lines), 12000),
    }


def score_payload(score: Any) -> dict[str, Any]:
    """Serialize DebugScore without making artifact code depend on its class."""
    return {
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
    }


def build_case_artifact(
    *,
    entry: dict[str, Any],
    result: dict[str, Any],
    score: Any,
    original_file: Path,
    fixed_file: Path | None,
    project_root: Path,
    case_path: Path,
) -> dict[str, Any]:
    """Build the JSON object used by both per-case and run-level artifacts."""
    diff = sandbox_diff_summary(original_file, fixed_file)
    agent = protocol_summary(result.get("msg"))
    return {
        "id": entry["id"],
        "file": entry["file"],
        "tags": entry["tags"],
        "bug_count": entry["bug_count"],
        "status": result.get("status", "unknown"),
        "score": score_payload(score),
        "grade": score.grade,
        "metrics": {
            "bugs_fixed": score.bugs_fixed,
            "bugs_total": score.bugs_total,
            "lines_changed": score.lines_changed,
            "retry_count": score.retry_count,
            "wall_time": round(score.wall_time, 2),
        },
        "agent_summary": {
            "issues": agent.get("issues", []),
            "root_cause": agent.get("root_cause", ""),
            "patch_desc": agent.get("patch_desc", ""),
            "test_result": agent.get("test_result", ""),
            "retry_count": agent.get("retry_count", score.retry_count),
            "phase": agent.get("phase", ""),
            "status": agent.get("status", ""),
        },
        "artifacts": {
            "case_json": relpath(case_path, project_root),
            "original_file": relpath(original_file, project_root),
            "fixed_file": relpath(fixed_file, project_root) if fixed_file else None,
            "sandbox_diff": diff,
        },
        "raw_protocol": agent,
    }


def write_json(path: Path, payload: Any) -> None:
    """Write UTF-8 JSON with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def build_run_payload(
    *,
    run_id: str,
    project_root: Path,
    cases: list[dict[str, Any]],
    started_at: float,
) -> dict[str, Any]:
    """Build the top-level results.json payload."""
    totals = [case["score"]["total"] for case in cases]
    return {
        "run_id": run_id,
        "started_at": datetime.fromtimestamp(started_at).isoformat(timespec="seconds"),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "wall_time": round(time.time() - started_at, 2),
        "project_root": str(project_root),
        "case_count": len(cases),
        "summary": {
            "avg_score": round(sum(totals) / len(totals), 1) if totals else 0.0,
            "fix_rate": round(
                sum(1 for case in cases if case["score"]["fix_correctness"] == 50.0)
                / max(len(cases), 1),
                3,
            ),
            "bugs_total": sum(case["score"]["bugs_total"] for case in cases),
            "bugs_fixed": sum(case["score"]["bugs_fixed"] for case in cases),
        },
        "cases": cases,
    }
