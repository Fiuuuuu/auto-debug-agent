"""
evals/scorer.py
---------------
Scoring logic for a single Auto-Debug Agent run.

Score breakdown (100 pts total)
────────────────────────────────
  50  Fix Correctness   — fixed file runs without exception (exit code 0)
  20  Bug Completeness  — fraction of per-bug checkers that pass
  15  Patch Minimality  — fewer lines changed = higher score
  15  Efficiency        — penalise retries and wall-clock time

Grade mapping
─────────────
  A  ≥ 90   B  ≥ 75   C  ≥ 60   D  ≥ 45   F  < 45
"""

from __future__ import annotations
import subprocess
import importlib.util
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class DebugScore:
    fix_correctness: float = 0.0    # 0–50
    bug_completeness: float = 0.0   # 0–20
    patch_minimality: float = 0.0   # 0–15
    efficiency: float = 0.0         # 0–15

    bugs_fixed: int = 0
    bugs_total: int = 0
    lines_changed: int = 0
    retry_count: int = 0
    wall_time: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def total(self) -> float:
        return round(
            self.fix_correctness + self.bug_completeness +
            self.patch_minimality + self.efficiency, 1
        )

    @property
    def grade(self) -> str:
        t = self.total
        if t >= 90: return "A"
        if t >= 75: return "B"
        if t >= 60: return "C"
        if t >= 45: return "D"
        return "F"

    def pretty(self) -> str:
        bar_len = int(self.total / 5)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        lines = [
            f"  Grade : {self.grade}   Total : {self.total}/100",
            f"  [{bar}]",
            f"  Fix Correctness  : {self.fix_correctness:5.1f}/50",
            f"  Bug Completeness : {self.bug_completeness:5.1f}/20  ({self.bugs_fixed}/{self.bugs_total} bugs)",
            f"  Patch Minimality : {self.patch_minimality:5.1f}/15  ({self.lines_changed} lines changed)",
            f"  Efficiency       : {self.efficiency:5.1f}/15  ({self.retry_count} retries, {self.wall_time:.1f}s)",
        ]
        if self.notes:
            lines.append("  Notes:")
            for n in self.notes:
                lines.append(f"    • {n}")
        return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_module(path: Path) -> types.ModuleType | None:
    """Import a Python file as a fresh module without running __main__ block."""
    try:
        spec = importlib.util.spec_from_file_location("_eval_target", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:
        return None


def _exit_code(path: Path, timeout: int = 30) -> int:
    """Run a Python file and return its exit code."""
    result = subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        timeout=timeout,
    )
    return result.returncode


def _count_diff_lines(original: Path, fixed: Path) -> int:
    """Return the number of lines that differ between original and fixed."""
    try:
        orig_lines = original.read_text(errors="replace").splitlines()
        fixed_lines = fixed.read_text(errors="replace").splitlines()
    except Exception:
        return 999

    import difflib
    diff = list(difflib.unified_diff(orig_lines, fixed_lines))
    # Count only added/removed lines (lines starting with + or - but not +++ / ---)
    changed = sum(1 for l in diff if (l.startswith("+") or l.startswith("-"))
                  and not l.startswith("+++") and not l.startswith("---"))
    return changed


# ── Main scorer ───────────────────────────────────────────────────────────────

def compute_score(
    *,
    pipeline_status: str,             # "ok" | "failed" | "no_bug" | "rejected" | "error"
    fixed_file: Path | None,          # path to the sandbox copy after fix
    original_file: Path,              # original (unmodified) bug file
    checkers: list[Callable],         # per-bug checker functions
    bug_count: int,
    retry_count: int,
    wall_time: float,
    timeout: int = 30,
) -> DebugScore:
    score = DebugScore(
        bugs_total=bug_count,
        retry_count=retry_count,
        wall_time=wall_time,
    )

    # ── 1. Fix Correctness (50 pts) ──────────────────────────────────────────
    if pipeline_status == "no_bug":
        score.fix_correctness = 50.0
        score.notes.append("No bug detected — file already clean.")
    elif fixed_file and fixed_file.exists():
        try:
            code = _exit_code(fixed_file, timeout=timeout)
            if code == 0:
                score.fix_correctness = 50.0
            else:
                score.fix_correctness = 0.0
                score.notes.append(f"Fixed file exits with code {code}.")
        except subprocess.TimeoutExpired:
            score.fix_correctness = 0.0
            score.notes.append("Fixed file timed out during execution.")
    else:
        score.fix_correctness = 0.0
        score.notes.append(f"Pipeline status: {pipeline_status}. No fixed file.")

    # ── 2. Bug Completeness (20 pts) ─────────────────────────────────────────
    if fixed_file and fixed_file.exists():
        mod = _load_module(fixed_file)
        if mod is None:
            score.bug_completeness = 0.0
            score.notes.append("Fixed file failed to import — cannot run checkers.")
        else:
            passed = 0
            for i, checker in enumerate(checkers):
                try:
                    ok = bool(checker(mod))
                except Exception as e:
                    ok = False
                    score.notes.append(f"Checker {i+1} raised: {e}")
                if ok:
                    passed += 1
            score.bugs_fixed = passed
            score.bug_completeness = round(20.0 * passed / max(len(checkers), 1), 1)
    elif pipeline_status == "no_bug":
        score.bugs_fixed = 0
        score.bug_completeness = 0.0

    # ── 3. Patch Minimality (15 pts) ─────────────────────────────────────────
    if fixed_file and fixed_file.exists():
        lines_changed = _count_diff_lines(original_file, fixed_file)
        score.lines_changed = lines_changed
        # Perfect: ≤ bug_count*3 lines changed → 15 pts
        # Each extra 5 lines beyond that → −1 pt (min 0)
        ideal = max(bug_count * 3, 3)
        excess = max(0, lines_changed - ideal)
        penalty = excess // 5
        score.patch_minimality = max(0.0, 15.0 - penalty)
    else:
        score.patch_minimality = 0.0

    # ── 4. Efficiency (15 pts) ───────────────────────────────────────────────
    # −5 per retry, −1 per 30s of wall time (max penalty 15)
    retry_penalty = min(retry_count * 5, 10)
    time_penalty = min(int(wall_time / 30), 5)
    score.efficiency = max(0.0, 15.0 - retry_penalty - time_penalty)

    return score
