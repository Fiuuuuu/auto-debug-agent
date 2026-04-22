#!/usr/bin/env python3
"""
main.py — CLI entry point and Orchestrator for the Auto-Debug Agent.

This file is intentionally thin: it only contains the CLI loop and the
orchestrator function that sequences the four phase agents.  All other
logic lives in dedicated modules:

    agent/config.py    — WORKDIR, client, MODEL, directory constants
    agent/protocol.py  — TeamProtocol dataclass + message bus
    agent/tasks.py     — phase task board (.debug/tasks.json)
    agent/memory.py    — FixMemory: cross-session error→fix store
    agent/sandbox.py   — Sandbox: isolated file copy for the Fixer
    agent/tools.py     — all 11 tool implementations + per-agent schema lists
    agent/skills.py    — LOG_PARSER / STATIC_ANALYSIS / FIXER skill strings
    agent/pipeline.py  — run_subagent() + four phase-agent functions

Pipeline:
    [User: "debug <file>"]
           │
           ▼
    ┌─────────────┐  error_info  ┌─────────────┐
    │  Reproducer │─────────────►│   Analyst   │
    └─────────────┘              └──────┬──────┘
                                        │ root_cause
                                        ▼
    ┌─────────────┐  test_result ┌─────────────┐
    │  Verifier   │◄─────────────│    Fixer    │
    └─────────────┘              └─────────────┘

Run:  python main.py
Docs: see GUIDE.md
"""
import json
import time
from pathlib import Path

from autodebug.config import WORKDIR, BUS_DIR
from autodebug.protocol import TeamProtocol, bus_write
from autodebug.sandbox import Sandbox
from autodebug.tasks import PHASES, tasks_load, tasks_save, tasks_update
from autodebug.pipeline import MEMORY, reproducer_agent, analyst_agent, fixer_agent, verifier_agent


# ── Summary printer ───────────────────────────────────────────────────────────
def _print_summary(header: str, text: str, color: str = "\033[0m", max_lines: int = 8) -> None:
    """
    Strip Markdown syntax and print a clean indented summary box.

    Removes fenced code blocks, heading markers, bold/italic markers, and
    horizontal rules, then prints at most `max_lines` non-empty lines inside
    a thin border.
    """
    import re
    # Drop fenced code blocks entirely (``` ... ```)
    text = re.sub(r"```[\s\S]*?```", "", text)
    # Drop heading markers, bold/italic, inline code, horizontal rules
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"^---+$", "", text, flags=re.MULTILINE)

    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    shown = lines[:max_lines]
    omitted = len(lines) - len(shown)

    print(f"\n  {color}╔═ {header} {'═' * max(0, 44 - len(header))}╗\033[0m")
    for line in shown:
        # Truncate very long lines
        display = line[:100] + ("…" if len(line) > 100 else "")
        print(f"  {color}║\033[0m  {display}")
    if omitted:
        print(f"  {color}║\033[0m  \033[2m… {omitted} more line(s) — see .debug/bus/ for full output\033[0m")
    print(f"  {color}╚{'═' * 48}╝\033[0m\n")


# ── Permission gate ──────────────────────────────────────────────────────────
def ask_permission(msg: TeamProtocol) -> bool:
    print("\n\033[33m╔══════════════════════════════════════════╗\033[0m")
    print("\033[33m║        Permission Required          ║\033[0m")
    print("\033[33m╚══════════════════════════════════════════╝\033[0m")
    print(f"\033[36mTarget    :\033[0m {msg.target_file}")
    print(f"\033[36mRoot cause:\033[0m {msg.root_cause[:300]}")
    print(f"\033[36mProposed  :\033[0m {msg.patch_desc[:300]}")
    return input("\n\033[33mApply fix? [y/N]: \033[0m").strip().lower() == "y"


# ── Orchestrator ────────────────────────────────────────────────────────────
def run_debug_pipeline(
    target_file: str,
    max_fix_attempts: int = 2,
    auto_approve: bool = False,
) -> dict:
    """
    Run the four-phase debug pipeline.

    Returns a result dict:
        status      : "no_bug" | "ok" | "failed" | "rejected"
        msg         : final TeamProtocol object
        sandbox     : Sandbox (caller owns apply / discard)
        wall_time   : float seconds
        retry_count : int
    """
    import time as _time
    _t0 = _time.monotonic()

    target = Path(target_file)
    if not target.exists():
        print(f"\033[31mFile not found: {target_file}h\033[0m")
        return {"status": "error", "msg": None, "sandbox": None, "wall_time": 0.0, "retry_count": 0}

    print(f"\n\033[36m{'━' * 50}\033[0m")
    print(f"\033[36m  Auto-Debug Pipeline → {target.name}\033[0m")
    print(f"\033[36m{'━' * 50}\033[0m\n")

    tasks_save({p: "pending" for p in PHASES})

    # Phase 1: Reproduce
    print("\n\033[32m▶ Phase 1: Reproducer\033[0m")
    tasks_update("reproduce", "in_progress")
    msg = reproducer_agent(target_file)
    bus_write(msg)
    tasks_update("reproduce", "done")

    if msg.status == "skip":
        print("\033[32m✓ No error detected. Nothing to fix.\033[0m")
        for p in ("analyse", "fix", "verify"):
            tasks_update(p, "skipped")
        return {"status": "no_bug", "msg": msg, "sandbox": None,
                "wall_time": _time.monotonic() - _t0, "retry_count": 0}

    _print_summary("Error detected", msg.error_info, color="\033[31m")

    # Phase 2: Analyse
    print("\n\033[32m▶ Phase 2: Analyst\033[0m")
    tasks_update("analyse", "in_progress")
    msg = analyst_agent(msg)
    bus_write(msg)
    tasks_update("analyse", "done")
    _print_summary("Root cause", msg.root_cause, color="\033[36m")

    # Sandbox setup
    sandbox = Sandbox(target)
    sandbox.setup()

    # Phase 3+4 with autonomous retry
    for attempt in range(1, max_fix_attempts + 1):
        msg.retry_count = attempt - 1

        print(f"\n\033[32m▶ Phase 3: Fixer  (attempt {attempt}/{max_fix_attempts})\033[0m")
        tasks_update("fix", "in_progress")
        msg = fixer_agent(msg, sandbox)
        bus_write(msg)
        tasks_update("fix", "done")

        approved = True
        if not auto_approve:
            approved = ask_permission(msg)
        if not approved:
            print("\033[33mFix rejected by user. Discarding sandbox.\033[0m")
            sandbox.discard()
            tasks_update("verify", "skipped")
            return {"status": "rejected", "msg": msg, "sandbox": None,
                    "wall_time": _time.monotonic() - _t0, "retry_count": attempt - 1}

        print(f"\n\033[32m▶ Phase 4: Verifier  (attempt {attempt}/{max_fix_attempts})\033[0m")
        tasks_update("verify", "in_progress")
        msg = verifier_agent(msg, sandbox)
        bus_write(msg)

        if msg.status == "ok":
            tasks_update("verify", "done")
            print(f"\n  \033[32m✓ PASS\033[0m\n")
            MEMORY.save(
                error_signature=msg.error_info[:500],
                root_cause=msg.root_cause[:500],
                fix_summary=msg.patch_desc[:500],
            )
            print("\033[32m[Memory]\033[0m Fix pattern saved for future sessions.")
            if not auto_approve:
                if input("\n\033[33mCopy fix to original file? [y/N]: \033[0m").strip().lower() == "y":
                    sandbox.apply_to_original()
                else:
                    print("Fix kept in sandbox only. Original unchanged.")
            return {"status": "ok", "msg": msg, "sandbox": sandbox,
                    "wall_time": _time.monotonic() - _t0, "retry_count": attempt - 1}

        tasks_update("verify", "failed")
        print(f"\n  \033[31m✗ FAIL\033[0m  {msg.test_result[:200]}\n")
        if attempt < max_fix_attempts:
            print("  Retrying with updated context...")
            msg.root_cause += f"\n\n[Retry {attempt}] Previous fix failed:\n{msg.test_result}"

    sandbox.discard()
    print(f"\033[31m✗ Pipeline failed after {max_fix_attempts} attempts.\033[0m")
    print("  Sandbox discarded. Original file unchanged.")
    return {"status": "failed", "msg": msg, "sandbox": None,
            "wall_time": _time.monotonic() - _t0, "retry_count": max_fix_attempts - 1}



# ── CLI ───────────────────────────────────────────────────────────────────────
HELP = """
Commands:
  debug <file>     Run the full 4-agent pipeline on a Python file
  memory           Show remembered fix patterns (last 10)
  tasks            Show current task board
  /history         Show message bus events (last 5)
  help             Show this help
  q / exit         Quit
"""


def show_memory() -> None:
    entries = MEMORY._entries()
    if not entries:
        print("  (no memories yet)")
        return
    for e in entries[-10:]:
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(e["ts"]))
        print(f"  [{ts}] {e['error_signature'][:60]} → {e['fix_summary'][:60]}")


def show_history() -> None:
    if not BUS_DIR.exists():
        print("  (no bus events yet)")
        return
    for f in sorted(BUS_DIR.glob("*.json"))[-5:]:
        data = json.loads(f.read_text())
        print(f"  {f.name}: phase={data.get('phase')} status={data.get('status')}")


if __name__ == "__main__":
    print("\033[36m")
    print("╔══════════════════════════════════════════╗")
    print("║          Auto-Debug Agent  v1.0          ║")
    print("║  Reproducer → Analyst → Fixer → Verify   ║")
    print("╚══════════════════════════════════════════╝")
    print("\033[0m")
    print(f"Working dir: {WORKDIR}")
    mem_count = len(MEMORY._entries())
    if mem_count:
        print(f"\033[33m[Memory]\033[0m {mem_count} past fix(es) loaded.")
    print('Type "help" for commands.\n')

    while True:
        try:
            query = input("\033[36mdebug >> \033[0m").strip()
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
        elif query == "tasks":
            t = tasks_load()
            for phase, status in t.items():
                icon = {"pending": "○", "in_progress": "►", "done": "✓",
                        "failed": "✗", "skipped": "–"}.get(status, "?")
                print(f"  {icon} {phase}: {status}")
        elif query == "/history":
            show_history()
        elif query.startswith("debug "):
            run_debug_pipeline(query[6:].strip())
        else:
            print(f"Unknown command: {query}  (type 'help')")
        print()
