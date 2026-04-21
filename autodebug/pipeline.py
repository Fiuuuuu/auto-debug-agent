#!/usr/bin/env python3
"""
agents.py — run_subagent() + the four phase-agent functions.

Each agent function:
  1. Builds a system prompt (base + injected skills + optional memory hint)
  2. Calls run_subagent() with phase-specific tools and handlers
  3. Fills the appropriate field of the TeamProtocol message
  4. Returns the updated message for the next phase

run_subagent() is a self-contained agent loop with:
  - Exponential backoff retry on API errors
  - max_tokens continuation injection
  - Auto-compact when context grows too large

MiniMax M2.5 note:
  API returns ThinkingBlock objects in response.content.
  Check block type with: getattr(block, "type", None) == "text"
  Do NOT use hasattr(block, "text") — ThinkingBlock also has .text.
"""
import json
import time
from pathlib import Path
from anthropic import APIError

from .config import client, MODEL, WORKDIR, MAX_TOKENS, TOKEN_THRESHOLD, MAX_RETRIES, BACKOFF_BASE
from .protocol import TeamProtocol
from .memory import FixMemory
from .sandbox import Sandbox
from .tools import (
    run_bash, run_read, run_write, run_edit, run_search,
    run_list_dir, run_python_check, run_run_tests, run_git_diff,
    run_grep_files, run_view_traceback,
    REPRODUCER_TOOLS, ANALYST_TOOLS, FIXER_TOOLS, VERIFIER_TOOLS,
)
from .skills import SKILL_LOADER

# Single shared memory instance used across all agents and the CLI
MEMORY = FixMemory()


# ── Context compact ─────────────────────────────────────────────────────
def estimate_tokens(messages: list) -> int:
    return len(json.dumps(messages, default=str)) // 4


def auto_compact(messages: list, label: str = "agent") -> list:
    text   = json.dumps(messages, default=str)[:80000]
    prompt = (
        "Summarize this agent conversation for continuity. Include:\n"
        "1) Task and goal\n"
        "2) Work done, files touched\n"
        "3) Key decisions and failed attempts\n"
        "4) Next steps\n\n" + text
    )
    try:
        r = client.messages.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
        )
        summary = ""
        for b in r.content:
            if getattr(b, "type", None) == "text":
                summary = getattr(b, "text", "")
                break
    except Exception as e:
        summary = f"(compact failed: {e})"
    print(f"  \033[33m[compact]\033[0m {label} context compacted")
    return [{"role": "user", "content":
             f"Previous context was compacted. Summary:\n{summary}\nContinue."}]


# ── Generic subagent runner ─────────────────────────────────────────────
def run_subagent(system: str, initial_prompt: str, tools: list,
                 tool_handlers: dict, label: str = "agent") -> str:
    """
    Run an isolated agent loop and return the final text response.

    Each call starts with a fresh message history, so phase agents cannot
    contaminate each other's context.
    """
    messages           = [{"role": "user", "content": initial_prompt}]
    max_output_recovery = 0

    while True:
        # Proactive compact before hitting the API limit
        if estimate_tokens(messages) > TOKEN_THRESHOLD:
            messages = auto_compact(messages, label)

        # API call with exponential backoff retry
        response = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = client.messages.create(
                    model=MODEL, system=system, messages=messages,
                    tools=tools, max_tokens=MAX_TOKENS,
                )
                break
            except APIError as e:
                if attempt < MAX_RETRIES:
                    delay = min(BACKOFF_BASE * (2 ** attempt), 30.0)
                    print(f"  \033[33m[{label}]\033[0m API error: {e}. Retry in {delay:.1f}s")
                    time.sleep(delay)
                else:
                    return f"Error: API call failed after {MAX_RETRIES} retries: {e}"

        if response is None:
            return "Error: No response received."

        messages.append({"role": "assistant", "content": response.content})

        # max_tokens continuation
        if response.stop_reason == "max_tokens":
            max_output_recovery += 1
            if max_output_recovery <= MAX_RETRIES:
                messages.append({"role": "user", "content":
                    "Output limit hit. Continue from where you stopped — no recap."})
                continue
            return "Error: max_tokens recovery exhausted."

        # Normal end: collect and return text blocks
        if response.stop_reason != "tool_use":
            return next(
                (getattr(b, "text", "") for b in response.content
                 if getattr(b, "type", None) == "text"), ""
            )

        # Process tool calls
        results = []
        for block in response.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            handler = tool_handlers.get(block.name)
            try:
                output = handler(**(block.input or {})) if handler else f"Unknown tool: {block.name}"
            except Exception as e:
                output = f"Error: {e}"

            # ── Tool call header: agent label + tool name + first input arg preview
            AGENT_COLORS = {
                "reproducer": "\033[34m",   # blue
                "analyst":    "\033[35m",   # magenta
                "fixer":      "\033[33m",   # yellow
                "verifier":   "\033[36m",   # cyan
            }
            color = AGENT_COLORS.get(label, "\033[37m")
            key_input = ""
            if block.input:
                first_val = next(iter(block.input.values()), "")
                first_val = first_val.replace("\n", " ")  # single-line preview
                key_input = f" \033[2m({str(first_val)[:60]})\033[0m" if first_val else ""
            print(f"\n  {color}┌─ [{label}] \033[1m{block.name}\033[0m{key_input}{color} ─\033[0m")

            # ── Tool result body: truncate long output, highlight errors in red
            output_str = str(output)
            is_error   = output_str.lower().startswith("error")
            result_color = "\033[31m" if is_error else "\033[0m"
            preview    = output_str[:300].rstrip()
            if len(output_str) > 300:
                preview += f"\033[2m … ({len(output_str)} chars total)\033[0m"
            for line in preview.splitlines():
                print(f"  {color}│\033[0m {result_color}{line}\033[0m")
            print(f"  {color}└{'─' * 40}\033[0m")

            results.append({
                "type":        "tool_result",
                "tool_use_id": block.id,
                "content":     str(output),
            })
        messages.append({"role": "user", "content": results})


# ── Phase 1: Reproducer ───────────────────────────────────────────────────────
def reproducer_agent(target_file: str) -> TeamProtocol:
    """
    Run the target file, capture the full traceback, return a structured report.
    Tools: bash, read_file, list_dir, python_check, view_traceback
    """
    system = (
        f"You are the Reproducer agent. RUN the target file and capture the full error.\n"
        f"Working directory: {WORKDIR}\n"
        f"Do NOT attempt to fix anything. Reproduce and report only.\n\n"
        f"Skills available (call load_skill('<name>') to load full instructions):\n"
        + SKILL_LOADER.get_descriptions()
    )
    prompt = (
        f"Target file: {target_file}\n\n"
        f"Steps:\n"
        f"1. Call load_skill('log-parser') to load traceback parsing instructions.\n"
        f"2. Use list_dir to understand the project structure.\n"
        f"3. Read the file to understand what it does.\n"
        f"4. Run python_check first to detect syntax errors before executing.\n"
        f"5. Run: python {target_file}\n"
        f"6. If it fails, report the FULL traceback, then use view_traceback to parse it.\n"
        f"7. If it succeeds, report exactly: 'No error found'.\n"
        f"Return your full error report as plain text."
    )
    handlers = {
        "bash":           lambda **kw: run_bash(kw["command"]),
        "read_file":      lambda **kw: run_read(kw["path"], kw.get("limit")),
        "list_dir":       lambda **kw: run_list_dir(kw.get("path", ".")),
        "python_check":   lambda **kw: run_python_check(kw["path"]),
        "view_traceback": lambda **kw: run_view_traceback(kw["error_text"]),
        "load_skill":     lambda **kw: SKILL_LOADER.get_content(kw["name"]),
    }
    result = run_subagent(system, prompt, REPRODUCER_TOOLS, handlers, label="reproducer")
    status = "ok" if ("error" in result.lower() or "traceback" in result.lower()) else "skip"
    if "no error found" in result.lower():
        status = "skip"
    return TeamProtocol(
        phase="reproduce", status=status,
        target_file=target_file, error_info=result,
    )


# ── Phase 2: Analyst ──────────────────────────────────────────────────────────
def analyst_agent(msg: TeamProtocol) -> TeamProtocol:
    """
    Read the source + error, identify root cause, propose a fix strategy.
    Tools: read_file, search_code, grep_files, bash, list_dir, view_traceback
    Injects memory hint if a similar past fix exists.
    """
    memory_hint = MEMORY.prompt_section(msg.error_info)
    system = (
        f"You are the Analyst agent. Diagnose the bug and propose a fix strategy.\n"
        f"Working directory: {WORKDIR}\n\n"
        f"Skills available (call load_skill('<name>') to load full instructions):\n"
        + SKILL_LOADER.get_descriptions()
        + (f"\n\n{memory_hint}" if memory_hint else "")
    )
    prompt = (
        f"Target file : {msg.target_file}\n\n"
        f"Error output:\n```\n{msg.error_info}\n```\n\n"
        f"Steps:\n"
        f"1. Call load_skill('log-parser') then load_skill('static-analysis').\n"
        f"2. Use view_traceback to get a structured exception summary.\n"
        f"3. Read the target file.\n"
        f"4. Run python_check to confirm syntax is valid.\n"
        f"5. Use search_code to locate the exact failing line(s).\n"
        f"6. Use grep_files to find all call sites of the buggy function/variable.\n"
        f"7. Explain root cause in ≤ 5 bullet points.\n"
        f"8. Propose a minimal fix strategy (which lines to change and how).\n"
        f"Return: root cause analysis + fix strategy."
    )
    handlers = {
        "read_file":      lambda **kw: run_read(kw["path"], kw.get("limit")),
        "search_code":    lambda **kw: run_search(kw["pattern"], kw["path"]),
        "grep_files":     lambda **kw: run_grep_files(
                              kw["pattern"],
                              kw.get("directory", "."),
                              kw.get("file_glob", "*.py"),
                          ),
        "bash":           lambda **kw: run_bash(kw["command"]),
        "list_dir":       lambda **kw: run_list_dir(kw.get("path", ".")),
        "view_traceback": lambda **kw: run_view_traceback(kw["error_text"]),
        "load_skill":     lambda **kw: SKILL_LOADER.get_content(kw["name"]),
    }
    result = run_subagent(system, prompt, ANALYST_TOOLS, handlers, label="analyst")
    msg.phase      = "analyse"
    msg.root_cause = result
    return msg


# ── Phase 3: Fixer ────────────────────────────────────────────────────────────
def fixer_agent(msg: TeamProtocol, sandbox: Sandbox) -> TeamProtocol:
    """
    Apply a minimal fix to the sandbox copy of the file.
    Tools: read_file, write_file, edit_file, bash, python_check
    All file paths are rooted in sandbox.sandbox_dir — cannot touch originals.
    """
    sb    = sandbox.sandbox_dir
    fname = sandbox.sandbox_file.name
    system = (
        f"You are the Fixer agent. Fix {fname} inside the sandbox only.\n"
        f"Sandbox directory: {sb}\n"
        f"Do NOT reference or modify any file outside the sandbox.\n\n"
        f"Skills available (call load_skill('<name>') to load full instructions):\n"
        + SKILL_LOADER.get_descriptions()
    )
    prompt = (
        f"File to fix : {fname}  (sandbox copy at {sb / fname})\n\n"
        f"Root cause from Analyst:\n{msg.root_cause}\n\n"
        f"Steps:\n"
        f"1. Call load_skill('fixer') to load the mandatory edit checklist.\n"
        f"2. Read {fname}.\n"
        f"3. Run python_check baseline.\n"
        f"4. Write your TODO plan (max 5 items).\n"
        f"5. Apply fix using edit_file.\n"
        f"6. Run python_check again — must return 'Syntax OK'.\n"
        f"7. Read back the patched lines to verify.\n"
        f"Return: a clear description of every change you made."
    )
    handlers = {
        "read_file":    lambda **kw: run_read(kw["path"], kw.get("limit"), root=sb),
        "write_file":   lambda **kw: run_write(kw["path"], kw["content"], root=sb),
        "edit_file":    lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"], root=sb),
        "bash":         lambda **kw: run_bash(kw["command"], cwd=sb),
        "python_check": lambda **kw: run_python_check(kw["path"], root=sb),
        "load_skill":   lambda **kw: SKILL_LOADER.get_content(kw["name"]),
    }
    result      = run_subagent(system, prompt, FIXER_TOOLS, handlers, label="fixer")
    msg.phase      = "fix"
    msg.patch_desc = result
    return msg


# ── Phase 4: Verifier ─────────────────────────────────────────────────────────
def verifier_agent(msg: TeamProtocol, sandbox: Sandbox) -> TeamProtocol:
    """
    Run the patched file and tests to confirm the fix is correct.
    Tools: bash, read_file, run_tests, python_check, git_diff
    Reports PASS or FAIL; status field drives Orchestrator retry logic.
    """
    sb    = sandbox.sandbox_dir
    fname = sandbox.sandbox_file.name
    system = (
        f"You are the Verifier agent. Confirm the patched file has no errors.\n"
        f"Sandbox directory: {sb}\n"
    )
    prompt = (
        f"Patched file: {fname}  (sandbox: {sb})\n\n"
        f"Original error:\n```\n{msg.error_info}\n```\n\n"
        f"Fixer's changes:\n{msg.patch_desc}\n\n"
        f"Verification steps:\n"
        f"1. Run python_check on {fname} — must be 'Syntax OK'.\n"
        f"2. Run: python {fname}\n"
        f"3. Run run_tests to check if a test suite exists and all tests pass.\n"
        f"4. Run git_diff to confirm only the expected lines were changed.\n"
        f"5. Report PASS if there are no errors, or FAIL with the full traceback.\n"
        f"Your final line must start with either 'PASS' or 'FAIL'."
    )
    handlers = {
        "bash":         lambda **kw: run_bash(kw["command"], cwd=sb),
        "read_file":    lambda **kw: run_read(kw["path"], kw.get("limit"), root=sb),
        "run_tests":    lambda **kw: run_run_tests(kw.get("directory", "."), root=sb),
        "python_check": lambda **kw: run_python_check(kw["path"], root=sb),
        "git_diff":     lambda **kw: run_git_diff(kw.get("path", ""), root=sb),
        "load_skill":   lambda **kw: SKILL_LOADER.get_content(kw["name"]),
    }
    result          = run_subagent(system, prompt, VERIFIER_TOOLS, handlers, label="verifier")
    msg.phase       = "verify"
    msg.test_result = result
    msg.status      = "ok" if "pass" in result.lower() else "error"
    return msg
