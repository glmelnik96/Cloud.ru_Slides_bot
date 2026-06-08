"""Designer-skill LangGraph nodes (the /design from-scratch path).

Flow: art_director (locked stub) → compose (per-slide DSL + critic gate) →
native_assemble (DSL → native .pptx). Upstream parse/brief/classify are
reused from the donor pipeline (read-only).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog

from llm.output_parsers import call_and_parse
from llm.prompts.designer import (
    art_director,
    brand_critic_v2,
    slide_composer,
)
from llm.roles import Role
from renderers.designer.composition_dsl import Composition
from renderers.designer.native_assembler import build_deck
from schemas.design import CriticVerdict, DesignStub
from schemas.session import SessionState, Stage
from worker import progress
from graph.designer.planner import archetype_for, slide_content_for

logger = structlog.get_logger(__name__)

COMPOSE_RETRY_BUDGET = 2  # spec §10: max 2 re-composes before fallback


def _artefacts(state: SessionState) -> dict[str, Any]:
    return dict(state.artefacts)


def _emit(state: SessionState, stage: Stage, pct: int, detail: str) -> None:
    progress.stage(state.session_id, stage, pct=pct, detail=detail)


# ─── art_director (combined locked stub) ─────────────────────────────────────

def art_director_node(state: SessionState) -> dict[str, Any]:
    _emit(state, Stage.DESIGNING, pct=30, detail="арт-директор")
    arts = _artefacts(state)
    brief = arts.get("brief")
    if brief is None:
        raise RuntimeError("art_director_node: artefacts['brief'] missing")

    stub, _ = call_and_parse(
        role=Role.ART_DIRECTOR,
        messages=art_director.build_messages(brief),
        model_cls=DesignStub,
    )
    arts["design_stub"] = stub.model_dump()
    logger.info("node.art_director.done", session_id=state.session_id,
                tonality=stub.tonality, dark_ratio=stub.dark_ratio)
    return {"artefacts": arts, "stage": Stage.DESIGNING.value, "progress_pct": 35}


# ─── compose (per-slide DSL + critic gate) ───────────────────────────────────

def _fallback_title_body(content: dict[str, Any], num: int, dark: bool) -> dict[str, Any]:
    """Safest archetype — always renderable (spec §5 fallback)."""
    blocks: list[dict[str, Any]] = [{
        "role": "title", "text": content.get("title") or "",
        "grid": {"c": 1, "r": 1, "cs": 10, "rs": 2},
    }]
    body = content.get("body") or []
    if body:
        blocks.append({
            "role": "body", "bullets": [str(b) for b in body][:6],
            "grid": {"c": 1, "r": 3, "cs": 11, "rs": 7},
        })
    return {
        "slide_num": num,
        "tone": "dark" if dark else "light",
        "background": {"kind": "graphite" if dark else "white"},
        "blocks": blocks,
    }


def _compose_one(stub: dict[str, Any], content: dict[str, Any], archetype: str,
                 num: int, use_critic: bool = True) -> dict[str, Any]:
    messages = slide_composer.build_messages(stub, content, archetype)
    reasons: list[str] = []
    for attempt in range(COMPOSE_RETRY_BUDGET + 1):
        msgs = messages
        if reasons:
            msgs = messages + [{
                "role": "user",
                "content": "Композиция отклонена бренд-критиком. Исправь: "
                           + "; ".join(reasons),
            }]
        try:
            comp, _ = call_and_parse(
                role=Role.SLIDE_COMPOSER, messages=msgs, model_cls=Composition,
            )
        except Exception as exc:  # parse/validation failed even after retry
            logger.warning("node.compose.parse_fail", num=num, attempt=attempt, err=str(exc))
            break
        comp_dump = comp.model_dump()
        comp_dump["slide_num"] = num
        if not use_critic:
            return comp_dump
        verdict, _ = call_and_parse(
            role=Role.BRAND_CRITIC_V2,
            messages=brand_critic_v2.build_messages(stub, comp_dump),
            model_cls=CriticVerdict,
        )
        if verdict.verdict == "READY":
            return comp_dump
        reasons = verdict.reasons or ["не соответствует locked stub"]
        logger.info("node.compose.not_ready", num=num, attempt=attempt, reasons=reasons)
    return _fallback_title_body(content, num, bool(content.get("dark")))


def compose_node(state: SessionState) -> dict[str, Any]:
    _emit(state, Stage.DESIGNING, pct=55, detail="компоновка слайдов")
    arts = _artefacts(state)
    stub = arts["design_stub"]
    classification = arts.get("classification") or {}
    brief = arts.get("brief") or {}
    cls_slides = classification.get("slides") or []
    brief_by_num = {int(s.get("num", 0)): s for s in (brief.get("slides") or [])}

    use_critic = bool(arts.get("designer_use_critic", True))
    comps: list[dict[str, Any]] = []
    fallbacks = 0
    for i, cls in enumerate(cls_slides):
        num = int(cls.get("num") or (i + 1))
        archetype = archetype_for(cls, is_first=(i == 0))
        content = slide_content_for(cls, brief_by_num.get(num))
        has_text = bool((content.get("title") or "").strip()) or any(
            str(b).strip() for b in (content.get("body") or [])
        )
        has_native = any(content.get(k) for k in ("kpi", "chart", "table", "flow", "image"))
        if not has_text and not has_native:
            logger.info("node.compose.skip_phantom", session_id=state.session_id, num=num)
            continue  # phantom/empty slide — do not fabricate
        comp = _compose_one(stub, content, archetype, num, use_critic=use_critic)
        if not comp.get("blocks") or all(b.get("role") == "title" for b in comp["blocks"]):
            fallbacks += 1
        comps.append(comp)

    arts["compositions"] = comps
    logger.info("node.compose.done", session_id=state.session_id,
                slides=len(comps), fallbacks=fallbacks)
    return {"artefacts": arts, "stage": Stage.DESIGNING.value, "progress_pct": 75}


# ─── native_assemble (DSL → native .pptx) ────────────────────────────────────

def native_assemble_node(state: SessionState, out_dir: str = "tmp/design_out") -> dict[str, Any]:
    _emit(state, Stage.RENDERING, pct=85, detail="сборка .pptx")
    arts = _artefacts(state)
    comps = [Composition(**c) for c in (arts.get("compositions") or [])]
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    out_path = str(Path(out_dir) / f"{state.session_id}_design.pptx")
    build_deck(comps, out_path)
    arts["result_path"] = out_path
    logger.info("node.native_assemble.done", session_id=state.session_id,
                slides=len(comps), path=out_path)
    return {"artefacts": arts, "result_s3_key": out_path,
            "stage": Stage.FINALIZING.value, "progress_pct": 95}
