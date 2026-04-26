#!/usr/bin/env python3
"""
nodes.py — Five LangGraph node functions for the Auto-Debug pipeline.

Each node:
  1. Converts DebugState → TeamProtocol  (helper: _to_msg)
  2. Calls the corresponding agent function from autodebug/pipeline.py
  3. Converts the result back to a partial DebugState dict  (helper: _from_msg)
  4. Returns only the fields it changed (LangGraph merges them into State)

Nodes:
  reproducer_node  — Phase 1: run file, capture traceback
  analyst_node     — Phase 2: diagnose root cause, set up sandbox
  fixer_node       — Phase 3: apply patch in sandbox
  permission_node  — Gate:    interrupt() for human approval
  verifier_node    — Phase 4: confirm fix, handle retry bookkeeping

All autodebug.* modules (tools, sandbox, memory, skills, pipeline) are
imported directly — zero duplication.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure autodebug package is importable when running as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

from langgraph.types import interrupt

from autodebug.protocol import TeamProtocol, bus_write
from autodebug.sandbox import Sandbox
from autodebug.tasks import tasks_update
from autodebug.ui import print_summary
from autodebug.pipeline import (
    reproducer_agent,
    analyst_agent,
    fixer_agent,
    verifier_agent,
    MEMORY,
)

from .state import DebugState


# Keep the node display aligned with graph.py's retry limit.
MAX_FIX_ATTEMPTS = 4


# ── State ↔ TeamProtocol helpers ─────────────────────────────────────────────

def _to_msg(state: DebugState) -> TeamProtocol:
    """Build a TeamProtocol from the current graph state."""
    return TeamProtocol(
        phase       = "",
        status      = state.get("status", "ok"),        # type: ignore[arg-type]
        target_file = state.get("target_file", ""),     # type: ignore[arg-type]
        error_info  = state.get("error_info", ""),      # type: ignore[arg-type]
        root_cause  = state.get("root_cause", ""),      # type: ignore[arg-type]
        issues      = state.get("issues", []),          # type: ignore[arg-type]
        fix_plan    = state.get("fix_plan", ""),        # type: ignore[arg-type]
        patch_desc  = state.get("patch_desc", ""),      # type: ignore[arg-type]
        test_result = state.get("test_result", ""),     # type: ignore[arg-type]
        retry_count = state.get("retry_count", 0),      # type: ignore[arg-type]
    )


def _from_msg(msg: TeamProtocol) -> dict:
    """Extract only the fields that a TeamProtocol carries back to State."""
    return {
        "status":      msg.status,
        "error_info":  msg.error_info,
        "root_cause":  msg.root_cause,
        "issues":      msg.issues,
        "fix_plan":    msg.fix_plan,
        "patch_desc":  msg.patch_desc,
        "test_result": msg.test_result,
        "retry_count": msg.retry_count,
    }


def _make_sandbox(state: DebugState) -> Sandbox:
    """Reconstruct Sandbox from the target_file path stored in state."""
    return Sandbox(Path(state["target_file"]))   # type: ignore[arg-type]


# ── Node 1: Reproducer ────────────────────────────────────────────────────────

def reproducer_node(state: DebugState) -> dict:
    """
    Run the target file, capture the full traceback.
    Sets: error_info, status ("ok" = has error, "skip" = clean).
    """
    print("\n\033[32m▶ Phase 1: Reproducer\033[0m")
    tasks_update("reproduce", "in_progress")
    msg = reproducer_agent(state["target_file"])    # type: ignore[arg-type]
    bus_write(msg)
    tasks_update("reproduce", "done")

    if msg.status == "skip":
        print("\033[32m✓ No error detected. Nothing to fix.\033[0m")
        for phase in ("analyse", "fix", "verify"):
            tasks_update(phase, "skipped")
    else:
        print_summary("Error detected", msg.error_info, color="\033[31m")

    return _from_msg(msg)


# ── Node 2: Analyst ───────────────────────────────────────────────────────────

def analyst_node(state: DebugState) -> dict:
    """
    Read source + error, identify root cause, propose fix strategy.
    Also sets up the sandbox (copy original → .debug/sandbox/) so the
    sandbox exists before fixer_node runs.
    Sets: root_cause (and fix_plan, patch_desc empty at this point).
    """
    print("\n\033[32m▶ Phase 2: Analyst\033[0m")
    tasks_update("analyse", "in_progress")
    msg = analyst_agent(_to_msg(state))
    bus_write(msg)
    tasks_update("analyse", "done")
    print_summary("Root cause", msg.root_cause, color="\033[36m")

    # Set up sandbox once here, before the fixer/verifier retry loop.
    # LangGraph checkpoint ensures analyst_node is never re-run, so
    # sandbox.setup() is called exactly once per pipeline run.
    #
    # On retry: fixer_node reconstructs Sandbox via _make_sandbox() but does
    # NOT call setup() again — intentionally. The second Fixer attempt starts
    # from the file left by the first attempt (already partially patched),
    # which lets it build on the previous edit rather than restart from scratch.
    # If you want each attempt to start from the original, call sandbox.setup()
    # inside fixer_node instead.
    sandbox = _make_sandbox(state)
    sandbox.setup()

    return _from_msg(msg)


# ── Node 3: Fixer ─────────────────────────────────────────────────────────────

def fixer_node(state: DebugState) -> dict:
    """
    Apply a minimal fix to the sandbox copy of the file.
    All writes are confined to .debug/sandbox/ — original is untouched.
    Sets: fix_plan, patch_desc.
    """
    attempt = state.get("retry_count", 0) + 1   # type: ignore[operator]
    print(f"\n\033[32m▶ Phase 3: Fixer  (attempt {attempt}/{MAX_FIX_ATTEMPTS})\033[0m")
    tasks_update("fix", "in_progress")

    # _make_sandbox() reconstructs the Sandbox object from the path in state.
    # setup() is NOT called here — see analyst_node for the rationale.
    sandbox = _make_sandbox(state)
    msg = fixer_agent(_to_msg(state), sandbox)
    bus_write(msg)
    tasks_update("fix", "done")
    print_summary("Patch applied", msg.patch_desc, color="\033[33m")

    return _from_msg(msg)


# ── Node 4: Permission gate ───────────────────────────────────────────────────

def permission_node(state: DebugState) -> dict:
    """
    Pause the graph and ask the human whether to apply the proposed fix.

    LangGraph's interrupt() suspends execution here and returns control to
    the caller.  The caller resumes with Command(resume="y" | "n").

    Sets: approved (bool).
    """
    # interrupt() serialises this dict and surfaces it to the caller.
    # Execution resumes when the caller calls app.invoke(Command(resume=answer)).
    answer: str = interrupt({
        "target_file": state.get("target_file", ""),
        "root_cause":  state.get("root_cause", ""),
        "patch_desc":  state.get("patch_desc", ""),
    })

    approved = str(answer).strip().lower() == "y"
    if not approved:
        print("\033[33mFix rejected by user. Sandbox will be discarded.\033[0m")
        _make_sandbox(state).discard()
        tasks_update("verify", "skipped")

    result = {"approved": approved}
    if not approved:
        result["status"] = "rejected"
    return result


# ── Node 5: Verifier ──────────────────────────────────────────────────────────

def verifier_node(state: DebugState) -> dict:
    """
    Run the patched sandbox file and tests.
    On success: saves fix pattern to FixMemory.
    On failure: increments retry_count and appends failure info to
                root_cause so the next Fixer attempt has more context.
    Sets: test_result, status, and (on failure) root_cause + retry_count.
    """
    attempt = state.get("retry_count", 0) + 1   # type: ignore[operator]
    print(f"\n\033[32m▶ Phase 4: Verifier  (attempt {attempt}/{MAX_FIX_ATTEMPTS})\033[0m")
    tasks_update("verify", "in_progress")

    sandbox = _make_sandbox(state)
    msg = verifier_agent(_to_msg(state), sandbox)
    bus_write(msg)

    result = _from_msg(msg)
    print_summary("Verification result", msg.test_result, color="\033[32m" if msg.status == "ok" else "\033[31m")

    if msg.status == "ok":
        tasks_update("verify", "done")
        print(f"\n  \033[32m✓ PASS\033[0m\n")
        MEMORY.save(
            error_signature = msg.error_info[:500],
            root_cause      = msg.root_cause[:500],
            fix_summary     = msg.patch_desc[:500],
        )
        print("\033[32m[Memory]\033[0m Fix pattern saved for future sessions.")
    else:
        current_retry = state.get("retry_count", 0)     # type: ignore[assignment]
        tasks_update("verify", "failed")
        print(f"\n  \033[31m✗ FAIL\033[0m  {msg.test_result[:200]}\n")
        # Append failure detail so next Fixer has more context
        result["root_cause"] = (
            state.get("root_cause", "")                 # type: ignore[operator]
            + f"\n\n[Retry {current_retry + 1}] Previous fix failed:\n{msg.test_result}"
        )
        result["retry_count"] = current_retry + 1
        if current_retry + 1 < MAX_FIX_ATTEMPTS:
            print("  Retrying with updated context...")
        else:
            result["status"] = "failed"

    return result
