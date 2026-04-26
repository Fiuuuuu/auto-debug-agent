"""
evals/reporting.py
------------------
Terminal output helpers for the eval harness.

The runner should produce data; this module decides how that data is displayed.
"""

from __future__ import annotations

from .scorer import DebugScore


C_RESET = "\033[0m"
C_CYAN = "\033[36m"
C_GREEN = "\033[32m"
C_RED = "\033[31m"
C_YELLOW = "\033[33m"
C_BOLD = "\033[1m"


def grade_colour(grade: str) -> str:
    return {
        "A": C_GREEN,
        "B": C_GREEN,
        "C": C_YELLOW,
        "D": C_YELLOW,
        "F": C_RED,
    }.get(grade, C_RESET)


def print_case_header(entry: dict) -> None:
    print(f"\n{C_CYAN}{'━' * 60}{C_RESET}")
    print(f"{C_BOLD}  [{entry['id']}]  {entry['file']}{C_RESET}")
    print(f"  Tags: {', '.join(entry['tags'])}   Bugs: {entry['bug_count']}")
    print(f"{C_CYAN}{'━' * 60}{C_RESET}")


def print_summary(results: list[tuple[str, DebugScore]]) -> None:
    print(f"\n{C_BOLD}{'━' * 60}")
    print("  EVALUATION SUMMARY")
    print(f"{'━' * 60}{C_RESET}")

    header = f"  {'ID':<10} {'Grade':>5} {'Total':>7} {'Correct':>9} {'Bugs':>8} {'Minimal':>9} {'Effic':>7}"
    print(header)
    print(f"  {'-' * 57}")

    totals = []
    for eid, score in results:
        gc = grade_colour(score.grade)
        print(
            f"  {eid:<10} "
            f"{gc}{score.grade:>5}{C_RESET} "
            f"{score.total:>7.1f} "
            f"{score.fix_correctness:>9.1f} "
            f"{score.bug_completeness:>8.1f} "
            f"{score.patch_minimality:>9.1f} "
            f"{score.efficiency:>7.1f}"
        )
        totals.append(score.total)

    print(f"  {'-' * 57}")
    avg = sum(totals) / len(totals) if totals else 0
    fixed = sum(1 for _, score in results if score.fix_correctness == 50.0)
    print(f"\n  Cases run   : {len(results)}")
    print(f"  Avg score   : {avg:.1f}/100")
    print(f"  Fix rate    : {fixed / max(len(results), 1) * 100:.0f}%  ({fixed}/{len(results)} files ran clean)")
    print(
        f"  Total bugs  : {sum(score.bugs_total for _, score in results)}   "
        f"Fixed: {sum(score.bugs_fixed for _, score in results)}"
    )
