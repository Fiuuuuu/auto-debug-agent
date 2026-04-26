#!/usr/bin/env python3
"""
evals/run_evals.py
------------------
CLI entry point for the Auto-Debug Agent evaluation harness.

Usage:
    python evals/run_evals.py
    python evals/run_evals.py bug1 bug3
    python evals/run_evals.py --output evals/results.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from evals.runner import run_eval_suite


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Auto-Debug Agent evaluations")
    parser.add_argument("ids", nargs="*", help="Case ids to run (default: all)")
    parser.add_argument("--output", "-o", help="Also save results JSON to this path")
    args = parser.parse_args()

    try:
        run_eval_suite(ids=args.ids, output=args.output)
    except KeyError as exc:
        if str(exc).strip("'") == "MODEL_ID":
            print("MODEL_ID is required to run evals. Set it in .env or export it in your shell.")
            sys.exit(2)
        raise
    except ValueError as exc:
        print(exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
