"""
sample_bugs/bug4.py — Concurrency and iterator bugs
Three bugs intentionally planted:
  1. RuntimeError: dict changed size during iteration
  2. StopIteration leak: next() without a default raises outside a for-loop
  3. Race condition: unsynchronised counter increment in threads (silent wrong result)
"""
import threading


def drop_inactive(users: dict) -> dict:
    """BUG 1: mutates the dict while iterating over it."""
    for uid, info in users.items():         # should iterate over list(users.items())
        if not info["active"]:
            del users[uid]
    return users


def first_even(numbers):
    """BUG 2: next() with no default raises StopIteration if no even number exists."""
    gen = (n for n in numbers if n % 2 == 0)
    return next(gen)                        # should be next(gen, None)


class Counter:
    """BUG 3: no lock — concurrent increments lose updates."""
    def __init__(self):
        self.value = 0

    def increment(self):
        current = self.value
        self.value = current + 1            # not atomic; needs threading.Lock


if __name__ == "__main__":
    # Bug 1
    users = {
        1: {"name": "Alice", "active": True},
        2: {"name": "Bob",   "active": False},
        3: {"name": "Carol", "active": True},
    }
    print("Active users:", drop_inactive(users))

    # Bug 2 (reached if bug 1 is fixed)
    print("First even in [1,3,5]:", first_even([1, 3, 5]))

    # Bug 3 (reached if bugs 1+2 are fixed — silent wrong output)
    counter = Counter()
    threads = [threading.Thread(target=counter.increment) for _ in range(1000)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print(f"Counter (expected 1000, got {counter.value})")
