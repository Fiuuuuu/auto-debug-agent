"""
sample_bugs/bug6.py - API payload edge cases
"""


def get_user_email(payload: dict) -> str:
    """Return a normalized user email from an API response payload."""
    return payload["user"]["email"].lower()


def parse_retry_after(headers: dict) -> int:
    """Return the Retry-After header as seconds."""
    return int(headers["Retry-After"])


def average_latency(samples: list[float]) -> float:
    """Return the average request latency."""
    return sum(samples) / len(samples)


if __name__ == "__main__":
    print("Email:", get_user_email({}))
    print("Retry after:", parse_retry_after({"Retry-After": "1.5"}))
    print("Average latency:", average_latency([]))
