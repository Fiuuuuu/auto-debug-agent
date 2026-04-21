"""
sample_bugs/bug4.py — Class & state bugs
Three bugs intentionally planted:
  1. Missing self.balance init — AttributeError on withdraw
  2. Mutable default argument shared across instances
  3. __str__ returns int instead of str — implicit TypeError in some contexts
"""


class BankAccount:
    def __init__(self, owner: str):
        self.owner = owner
        # BUG 1: forgot to initialise self.balance = 0

    def deposit(self, amount: float):
        self.balance += amount   # AttributeError: 'BankAccount' has no attribute 'balance'

    def withdraw(self, amount: float):
        if amount > self.balance:
            raise ValueError("Insufficient funds")
        self.balance -= amount

    def __str__(self):
        return self.balance   # BUG 3: should be str(self.balance) or f"Balance: {self.balance}"


class ShoppingCart:
    """BUG 2: mutable default argument — all instances share the same list."""
    def __init__(self, items=[]):   # should be items=None, then self.items = items or []
        self.items = items

    def add(self, item: str):
        self.items.append(item)

    def total_items(self) -> int:
        return len(self.items)


if __name__ == "__main__":
    # Bug 1 & 3
    acc = BankAccount("Alice")
    acc.deposit(100)
    print(acc)

    # Bug 2 — second cart mysteriously has the first cart's items
    cart_a = ShoppingCart()
    cart_a.add("apple")
    cart_b = ShoppingCart()
    print("cart_b items:", cart_b.total_items())   # should be 0, will be 1
