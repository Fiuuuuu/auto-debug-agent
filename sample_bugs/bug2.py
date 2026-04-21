"""
sample_bugs/bug2.py — Recursive & logic bugs
Three bugs intentionally planted:
  1. RecursionError: missing base case in factorial
  2. Logic error: wrong comparison operator causes silent wrong output
  3. ZeroDivisionError: no guard when denominator is 0
"""


def factorial(n):
    """BUG 1: no base case — infinite recursion."""
    if n == 0:
        return 1
    return n * factorial(n - 1)


def is_adult(age):
    """BUG 2: should be >= 18, using > 18 so 18-year-olds are excluded."""
    return age > 18   # should be >=


def average(numbers):
    """BUG 3: no guard for empty list — ZeroDivisionError."""
    return sum(numbers) / len(numbers)


if __name__ == "__main__":
    # Bug 1
    print("5! =", factorial(5))

    # Bug 2 (silent — wrong output, no exception)
    print("Is 18 an adult?", is_adult(18))   # should be True, returns False

    # Bug 3
    print("Average of []:", average([]))
