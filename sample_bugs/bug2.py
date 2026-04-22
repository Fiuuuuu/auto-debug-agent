"""
sample_bugs/bug2.py — Object-oriented state management
"""


class ShoppingCart:
    """A simple shopping cart that holds item names."""
    def __init__(self, items=[]):
        self.items = items

    def add(self, item: str):
        self.items.append(item)


class BankAccount:
    def __init__(self, balance: float):
        self.balance = balance

    def withdraw(self, amount: float):
        """Deduct amount from balance and return the new balance."""
        if amount <= self.balance:
            self.balance -= amount

    def __str__(self):
        return self.balance


if __name__ == "__main__":
    cart_a = ShoppingCart()
    cart_b = ShoppingCart()
    cart_a.add("apple")
    print("Cart B (should be empty):", cart_b.items)

    acc = BankAccount(100.0)
    new_bal = acc.withdraw(30.0)
    print("New balance:", new_bal + 0)

    print("Account: " + str(acc))
