#!/usr/bin/env python3
"""
tasks.py — Phase task board backed by .debug/tasks.json.

Statuses: pending → in_progress → done | failed | skipped
"""
import json
from .config import DEBUG_DIR, TASK_FILE

PHASES = ["reproduce", "analyse", "fix", "verify"]


def tasks_save(tasks: dict) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    TASK_FILE.write_text(json.dumps(tasks, indent=2))


def tasks_load() -> dict:
    if TASK_FILE.exists():
        return json.loads(TASK_FILE.read_text())
    return {p: "pending" for p in PHASES}


def tasks_update(phase: str, status: str) -> None:
    t = tasks_load()
    t[phase] = status
    tasks_save(t)
    print(f"  \033[33m[task]\033[0m {phase} → {status}")
