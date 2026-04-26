"""
sample_bugs/bug7.py - Environment and CLI-style config parsing
"""
import os


def feature_enabled() -> bool:
    """Return whether the FEATURE_ENABLED environment flag is enabled."""
    return os.getenv("FEATURE_ENABLED").lower() == "true"


def parse_port(value) -> int:
    """Parse a server port value."""
    return int(value)


def build_url(host: str, path: str) -> str:
    """Join a host and URL path."""
    return host.rstrip("/") + "/" + path.strip("/")


if __name__ == "__main__":
    os.environ.pop("FEATURE_ENABLED", None)
    print("Feature enabled:", feature_enabled())
    print("Port:", parse_port(None))
    print("URL:", build_url("https://api.example.com", None))
