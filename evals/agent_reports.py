"""
evals/agent_reports.py
----------------------
Read-only model helpers for evaluation review reports.

These helpers intentionally do not expose file editing tools.  The reviewer and
proposal agents can write Markdown reports, but they cannot mutate the target
agent or the scoring rules.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).parent.parent.resolve()


def read_json(path: Path) -> dict[str, Any]:
    """Load a JSON artifact with a clear error if the path is wrong."""
    return json.loads(path.read_text(encoding="utf-8"))


def compact_json(data: Any, limit: int = 50000) -> str:
    """Serialize artifact data for a prompt without flooding context."""
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[truncated: {len(text) - limit} chars omitted]"


def source_context(paths: list[str], limit_per_file: int = 12000) -> str:
    """Read selected source files for proposal analysis."""
    chunks = []
    for rel in paths:
        path = PROJECT_ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(errors="replace", encoding="utf-8")
        if len(text) > limit_per_file:
            text = text[:limit_per_file] + f"\n\n[truncated: {len(text) - limit_per_file} chars omitted]"
        chunks.append(f"## {rel}\n```python\n{text}\n```")
    return "\n\n".join(chunks)


def call_report_agent(*, system: str, prompt: str, max_tokens: int = 5000) -> str:
    """Call the configured Anthropic-compatible model and return plain text."""
    load_dotenv(override=True)
    model = os.getenv("MODEL_ID")
    if not model:
        raise RuntimeError("MODEL_ID is required. Set it in .env or export it in your shell.")

    if os.getenv("ANTHROPIC_BASE_URL"):
        os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

    from anthropic import Anthropic

    client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
    response = client.messages.create(
        model=model,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
    )
    return next(
        (getattr(block, "text", "") for block in response.content if getattr(block, "type", None) == "text"),
        "",
    ).strip()


def write_report(path: Path, content: str) -> None:
    """Write one Markdown report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
