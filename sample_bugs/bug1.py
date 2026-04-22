"""
sample_bugs/bug1.py — Data processing pipeline bugs
Three bugs intentionally planted:
  1. KeyError: accessing a missing dict key instead of using .get()
  2. TypeError: passing None into a numeric operation
  3. ValueError: int() called on a decimal string like '3.0'
"""


def extract_price(record: dict) -> float:
    """BUG 1: 'price' key may be absent — should use .get() with a default."""
    return record["price"]          # raises KeyError when key is missing


def apply_discount(price, discount):
    """BUG 2: discount may be None when no promo is active."""
    return price * (1 - discount)   # TypeError if discount is None


def parse_quantity(raw: str) -> int:
    """BUG 3: raw value like '3.0' cannot be parsed directly by int()."""
    return int(raw)                 # should be int(float(raw))


if __name__ == "__main__":
    # Bug 1 — record without a 'price' key
    item = {"name": "Widget", "sku": "W-001"}
    print("Price:", extract_price(item))

    # Bug 2 (reached if bug 1 is fixed)
    print("Discounted:", apply_discount(99.0, None))

    # Bug 3 (reached if bugs 1+2 are fixed)
    print("Quantity:", parse_quantity("3.0"))

