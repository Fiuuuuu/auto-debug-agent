"""
sample_bugs/bug1.py — Data processing pipeline
"""


def extract_price(record: dict) -> float:
    """Return the price from a product record."""
    return record["price"]


def apply_discount(price, discount):
    """Return price after applying a promotional discount."""
    return price * (1 - discount)


def parse_quantity(raw: str) -> int:
    """Parse a raw quantity string and return an integer."""
    return int(raw)


if __name__ == "__main__":
    item = {"name": "Widget", "sku": "W-001"}
    print("Price:", extract_price(item))

    print("Discounted:", apply_discount(99.0, None))

    print("Quantity:", parse_quantity("3.0"))
