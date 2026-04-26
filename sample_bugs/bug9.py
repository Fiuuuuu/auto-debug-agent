"""
sample_bugs/bug9.py - Serialization and text parsing
"""
import csv
import json
from datetime import datetime


def parse_json(raw: str) -> dict:
    """Parse a JSON object from a string."""
    return json.loads(raw)


def load_amounts(csv_text: str) -> list[int]:
    """Read integer amounts from CSV text."""
    reader = csv.DictReader(csv_text.splitlines())
    return [int(row["amount"]) for row in reader]


def export_user(user: dict) -> str:
    """Serialize a user record to JSON."""
    return json.dumps(user)


if __name__ == "__main__":
    print("JSON:", parse_json(""))
    print("Amounts:", load_amounts("amount\n3.5\n"))
    print("User:", export_user({"name": "Ada", "created_at": datetime(2024, 1, 1)}))
