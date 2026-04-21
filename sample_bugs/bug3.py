"""
sample_bugs/bug3.py — File I/O & encoding bugs
Three bugs intentionally planted:
  1. FileNotFoundError: hardcoded path that doesn't exist
  2. AttributeError: calling .strip() on int (wrong type from json.load)
  3. UnicodeDecodeError risk: open without explicit encoding on non-ASCII file
"""
import json


def read_config():
    """BUG 1: hardcoded path that almost certainly doesn't exist."""
    with open("/etc/myapp/config.json") as f:
        return json.load(f)


def clean_username(data: dict) -> str:
    """BUG 2: data['user_id'] is int, calling .strip() on it raises AttributeError."""
    return data["user_id"].strip()   # user_id is an int, not a str


def load_log(path: str) -> list[str]:
    """BUG 3: no encoding specified — breaks on non-ASCII content."""
    with open(path) as f:           # should be open(path, encoding="utf-8")
        return f.readlines()


if __name__ == "__main__":
    # Bug 1
    cfg = read_config()
    print("Config:", cfg)

    # Bug 2
    user_data = {"user_id": 42, "name": "Bob"}
    print("Username:", clean_username(user_data))

    # Bug 3
    lines = load_log("sample_bugs/bug3.py")
    print(f"Loaded {len(lines)} lines")
