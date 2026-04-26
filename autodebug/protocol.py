#!/usr/bin/env python3
"""
protocol.py — TeamProtocol dataclass + message bus helpers.

Each pipeline phase reads the previous TeamProtocol, fills in its own
field, and writes a new one.  All messages are persisted to .debug/bus/
as individual JSON files so the pipeline is fully auditable.

Fields filled per phase:
  Reproducer  → error_info
  Analyst     → root_cause
  Fixer       → fix_plan, patch_desc
  Verifier    → test_result, status
"""
import json
import time
from dataclasses import dataclass, asdict, field
from typing import Optional

from .config import BUS_DIR


@dataclass
class TeamProtocol:
    phase:       str            # "reproduce" | "analyse" | "fix" | "verify"
    status:      str            # "ok" | "error" | "skip"
    target_file: str = ""
    error_info:  str = ""       # full traceback captured by Reproducer
    root_cause:  str = ""       # diagnosis written by Analyst
    issues:      list[dict] = field(default_factory=list)  # structured runtime issues found so far
    fix_plan:    str = ""       # markdown TODO list from Fixer
    patch_desc:  str = ""       # human-readable summary of changes made
    test_result: str = ""       # Verifier stdout/pass-fail report
    retry_count: int = 0        # how many Fixer retries so far
    notes:       str = ""       # free-text scratch space

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @staticmethod
    def from_json(s: str) -> "TeamProtocol":
        return TeamProtocol(**json.loads(s))


def bus_write(msg: TeamProtocol) -> None:
    """Append a phase message to .debug/bus/ (append-only, timestamped)."""
    BUS_DIR.mkdir(parents=True, exist_ok=True)
    ts   = int(time.time() * 1000)
    path = BUS_DIR / f"{ts}_{msg.phase}.json"
    path.write_text(msg.to_json())


def bus_read_latest(phase: str) -> Optional[TeamProtocol]:
    """Return the most recent persisted message for a given phase."""
    if not BUS_DIR.exists():
        return None
    files = sorted(BUS_DIR.glob(f"*_{phase}.json"))
    return TeamProtocol.from_json(files[-1].read_text()) if files else None
