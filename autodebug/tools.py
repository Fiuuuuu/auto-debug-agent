#!/usr/bin/env python3
"""
tools.py — All tool implementations + per-agent TOOLS schema lists.

Tool inventory (11 tools):
  ┌──────────────────┬────────────────────────────────────────────────────┐
  │ Tool             │ Description                                        │
  ├──────────────────┼────────────────────────────────────────────────────┤
  │ bash             │ Run any shell command                              │
  │ read_file        │ Read a file (with optional line limit)             │
  │ write_file       │ Write/overwrite a file                             │
  │ edit_file        │ Replace an exact substring in a file               │
  │ list_dir         │ List directory contents with file sizes            │
  │ search_code      │ Regex search within a single file                  │
  │ grep_files       │ Regex search across all files matching a glob      │
  │ python_check     │ Syntax-check a .py file without executing it       │
  │ run_tests        │ Run pytest in a directory                          │
  │ git_diff         │ Show git diff for a file or whole repo             │
  │ view_traceback   │ Parse a Python traceback into a structured report  │
  └──────────────────┴────────────────────────────────────────────────────┘

Per-agent tool sets (minimum required for each phase):
  Reproducer : bash, read_file, list_dir, python_check, view_traceback
  Analyst    : read_file, search_code, grep_files, bash, list_dir, view_traceback
  Fixer      : read_file, write_file, edit_file, bash, python_check
  Verifier   : bash, read_file, run_tests, python_check, git_diff
"""
import re
import subprocess
import sys
from pathlib import Path

from .config import WORKDIR

DANGEROUS = ["rm -rf /", "sudo rm", "shutdown", "reboot", "> /dev/"]


# ── Path safety ───────────────────────────────────────────────────────────────
def safe_path(p: str, root: Path = WORKDIR) -> Path:
    path = (root / p).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


# ── Core file tools ───────────────────────────────────────────────────────────
def run_bash(command: str, cwd: Path = WORKDIR) -> str:
    if any(d in command for d in DANGEROUS):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=cwd,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


def run_read(path: str, limit: int = None, root: Path = WORKDIR) -> str:
    try:
        lines = safe_path(path, root).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str, root: Path = WORKDIR) -> str:
    try:
        fp = safe_path(path, root)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str, root: Path = WORKDIR) -> str:
    try:
        fp = safe_path(path, root)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: old_text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


# ── Search tools ──────────────────────────────────────────────────────────────
def run_search(pattern: str, path: str, root: Path = WORKDIR) -> str:
    """Search for a regex pattern within a single file. Returns matching lines."""
    try:
        fp = safe_path(path, root)
        rx = re.compile(pattern, re.IGNORECASE)
        results = [
            f"  L{i}: {line.rstrip()}"
            for i, line in enumerate(fp.read_text().splitlines(), 1)
            if rx.search(line)
        ]
        return "\n".join(results) if results else "(no matches)"
    except Exception as e:
        return f"Error: {e}"


def run_grep_files(pattern: str, directory: str = ".",
                   file_glob: str = "*.py", root: Path = WORKDIR) -> str:
    """
    Search a regex pattern across all files matching file_glob in a directory.
    Useful for finding all call sites of a buggy function.
    """
    try:
        dp = safe_path(directory, root)
        rx = re.compile(pattern, re.IGNORECASE)
        results = []
        for fp in sorted(dp.rglob(file_glob)):
            try:
                for i, line in enumerate(fp.read_text().splitlines(), 1):
                    if rx.search(line):
                        results.append(f"  {fp.relative_to(dp)}:{i}: {line.rstrip()}")
            except Exception:
                pass
        if not results:
            return "(no matches)"
        if len(results) > 200:
            results = results[:200] + [f"  ... ({len(results) - 200} more truncated)"]
        return "\n".join(results)
    except Exception as e:
        return f"Error: {e}"


# ── Directory and file info tools ─────────────────────────────────────────────
def run_list_dir(path: str = ".", root: Path = WORKDIR) -> str:
    """List directory contents with file sizes."""
    try:
        dp = safe_path(path, root)
        if not dp.is_dir():
            return f"Error: {path} is not a directory"
        lines = []
        for item in sorted(dp.iterdir()):
            if item.is_dir():
                lines.append(f"  {item.name}/")
            else:
                lines.append(f"  {item.name}  ({item.stat().st_size} bytes)")
        return "\n".join(lines) if lines else "(empty directory)"
    except Exception as e:
        return f"Error: {e}"


def run_python_check(path: str, root: Path = WORKDIR) -> str:
    """Syntax-check a Python file without executing it. Returns 'Syntax OK' or the error."""
    try:
        fp = safe_path(path, root)
        r = subprocess.run(
            [sys.executable, "-m", "py_compile", str(fp)],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            return f"Syntax OK: {path}"
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return f"Error: {e}"


# ── Test and diff tools ───────────────────────────────────────────────────────
def run_run_tests(directory: str = ".", root: Path = WORKDIR) -> str:
    """Run pytest in a directory. Returns full test output."""
    try:
        dp = safe_path(directory, root)
        r = subprocess.run(
            [sys.executable, "-m", "pytest", str(dp), "-v", "--tb=short", "--no-header"],
            capture_output=True, text=True, timeout=120,
        )
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: pytest timeout (120s)"
    except Exception as e:
        return f"Error: {e}"


def run_git_diff(path: str = "", root: Path = WORKDIR) -> str:
    """Show git diff for a specific file, or the whole repo if path is empty."""
    try:
        cmd = ["git", "diff", "--", path] if path else ["git", "diff"]
        r = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=30)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no changes)"
    except Exception as e:
        return f"Error: {e}"


# ── Traceback parser ──────────────────────────────────────────────────────────
def run_view_traceback(error_text: str) -> str:
    """
    Parse a Python traceback string into a structured exception/location/chain report.
    Saves the Analyst from having to manually scan multi-line tracebacks.
    """
    lines = error_text.splitlines()
    # Last "File ..." line = innermost frame
    file_lines = [l for l in lines if l.strip().startswith("File ")]
    location = file_lines[-1].strip() if file_lines else "(unknown)"
    # Last non-empty, non-header line = exception message
    exception = ""
    for line in reversed(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith(("File ", "Traceback", "During", "  ")):
            exception = stripped
            break
    # Chained exception markers
    chain = [l.strip() for l in lines
             if "During handling" in l or "above exception" in l]
    return (
        f"Exception : {exception}\n"
        f"Location  : {location}\n"
        f"Chained   : {'; '.join(chain) or 'none'}"
    )


# ── Tool schemas (passed to client.messages.create as `tools=`) ───────────────
_BASH = {
    "name": "bash",
    "description": "Run a shell command. Avoid destructive commands.",
    "input_schema": {"type": "object",
                     "properties": {"command": {"type": "string"}},
                     "required": ["command"]},
}
_READ = {
    "name": "read_file",
    "description": "Read a file. Optional `limit` truncates to that many lines.",
    "input_schema": {"type": "object",
                     "properties": {"path": {"type": "string"},
                                    "limit": {"type": "integer"}},
                     "required": ["path"]},
}
_WRITE = {
    "name": "write_file",
    "description": "Write (or overwrite) a file with the given content.",
    "input_schema": {"type": "object",
                     "properties": {"path": {"type": "string"},
                                    "content": {"type": "string"}},
                     "required": ["path", "content"]},
}
_EDIT = {
    "name": "edit_file",
    "description": "Replace the first occurrence of old_text with new_text in a file.",
    "input_schema": {"type": "object",
                     "properties": {"path":     {"type": "string"},
                                    "old_text": {"type": "string"},
                                    "new_text": {"type": "string"}},
                     "required": ["path", "old_text", "new_text"]},
}
_SEARCH = {
    "name": "search_code",
    "description": "Regex search within a single file. Returns matching lines with line numbers.",
    "input_schema": {"type": "object",
                     "properties": {"pattern": {"type": "string"},
                                    "path":    {"type": "string"}},
                     "required": ["pattern", "path"]},
}
_GREP_FILES = {
    "name": "grep_files",
    "description": (
        "Search a regex pattern across all files matching file_glob in a directory. "
        "Useful for finding all call sites of a buggy function. "
        "Defaults: directory='.', file_glob='*.py'."
    ),
    "input_schema": {"type": "object",
                     "properties": {"pattern":   {"type": "string"},
                                    "directory": {"type": "string"},
                                    "file_glob": {"type": "string"}},
                     "required": ["pattern"]},
}
_LIST_DIR = {
    "name": "list_dir",
    "description": "List files and subdirectories with sizes. Default path='.'.",
    "input_schema": {"type": "object",
                     "properties": {"path": {"type": "string"}},
                     "required": []},
}
_PYTHON_CHECK = {
    "name": "python_check",
    "description": "Syntax-check a Python file without running it. Returns 'Syntax OK' or the SyntaxError.",
    "input_schema": {"type": "object",
                     "properties": {"path": {"type": "string"}},
                     "required": ["path"]},
}
_RUN_TESTS = {
    "name": "run_tests",
    "description": "Run pytest in a directory. Returns full test output. Default directory='.'.",
    "input_schema": {"type": "object",
                     "properties": {"directory": {"type": "string"}},
                     "required": []},
}
_GIT_DIFF = {
    "name": "git_diff",
    "description": "Show git diff. Pass a file path to scope to one file, or leave empty for all changes.",
    "input_schema": {"type": "object",
                     "properties": {"path": {"type": "string"}},
                     "required": []},
}
_VIEW_TB = {
    "name": "view_traceback",
    "description": (
        "Parse a raw Python traceback string into a structured report "
        "(exception type, innermost location, chained exceptions). "
        "Use this before deeper analysis."
    ),
    "input_schema": {"type": "object",
                     "properties": {"error_text": {"type": "string"}},
                     "required": ["error_text"]},
}

_LOAD_SKILL = {
    "name": "load_skill",
    "description": (
        "Load the full body of a named skill to get detailed instructions. "
        "Call this before tackling an unfamiliar task (e.g. load_skill('fixer') "
        "before patching a file). Available skills are listed in your system prompt."
    ),
    "input_schema": {"type": "object",
                     "properties": {"name": {"type": "string",
                                              "description": "Skill name to load"}},
                     "required": ["name"]},
}

# ── Per-agent tool sets ────────────────────────────────────────────────────────
REPRODUCER_TOOLS = [_BASH, _READ, _LIST_DIR, _PYTHON_CHECK, _VIEW_TB, _LOAD_SKILL]
ANALYST_TOOLS    = [_READ, _SEARCH, _GREP_FILES, _BASH, _LIST_DIR, _VIEW_TB, _LOAD_SKILL]
FIXER_TOOLS      = [_READ, _WRITE, _EDIT, _BASH, _PYTHON_CHECK, _LOAD_SKILL]
VERIFIER_TOOLS   = [_BASH, _READ, _RUN_TESTS, _PYTHON_CHECK, _GIT_DIFF, _LOAD_SKILL]
