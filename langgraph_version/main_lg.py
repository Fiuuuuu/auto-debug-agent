#!/usr/bin/env python3
"""
main_lg.py — CLI entry point for the LangGraph Auto-Debug Agent.

This version keeps the LangGraph graph, checkpointing, and interrupt-based
permission gate, but its terminal output and end-of-run behavior intentionally
match main.py.

Run from the auto-debug-agent/ directory:
    python langgraph_version/main_lg.py

Commands
--------
  debug <file>   Run the full 4-agent LangGraph pipeline
  memory         Show remembered fix patterns (last 10)
  graph          Print graph topology as Mermaid diagram
  tasks          Show current task board
  /history       Show message bus events (last 5)
  help           Show this help
  q / exit       Quit
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Ensure autodebug and langgraph_version are importable when run as a script.
sys.path.insert(0, str(Path(__file__).parent.parent))

from langgraph.types import Command

from autodebug.config import BUS_DIR, WORKDIR
from autodebug.pipeline import MEMORY
from autodebug.sandbox import Sandbox
from autodebug.tasks import PHASES, tasks_load, tasks_save
from autodebug.ui import ask_permission as ask_user_permission
from langgraph_version.graph import app, draw_pipeline_mermaid


# ── Unique thread id per debug session ───────────────────────────────────────
_SESSION_COUNTER = 0


def _new_thread_id() -> str:
    global _SESSION_COUNTER
    _SESSION_COUNTER += 1
    return f"debug-session-{_SESSION_COUNTER}"


# ── Core pipeline runner ─────────────────────────────────────────────────────
def run_debug(target_file: str, auto_approve: bool = False) -> dict:
    """
    Run the LangGraph debug pipeline.

    Returns a result dict shaped like main.py's runner:
        status      : "no_bug" | "ok" | "failed" | "rejected" | "error"
        state       : final LangGraph state values
        sandbox     : Sandbox when a successful sandbox remains available
        wall_time   : float seconds
        retry_count : verifier failures so far
    """
    started = time.monotonic()
    path = Path(target_file)
    if not path.exists():
        print(f"\033[31mFile not found: {target_file}\033[0m")
        return {"status": "error", "state": {}, "sandbox": None, "wall_time": 0.0, "retry_count": 0}

    config = {"configurable": {"thread_id": _new_thread_id()}}

    print(f"\n\033[36m{'━' * 50}\033[0m")
    print(f"\033[36m  LangGraph Auto-Debug → {path.name}\033[0m")
    print(f"\033[36m{'━' * 50}\033[0m\n")

    tasks_save({phase: "pending" for phase in PHASES})

    app.invoke(
        {
            "target_file": target_file,
            "retry_count": 0,
            "approved": False,
            "issues": [],
        },
        config,
    )

    # The graph may pause multiple times, once per fixer/verifier cycle.
    while True:
        snapshot = app.get_state(config)
        if not snapshot.next:
            break

        interrupts = []
        for task in snapshot.tasks:
            interrupts.extend(getattr(task, "interrupts", []))

        if not interrupts:
            print("\033[31mGraph suspended without an interrupt payload.\033[0m")
            break

        payload = interrupts[0].value
        if auto_approve:
            answer = "y"
        else:
            approved = ask_user_permission(
                payload.get("target_file", target_file),
                payload.get("root_cause", ""),
                payload.get("patch_desc", ""),
            )
            answer = "y" if approved else "n"

        app.invoke(Command(resume=answer), config)

    final = app.get_state(config).values
    status = final.get("status", "")
    retry_count = int(final.get("retry_count", 0) or 0)
    sandbox: Sandbox | None = Sandbox(path)
    result_status = status

    if status == "ok":
        if sandbox.sandbox_file.exists() and not auto_approve:
            answer = input("\n\033[33mCopy fix to original file? [y/N]: \033[0m").strip()
            if answer.lower() == "y":
                sandbox.apply_to_original()
            else:
                print("Fix kept in sandbox only. Original unchanged.")
        result_status = "ok"

    elif status == "skip":
        result_status = "no_bug"
        sandbox = None

    elif status == "rejected" or final.get("approved") is False:
        print("\033[33mFix rejected. Original file unchanged.\033[0m")
        result_status = "rejected"
        sandbox = None

    else:
        if sandbox.sandbox_file.exists():
            sandbox.discard()
        print(f"\033[31m✗ Pipeline failed after {retry_count} attempts.\033[0m")
        print("  Sandbox discarded. Original file unchanged.")
        result_status = "failed"
        sandbox = None

    return {
        "status": result_status,
        "state": dict(final),
        "sandbox": sandbox,
        "wall_time": time.monotonic() - started,
        "retry_count": retry_count,
    }


# ── Helper commands ───────────────────────────────────────────────────────────
def show_memory() -> None:
    entries = MEMORY._entries()
    if not entries:
        print("  (no memories yet)")
        return
    for entry in entries[-10:]:
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(entry["ts"]))
        print(f"  [{ts}] {entry['error_signature'][:60]} → {entry['fix_summary'][:60]}")


def show_graph() -> None:
    """Print the graph topology as a Mermaid diagram."""
    print(draw_pipeline_mermaid())


def show_history() -> None:
    if not BUS_DIR.exists():
        print("  (no bus events yet)")
        return
    for f in sorted(BUS_DIR.glob("*.json"))[-5:]:
        data = json.loads(f.read_text())
        print(f"  {f.name}: phase={data.get('phase')} status={data.get('status')}")


def show_tasks() -> None:
    for phase, status in tasks_load().items():
        icon = {
            "pending": "○",
            "in_progress": "►",
            "done": "✓",
            "failed": "✗",
            "skipped": "–",
        }.get(status, "?")
        print(f"  {icon} {phase}: {status}")


# ── CLI ───────────────────────────────────────────────────────────────────────
HELP = """
Commands:
  debug <file>   Run the full 4-agent LangGraph pipeline on a Python file
  memory         Show remembered fix patterns (last 10)
  graph          Print graph topology as Mermaid diagram
  tasks          Show current task board
  /history       Show message bus events (last 5)
  help           Show this help
  q / exit       Quit
"""


if __name__ == "__main__":
    print("\033[36m")
    print("╔══════════════════════════════════════════╗")
    print("║   Auto-Debug Agent  v2.0  (LangGraph)   ║")
    print("║  Reproducer → Analyst → Fixer → Verify  ║")
    print("╚══════════════════════════════════════════╝")
    print("\033[0m")

    print(f"Working dir: {WORKDIR}")
    mem_count = len(MEMORY._entries())
    if mem_count:
        print(f"\033[33m[Memory]\033[0m {mem_count} past fix(es) loaded.")
    print('Type "help" for commands.\n')

    while True:
        try:
            query = input("\033[36mdebug-lg >> \033[0m").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not query:
            continue
        if query in ("q", "exit"):
            print("Bye.")
            break
        elif query == "help":
            print(HELP)
        elif query == "memory":
            show_memory()
        elif query == "graph":
            show_graph()
        elif query == "tasks":
            show_tasks()
        elif query == "/history":
            show_history()
        elif query.startswith("debug "):
            run_debug(query[6:].strip())
        else:
            print(f"Unknown command: {query!r}  (type 'help')")
        print()
