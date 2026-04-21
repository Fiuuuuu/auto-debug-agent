#!/usr/bin/env python3
"""
config.py — Single source of truth for all configuration.

Import from here everywhere so changing the model or base URL
only requires editing one file.
"""
import os
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()
client  = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL   = os.environ["MODEL_ID"]

# Runtime directories (all under .debug/ so one .gitignore line hides them)
DEBUG_DIR = WORKDIR / ".debug"
BUS_DIR   = DEBUG_DIR / "bus"
MEM_DIR   = DEBUG_DIR / "memory"
TASK_FILE = DEBUG_DIR / "tasks.json"

# Agent loop tuning
MAX_TOKENS      = 8000
TOKEN_THRESHOLD = 40000   # chars / 4 ≈ tokens; triggers auto_compact
MAX_RETRIES     = 3
BACKOFF_BASE    = 1.0     # seconds; doubles each attempt
