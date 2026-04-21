#!/usr/bin/env python3
"""
main_lg.py — CLI entry point for the LangGraph Auto-Debug Agent.

Run from the auto-debug-agent/ directory:
    python langgraph_version/main_lg.py

How interrupt / human-in-the-loop works
----------------------------------------
1. app.invoke(initial_state, config)
   → graph runs Reproducer → Analyst → Fixer → permission_node
   → permission_node calls interrupt() and suspends the graph
   → invoke() returns with the current state (graph is NOT done)

2. We detect suspension via app.get_state(config).next != ()
   → read the interrupt payload (root_cause, patch_desc)
   → print the permission banner and ask the user

3. app.invoke(Command(resume=answer), config)
   → graph resumes from permission_node with the user's answer
   → permission_node sets approved, then routes to Verifier or END
   → if Verifier fails and retry_count < MAX, graph loops back to Fixer
     which triggers another interrupt → handled by the same while-loop

4. After graph finishes (snapshot.next == ()):
   → if status == "ok", offer to copy sandbox → original

Commands
--------
  debug <file>   Run the full 4-agent LangGraph pipeline
  memory         Show remembered fix patterns (last 10)
  graph          Print graph topology as Mermaid diagram
  help           Show this help
  q / exit       Quit
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Ensure autodebug and langgraph_version are importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from langgraph.types import Command

from autodebug.pipeline import MEMORY
from autodebug.sandbox import Sandbox
from langgraph_version.graph import app


# ── Unique thread id per debug session ───────────────────────────────────────
_SESSION_COUNTER = 0


def _new_thread_id() -> str:
    global _SESSION_COUNTER
    _SESSION_COUNTER += 1
    return f"debug-session-{_SESSION_COUNTER}"


# ── Core pipeline runner ─────────────────────────────────────────────────────

def run_debug(target_file: str) -> None:
    path = Path(target_file)
    if not path.exists():
        print(f"\033[31mFile not found: {target_file}\033[0m")
        return

    config = {"configurable": {"thread_id": _new_thread_id()}}

    print(f"\n\033[36m{'━' * 50}\033[0m")
    print(f"\033[36m  LangGraph Auto-Debug → {path.name}\033[0m")
    print(f"\033[36m{'━' * 50}\033[0m\n")

    # ── Initial invocation ────────────────────────────────────────────────────
    app.invoke(
        {"target_file": target_file, "retry_count": 0, "approved": False},
        config,
    )

    # ── Handle permission interrupt(s) ────────────────────────────────────────
    # The graph may pause multiple times (once per fixer/verifier cycle).
    while True:
        snapshot = app.get_state(config)

        # Graph finished — no more nodes to run
        if not snapshot.next:
            break

        # Extract the interrupt payload surfaced by permission_node
        interrupts = []
        for task in snapshot.tasks:
            interrupts.extend(getattr(task, "interrupts", []))

        if not interrupts:
            # Suspended for another reason — shouldn't happen, but bail safely
            break

        data = interrupts[0].value  # dict from interrupt({...})

        print("\n\033[33m╔══════════════════════════════════════════╗\033[0m")
        print("\033[33m║        Permission Required               ║\033[0m")
        print("\033[33m╚══════════════════════════════════════════╝\033[0m")
        print(f"\033[36mTarget    :\033[0m {data.get('target_file', target_file)}")
        print(f"\033[36mRoot cause:\033[0m {data.get('root_cause', '')}")
        print(f"\033[36mProposed  :\033[0m {data.get('patch_desc', '')}")

        answer = input("\n\033[33mApply fix? [y/N]: \033[0m").strip()

        # Resume the graph with the user's answer
        app.invoke(Command(resume=answer), config)

    # ── Post-pipeline actions ─────────────────────────────────────────────────
    final   = app.get_state(config).values
    status  = final.get("status", "")

    if status == "ok":
        sandbox = Sandbox(path)
        if sandbox.sandbox_file.exists():
            answer = input(
                "\n\033[33mCopy fix to original file? [y/N]: \033[0m"
            ).strip()
            if answer.lower() == "y":
                sandbox.apply_to_original()
            else:
                print("Fix kept in sandbox only. Original unchanged.")

    elif status == "skip":
        # Already printed by reproducer_node
        pass

    elif final.get("approved") is False:
        print("\033[33mFix rejected. Original file unchanged.\033[0m")

    else:
        print(
            f"\033[31m✗ Pipeline ended: status={status!r}. "
            "Original file unchanged.\033[0m"
        )


# ── Helper commands ───────────────────────────────────────────────────────────

def show_memory() -> None:
    entries = MEMORY._entries()
    if not entries:
        print("  (no memories yet)")
        return
    for e in entries[-10:]:
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(e["ts"]))
        print(f"  [{ts}] {e['error_signature'][:60]} → {e['fix_summary'][:60]}")


def show_graph() -> None:
    """Print the graph topology as a Mermaid diagram."""
    try:
        print(app.get_graph().draw_mermaid())
    except Exception as e:
        print(f"  (could not render graph: {e})")


# ── CLI ───────────────────────────────────────────────────────────────────────

HELP = """
Commands:
  debug <file>   Run the full 4-agent LangGraph pipeline on a Python file
  memory         Show remembered fix patterns (last 10)
  graph          Print graph topology as Mermaid diagram
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
        elif query.startswith("debug "):
            run_debug(query[6:].strip())
        else:
            print(f"Unknown command: {query!r}  (type 'help')")
        print()
