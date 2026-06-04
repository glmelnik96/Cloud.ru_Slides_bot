"""LangGraph wiring — v0.9 batch pipeline (M3).

Sync everywhere — see PLAN.md §1 (Approach A): the graph runs inside a
Celery prefork worker. Async only lives in the bot process.

Flow:

    START
      → parse
      → brief        (Kimi vision)
      → classify     (DeepSeek)
      → design       (DeepSeek)   # donor pick BEFORE distribute — distributor
                                  # needs slot capacities of the chosen donor
      → distribute   (GLM OFF)
      → icons        (GLM OFF)
      → infographic  (GLM OFF)
      → copyedit     (GLM OFF)
      → assemble_plan
      → build        (skeleton — wraps build_v9.py in next chunk)
      → brand_guard  (skeleton — wraps brand_guardian.py)
      → render_png   (skeleton — LibreOffice headless)
      → visual_verify (Kimi vision)
      → process_verify (skeleton — synthesises validator verdicts)
      → finalize
      → END

Skeleton nodes write a clear FIXME marker into their artefact key so a
trace of any session immediately shows where the pipeline is still
unfinished. LLM nodes run end-to-end and produce real Pydantic-validated
output.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from langgraph.graph import END, START, StateGraph

from graph.nodes.agents import (
    AUTOFIX_BUDGET,
    autofix_node,
    brief_node,
    classify_node,
    copyedit_node,
    design_node,
    distribute_node,
    icons_node,
    infographic_node,
    visual_verify_node,
)
from graph.nodes.pipeline import (
    assemble_plan_node,
    brand_guard_node,
    build_node,
    finalize_node,
    parse_node,
    process_verify_node,
    render_png_node,
)
from schemas.session import SessionState
from storage.redis_client import DB, url_for


# Node-name constants kept here so wiring + tests share one source.
N_PARSE = "parse"
N_BRIEF = "brief"
N_CLASSIFY = "classify"
N_DESIGN = "design"
N_DISTRIBUTE = "distribute"
N_ICONS = "icons"
N_INFOGRAPHIC = "infographic"
N_COPYEDIT = "copyedit"
N_ASSEMBLE = "assemble_plan"
N_BUILD = "build"
N_BRAND = "brand_guard"
N_RENDER_PNG = "render_png"
N_VISUAL = "visual_verify"
N_PROCESS_VERIFY = "process_verify"
N_AUTOFIX = "autofix"
N_FINALIZE = "finalize"


def _route_after_verify(state: SessionState) -> str:
    """Conditional edge router after process_verify.

    READY → finalize (ship).
    NEEDS_REWORK with budget remaining → autofix (loop).
    NEEDS_REWORK with no budget → finalize (ship as draft with NEEDS_REWORK noted).

    We read the verdict from ``state.artefacts['verifier_verdict']`` rather
    than re-deriving it, so the route stays in lockstep with what the
    finalize/UI notes show. ``autofix_iterations`` is incremented inside
    ``autofix_node`` itself, so checking ``< AUTOFIX_BUDGET`` here gives
    exactly one retry pass before we ship as draft.
    """
    arts = state.artefacts or {}
    verdict = (arts.get("verifier_verdict") or {}).get("verdict", "NEEDS_REWORK")
    if verdict == "READY":
        return N_FINALIZE
    if (state.autofix_iterations or 0) < AUTOFIX_BUDGET:
        return N_AUTOFIX
    return N_FINALIZE


def _build_graph() -> StateGraph:
    g = StateGraph(SessionState)
    g.add_node(N_PARSE, parse_node)
    g.add_node(N_BRIEF, brief_node)
    g.add_node(N_CLASSIFY, classify_node)
    g.add_node(N_DESIGN, design_node)
    g.add_node(N_DISTRIBUTE, distribute_node)
    g.add_node(N_ICONS, icons_node)
    g.add_node(N_INFOGRAPHIC, infographic_node)
    g.add_node(N_COPYEDIT, copyedit_node)
    g.add_node(N_ASSEMBLE, assemble_plan_node)
    g.add_node(N_BUILD, build_node)
    g.add_node(N_BRAND, brand_guard_node)
    g.add_node(N_RENDER_PNG, render_png_node)
    g.add_node(N_VISUAL, visual_verify_node)
    g.add_node(N_PROCESS_VERIFY, process_verify_node)
    g.add_node(N_AUTOFIX, autofix_node)
    g.add_node(N_FINALIZE, finalize_node)

    g.add_edge(START, N_PARSE)
    g.add_edge(N_PARSE, N_BRIEF)
    g.add_edge(N_BRIEF, N_CLASSIFY)
    g.add_edge(N_CLASSIFY, N_DESIGN)
    g.add_edge(N_DESIGN, N_DISTRIBUTE)
    g.add_edge(N_DISTRIBUTE, N_ICONS)
    g.add_edge(N_ICONS, N_INFOGRAPHIC)
    g.add_edge(N_INFOGRAPHIC, N_COPYEDIT)
    g.add_edge(N_COPYEDIT, N_ASSEMBLE)
    g.add_edge(N_ASSEMBLE, N_BUILD)
    g.add_edge(N_BUILD, N_BRAND)
    g.add_edge(N_BRAND, N_RENDER_PNG)
    g.add_edge(N_RENDER_PNG, N_VISUAL)
    g.add_edge(N_VISUAL, N_PROCESS_VERIFY)
    # M4 autofix loop: verify → (READY → finalize) | (NEEDS_REWORK + budget → autofix → re-assemble → ...)
    g.add_conditional_edges(
        N_PROCESS_VERIFY,
        _route_after_verify,
        {N_AUTOFIX: N_AUTOFIX, N_FINALIZE: N_FINALIZE},
    )
    g.add_edge(N_AUTOFIX, N_ASSEMBLE)
    g.add_edge(N_FINALIZE, END)
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
