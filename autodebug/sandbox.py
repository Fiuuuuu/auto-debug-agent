#!/usr/bin/env python3
"""
sandbox.py — Sandbox: directory-level isolation for the Fixer.

The Fixer only ever sees and modifies .debug/sandbox/<filename>.
The original file is untouched until the user explicitly confirms.

Lifecycle:
  sandbox.setup()            — copy original → sandbox/
  fixer runs, edits sandbox  — sandbox/ diverges from original
  verifier confirms PASS     — user prompted
  sandbox.apply_to_original()— copy sandbox → original (if approved)
  sandbox.discard()          — rm -rf sandbox/ on reject or failure
"""
import shutil
from pathlib import Path

from .config import DEBUG_DIR


class Sandbox:
    def __init__(self, target: Path):
        self.original     = target.resolve()
        self.sandbox_dir  = DEBUG_DIR / "sandbox"
        self.sandbox_file = self.sandbox_dir / target.name

    def setup(self) -> None:
        self.sandbox_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.original, self.sandbox_file)
        print(f"  \033[33m[sandbox]\033[0m copied {self.original.name} → {self.sandbox_dir}")

    def apply_to_original(self) -> None:
        shutil.copy2(self.sandbox_file, self.original)
        print(f"  \033[32m[sandbox]\033[0m fix applied to original: {self.original}")

    def discard(self) -> None:
        shutil.rmtree(self.sandbox_dir, ignore_errors=True)
        print("  \033[33m[sandbox]\033[0m discarded")
