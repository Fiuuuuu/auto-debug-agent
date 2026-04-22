"""
sample_bugs/bug2.py — Object-oriented state bugs
Three bugs intentionally planted:
  1. Mutable default argument: list shared across all instances
  2. Missing return statement: method implicitly returns None
  3. AttributeError: __str__ returns an int instead of a string
"""


class ShoppingCart:
    """BUG 1: mutable default argument — all carts share the same list."""
    def __init__(self, items=[]):   # should be items=None, then self.items = items or []
        self.items = items

    def add(self, item: str):
        self.items.append(item)


class BankAccount:
    def __init__(self, balance: float):
        self.balance = balance

    def withdraw(self, amount: float):
        """BUG 2: no return — caller gets None instead of the new balance."""
        if amount <= self.balance:
            self.balance -= amount
            # missing: return self.balance

    def __str__(self):
        """BUG 3: returns float, not str — raises TypeError on concatenation."""
        return self.balance         # should be return f"Balance: {self.balance}"


if __name__ == "__main__":
    # Bug 1 — two carts share items
    cart_a = ShoppingCart()
    cart_b = ShoppingCart()
    cart_a.add("apple")
    print("Cart B (should be empty):", cart_b.items)

    # Bug 2 (reached if bug 1 is fixed)
    acc = BankAccount(100.0)
    new_bal = acc.withdraw(30.0)
    print("New balance:", new_bal + 0)   # TypeError: None + 0

    # Bug 3 (reached if bugs 1+2 are fixed)
    print("Account: " + str(acc))

