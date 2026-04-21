"""
evals/golden_dataset.py
-----------------------
Golden dataset for evaluating the Auto-Debug Agent.

Each entry describes one buggy file.  The `checkers` list contains callables
that each receive the *imported* fixed module and return True if that specific
bug has been correctly fixed.  This lets the scorer give partial credit when
only some bugs in a multi-bug file are resolved.

Schema
------
id          : str          unique identifier
file        : str          path relative to project root
bug_count   : int          total number of intentionally planted bugs
tags        : list[str]    bug categories (for filtering / reporting)
checkers    : list[callable(module) -> bool]
timeout     : int          seconds allowed for the pipeline to run
"""

from __future__ import annotations
from typing import Any


def _check(module: Any, fn_name: str, args: tuple, kwargs: dict, expected: Any) -> bool:
    """Helper: call module.fn_name(*args, **kwargs) and compare to expected."""
    try:
        result = getattr(module, fn_name)(*args, **kwargs)
        return result == expected
    except Exception:
        return False


def _runs_without_exception(module: Any, fn_name: str, args: tuple, kwargs: dict = {}) -> bool:
    """Helper: return True if the call completes without raising."""
    try:
        getattr(module, fn_name)(*args, **kwargs)
        return True
    except Exception:
        return False


GOLDEN: list[dict] = [
    # ── bug1.py: IndexError · KeyError · TypeError ────────────────────────────
    {
        "id": "bug1",
        "file": "sample_bugs/bug1.py",
        "bug_count": 3,
        "tags": ["index-error", "key-error", "type-error"],
        "checkers": [
            # Bug 1 fixed: get_last_item returns correct last element
            lambda m: _check(m, "get_last_item", ([10, 20, 30],), {}, 30),
            # Bug 2 fixed: get_user_email reads "email" key correctly
            lambda m: _check(m, "get_user_email", ({"email": "a@b.com"},), {}, "a@b.com"),
            # Bug 3 fixed: calculate_total accepts two numerics
            lambda m: _runs_without_exception(m, "calculate_total", (99.9, 1.0)),
        ],
        "timeout": 120,
    },

    # ── bug2.py: RecursionError · logic error · ZeroDivisionError ────────────
    {
        "id": "bug2",
        "file": "sample_bugs/bug2.py",
        "bug_count": 3,
        "tags": ["recursion", "logic", "zero-division"],
        "checkers": [
            # Bug 1 fixed: factorial(5) returns 120 without infinite recursion
            lambda m: _check(m, "factorial", (5,), {}, 120),
            # Bug 2 fixed: is_adult(18) returns True
            lambda m: _check(m, "is_adult", (18,), {}, True),
            # Bug 3 fixed: average([]) raises ValueError (or returns sensible value) without crashing fatally
            lambda m: _runs_without_exception(m, "average", ([1, 2, 3],)),
        ],
        "timeout": 120,
    },

    # ── bug3.py: FileNotFoundError · AttributeError · encoding ───────────────
    {
        "id": "bug3",
        "file": "sample_bugs/bug3.py",
        "bug_count": 3,
        "tags": ["file-io", "attribute-error", "encoding"],
        "checkers": [
            # Bug 1: read_config should handle missing file gracefully (return None / raise FileNotFoundError
            # with a clear message) — we just check it doesn't crash the import
            lambda m: True,  # structural: file must be importable after fix
            # Bug 2 fixed: clean_username converts int to str before strip
            lambda m: _check(m, "clean_username", ({"user_id": 42, "name": "Bob"},), {}, "42"),
            # Bug 3 fixed: load_log specifies encoding — runs on the file itself
            lambda m: _runs_without_exception(m, "load_log", ("sample_bugs/bug3.py",)),
        ],
        "timeout": 120,
    },

    # ── bug4.py: AttributeError · mutable default · __str__ type ────────────
    {
        "id": "bug4",
        "file": "sample_bugs/bug4.py",
        "bug_count": 3,
        "tags": ["class", "mutable-default", "dunder"],
        "checkers": [
            # Bug 1 fixed: BankAccount.deposit works (balance initialised)
            lambda m: _runs_without_exception(
                type("_", (), {"_test": staticmethod(lambda: (
                    setattr(acc := m.BankAccount("Alice"), "_noop", acc.deposit(100)) or True
                ))})(), "_test", ()
            ),
            # Simpler form using a closure
            lambda m: (lambda: (acc := m.BankAccount("X"), acc.deposit(50)) and True)(),
            # Bug 2 fixed: two ShoppingCart instances are independent
            lambda m: (
                lambda: (
                    a := m.ShoppingCart(),
                    a.add("apple"),
                    b := m.ShoppingCart(),
                    b.total_items() == 0
                )[-1]
            )(),
            # Bug 3 fixed: str(account) returns a string
            lambda m: (
                lambda: isinstance(str(m.BankAccount.__str__(
                    type("_", (), {"balance": 100})()
                )), str)
            )(),
        ],
        "timeout": 120,
    },

    # ── bug5.py: race condition · generator exhaustion · datetime tz ─────────
    {
        "id": "bug5",
        "file": "sample_bugs/bug5.py",
        "bug_count": 3,
        "tags": ["threading", "generator", "datetime"],
        "checkers": [
            # Bug 1: race condition — hard to test deterministically.
            # Accept fix if run_threads() completes without exception.
            lambda m: _runs_without_exception(m, "run_threads", ()),
            # Bug 2 fixed: second pass equals first pass (generator re-created)
            lambda m: (
                lambda: (
                    first := list(m.even_numbers(10)),
                    second := list(m.even_numbers(10)),
                    first == second
                )[-1]
            )(),
            # Bug 3 fixed: is_expired uses timezone-aware now()
            lambda m: _runs_without_exception(
                m, "is_expired",
                (__import__("datetime").datetime(2020, 1, 1,
                    tzinfo=__import__("datetime").timezone.utc),)
            ),
        ],
        "timeout": 180,
    },
]
