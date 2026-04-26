#!/usr/bin/env python3
"""
evals/propose_improvements.py
-----------------------------
V2 proposal agent for improving the Auto-Debug Agent.

It reads a reviewer report plus the current source context and writes
`improvement_plan.md`.  It is deliberately advisory: no source files are edited.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from evals.agent_reports import (
    call_report_agent,
    compact_json,
    read_json,
    source_context,
    write_report,
)


SYSTEM = """
你是 Auto-Debug Agent 的 improvement proposal agent。
你的任务是根据 eval review 和当前源码提出工程修改计划。
你不能修改源码，不能建议通过放宽 scorer、改 golden dataset、硬编码 sample_bugs 来刷分。
请给出可以交给另一个工程师实施的中文 Markdown 计划，优先小步、可验证、可回滚。
"""


SOURCE_FILES = [
    "main.py",
    "autodebug/pipeline.py",
    "autodebug/tools.py",
    "autodebug/protocol.py",
    "evals/runner.py",
    "evals/artifacts.py",
]


def build_prompt(review_text: str, results: dict | None, sources: str) -> str:
    results_block = compact_json(results, 30000) if results else "(results.json not found next to review)"
    return f"""
下面是 eval reviewer 的报告、可选 results.json，以及当前关键源码。

请输出 improvement_plan.md，结构固定为：

# Improvement Plan

## Diagnosis
- 用 3-6 条说明当前主要问题和证据。

## Proposed Changes
- 按优先级列出要改的地方。
- 每条写清楚：改什么、为什么、预期影响、风险。

## Acceptance Criteria
- 写清楚重新跑哪些 eval 命令，什么结果算通过。

## Guardrails
- 明确哪些东西不能改，例如 scorer/golden dataset、硬编码样例答案。

eval_review.md:
```md
{review_text}
```

results.json:
```json
{results_block}
```

source context:
{sources}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Propose Auto-Debug improvements from an eval review")
    parser.add_argument("review_md", help="Path to evals/runs/<run_id>/eval_review.md")
    parser.add_argument("--output", "-o", help="Markdown output path (default: improvement_plan.md next to review)")
    args = parser.parse_args()

    review_path = Path(args.review_md)
    if not review_path.is_absolute():
        review_path = (Path.cwd() / review_path).resolve()
    output = Path(args.output) if args.output else review_path.parent / "improvement_plan.md"
    if not output.is_absolute():
        output = (Path.cwd() / output).resolve()

    try:
        review_text = review_path.read_text(encoding="utf-8")
        results_path = review_path.parent / "results.json"
        results = read_json(results_path) if results_path.exists() else None
        sources = source_context(SOURCE_FILES)
        report = call_report_agent(
            system=SYSTEM,
            prompt=build_prompt(review_text, results, sources),
            max_tokens=6000,
        )
    except Exception as exc:
        print(f"Failed to propose improvements: {exc}")
        sys.exit(1)

    write_report(output, report)
    print(f"Improvement plan saved -> {output}")


if __name__ == "__main__":
    main()
