"""Deterministic per-slide archetype planner for the designer skill.

Maps a classified slide (Agent 02 output) to one of the designer archetypes
and extracts the content payload the slide_composer needs. No LLM here — the
art direction is already locked; this is a pure routing function.
"""
from __future__ import annotations

from typing import Any

# Designer archetypes (see spec §5).
ARCHETYPES = (
    "cover", "data-chart", "kpi", "diagram-flow", "comparison",
    "timeline", "team", "section-divider", "title-body",
)


def archetype_for(cls: dict[str, Any], is_first: bool) -> str:
    """Pick an archetype for one classified slide."""
    slide_type = cls.get("slide_type")
    category = cls.get("category", "other")

    if slide_type == "kpi_native":
        return "kpi"
    if slide_type in ("chart_native", "chart_pptx_native"):
        return "data-chart"
    if slide_type == "flow_diagram_native":
        return "diagram-flow"
    if slide_type == "table_native":
        return "comparison"

    if is_first or category == "title":
        return "cover" if is_first else "section-divider"
    if category == "divider":
        return "section-divider"
    if category == "team":
        return "team"
    if category == "timeline":
        return "timeline"
    if category == "multicolumn":
        return "comparison"
    if category in ("kpi", "callout"):
        return "kpi"
    return "title-body"


def slide_content_for(cls: dict[str, Any], brief_slide: dict[str, Any] | None) -> dict[str, Any]:
    """Assemble the content payload handed to the composer for one slide.

    Pulls native data blocks (kpi/chart/table/flow) when present, plus the
    raw title/body text from the brief slide. Text is passed through verbatim
    (text-is-sacred) — the composer may re-layout but not paraphrase.
    """
    payload: dict[str, Any] = {
        "num": cls.get("num"),
        "category": cls.get("category"),
        "slide_type": cls.get("slide_type"),
        "subcategory_hint": cls.get("subcategory_hint", ""),
        "dark": cls.get("dark", False),
    }
    for key in ("kpi", "chart", "table", "flow", "image"):
        if cls.get(key):
            payload[key] = cls[key]
    if brief_slide:
        payload["title"] = brief_slide.get("raw_title") or ""
        payload["body"] = brief_slide.get("raw_body") or []
        payload["key_phrase"] = brief_slide.get("key_phrase", "")
    return payload
