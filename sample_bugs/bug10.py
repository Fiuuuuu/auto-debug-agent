"""
sample_bugs/bug10.py - Paths and file boundaries
"""
from pathlib import Path


def ensure_txt_extension(path) -> str:
    """Return a string path ending in .txt."""
    if path.endswith(".txt"):
        return path
    return path + ".txt"


def parent_name(path: str) -> str:
    """Return the parent directory name for a path."""
    return path.split("/")[-2]


def read_first_line(path: str) -> str:
    """Read the first line from a text file."""
    with open(path) as f:
        return f.readline().strip()


if __name__ == "__main__":
    print("Path:", ensure_txt_extension(Path("report")))
    print("Parent:", parent_name("file.txt"))
    print("First line:", read_first_line("missing.txt"))
