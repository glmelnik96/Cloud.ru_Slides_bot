"""LLM-agent nodes for the v0.9 batch pipeline.

Each function is a LangGraph node:
    (state: SessionState) -> dict (state patch)

All nodes read upstream artefacts from ``state.artefacts`` and write their
own output back into the same dict. The reducer is shallow-merge by
LangGraph; we copy + update + return the whole ``artefacts`` dict to avoid
clobbering sibling keys.

Vision-capable nodes (Brief Reader, Visual Verifier) accept rendered PNGs.
Brief Reader runs vision-grounded if ``parsed_deck`` includes an
``original_pngs`` key with a list of base64 data URLs or paths; otherwise
falls back to text-only (still on Kimi — accuracy boost from grounding is
nice-to-have, not required).
"""
from __future__ import annotations

from typing import Any

import structlog

from llm.output_parsers import call_and_parse
from llm.prompts import (
    agent_01_brief_reader,
    agent_02_slide_classifier,
    agent_03_content_distributor,
    agent_04_layout_designer,
    agent_05_icon_picker,
    agent_06_infographic_maker,
    agent_07_copy_editor,
    agent_10_visual_verifier,
)
from llm.roles import Role
from schemas.session import SessionState, Stage
from schemas.slides import (
    Brief,
    ContentAssignment,
    DeckClassification,
    IconAssignments,
    InfographicSpec,
    LayoutPlan,
    VisualVerdict,
)
from worker import progress

logger = structlog.get_logger(__name__)


# ─── shared helpers ──────────────────────────────────────────────────────────

def _artefacts(state: SessionState) -> dict[str, Any]:
    """Shallow copy of state.artefacts so we can mutate-and-return safely."""
    return dict(state.artefacts)


def _emit(state: SessionState, stage: Stage, pct: int, detail: str) -> None:
    progress.stage(state.session_id, stage, pct=pct, detail=detail)


# ─── 01 Brief Reader (Kimi vision) ───────────────────────────────────────────

def brief_node(state: SessionState) -> dict[str, Any]:
    _emit(state, Stage.PARSING, pct=15, detail="чтение брифа")
    arts = _artefacts(state)
    parsed_deck = arts.get("parsed_deck")
    if parsed_deck is None:
        raise RuntimeError("brief_node: artefacts['parsed_deck'] missing — parse_node didn't run")

    # Optional vision grounding: orchestrator stores rendered PNGs under
    # 'original_pngs' (list of bytes / data-URLs). Kimi vision tolerates empty.
    images = arts.get("original_pngs", [])

    messages, imgs = agent_01_brief_reader.build_messages(parsed_deck, images=images)
    # Brief Reader uses Kimi vision (requires_vision=True). If no PNGs were
    # rendered (text-only draft like .md), inject a 1×1 placeholder PNG so
    # the vision gate in call_role doesn't fire. FIXME: render first slide
    # of input pptx to PNG in parse_node — better grounding than placeholder.
    if not imgs:
        # 1×1 transparent PNG (base64). Keeps Kimi happy without misleading.
        imgs = [
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkAAIAAAoAAv/lxKUAAAAASUVORK5CYII="
        ]

    brief, _ = call_and_parse(
        role=Role.BRIEF_PARSER,
        messages=messages,
        model_cls=Brief,
        images=imgs,
    )
    arts["brief"] = brief.model_dump()
    logger.info("node.brief.done", session_id=state.session_id,
                slide_count=brief.slide_count, topic=brief.topic[:60])
    return {"artefacts": arts, "stage": Stage.PARSING.value, "progress_pct": 20}


# ─── 02 Slide Classifier (DeepSeek) ──────────────────────────────────────────

def classify_node(state: SessionState) -> dict[str, Any]:
    _emit(state, Stage.CLASSIFYING, pct=25, detail="классификация слайдов")
    arts = _artefacts(state)
    brief = arts["brief"]

    classification, _ = call_and_parse(
        role=Role.CLASSIFIER,
        messages=agent_02_slide_classifier.build_messages(brief),
        model_cls=DeckClassification,
    )
    arts["classification"] = classification.model_dump()
    logger.info("node.classify.done", session_id=state.session_id,
                slides=len(classification.slides))
    return {"artefacts": arts, "stage": Stage.CLASSIFYING.value, "progress_pct": 30}


# ─── 04 Layout Designer (DeepSeek) ───────────────────────────────────────────

def design_node(state: SessionState) -> dict[str, Any]:
    """Runs Agent 04 BEFORE Distributor — Distributor needs slot capacities
    from the chosen donors. Order: classify → design → distribute.
    """
    _emit(state, Stage.DESIGNING, pct=35, detail="подбор layout")
    arts = _artefacts(state)
    classification = arts["classification"]

    layouts, _ = call_and_parse(
        role=Role.DESIGNER,
        messages=agent_04_layout_designer.build_messages(classification),
        model_cls=LayoutPlan,
    )
    arts["layouts"] = layouts.model_dump(by_alias=True)
    logger.info("node.design.done", session_id=state.session_id,
                slides=len(layouts.slides))
    return {"artefacts": arts, "stage": Stage.DESIGNING.value, "progress_pct": 40}


# ─── 03 Content Distributor (GLM OFF) ────────────────────────────────────────

def distribute_node(state: SessionState) -> dict[str, Any]:
    _emit(state, Stage.DESIGNING, pct=45, detail="распределение контента")
    arts = _artefacts(state)
    brief = arts["brief"]
    classification = arts["classification"]
    layouts = arts["layouts"]
    # FIXME(next-chunk): build per-layout slot specs from
    # skill_assets/brand/donor-slot-map.yaml. For now pass an empty mapping —
    # GLM will fall back to category-based heuristics. Distributor still
    # produces valid output, but capacity-aware overflow handling is degraded.
    slot_specs: dict[str, Any] = {}

    content, _ = call_and_parse(
        role=Role.DISTRIBUTOR,
        messages=agent_03_content_distributor.build_messages(
            brief, classification, layouts, slot_specs,
        ),
        model_cls=_DeckContentAssignment,
    )
    arts["content"] = content.model_dump()
    logger.info("node.distribute.done", session_id=state.session_id,
                slides=len(content.slides))
    return {"artefacts": arts, "stage": Stage.DESIGNING.value, "progress_pct": 50}


# Distributor outputs a deck-level wrapper {"slides": [ContentAssignment, ...]}.
# schemas/slides.py defines ContentAssignment per-slide; declare the wrapper
# locally so we don't pollute the public schema module.
from pydantic import BaseModel, ConfigDict, Field  # noqa: E402 — co-located helper


class _DeckContentAssignment(BaseModel):
    model_config = ConfigDict(extra="allow")
    slides: list[ContentAssignment] = Field(default_factory=list)


class _DeckIcons(BaseModel):
    model_config = ConfigDict(extra="allow")
    slides: list[IconAssignments] = Field(default_factory=list)


class _DeckInfographics(BaseModel):
    model_config = ConfigDict(extra="allow")
    slides: list[InfographicSpec] = Field(default_factory=list)


# ─── 05 Icon Picker (GLM OFF) ────────────────────────────────────────────────

def icons_node(state: SessionState) -> dict[str, Any]:
    _emit(state, Stage.DESIGNING, pct=55, detail="подбор иконок")
    arts = _artefacts(state)
    # FIXME(next-chunk): scan skill_assets/brand/icons/ for available .svg files.
    # For now use a minimal hard-coded list reflecting the only icon vendored
    # in M2 (brand_arrow.svg). Icon Picker will likely return fallback=TODO
    # for most blocks until the library is populated.
    icon_library = ["icons/brand_arrow.svg"]

    icons, _ = call_and_parse(
        role=Role.ICON_PICKER,
        messages=agent_05_icon_picker.build_messages(
            arts["classification"], arts["content"], icon_library,
        ),
        model_cls=_DeckIcons,
    )
    arts["icons"] = icons.model_dump()
    logger.info("node.icons.done", session_id=state.session_id,
                slides=len(icons.slides))
    return {"artefacts": arts, "stage": Stage.DESIGNING.value, "progress_pct": 60}


# ─── 06 Infographic Maker (GLM OFF) ──────────────────────────────────────────

def infographic_node(state: SessionState) -> dict[str, Any]:
    _emit(state, Stage.DESIGNING, pct=65, detail="инфографика")
    arts = _artefacts(state)
    infographics, _ = call_and_parse(
        role=Role.INFOGRAPHIC_MAKER,
        messages=agent_06_infographic_maker.build_messages(
            arts["classification"], arts["content"],
        ),
        model_cls=_DeckInfographics,
    )
    arts["infographics"] = infographics.model_dump()
    logger.info("node.infographic.done", session_id=state.session_id,
                slides=len(infographics.slides))
    return {"artefacts": arts, "stage": Stage.DESIGNING.value, "progress_pct": 70}


# ─── 07 Copy Editor (GLM OFF) ────────────────────────────────────────────────

def copyedit_node(state: SessionState) -> dict[str, Any]:
    _emit(state, Stage.DESIGNING, pct=72, detail="редактура текста")
    arts = _artefacts(state)
    edited, _ = call_and_parse(
        role=Role.COPY_EDITOR,
        messages=agent_07_copy_editor.build_messages(arts["content"]),
        model_cls=_DeckContentAssignment,
    )
    arts["copy_edited"] = edited.model_dump()
    total_edits = sum(s.edits_count for s in edited.slides)
    logger.info("node.copyedit.done", session_id=state.session_id,
                slides=len(edited.slides), edits=total_edits)
    return {"artefacts": arts, "stage": Stage.DESIGNING.value, "progress_pct": 75}


# ─── 10 Visual Verifier (Kimi vision) ────────────────────────────────────────

def visual_verify_node(state: SessionState) -> dict[str, Any]:
    _emit(state, Stage.VALIDATING, pct=90, detail="визуальная проверка")
    arts = _artefacts(state)
    plan = arts.get("plan")
    if plan is None:
        raise RuntimeError("visual_verify_node: artefacts['plan'] missing — assemble_plan_node didn't run")
    rendered_pngs = arts.get("rendered_pngs", [])
    if not rendered_pngs:
        # FIXME(next-chunk): render_png_node must populate this. For now
        # skip with a NEEDS_REWORK verdict so we don't silently pass.
        logger.warning("node.visual.skip_no_pngs", session_id=state.session_id)
        arts["visual_verdict"] = {
            "llm_verdict": "NEEDS_REWORK",
            "score_avg": 0,
            "slides": [],
            "next_actions": ["render_png_node not yet implemented — cannot verify"],
        }
        return {"artefacts": arts, "stage": Stage.VALIDATING.value, "progress_pct": 92}

    messages, imgs = agent_10_visual_verifier.build_messages(plan, rendered_pngs)
    verdict, _ = call_and_parse(
        role=Role.VISUAL_VERIFIER,
        messages=messages,
        model_cls=VisualVerdict,
        images=imgs,
    )
    arts["visual_verdict"] = verdict.model_dump()
    logger.info("node.visual.done", session_id=state.session_id,
                verdict=verdict.llm_verdict, score=verdict.score_avg)
    return {"artefacts": arts, "stage": Stage.VALIDATING.value, "progress_pct": 92}
