"""LangGraph wiring. Sync graph + RedisSaver checkpoint store.

Sync everywhere — see PLAN.md §1 (Approach A): the graph runs inside a
Celery prefork worker. Async only lives in the bot process.

The graph is intentionally tiny in M2:

    START → parse → process → finalize → END

Real nodes replace these stubs in M3+. The wiring (state schema, checkpointer,
edges) is what we want to lock in early.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from langgraph.graph import END, START, StateGraph

from graph.nodes._stubs import finalize_stub, parse_stub, process_stub
from schemas.session import SessionState
from storage.redis_client import DB, url_for


def _build_graph() -> StateGraph:
    g = StateGraph(SessionState)
    g.add_node("parse", parse_stub)
    g.add_node("process", process_stub)
    g.add_node("finalize", finalize_stub)
    g.add_edge(START, "parse")
    g.add_edge("parse", "process")
    g.add_edge("process", "finalize")
    g.add_edge("finalize", END)
    return g


@lru_cache(maxsize=1)
def get_compiled_graph() -> Any:
    """Compiled graph with RedisSaver — cached per-process.

    Import is deferred so that unit tests can exercise the graph builder
    without requiring the langgraph-checkpoint-redis package or a live Redis.
    """
    from langgraph.checkpoint.redis import RedisSaver

    saver = RedisSaver.from_conn_string(url_for(DB.LANGGRAPH))
    # Some versions of the lib expose a context manager — handle both shapes.
    if hasattr(saver, "__enter__"):
        saver = saver.__enter__()  # noqa: PLC2801 — long-lived process owns it
    if hasattr(saver, "setup"):
        saver.setup()
    return _build_graph().compile(checkpointer=saver)


def thread_config(session_id: str) -> dict[str, dict[str, str]]:
    """LangGraph addresses checkpoints by `thread_id`. We use session_id."""
    return {"configurable": {"thread_id": session_id}}
