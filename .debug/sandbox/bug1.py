"""
sample_bugs/bug1.py
A deliberately buggy Python script for testing the auto-debug pipeline.
Three bugs intentionally planted:
  1. Off-by-one: list index out of range
  2. Key error: accessing dict key that doesn't exist
  3. Type error: adding int to string
"""

def get_last_item(items):
    """Return the last item. BUG: off-by-one index."""
    return items[-1]


def get_user_email(user_dict):
    """Return user email. BUG: wrong key name."""
    return user_dict["email"]   # should be "email"


def calculate_total(price, tax_label):
    """Return total as string. BUG: type mismatch."""
    # Convert tax_label like "10%" to float 0.10
    tax_rate = float(tax_label.strip().rstrip("%")) / 100
    total = price + (price * tax_rate)
    return f"Total: {total}"


if __name__ == "__main__":
    # Bug 1
    numbers = [10, 20, 30]
    print("Last number:", get_last_item(numbers))

    # Bug 2 (would be reached if bug 1 fixed)
    user = {"name": "Alice", "email": "alice@example.com"}
    print("Email:", get_user_email(user))

    # Bug 3 (would be reached if bugs 1+2 fixed)
    print(calculate_total(99.9, "10%"))
