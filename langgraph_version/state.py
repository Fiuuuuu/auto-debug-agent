#!/usr/bin/env python3
"""
state.py — LangGraph State definition for the Auto-Debug pipeline.

Replaces the TeamProtocol dataclass with a TypedDict that LangGraph can
checkpoint, snapshot, and pass between nodes automatically.

Field-to-phase mapping (mirrors TeamProtocol):
  target_file  : set by CLI / entry
  error_info   : written by Reproducer
  root_cause   : written by Analyst  (appended on retry by Verifier)
  fix_plan     : written by Fixer
  patch_desc   : written by Fixer
  test_result  : written by Verifier
  status       : "ok" | "error" | "skip"
  retry_count  : incremented by Verifier after each failed attempt
  approved     : set by PermissionNode after human interrupt
"""
from typing import TypedDict


class DebugState(TypedDict, total=False):
    # ── Input ────────────────────────────────────────────────────────────────
    target_file: str        # path to the file being debugged

    # ── Phase outputs ────────────────────────────────────────────────────────
    error_info:  str        # full traceback / "No error found" (Reproducer)
    root_cause:  str        # diagnosis + fix strategy (Analyst)
    fix_plan:    str        # markdown TODO list (Fixer)
    patch_desc:  str        # human-readable change summary (Fixer)
    test_result: str        # pytest / execution output (Verifier)

    # ── Control flow ─────────────────────────────────────────────────────────
    status:      str        # "ok" | "error" | "skip"
    retry_count: int        # fixer attempts so far (0-based)
    approved:    bool       # True if user approved the fix
