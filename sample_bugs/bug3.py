"""
sample_bugs/bug3.py — File I/O and encoding bugs
Three bugs intentionally planted:
  1. FileNotFoundError: hardcoded absolute path that does not exist
  2. AttributeError: calling a string method on an int from JSON
  3. UnicodeDecodeError risk: file opened without explicit encoding
"""
import json
import os


def read_config() -> dict:
    """BUG 1: hardcoded path almost certainly does not exist on this machine."""
    with open("/etc/myapp/config.json") as f:   # should derive path from __file__
        return json.load(f)


def clean_user_id(data: dict) -> str:
    """BUG 2: data['user_id'] is an int; .upper() is a str method."""
    return data["user_id"].upper()  # AttributeError: 'int' has no attribute 'upper'


def read_lines(path: str) -> list[str]:
    """BUG 3: no encoding arg — fails when file contains non-ASCII characters."""
    with open(path) as f:           # should be open(path, encoding="utf-8")
        return f.readlines()


if __name__ == "__main__":
    # Bug 1
    cfg = read_config()
    print("Config loaded:", cfg)

    # Bug 2 (reached if bug 1 is fixed)
    user = {"user_id": 7, "name": "Carol"}
    print("User ID:", clean_user_id(user))

    # Bug 3 (reached if bugs 1+2 are fixed)
    lines = read_lines(__file__)
    print(f"Read {len(lines)} lines from this file")

