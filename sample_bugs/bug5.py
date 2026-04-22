"""
sample_bugs/bug5.py — Datetime and recursion bugs
Three bugs intentionally planted:
  1. TypeError: naive and timezone-aware datetimes compared with >
  2. RecursionError: missing base case in recursive list flattening
  3. OverflowError: exponential recursion depth in naive Fibonacci
"""
from datetime import datetime, timezone


def is_expired(expiry_str: str) -> bool:
    """BUG 1: expiry is timezone-aware; datetime.now() is naive — comparison raises."""
    expiry = datetime.fromisoformat(expiry_str)         # has tzinfo
    return datetime.now() > expiry                      # should be datetime.now(timezone.utc)


def flatten(lst) -> list:
    """BUG 2: no base case for non-list items — infinite recursion on plain values."""
    result = []
    for item in lst:
        result.extend(flatten(item))    # should check: if isinstance(item, list)
    return result


def fib(n: int) -> int:
    """BUG 3: no memoisation — O(2^n) calls, hits recursion limit for n > ~35."""
    if n <= 1:
        return n
    return fib(n - 1) + fib(n - 2)     # should use functools.lru_cache or iteration


if __name__ == "__main__":
    print("Expired:", is_expired("2020-01-01T00:00:00+00:00"))
    print("Flattened:", flatten([1, [2, [3, 4]], 5]))
    print("fib(40):", fib(40))
