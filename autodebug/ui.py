#!/usr/bin/env python3
"""
ui.py — Small shared terminal UI helpers.

Both the hand-written orchestrator and the LangGraph orchestrator should show
the same phase summaries and permission gate. Keeping these helpers here avoids
two slightly different copies drifting apart.
"""
from __future__ import annotations

import re


def strip_markdown(text: str, limit: int | None = None, join_lines: bool = False) -> str:
    """Remove noisy Markdown syntax before showing model text in the terminal."""
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"^---+$", "", text, flags=re.MULTILINE)

    if join_lines:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        text = " | ".join(lines)

    if limit is not None:
        text = text[:limit]
    return text


def print_summary(header: str, text: str, color: str = "\033[0m", max_lines: int = 8) -> None:
    """
    Print a clean indented summary box.

    Agent responses are often Markdown-heavy. The box is intentionally compact
    so the operator sees the important outcome without losing the full audit
    trail stored in .debug/bus/.
    """
    text = strip_markdown(text)
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    shown = lines[:max_lines]
    omitted = len(lines) - len(shown)

    print(f"\n  {color}╔═ {header} {'═' * max(0, 44 - len(header))}╗\033[0m")
    for line in shown:
        display = line[:100] + ("…" if len(line) > 100 else "")
        print(f"  {color}║\033[0m  {display}")
    if omitted:
        print(f"  {color}║\033[0m  \033[2m… {omitted} more line(s) — see .debug/bus/ for full output\033[0m")
    print(f"  {color}╚{'═' * 48}╝\033[0m\n")


def ask_permission(target_file: str, root_cause: str, patch_desc: str) -> bool:
    """Show the shared permission gate and return True only for an explicit y."""
    print("\n\033[33m╔══════════════════════════════════════════╗\033[0m")
    print("\033[33m║           Permission Required            ║\033[0m")
    print("\033[33m╚══════════════════════════════════════════╝\033[0m")
    print(f"\033[36mTarget    :\033[0m {target_file}")
    print(f"\033[36mRoot cause:\033[0m {strip_markdown(root_cause, limit=300, join_lines=True)}")
    print(f"\033[36mProposed  :\033[0m {strip_markdown(patch_desc, limit=300, join_lines=True)}")
    return input("\n\033[33mApply fix? [y/N]: \033[0m").strip().lower() == "y"
