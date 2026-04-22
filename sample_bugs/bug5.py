"""
sample_bugs/bug5.py — Datetime and recursion
"""
from datetime import datetime, timezone


def is_expired(expiry_str: str) -> bool:
    """Return True if the given ISO-format expiry timestamp is in the past."""
    expiry = datetime.fromisoformat(expiry_str)
    return datetime.now() > expiry


def flatten(lst) -> list:
    """Recursively flatten a nested list into a single list."""
    result = []
    for item in lst:
        result.extend(flatten(item))
    return result


def fib(n: int) -> int:
    """Return the n-th Fibonacci number."""
    if n <= 1:
        return n
    return fib(n - 1) + fib(n - 2)


if __name__ == "__main__":
    print("Expired:", is_expired("2020-01-01T00:00:00+00:00"))
    print("Flattened:", flatten([1, [2, [3, 4]], 5]))
    print("fib(40):", fib(40))
