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

from .config import client, MODEL, WORKDIR, DEBUG_DIR, MAX_TOKENS, TOKEN_THRESHOLD, MAX_RETRIES, BACKOFF_BASE
from .protocol import TeamProtocol
from .memory import FixMemory
from .sandbox import Sandbox
from .tools import (
    run_bash, run_read, run_write, run_edit, run_search,
    run_list_dir, run_python_check, run_run_tests,
    run_grep_files, run_view_traceback, run_sandbox_diff,
    REPRODUCER_TOOLS, ANALYST_TOOLS, FIXER_TOOLS, VERIFIER_TOOLS,
)
from .skills import SKILL_LOADER

# Single shared memory instance used across all agents and the CLI
MEMORY = FixMemory()


# ── Issue helpers ───────────────────────────────────────────────────────
def make_issue(text: str, attempt_found: int = 0, status: str = "open") -> dict:
    """
    Extract a small issue record from traceback-like text.

    The project stays deliberately lightweight: the LLM still writes rich
    prose, while the orchestrator keeps just enough structure to guide retries.
    """
    import re

    exception = ""
    for line in reversed(text.splitlines()):
        s = line.strip()
        if not s or s.startswith(("File ", "Traceback", "```", "[exit_code=")):
            continue
        if "Error" in s or "Exception" in s or "Traceback" in s:
            exception = s
            break
    if not exception:
        exception = text.strip().splitlines()[-1][:160] if text.strip() else "Unknown error"

    location = "(unknown)"
    file_lines = [l.strip() for l in text.splitlines() if l.strip().startswith("File ")]
    if file_lines:
        location = file_lines[-1]

    m = re.search(r"\b([A-Z][A-Za-z]+(?:Error|Exception))\b", exception)
    return {
        "exception_type": m.group(1) if m else "Unknown",
        "location": location,
        "summary": exception[:240],
        "status": status,
        "attempt_found": attempt_found,
    }


def merge_issue(issues: list[dict], issue: dict) -> list[dict]:
    """Append a new issue unless the same exception/location is already known."""
    key = (issue.get("exception_type"), issue.get("location"))
    for old in issues:
        if (old.get("exception_type"), old.get("location")) == key:
            old.update(issue)
            return issues
    issues.append(issue)
    return issues


def extract_issues_json(text: str) -> list[dict]:
    """Read an optional ```json {"issues": [...]} ``` block from an agent answer."""
    import re

    for m in re.finditer(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL):
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        issues = data.get("issues")
        if isinstance(issues, list):
            return [i for i in issues if isinstance(i, dict)]
    return []


# ── Context compact ─────────────────────────────────────────────────────
def estimate_tokens(messages: list) -> int:
    return len(json.dumps(messages, default=str)) // 4


# Number of recent tool results to keep verbatim; older ones get truncated.
_KEEP_RECENT = 3


def micro_compact(messages: list) -> list:
    """
    Lightweight pass: truncate old tool-result blocks in-place.
    Keeps the last _KEEP_RECENT tool results verbatim; replaces earlier ones
    with a short placeholder so the model can still see the call sequence.
    Much cheaper than a full LLM summarisation call.
    """
    tool_result_blocks = []
    for msg in messages:
        content = msg.get("content")
        if msg.get("role") != "user" or not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                tool_result_blocks.append(block)

    for block in tool_result_blocks[:-_KEEP_RECENT]:
        body = block.get("content", "")
        if isinstance(body, str) and len(body) > 120:
            block["content"] = "[Earlier result compacted — re-run the tool if needed.]"

    return messages


def _write_transcript(messages: list, label: str) -> None:
    """Persist full message history to .debug/transcripts/ before compacting."""
    transcript_dir = DEBUG_DIR / "transcripts"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    path = transcript_dir / f"{label}_{int(time.time())}.jsonl"
    with path.open("w") as fh:
        for msg in messages:
            fh.write(json.dumps(msg, default=str) + "\n")
    print(f"  \033[2m[compact] transcript saved: {path.relative_to(WORKDIR)}\033[0m")


def auto_compact(messages: list, label: str = "agent") -> list:
    """
    Full compaction: summarise the whole conversation into one user message.
    Steps:
      1. Save a JSONL transcript to .debug/transcripts/ (never lose history).
      2. Ask the model to produce a structured summary (goal / findings /
         files changed / remaining work / constraints).
      3. Return a single-message list so the next API call starts fresh.
    Call micro_compact() first for a cheaper size reduction.
    """
    _write_transcript(messages, label)

    conversation = json.dumps(messages, default=str)[:80000]
    prompt = (
        "Summarize this agent conversation so work can continue.\n"
        "Preserve ALL of the following:\n"
        "1. The current goal and target file\n"
        "2. Important findings (error type, root cause, failing line)\n"
        "3. Files read or changed, and what was changed\n"
        "4. Failed attempts and why they failed\n"
        "5. Remaining work / next step\n"
        "Be compact but concrete — use bullet points.\n\n"
        + conversation
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
                summary = getattr(b, "text", "").strip()
                break
    except Exception as e:
        summary = f"(compact failed: {e})"

    print(f"  \033[33m[compact]\033[0m {label} context compacted")
    return [{"role": "user", "content":
             f"This conversation was compacted so work can continue.\n\n{summary}"}]


# ── Generic subagent runner ─────────────────────────────────────────────
def run_subagent(system: str, initial_prompt: str, tools: list,
                 tool_handlers: dict, label: str = "agent",
                 max_tool_calls: int = None) -> str:
    """
    Run an isolated agent loop and return the final text response.

    Each call starts with a fresh message history, so phase agents cannot
    contaminate each other's context.
    """
    messages           = [{"role": "user", "content": initial_prompt}]
    max_output_recovery = 0
    max_steps           = 30
    step                = 0
    tool_calls          = 0

    while step < max_steps:
        # Lightweight pass first: truncate old tool results in-place
        messages = micro_compact(messages)
        # Full compaction only if still too large after micro_compact
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
            if max_tool_calls is not None and tool_calls >= max_tool_calls:
                return (
                    f"Error: {label} exceeded tool budget "
                    f"({max_tool_calls}). It must stop and write a verdict."
                )
            handler = tool_handlers.get(block.name)
            try:
                output = handler(**(block.input or {})) if handler else f"Unknown tool: {block.name}"
            except Exception as e:
                output = f"Error: {e}"
            tool_calls += 1

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
                first_val = str(next(iter(block.input.values()), ""))
                # Strip WORKDIR prefix so paths show as relative
                first_val = first_val.replace(str(WORKDIR) + "/", "").replace(str(WORKDIR), "")
                first_val = first_val.replace("\n", " ")
                key_input = f" \033[2m({first_val[:60]})\033[0m" if first_val else ""
            print(f"\n  {color}┌─ [{label}] \033[1m{block.name}\033[0m{key_input}{color} ─\033[0m")

            # ── Tool result body: truncate long output, highlight errors in red
            output_str = str(output)

            # load_skill: just confirm the skill name, don't dump the XML
            if block.name == "load_skill":
                skill_name = (block.input or {}).get("name", "?")
                print(f"  {color}│\033[0m \033[32m✓ Skill loaded:\033[0m {skill_name}")
                print(f"  {color}└{'─' * 40}\033[0m")
                results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     output_str,
                })
                continue

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
                "content":     output_str,
            })
        messages.append({"role": "user", "content": results})
        step += 1

    return f"Error: agent loop exceeded {max_steps} steps without a final answer."


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
        f"You MUST call tools in this exact order before writing your report:\n"
        f"1. load_skill('log-parser') — required first.\n"
        f"2. list_dir('.') — understand the project structure.\n"
        f"3. read_file({target_file!r}) — read the file to understand what it does.\n"
        f"4. python_check({target_file!r}) — detect syntax errors before executing.\n"
        f"5. bash('python {target_file}') — run the file and capture the full output.\n\n"
        f"After all 5 tool calls:\n"
        f"- If the run FAILED: call view_traceback once with the traceback text, "
        f"then IMMEDIATELY stop calling tools and write your final report.\n"
        f"- If the run SUCCEEDED: write exactly 'No error found'. Do NOT call any more tools.\n"
        f"Do NOT restart from step 1. Do NOT call load_skill or list_dir again.\n"
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
    issues = [] if status == "skip" else [make_issue(result, attempt_found=0)]
    return TeamProtocol(
        phase="reproduce", status=status,
        target_file=target_file, error_info=result, issues=issues,
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
        f"Known issues so far:\n```json\n{json.dumps(msg.issues, indent=2)}\n```\n\n"
        f"Error output:\n```\n{msg.error_info}\n```\n\n"
        f"You MUST call tools in this exact order before writing your analysis:\n"
        f"1. load_skill('log-parser') — required first.\n"
        f"2. load_skill('static-analysis') — required second.\n"
        f"3. view_traceback — pass the full error text above to get a structured summary.\n"
        f"4. read_file({msg.target_file!r}) — read the buggy file.\n"
        f"5. grep_files — search for ALL call sites of the buggy function/variable "
        f"across the project. Do NOT skip this step.\n"
        f"6. search_code — locate the exact failing line(s) in the file.\n\n"
        f"After completing all 6 tool calls, write your report in two parts:\n"
        f"Part A — Current traceback: root cause (≤ 5 bullets) and minimal fix strategy.\n"
        f"Part B — Full-file crash scan: list only patterns likely to cause runtime crashes "
        f"when the script continues. Do not include pure semantic or performance concerns "
        f"unless they can make the file crash.\n\n"
        f"End with a JSON block containing any crash issues you found:\n"
        f"```json\n"
        f'{{"issues": [{{"exception_type": "TypeError", "location": "file:line", '
        f'"summary": "short crash cause", "status": "open", "attempt_found": {msg.retry_count}}}]}}\n'
        f"```\n"
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
    for issue in extract_issues_json(result):
        msg.issues = merge_issue(msg.issues, issue)
    return msg


# ── Phase 3: Fixer ────────────────────────────────────────────────────────────
def fixer_agent(msg: TeamProtocol, sandbox: Sandbox) -> TeamProtocol:
    """
    Apply a minimal fix to the sandbox copy of the file.
    Tools: read_file, write_file, edit_file, bash, python_check
    All file paths are rooted in sandbox.sandbox_dir — cannot touch originals.
    """
    sb    = sandbox.sandbox_dir
    # Relative path inside the sandbox (e.g. sample_bugs/bug1.py)
    fname = sandbox.sandbox_file.relative_to(sb)
    system = (
        f"You are the Fixer agent. Fix {fname} inside the sandbox only.\n"
        f"Sandbox directory: {sb}\n"
        f"Do NOT reference or modify any file outside the sandbox.\n\n"
        f"Skills available (call load_skill('<name>') to load full instructions):\n"
        + SKILL_LOADER.get_descriptions()
    )
    prompt = (
        f"File to fix : {fname}  (sandbox copy at {sb / fname})\n\n"
        f"Known crash issues:\n```json\n{json.dumps(msg.issues, indent=2)}\n```\n\n"
        f"Root cause from Analyst:\n{msg.root_cause}\n\n"
        f"You MUST call tools in this exact order:\n"
        f"1. load_skill('fixer') — required first, loads the mandatory edit checklist.\n"
        f"2. read_file({str(fname)!r}) — read the current file content.\n"
        f"3. python_check({str(fname)!r}) — baseline syntax check before any edit.\n"
        f"4. edit_file — apply the minimal fix for open crash issues.\n"
        f"   Prioritize the newest issue found by Verifier. If multiple open issues "
        f"are already clear from the issue list, fix them in the same small patch.\n"
        f"   Use write_file only if a full rewrite is truly needed.\n"
        f"5. python_check({str(fname)!r}) — confirm 'Syntax OK' after the edit.\n"
        f"6. read_file({str(fname)!r}) — read back the patched lines to verify the change.\n\n"
        f"After all 6 tool calls, write a clear description of every change you made "
        f"and which issue(s) it closes."
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
    # Relative path inside the sandbox (e.g. sample_bugs/bug1.py)
    fname = sandbox.sandbox_file.relative_to(sb)
    system = (
        f"You are the Verifier agent. Confirm the patched file has no errors.\n"
        f"Sandbox directory: {sb}\n"
    )
    prompt = (
        f"Patched file: {fname}  (sandbox: {sb})\n\n"
        f"Known crash issues:\n```json\n{json.dumps(msg.issues, indent=2)}\n```\n\n"
        f"Original error:\n```\n{msg.error_info}\n```\n\n"
        f"Fixer's changes:\n{msg.patch_desc}\n\n"
        f"You MUST call tools in this exact order before writing your verdict:\n"
        f"1. python_check({str(fname)!r}) — must return 'Syntax OK'. Stop and verdict=FAIL if not.\n"
        f"2. bash('python {fname}') — run the patched file. Capture the full output.\n"
        f"3. run_tests('.') — run pytest; note any failures (it's OK if no tests exist).\n"
        f"4. sandbox_diff({str(fname)!r}) — review the real patch against the original file.\n\n"
        f"After all 4 tool calls, write your verdict.\n"
        f"Your response MUST end with a JSON block (nothing after it):\n"
        f"```json\n"
        f'{{"verdict": "PASS", "summary": "one-line reason"}}\n'
        f"```\n"
        f"verdict=PASS ONLY if step 2 shows [exit_code=0] and NO traceback appears anywhere in the output.\n"
        f"If ANY exception or traceback is present — even a NEW one different from the original — verdict=FAIL.\n"
        f"Do NOT call tools beyond the 4 steps. Decide immediately and write your verdict."
    )
    handlers = {
        "bash":         lambda **kw: run_bash(kw["command"], cwd=sb),
        "run_tests":    lambda **kw: run_run_tests(kw.get("directory", "."), root=sb),
        "python_check": lambda **kw: run_python_check(kw["path"], root=sb),
        "sandbox_diff": lambda **kw: run_sandbox_diff(
            kw["path"], sandbox_root=sb, original_file=sandbox.original,
        ),
    }
    result          = run_subagent(system, prompt, VERIFIER_TOOLS, handlers, label="verifier", max_tool_calls=4)
    msg.phase       = "verify"
    msg.test_result = result
    # Parse structured JSON verdict — immune to stray "pass"/"fail" words in prose
    import re as _re, json as _json
    _verdict = "error"
    _m = _re.search(r'```json\s*(\{.*?\})\s*```', result, _re.DOTALL)
    if _m:
        try:
            _verdict = "ok" if _json.loads(_m.group(1)).get("verdict", "").upper() == "PASS" else "error"
        except Exception:
            pass
    msg.status = _verdict
    if msg.status == "ok":
        for issue in msg.issues:
            if issue.get("status") == "open":
                issue["status"] = "closed"
    else:
        msg.issues = merge_issue(
            msg.issues,
            make_issue(result, attempt_found=msg.retry_count + 1, status="open"),
        )
    return msg
