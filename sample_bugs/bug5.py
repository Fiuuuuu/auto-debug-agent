"""
sample_bugs/bug5.py — Concurrency & generator bugs
Three bugs intentionally planted:
  1. Race condition: shared counter mutated from multiple threads without a lock
  2. Generator exhausted silently — second iteration yields nothing
  3. datetime comparison with naive vs aware timezone objects — TypeError
"""
import threading
from datetime import datetime, timezone


# ── Bug 1: race condition ─────────────────────────────────────────────────────
counter = 0

def increment(n: int):
    global counter
    for _ in range(n):
        tmp = counter      # read
        counter = tmp + 1  # write — not atomic, threads can interleave


def run_threads():
    threads = [threading.Thread(target=increment, args=(10_000,)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print(f"Expected 40000, got {counter}")   # likely < 40000


# ── Bug 2: generator exhausted ────────────────────────────────────────────────
def even_numbers(limit: int):
    for n in range(0, limit, 2):
        yield n


def process_evens():
    evens = even_numbers(10)
    first_pass  = list(evens)   # consumes the generator
    second_pass = list(evens)   # BUG 2: always [] — generator already exhausted
    print("First :", first_pass)
    print("Second:", second_pass)   # should equal first_pass


# ── Bug 3: naive vs aware datetime comparison ─────────────────────────────────
def is_expired(expiry_ts: datetime) -> bool:
    """BUG 3: datetime.now() is naive; expiry_ts is tz-aware → TypeError."""
    return datetime.now() > expiry_ts   # should be datetime.now(timezone.utc)


if __name__ == "__main__":
    run_threads()
    process_evens()
    expiry = datetime(2020, 1, 1, tzinfo=timezone.utc)
    print("Expired:", is_expired(expiry))
