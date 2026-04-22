# sample_bugs — Answer Key

Each file has **three intentional bugs**, listed below with the location and fix.

---

## bug1.py — Data processing pipeline

| # | Function | Error | Fix |
|---|----------|-------|-----|
| 1 | `extract_price` | `KeyError` when `"price"` key is absent | `record.get("price", 0.0)` |
| 2 | `apply_discount` | `TypeError: unsupported operand type(s) for *: 'float' and 'NoneType'` | Guard: `if discount is None: return price` |
| 3 | `parse_quantity` | `ValueError: invalid literal for int() with base 10: '3.0'` | `int(float(raw))` |

---

## bug2.py — OO state management

| # | Location | Error | Fix |
|---|----------|-------|-----|
| 1 | `ShoppingCart.__init__(self, items=[])` | Mutable default arg — all instances share the **same** list | `items=None`; `self.items = items if items is not None else []` |
| 2 | `BankAccount.withdraw` | Missing `return` — caller receives `None` | Add `return self.balance` after the deduction |
| 3 | `BankAccount.__str__` | Returns `float` not `str` — `TypeError` on string concatenation | `return f"Balance: {self.balance}"` |

---

## bug3.py — File I/O and encoding

| # | Function | Error | Fix |
|---|----------|-------|-----|
| 1 | `read_config` | `FileNotFoundError` — hardcoded `/etc/myapp/config.json` | Derive path from `__file__`: `os.path.join(os.path.dirname(__file__), "config.json")` |
| 2 | `clean_user_id` | `AttributeError: 'int' object has no attribute 'upper'` | Cast first: `str(data["user_id"]).upper()` |
| 3 | `read_lines` | `UnicodeDecodeError` on non-ASCII files (platform-dependent default encoding) | `open(path, encoding="utf-8")` |

---

## bug4.py — Concurrency and iterators

| # | Location | Error | Fix |
|---|----------|-------|-----|
| 1 | `drop_inactive` — `for uid, info in users.items()` | `RuntimeError: dictionary changed size during iteration` | Iterate over a snapshot: `list(users.items())` |
| 2 | `first_even` — `next(gen)` | `StopIteration` propagates out when no even number exists | `next(gen, None)` |
| 3 | `Counter.increment` | Silent wrong result — non-atomic read-modify-write under threads | Protect with `threading.Lock`: acquire before read, release after write |

---

## bug5.py — Datetime and recursion

| # | Function | Error | Fix |
|---|----------|-------|-----|
| 1 | `is_expired` | `TypeError: can't compare offset-naive and offset-aware datetimes` | `datetime.now(timezone.utc)` instead of `datetime.now()` |
| 2 | `flatten` | `RecursionError` — plain values (int, str) are also iterable in the wrong sense; no base case | Check `if isinstance(item, list): result.extend(flatten(item))` else `result.append(item)` |
| 3 | `fib` | `RecursionError` for `n > ~35` (exponential call tree) | Add `@functools.lru_cache` or rewrite as iteration |
