"""
sample_bugs/bug8.py - Collection boundary cases
"""


def top_customer(orders: list[dict]) -> str:
    """Return the customer name from the highest-value order."""
    return max(orders, key=lambda order: order["total"])["customer"]


def normalize_tags(tags: list[str]) -> list[str]:
    """Normalize optional user tags."""
    return [tag.strip().lower() for tag in tags]


def merge_counts(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    """Merge two count dictionaries."""
    result = left.copy()
    for key, value in right.items():
        result[key] += value
    return result


if __name__ == "__main__":
    print("Top customer:", top_customer([]))
    print("Tags:", normalize_tags(None))
    print("Counts:", merge_counts({"a": 1}, {"b": 2}))
