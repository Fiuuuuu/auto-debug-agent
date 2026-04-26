#!/usr/bin/env python3
"""
graph.py — Build and compile the LangGraph StateGraph.

Topology
--------

                     ┌─────────────┐
          START ────►│  reproducer │
                     └──────┬──────┘
                            │
               ┌────────────┴────────────┐
           has_error                  no_error
               │                         │
               ▼                        END
        ┌─────────────┐
        │   analyst   │
        └──────┬──────┘
               │
               ▼
        ┌─────────────┐
        │    fixer    │◄──────────────────┐
        └──────┬──────┘                   │ (retry)
               │                         │
               ▼                         │
        ┌─────────────┐                  │
        │ permission  │                  │
        └──────┬──────┘                  │
               │                         │
      ┌────────┴────────┐                │
   approved          rejected            │
      │                  │               │
      ▼                 END              │
 ┌─────────────┐                        │
 │  verifier   │                        │
 └──────┬──────┘                        │
        │                               │
  ┌─────┴─────┐                         │
  ok        fail                        │
  │            │                        │
 END    retry_count < MAX? ────────────►┘
                │ (no)
               END

Checkpointing
-------------
MemorySaver stores the full DebugState after each node.
Crash recovery: re-instantiate app with the same thread_id to resume.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from .state import DebugState
from .nodes import (
    reproducer_node,
    analyst_node,
    fixer_node,
    permission_node,
    verifier_node,
)

# Maximum number of total fixer attempts (matches main.py default)
MAX_FIX_ATTEMPTS = 4


def draw_pipeline_mermaid() -> str:
    """
    Return the teaching-friendly Mermaid graph for the pipeline.

    LangGraph's built-in draw_mermaid() can collapse multiple conditional edges
    that point to END. We print the graph ourselves so the important
    verifier.ok -> END path is always visible.
    """
    return """---
config:
  flowchart:
    curve: linear
---
graph TD;
        __start__([<p>__start__</p>]):::first
        reproducer(reproducer)
        analyst(analyst)
        fixer(fixer)
        permission(permission)
        verifier(verifier)
        __end__([<p>__end__</p>]):::last
        __start__ --> reproducer;
        reproducer -. has_error .-> analyst;
        reproducer -. no_error .-> __end__;
        analyst --> fixer;
        fixer --> permission;
        permission -. approved .-> verifier;
        permission -. rejected .-> __end__;
        verifier -. ok .-> __end__;
        verifier -. retry .-> fixer;
        verifier -. give_up .-> __end__;
        classDef default fill:#f2f0ff,line-height:1.2
        classDef first fill-opacity:0
        classDef last fill:#bfb6fc
"""


# ── Conditional edge routers ──────────────────────────────────────────────────

def route_after_reproduce(state: DebugState) -> str:
    """Skip the rest of the pipeline if no error was found."""
    return "end" if state.get("status") == "skip" else "analyst"


def route_after_permission(state: DebugState) -> str:
    """Abort if the user rejected the fix."""
    return "verifier" if state.get("approved") else "end"


def route_after_verify(state: DebugState) -> str:
    """
    Decide next step after verification:
      ok      → done
      fail    → retry fixer if attempts remain, otherwise give up
    """
    if state.get("status") == "ok":
        return "ok"
    # retry_count was already incremented by verifier_node on failure
    if state.get("retry_count", 0) < MAX_FIX_ATTEMPTS:
        return "retry"
    return "give_up"


# ── Graph assembly ────────────────────────────────────────────────────────────

def build_graph():
    """Return a compiled LangGraph application with MemorySaver checkpointing."""
    builder = StateGraph(DebugState)

    # Register nodes
    builder.add_node("reproducer", reproducer_node)
    builder.add_node("analyst",    analyst_node)
    builder.add_node("fixer",      fixer_node)
    builder.add_node("permission", permission_node)
    builder.add_node("verifier",   verifier_node)

    # Entry point
    builder.set_entry_point("reproducer")

    # Reproducer → (has error → analyst) | (no error → END)
    builder.add_conditional_edges(
        "reproducer",
        route_after_reproduce,
        {"analyst": "analyst", "end": END},
    )

    # Analyst always feeds fixer
    builder.add_edge("analyst", "fixer")

    # Fixer → permission gate
    builder.add_edge("fixer", "permission")

    # Permission → (approved → verifier) | (rejected → END)
    builder.add_conditional_edges(
        "permission",
        route_after_permission,
        {"verifier": "verifier", "end": END},
    )

    # Verifier → (pass → END) | (fail+retry → fixer) | (fail+give_up → END)
    builder.add_conditional_edges(
        "verifier",
        route_after_verify,
        {"ok": END, "retry": "fixer", "give_up": END},
    )

    # Compile with in-memory checkpointer (swap for SqliteSaver for persistence)
    checkpointer = MemorySaver()
    return builder.compile(checkpointer=checkpointer)


# Module-level compiled app — imported by main_lg.py
app = build_graph()
