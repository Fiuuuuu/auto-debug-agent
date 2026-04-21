---
name: static-analysis
description: Diagnose the root cause of a Python bug from source code and traceback. Use when an agent needs to reason about why a crash happened and produce a minimal fix plan.
---

# Static Analysis Skill

You now have expertise in diagnosing Python bugs from source code. Follow this structured approach:

## Analysis Checklist

### 1. Confirm Syntax First

- [ ] Run `python_check` on the file before any deeper analysis
- [ ] If syntax is invalid, stop — the file cannot be analysed further until it compiles

### 2. Locate the Exact Lines

- [ ] Open the crash file with `read_file`, focusing on ±15 lines around the crash
- [ ] Identify the **exact expression** that raised the exception
- [ ] Look at what values are being passed in: trace the arguments one call-frame up

### 3. Scan for Bug Classes

Check for each of the following patterns:

| Bug Class | Pattern to Look For |
|-----------|-------------------|
| **Off-by-one** | `items[len(items)]`, `range(n+1)`, `> n` instead of `>= n` |
| **Wrong key** | `dict["mail"]` vs `dict["email"]`; keys added conditionally |
| **Type mismatch** | `int + str`; `None` in arithmetic; unchecked return type |
| **Missing init** | `self.x` used before assigned in `__init__` |
| **Mutable default** | `def f(x=[]):` or `def f(x={}):` — shared across calls |
| **Missing base case** | Recursive function with no termination condition |
| **Unchecked empty** | `list[0]` or `sum(x)/len(x)` without empty-list guard |
| **Wrong import path** | `from module import name` where `name` is misspelled or missing |
| **Naive datetime** | Comparing `datetime.now()` (naive) with tz-aware datetime |
| **Generator exhausted** | Iterating a generator twice without re-creating it |

### 4. Find All Call Sites

```bash
# Use grep_files to find every place the buggy function is called
grep_files(pattern="function_name\(", path=".")

# Find all places a suspicious variable is assigned
grep_files(pattern="variable_name\s*=", path=".")
```

### 5. Assess Impact

- [ ] Is the bug triggered every run, or only on certain inputs?
- [ ] Does fixing it require changing the call site, the function, or both?
- [ ] Are there other functions with the same pattern that need the same fix?

## Root Cause Output Format

Summarise in **≤ 3 bullet points**:

```
Root Cause:
• <Bug class> at <file>:<line> — <what is wrong>
• <Why it happens> — <what input or state triggers it>
• <Scope> — isolated to this function / affects N call sites

Minimal Fix Plan:
1. <file>:<line> — change `<old>` → `<new>`
2. (optional) <file>:<line> — change `<old>` → `<new>`
```

## Common Fix Patterns

```python
# Off-by-one
items[len(items)]      → items[len(items) - 1]  # or items[-1]

# Wrong dict key
d["mail"]              → d["email"]

# Type mismatch
total = price + label  → total = price + float(label.strip("%")) / 100

# Missing __init__ attribute
# (add to __init__)    self.balance = 0

# Mutable default argument
def f(x=[]):           → def f(x=None):
                              x = x if x is not None else []

# Missing base case
def fact(n):           → def fact(n):
    return n * fact(n-1)      if n == 0: return 1
                              return n * fact(n - 1)

# Empty list guard
sum(x) / len(x)        → sum(x) / len(x) if x else 0.0

# Naive vs aware datetime
datetime.now() > ts    → datetime.now(timezone.utc) > ts
```

## Workflow

1. **`python_check`** — confirm file compiles
2. **`read_file`** — read crash site ± context
3. **Bug class scan** — apply checklist above
4. **`grep_files`** — find call sites if needed
5. **Write root cause** in the output format above
6. **Hand off** to Fixer with the minimal fix plan
