#!/usr/bin/env python3
"""
memory.py — FixMemory: cross-session storage for past bug fixes.

Storage: .debug/memory/index.jsonl
Each line: {ts, error_signature, root_cause, fix_summary}

Lookup uses keyword overlap (≥ 3 matching words) so similar tracebacks
(same exception type, same filename, same function) are recognised
without needing a vector database.

When a match is found, prompt_section() injects it into the Analyst's
system prompt as a starting hypothesis.
"""
import json
import re
import time
from typing import Optional

from .config import MEM_DIR


class FixMemory:
    def __init__(self):
        MEM_DIR.mkdir(parents=True, exist_ok=True)
        self.index_path = MEM_DIR / "index.jsonl"
        if not self.index_path.exists():
            self.index_path.write_text("")

    def _entries(self) -> list[dict]:
        entries = []
        for line in self.index_path.read_text().splitlines():
            try:
                entries.append(json.loads(line))
            except Exception:
                pass
        return entries

    def lookup(self, error_snippet: str) -> Optional[dict]:
        """Return best matching past fix if keyword overlap ≥ 3."""
        words = set(re.findall(r"\w+", error_snippet.lower()))
        best, best_score = None, 0
        for e in self._entries():
            sig = set(re.findall(r"\w+", e.get("error_signature", "").lower()))
            score = len(words & sig)
            if score > best_score:
                best_score, best = score, e
        return best if best_score >= 3 else None

    def save(self, error_signature: str, root_cause: str, fix_summary: str) -> None:
        entry = {
            "ts":              time.time(),
            "error_signature": error_signature[:500],
            "root_cause":      root_cause[:500],
            "fix_summary":     fix_summary[:500],
        }
        with self.index_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    def prompt_section(self, error_snippet: str) -> str:
        """Return a memory block to inject into a system prompt, or ''."""
        hit = self.lookup(error_snippet)
        if not hit:
            return ""
        return (
            "\n\n# Recalled fix from memory\n"
            f"Error pattern : {hit['error_signature']}\n"
            f"Root cause    : {hit['root_cause']}\n"
            f"Previous fix  : {hit['fix_summary']}\n"
            "(Treat this as a starting hypothesis — verify against current code.)\n"
        )
