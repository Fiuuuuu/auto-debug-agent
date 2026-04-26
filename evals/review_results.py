#!/usr/bin/env python3
"""
evals/review_results.py
-----------------------
V1 read-only reviewer agent for eval results.

It reads `results.json` and writes `eval_review.md`.  The goal is diagnosis:
which phase failed, what evidence supports that, and what should be inspected
next.  It does not modify source code.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from evals.agent_reports import call_report_agent, compact_json, read_json, write_report


SYSTEM = """
你是 Auto-Debug Agent 的 eval reviewer。
你的任务是只读复盘，不写代码、不修改评分器、不修改 golden dataset。
请根据 artifacts 判断失败更可能发生在哪一层：reproducer、analyst、fixer、verifier、prompt/tooling、dataset/checker。
输出中文 Markdown，结论要基于证据，不要编造 artifact 中没有的信息。
"""


def build_prompt(results: dict) -> str:
    return f"""
下面是一次 Auto-Debug Agent eval run 的 results.json。

请输出一份 eval_review.md，结构固定为：

# Eval Review

## Run Summary
- 总体分数、通过率、最明显的问题。

## Case Findings
- 每个 case 一段。
- 写清楚 status、score、bugs_fixed/bugs_total、retry_count。
- 判断失败阶段，并引用 agent_summary 或 sandbox_diff 中的证据。

## Cross-Case Patterns
- 总结跨 case 的共同失败模式。

## Recommended Investigation
- 给出下一步最值得看的 3-5 个点。
- 这里只能建议调查方向，不能要求修改 scorer/golden 来提高分数。

results.json:
```json
{compact_json(results)}
```
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Review Auto-Debug eval results with a read-only agent")
    parser.add_argument("results_json", help="Path to evals/runs/<run_id>/results.json")
    parser.add_argument("--output", "-o", help="Markdown output path (default: eval_review.md next to results.json)")
    args = parser.parse_args()

    results_path = Path(args.results_json)
    if not results_path.is_absolute():
        results_path = (Path.cwd() / results_path).resolve()
    output = Path(args.output) if args.output else results_path.parent / "eval_review.md"
    if not output.is_absolute():
        output = (Path.cwd() / output).resolve()

    try:
        results = read_json(results_path)
        report = call_report_agent(system=SYSTEM, prompt=build_prompt(results), max_tokens=5000)
    except Exception as exc:
        print(f"Failed to review results: {exc}")
        sys.exit(1)

    write_report(output, report)
    print(f"Review saved -> {output}")


if __name__ == "__main__":
    main()
