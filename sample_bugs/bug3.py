"""
sample_bugs/bug3.py — File I/O and encoding
"""
import json
import os


def read_config() -> dict:
    """Load the application config file and return its contents."""
    with open("/etc/myapp/config.json") as f:
        return json.load(f)


def clean_user_id(data: dict) -> str:
    """Return a normalised (upper-case) user ID string."""
    return data["user_id"].upper()


def read_lines(path: str) -> list[str]:
    """Read all lines from a text file and return them as a list."""
    with open(path) as f:
        return f.readlines()


if __name__ == "__main__":
    cfg = read_config()
    print("Config loaded:", cfg)

    user = {"user_id": 7, "name": "Carol"}
    print("User ID:", clean_user_id(user))

    lines = read_lines(__file__)
    print(f"Read {len(lines)} lines from this file")
