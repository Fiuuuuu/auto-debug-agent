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
import inspect
import json
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
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


def _cart_instances_are_independent(module: Any) -> bool:
    """ShoppingCart() instances should not share the same default list."""
    try:
        cart_a = module.ShoppingCart()
        cart_b = module.ShoppingCart()
        cart_a.add("apple")
        return cart_b.items == []
    except Exception:
        return False


def _read_config_is_not_hardcoded(module: Any) -> bool:
    """
    read_config() should not depend on /etc/myapp/config.json.

    A good fix may return a dict from a project-local config, or gracefully
    return None/{} when the file is absent. Raising FileNotFoundError for the
    hardcoded system path means the original bug is still present.
    """
    try:
        source = inspect.getsource(module.read_config)
        if "/etc/myapp/config.json" in source:
            return False
        result = module.read_config()
        return result is None or isinstance(result, dict)
    except Exception:
        return False


def _read_lines_handles_utf8(module: Any) -> bool:
    """read_lines() should be able to read a UTF-8 file containing non-ASCII text."""
    try:
        source = inspect.getsource(module.read_lines)
        if "encoding" not in source:
            return False
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as f:
            f.write("hello\n中文\n")
            path = Path(f.name)
        try:
            return module.read_lines(str(path)) == ["hello\n", "中文\n"]
        finally:
            path.unlink(missing_ok=True)
    except Exception:
        return False


def _bank_account_str_is_string(module: Any) -> bool:
    """str(BankAccount(...)) should return a string without TypeError."""
    try:
        return isinstance(str(module.BankAccount(70.0)), str)
    except Exception:
        return False


def _drop_inactive_is_safe(module: Any) -> bool:
    """drop_inactive() should remove inactive users without mutating during iteration."""
    users = {
        1: {"name": "Alice", "active": True},
        2: {"name": "Bob", "active": False},
        3: {"name": "Carol", "active": True},
    }
    try:
        result = module.drop_inactive(users)
        return set(result.keys()) == {1, 3}
    except Exception:
        return False


def _first_even_handles_missing_match(module: Any) -> bool:
    """first_even() should not leak StopIteration when no even number exists."""
    try:
        return module.first_even([1, 3, 5]) is None
    except StopIteration:
        return False
    except Exception:
        return False


def _counter_reaches_expected_value(module: Any) -> bool:
    """Counter.increment() should use a shared lock and reach the expected value."""
    try:
        counter = module.Counter()
        has_lock = any(
            hasattr(value, "acquire") and hasattr(value, "release")
            for value in counter.__dict__.values()
        )
        threads = [threading.Thread(target=counter.increment) for _ in range(1000)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return has_lock and counter.value == 1000
    except Exception:
        return False


def _fib_is_optimized(module: Any) -> bool:
    """
    fib() should still be correct and avoid the original exponential recursion.

    We avoid running fib(40) in the evaluator. Instead, require a visible cache
    or iterative implementation in the function source.
    """
    try:
        if module.fib(10) != 55:
            return False
        source = inspect.getsource(module.fib)
        markers = ("lru_cache", "cache", "memo", "for ", "while ")
        return any(marker in source for marker in markers)
    except Exception:
        return False


def _feature_missing_defaults_false(module: Any) -> bool:
    """feature_enabled() should return False when the environment flag is absent."""
    old = os.environ.pop("FEATURE_ENABLED", None)
    try:
        return module.feature_enabled() is False
    except Exception:
        return False
    finally:
        if old is not None:
            os.environ["FEATURE_ENABLED"] = old


def _datetime_json_serializes(module: Any) -> bool:
    """export_user() should serialize datetime values without raising."""
    try:
        raw = module.export_user({"name": "Ada", "created_at": datetime(2024, 1, 1)})
        data = json.loads(raw)
        return data["name"] == "Ada" and isinstance(data["created_at"], str)
    except Exception:
        return False


def _missing_file_returns_empty_line(module: Any) -> bool:
    """read_first_line() should handle a missing file path gracefully."""
    try:
        missing = Path(tempfile.gettempdir()) / "autodebug_missing_input.txt"
        missing.unlink(missing_ok=True)
        return module.read_first_line(str(missing)) == ""
    except Exception:
        return False


GOLDEN: list[dict] = [
    # ── bug1.py: KeyError · TypeError · ValueError ───────────────────────────
    {
        "id": "bug1",
        "file": "sample_bugs/bug1.py",
        "bug_count": 3,
        "tags": ["key-error", "type-error", "value-error"],
        "checkers": [
            # Bug 1 fixed: missing price is handled with a sensible default.
            lambda m: _check(m, "extract_price", ({},), {}, 0.0),
            # Bug 2 fixed: None discount means no discount rather than TypeError.
            lambda m: _check(m, "apply_discount", (99.0, None), {}, 99.0),
            # Bug 3 fixed: "3.0" can be parsed as quantity 3.
            lambda m: _check(m, "parse_quantity", ("3.0",), {}, 3),
        ],
        "timeout": 120,
    },

    # ── bug2.py: mutable default · missing return · __str__ type ─────────────
    {
        "id": "bug2",
        "file": "sample_bugs/bug2.py",
        "bug_count": 3,
        "tags": ["mutable-default", "missing-return", "dunder"],
        "checkers": [
            # Bug 1 fixed: ShoppingCart instances do not share the same items list.
            _cart_instances_are_independent,
            # Bug 2 fixed: withdraw() returns the new balance.
            lambda m: m.BankAccount(100.0).withdraw(30.0) == 70.0,
            # Bug 3 fixed: str(account) returns a real string without TypeError.
            _bank_account_str_is_string,
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
            # Bug 1 fixed: read_config no longer depends on /etc/myapp/config.json.
            _read_config_is_not_hardcoded,
            # Bug 2 fixed: clean_user_id converts int to str before upper().
            lambda m: _check(m, "clean_user_id", ({"user_id": 42, "name": "Bob"},), {}, "42"),
            # Bug 3 fixed: read_lines specifies UTF-8 or otherwise handles non-ASCII files.
            _read_lines_handles_utf8,
        ],
        "timeout": 120,
    },

    # ── bug4.py: dict mutation · StopIteration · thread safety ───────────────
    {
        "id": "bug4",
        "file": "sample_bugs/bug4.py",
        "bug_count": 3,
        "tags": ["dict-mutation", "iterator", "threading"],
        "checkers": [
            # Bug 1 fixed: drop_inactive does not mutate the dict during iteration.
            _drop_inactive_is_safe,
            # Bug 2 fixed: first_even returns None when no even number exists.
            _first_even_handles_missing_match,
            # Bug 3 fixed: Counter reaches the expected value under threaded use.
            _counter_reaches_expected_value,
        ],
        "timeout": 120,
    },

    # ── bug5.py: datetime tz · flatten base case · Fibonacci recursion ───────
    {
        "id": "bug5",
        "file": "sample_bugs/bug5.py",
        "bug_count": 3,
        "tags": ["datetime", "recursion", "performance"],
        "checkers": [
            # Bug 1 fixed: aware expiry timestamps can be compared safely.
            lambda m: _check(m, "is_expired", ("2020-01-01T00:00:00+00:00",), {}, True),
            # Bug 2 fixed: flatten has a base case for scalar values.
            lambda m: _check(m, "flatten", ([1, [2, [3, 4]], 5],), {}, [1, 2, 3, 4, 5]),
            # Bug 3 fixed: fib remains correct and is no longer exponential recursion.
            _fib_is_optimized,
        ],
        "timeout": 180,
    },

    # ── bug6.py: nested payload · numeric header · empty aggregate ───────────
    {
        "id": "bug6",
        "file": "sample_bugs/bug6.py",
        "bug_count": 3,
        "tags": ["api-payload", "missing-field", "empty-list"],
        "checkers": [
            # Bug 1 fixed: missing nested email is handled safely.
            lambda m: _check(m, "get_user_email", ({},), {}, ""),
            # Bug 2 fixed: fractional Retry-After headers can be parsed.
            lambda m: _check(m, "parse_retry_after", ({"Retry-After": "1.5"},), {}, 1),
            # Bug 3 fixed: empty latency samples do not divide by zero.
            lambda m: _check(m, "average_latency", ([],), {}, 0.0),
        ],
        "timeout": 120,
    },

    # ── bug7.py: missing env · default port · optional path ──────────────────
    {
        "id": "bug7",
        "file": "sample_bugs/bug7.py",
        "bug_count": 3,
        "tags": ["environment", "cli-config", "none-handling"],
        "checkers": [
            # Bug 1 fixed: missing FEATURE_ENABLED defaults to False.
            _feature_missing_defaults_false,
            # Bug 2 fixed: missing port uses the conventional default.
            lambda m: _check(m, "parse_port", (None,), {}, 8000),
            # Bug 3 fixed: optional URL path can be absent.
            lambda m: _check(m, "build_url", ("https://api.example.com", None), {}, "https://api.example.com/"),
        ],
        "timeout": 120,
    },

    # ── bug8.py: empty max · None iterable · missing dict key ────────────────
    {
        "id": "bug8",
        "file": "sample_bugs/bug8.py",
        "bug_count": 3,
        "tags": ["collections", "empty-input", "key-error"],
        "checkers": [
            # Bug 1 fixed: top_customer handles no orders.
            lambda m: _check(m, "top_customer", ([],), {}, None),
            # Bug 2 fixed: missing tags normalize to an empty list.
            lambda m: _check(m, "normalize_tags", (None,), {}, []),
            # Bug 3 fixed: new keys can be merged into the count dictionary.
            lambda m: _check(m, "merge_counts", ({"a": 1}, {"b": 2}), {}, {"a": 1, "b": 2}),
        ],
        "timeout": 120,
    },

    # ── bug9.py: JSONDecodeError · numeric coercion · datetime serialization ─
    {
        "id": "bug9",
        "file": "sample_bugs/bug9.py",
        "bug_count": 3,
        "tags": ["json", "csv", "serialization"],
        "checkers": [
            # Bug 1 fixed: empty JSON input returns an empty object.
            lambda m: _check(m, "parse_json", ("",), {}, {}),
            # Bug 2 fixed: decimal-looking CSV amounts can be coerced to ints.
            lambda m: _check(m, "load_amounts", ("amount\n3.5\n",), {}, [3]),
            # Bug 3 fixed: datetime fields can be serialized to JSON.
            _datetime_json_serializes,
        ],
        "timeout": 120,
    },

    # ── bug10.py: Path object · missing parent · missing file ────────────────
    {
        "id": "bug10",
        "file": "sample_bugs/bug10.py",
        "bug_count": 3,
        "tags": ["pathlib", "file-io", "missing-file"],
        "checkers": [
            # Bug 1 fixed: pathlib.Path inputs are accepted.
            lambda m: _check(m, "ensure_txt_extension", (Path("report"),), {}, "report.txt"),
            # Bug 2 fixed: paths without a parent return an empty parent name.
            lambda m: _check(m, "parent_name", ("file.txt",), {}, ""),
            # Bug 3 fixed: missing files return an empty first line.
            _missing_file_returns_empty_line,
        ],
        "timeout": 120,
    },
]
