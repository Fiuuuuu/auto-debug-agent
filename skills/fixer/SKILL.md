---
name: fixer
description: Apply minimal, safe patches to fix diagnosed Python bugs. Use when an agent needs to edit source code based on a root cause analysis.
---

# Fixer Skill

You now have expertise in applying minimal, safe patches to Python code. Follow this mandatory checklist — **do not skip steps**.

## Pre-Edit Checklist

- [ ] **Read first** — always call `read_file` on the target file before touching it
- [ ] **Baseline check** — run `python_check` to record the current syntax state
- [ ] **Write TODO list** — before any edit, write a numbered plan (max 5 items):

```
TODO:
1. Fix <bug class> at <file>:<line> — change `<old>` → `<new>`
2. (if multi-bug) Fix ...
3. Run python_check to verify
4. Read back patched lines
```

## Edit Rules

| Rule | Why |
|------|-----|
| Prefer `edit_file` over `write_file` | Targeted replace is safer; can't accidentally delete unrelated code |
| Change as few lines as possible | Minimises regression risk; easier to review |
| Never rename functions or variables | Call sites break silently |
| Never reformat unrelated code | Diff noise hides the real change |
| One bug = one edit call | Easier to revert a single change if it breaks something |

## Post-Edit Checklist

- [ ] **`python_check`** — must pass; if it fails, revert immediately with another `edit_file`
- [ ] **`read_file`** — read back the patched lines to visually confirm correctness
- [ ] **`git_diff`** — confirm only the expected lines were changed

## Revert Procedure

If `python_check` fails after an edit:

```
1. Call edit_file again with newString = the original code
2. Run python_check to confirm revert succeeded
3. Re-analyse root cause before attempting another edit
```

## Common Fix Patterns

```python
# ── Off-by-one ─────────────────────────────────────────────────────────────
# Before:
return items[len(items)]
# After:
return items[-1]

# ── Wrong dict key ──────────────────────────────────────────────────────────
# Before:
return user_dict["mail"]
# After:
return user_dict["email"]

# ── Type mismatch (int + str) ───────────────────────────────────────────────
# Before:
total = price + tax_label
# After:
total = price + float(tax_label.strip("%")) / 100

# ── Missing __init__ attribute ──────────────────────────────────────────────
# Before (in __init__):
self.owner = owner
# After:
self.owner = owner
self.balance = 0.0

# ── Mutable default argument ────────────────────────────────────────────────
# Before:
def __init__(self, items=[]):
    self.items = items
# After:
def __init__(self, items=None):
    self.items = items if items is not None else []

# ── Missing recursion base case ─────────────────────────────────────────────
# Before:
def factorial(n):
    return n * factorial(n - 1)
# After:
def factorial(n):
    if n == 0:
        return 1
    return n * factorial(n - 1)

# ── Empty list guard ────────────────────────────────────────────────────────
# Before:
return sum(numbers) / len(numbers)
# After:
if not numbers:
    raise ValueError("Cannot average an empty sequence")
return sum(numbers) / len(numbers)

# ── Naive vs aware datetime ─────────────────────────────────────────────────
# Before:
return datetime.now() > expiry_ts
# After:
from datetime import timezone
return datetime.now(timezone.utc) > expiry_ts
```

## Output Format

After completing the fix, write a patch description:

```
Patch Description:
• Changed: <file>:<line(s)> — <what was changed and why>
• Method: edit_file targeted replace (N lines changed)
• Verified: python_check ✓  |  read-back ✓  |  git_diff ✓
```

## Workflow

1. `read_file` — read the file to understand current state
2. `python_check` — baseline syntax check
3. **Write TODO list** — plan each fix before touching files
4. `edit_file` — apply one fix at a time
5. `python_check` — verify syntax still valid
6. `read_file` — read back patched section
7. `git_diff` — sanity-check scope of changes
8. Write **Patch Description** and hand off to Verifier
