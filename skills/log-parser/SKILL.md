---
name: log-parser
description: Parse and interpret Python tracebacks and runtime error output. Use when an agent needs to understand where and why a Python program crashed.
---

# Log Parser Skill

You now have expertise in reading Python tracebacks and runtime logs. Follow this structured approach:

## Parsing Checklist

### 1. Identify the Exception

- [ ] **Type**: Record the exact exception class (`IndexError`, `KeyError`, `TypeError`, `AttributeError`, …)
- [ ] **Message**: Extract the human-readable message that follows the colon
- [ ] **Chained exceptions**: Look for `During handling of the above exception…` or `The above exception was the direct cause of…`

### 2. Locate the Crash Site

- [ ] Always use `view_traceback` first — it extracts the structured chain for you
- [ ] The **innermost** `File "…", line N, in <function>` is the actual crash site
- [ ] Distinguish **user code** (project files) from **library code** (`site-packages/`)
- [ ] If the crash is inside a library, look one frame up to find the calling user code

### 3. Trace the Call Chain

Read the traceback **bottom-up** (most recent call last):

```
Traceback (most recent call last):
  File "main.py", line 12, in run          ← entry point (top of stack)
    result = process(data)
  File "utils.py", line 34, in process     ← intermediate call
    return items[idx]
IndexError: list index out of range         ← crash site (bottom)
```

Walk **upward** from the crash until you find user code with a suspicious argument.

### 4. Common Exception → Root Cause Mapping

| Exception | Most Likely Cause |
|-----------|------------------|
| `IndexError` | Off-by-one; accessing empty list; wrong loop bound |
| `KeyError` | Typo in dict key; key added conditionally; wrong data source |
| `TypeError` | Wrong type passed to function; int+str arithmetic; calling None |
| `AttributeError` | Uninitialized attribute; wrong object type; None returned unexpectedly |
| `RecursionError` | Missing base case; infinite mutual recursion |
| `ZeroDivisionError` | No guard for empty sequence or zero denominator |
| `FileNotFoundError` | Hardcoded path; wrong working directory; missing file creation |
| `UnicodeDecodeError` | File opened without `encoding=` on non-ASCII content |

## Analysis Output Format

After using `view_traceback`, record your findings in this structure:

```
exception_type : <ExceptionClass>
message        : <exact message string>
crash_file     : <filename>:<line_number>
crash_fn       : <function name>
in_user_code   : yes / no
chained        : yes / no  (if yes, list parent exceptions)
suspicious_arg : <the value or expression that caused the crash>
```

## Workflow

1. **Run `view_traceback`** on the captured error output
2. **Record** the structured fields above
3. **Open the crash file** with `read_file` at ±10 lines around the crash line
4. **Identify** the suspicious expression or variable
5. **Hand off** the structured summary to the Analyst
