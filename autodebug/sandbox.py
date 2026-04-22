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

from .config import DEBUG_DIR, WORKDIR


class Sandbox:
    def __init__(self, target: Path):
        self.original    = target.resolve()
        self.sandbox_dir = DEBUG_DIR / "sandbox"

        # Mirror the file's position relative to WORKDIR inside the sandbox.
        # e.g. WORKDIR/sample_bugs/bug1.py  →  sandbox/sample_bugs/bug1.py
        # Falls back to just the basename if the file is outside WORKDIR.
        try:
            rel = self.original.relative_to(WORKDIR)
        except ValueError:
            rel = Path(self.original.name)

        self.sandbox_file = self.sandbox_dir / rel
        # The sub-directory inside sandbox that mirrors the target's parent
        self._sandbox_subdir = self.sandbox_file.parent

    def setup(self) -> None:
        self._sandbox_subdir.mkdir(parents=True, exist_ok=True)

        # Copy the target file
        shutil.copy2(self.original, self.sandbox_file)

        # Also copy sibling resource files (non-.py, non-pycache) from the
        # same directory so the script can open relative paths (e.g. config.json)
        for sibling in self.original.parent.iterdir():
            if sibling == self.original:
                continue
            if sibling.is_file() and "__pycache__" not in str(sibling):
                shutil.copy2(sibling, self._sandbox_subdir / sibling.name)

        rel_display = self.sandbox_file.relative_to(self.sandbox_dir)
        print(f"  \033[33m[sandbox]\033[0m copied {rel_display} → {self.sandbox_dir}")

    def apply_to_original(self) -> None:
        shutil.copy2(self.sandbox_file, self.original)
        print(f"  \033[32m[sandbox]\033[0m fix applied to original: {self.original}")

    def discard(self) -> None:
        shutil.rmtree(self.sandbox_dir, ignore_errors=True)
        print("  \033[33m[sandbox]\033[0m discarded")
