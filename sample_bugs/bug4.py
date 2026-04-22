"""
sample_bugs/bug4.py — Concurrency and iterators
"""
import threading


def drop_inactive(users: dict) -> dict:
    """Remove inactive users from the dict and return it."""
    for uid, info in users.items():
        if not info["active"]:
            del users[uid]
    return users


def first_even(numbers):
    """Return the first even number in the sequence."""
    gen = (n for n in numbers if n % 2 == 0)
    return next(gen)


class Counter:
    """A simple integer counter."""
    def __init__(self):
        self.value = 0

    def increment(self):
        current = self.value
        self.value = current + 1


if __name__ == "__main__":
    users = {
        1: {"name": "Alice", "active": True},
        2: {"name": "Bob",   "active": False},
        3: {"name": "Carol", "active": True},
    }
    print("Active users:", drop_inactive(users))

    print("First even in [1,3,5]:", first_even([1, 3, 5]))

    counter = Counter()
    threads = [threading.Thread(target=counter.increment) for _ in range(1000)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print(f"Counter (expected 1000, got {counter.value})")
