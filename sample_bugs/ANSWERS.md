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

---

## bug6.py — API payload edge cases

| # | Function | Error | Fix |
|---|----------|-------|-----|
| 1 | `get_user_email` | `KeyError` when nested `user.email` is absent | Use nested `.get()` defaults and return `""` when missing |
| 2 | `parse_retry_after` | `ValueError` for fractional header values such as `"1.5"` | Parse with `float()` before converting to `int` |
| 3 | `average_latency` | `ZeroDivisionError` for an empty sample list | Return `0.0` when no samples are available |

---

## bug7.py — Environment and CLI-style config parsing

| # | Function | Error | Fix |
|---|----------|-------|-----|
| 1 | `feature_enabled` | `AttributeError` when `FEATURE_ENABLED` is unset | Default missing env values to `"false"` |
| 2 | `parse_port` | `TypeError` when the port value is `None` | Return default port `8000` for missing input |
| 3 | `build_url` | `AttributeError` when `path` is `None` | Treat missing path as `""` |

---

## bug8.py — Collection boundary cases

| # | Function | Error | Fix |
|---|----------|-------|-----|
| 1 | `top_customer` | `ValueError` when `max()` receives an empty order list | Return `None` for no orders |
| 2 | `normalize_tags` | `TypeError` when tags is `None` | Treat missing tags as an empty list |
| 3 | `merge_counts` | `KeyError` when the right dict contains a new key | Use `result.get(key, 0) + value` |

---

## bug9.py — Serialization and text parsing

| # | Function | Error | Fix |
|---|----------|-------|-----|
| 1 | `parse_json` | `JSONDecodeError` for empty JSON text | Return `{}` for empty input |
| 2 | `load_amounts` | `ValueError` for decimal-looking CSV amounts | Parse via `float()` before converting to `int` |
| 3 | `export_user` | `TypeError` when serializing `datetime` | Use `json.dumps(..., default=str)` or convert datetime fields first |

---

## bug10.py — Paths and file boundaries

| # | Function | Error | Fix |
|---|----------|-------|-----|
| 1 | `ensure_txt_extension` | `AttributeError` when input is a `Path` object | Convert input with `str(path)` before string operations |
| 2 | `parent_name` | `IndexError` for paths without a parent directory | Return `""` when no parent component exists |
| 3 | `read_first_line` | `FileNotFoundError` for missing files | Return `""` when the file does not exist |
