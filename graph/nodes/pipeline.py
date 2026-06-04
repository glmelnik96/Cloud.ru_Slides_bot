"""Python-script nodes — skeletons.

These nodes wrap scripts vendored under ``skill_assets/scripts/`` and do
not call LLMs. Their full wiring (S3 read/write, donor-slot-map loading,
LibreOffice render, chart engine) lands in the NEXT chunk; this file
nails down signatures + state-patch shape so the graph can compile and
the LLM nodes can be exercised end-to-end against deterministic inputs.

Each skeleton:
- Reads the upstream artefact it needs (raises if missing).
- Emits a progress event.
- Writes a stub artefact under its expected key with a clear FIXME marker.
- Logs an info line so traces are obvious during M3 development.

The skeleton output shape is intentionally minimal but TYPED — wherever
possible we materialise the corresponding Pydantic model from
``schemas/slides.py`` so downstream consumers see the correct keys.
"""
from __future__ import annotations

from typing import Any

import structlog

from schemas.session import SessionState, Stage
from schemas.slides import (
    BrandReport,
    Plan,
    PlanSlide,
    VerifierVerdict,
)
from worker import progress

logger = structlog.get_logger(__name__)


def _artefacts(state: SessionState) -> dict[str, Any]:
    return dict(state.artefacts)


def _emit(state: SessionState, stage: Stage, pct: int, detail: str) -> None:
    progress.stage(state.session_id, stage, pct=pct, detail=detail)


# ─── parse_node — skeleton ───────────────────────────────────────────────────

def parse_node(state: SessionState) -> dict[str, Any]:
    """Run ``skill_assets/scripts/parse_pptx.py`` (or parse_docx / parse_md)
    on the user's uploaded draft and store ``ParsedDeck`` under
    ``artefacts['parsed_deck']``.

    FIXME(next-chunk):
        1. Pull input bytes from S3 using ``state.input_s3_key`` via
           ``storage.s3_client`` (already exists in the repo per M2).
        2. Dispatch parser by file extension (.pptx | .docx | .md).
        3. Optionally render first slide → PNG for Kimi grounding,
           store as ``artefacts['original_pngs']``.
        4. Call ``parse_pptx.parse(path)`` and feed result to
           ``ParsedDeck.model_validate`` for type safety.
        5. Honour the 50 MB Telegram cap before processing.
    """
    _emit(state, Stage.PARSING, pct=5, detail="разбор файла")
    arts = _artefacts(state)
    arts["parsed_deck"] = {
        "_fixme": "parse_node skeleton — see graph/nodes/pipeline.py",
        "file": state.input_s3_key or "<unset>",
        "slide_count": 0,
        "slide_size": {"width": 12192000, "height": 6858000},
        "slides": [],
    }
    logger.info("node.parse.skeleton", session_id=state.session_id,
                input=state.input_s3_key)
    return {"artefacts": arts, "stage": Stage.PARSING.value, "progress_pct": 10}


# ─── assemble_plan_node ──────────────────────────────────────────────────────

def assemble_plan_node(state: SessionState) -> dict[str, Any]:
    """Fold LayoutPlan + CopyEditedAssignment + IconAssignments +
    InfographicSpec + per-slide native configs into a single ``Plan``
    consumable by ``build_v9.py``.

    FIXME(next-chunk):
        1. For each slide: decide donor route vs native render.
           - If classification.slide_type is set → emit PlanSlide(slide_type=...)
             with the matching data block (kpi/chart/table/flow/image)
             pulled from classification.
           - Else → PlanSlide(clone_from_slide=layout_idx,
                              slots={ph_name: content for each ph in copy_edited},
                              slot_styles_override=layouts[i].slot_styles_override).
        2. Translate ph_idx → ph_name using donor-slot-map.yaml for the
           chosen donor (build_v9 keys slots by canonical slot names).
        3. Attach infographic shapes to flow_diagram_native slides where
           Infographic Maker produced them.
        4. Validate the whole thing through Plan.model_validate — the
           PlanSlide ``_one_route`` validator enforces XOR donor/native.
    """
    _emit(state, Stage.DESIGNING, pct=78, detail="сборка плана")
    arts = _artefacts(state)
    layouts = arts.get("layouts", {}).get("slides", [])

    # Skeleton: emit one PlanSlide per layout choice, donor route, empty slots.
    plan_slides = []
    for choice in layouts:
        # LayoutChoice serialises donor under alias "layout_idx" (see
        # schemas.slides.LayoutChoice). Read it back the same way.
        donor = choice.get("layout_idx") or choice.get("donor") or 1
        if donor == 0:
            # Native render — orchestrator decides slide_type from classification.
            # Skeleton skips native wiring and falls back to donor=1 (title) to
            # keep the schema valid; FIXME above tracks the real implementation.
            donor = 1
        try:
            ps = PlanSlide(
                clone_from_slide=int(donor),
                slots={"_fixme": "assemble_plan skeleton — slots not yet wired"},
                slot_styles_override=choice.get("slot_styles_override") or {},
            )
            plan_slides.append(ps)
        except Exception as e:  # noqa: BLE001
            logger.warning("node.assemble.slide_skip",
                           session_id=state.session_id, num=choice.get("num"), error=str(e))

    plan = Plan(slides=plan_slides)
    arts["plan"] = plan.model_dump()
    logger.info("node.assemble.skeleton", session_id=state.session_id,
                slides=len(plan_slides))
    return {"artefacts": arts, "stage": Stage.DESIGNING.value, "progress_pct": 80}


# ─── build_node — skeleton ───────────────────────────────────────────────────

def build_node(state: SessionState) -> dict[str, Any]:
    """Call ``skill_assets/scripts/build_v9.build()`` with the assembled
    Plan, returning .pptx bytes (or an S3 key).

    FIXME(next-chunk):
        1. Resolve Cloud.ru template path via template_path.resolve_template().
        2. Write plan.json + donor-slot-map.yaml + template.pptx to a
           per-session temp dir.
        3. Call build_v9.build(plan_path, template_path, output_path, donor_map_path).
        4. Read output bytes; upload to S3 under ``result.pptx``.
        5. Store result_s3_key on the state for the finalize node.
        6. Use worker.skill_bridge if subprocess isolation is desired
           (current preference: in-process — build_v9 is sync and pure).
    """
    _emit(state, Stage.RENDERING, pct=82, detail="сборка pptx")
    arts = _artefacts(state)
    arts["built_pptx_key"] = "<fixme:build_node>"
    logger.info("node.build.skeleton", session_id=state.session_id)
    return {"artefacts": arts, "stage": Stage.RENDERING.value, "progress_pct": 84}


# ─── brand_guard_node — skeleton ─────────────────────────────────────────────

def brand_guard_node(state: SessionState) -> dict[str, Any]:
    """Run ``skill_assets/scripts/brand_guardian.py`` over built pptx and
    populate ``artefacts['brand_report']`` (BrandReport).

    FIXME(next-chunk):
        1. Download built pptx from S3 to temp.
        2. Call brand_guardian.main() programmatically — refactor its
           __main__ block into a callable that accepts a Path and returns
           the report dict.
        3. Validate dict via BrandReport.model_validate.
        4. Set state.brand_score from report.score_avg for the bot UI.
    """
    _emit(state, Stage.VALIDATING, pct=85, detail="бренд-проверка")
    arts = _artefacts(state)
    skeleton = BrandReport(verdict="WARN", score_avg=0, slides=[])
    arts["brand_report"] = skeleton.model_dump()
    arts["brand_report"]["_fixme"] = "brand_guard skeleton"
    logger.info("node.brand.skeleton", session_id=state.session_id)
    return {
        "artefacts": arts,
        "stage": Stage.VALIDATING.value,
        "progress_pct": 87,
        "brand_score": 0,
    }


# ─── render_png_node — skeleton ──────────────────────────────────────────────

def render_png_node(state: SessionState) -> dict[str, Any]:
    """Render the built pptx to PNG slides for Visual Verifier (Agent 10).

    FIXME(next-chunk):
        1. Call ``render_slides.render(pptx_path, out_dir, dpi=96)``
           (already wraps LibreOffice headless + pdftoppm).
        2. Read each PNG into bytes (or store data-URLs to keep state JSON-able).
        3. Cap to first 20 slides to bound Kimi token budget (~10s per call
           is the per-deck verifier cost).
        4. Populate ``artefacts['rendered_pngs']`` as ordered list.
    """
    _emit(state, Stage.RENDERING, pct=88, detail="рендер PNG")
    arts = _artefacts(state)
    arts["rendered_pngs"] = []
    arts["_fixme_render"] = "render_png_node skeleton — Visual Verifier will short-circuit"
    logger.info("node.render_png.skeleton", session_id=state.session_id)
    return {"artefacts": arts, "stage": Stage.RENDERING.value, "progress_pct": 89}


# ─── process_verify_node — skeleton ──────────────────────────────────────────

def process_verify_node(state: SessionState) -> dict[str, Any]:
    """Agent 09 — synthesise validate_plan + brand_guardian + visual_validator
    + LLM Visual Verifier into the single READY / NEEDS_REWORK gate.

    FIXME(next-chunk):
        1. Run validate_plan.validate_slide for each PlanSlide.
        2. Aggregate verdict precedence: any FAIL → NEEDS_REWORK.
        3. Decide whether to loop into an autofix branch (M4) or stop here.
        4. Set state.notes with user-visible blockers and warnings.
    """
    _emit(state, Stage.VALIDATING, pct=94, detail="свод проверок")
    arts = _artefacts(state)
    brand = arts.get("brand_report", {})
    visual = arts.get("visual_verdict", {})

    # Best-effort skeleton vote: if both upstream are present, take worst.
    brand_v = brand.get("verdict", "WARN")
    visual_v = visual.get("llm_verdict", "NEEDS_REWORK")
    deck_verdict = "READY" if (brand_v == "OK" and visual_v == "READY") else "NEEDS_REWORK"

    skeleton = VerifierVerdict(
        verdict=deck_verdict,
        score_avg=int(visual.get("score_avg", 0) or 0),
        blockers=[] if deck_verdict == "READY" else ["skeleton: full verifier wiring pending"],
    )
    arts["verifier_verdict"] = skeleton.model_dump()
    logger.info("node.process_verify.skeleton",
                session_id=state.session_id, verdict=deck_verdict)
    return {
        "artefacts": arts,
        "stage": Stage.VALIDATING.value,
        "progress_pct": 96,
    }


# ─── finalize_node — terminal ────────────────────────────────────────────────

def finalize_node(state: SessionState) -> dict[str, Any]:
    """Publish the terminal progress event and surface user-visible notes.

    Real result delivery (S3 → Telegram document send) happens in the
    bot's progress handler when it sees a terminal stage; this node only
    finalises state for the worker.
    """
    arts = _artefacts(state)
    verdict = arts.get("verifier_verdict", {}).get("verdict", "NEEDS_REWORK")
    notes = list(state.notes)

    if verdict != "READY":
        notes.append(
            "[M3 draft] Pipeline доехал до конца, но финальные ноды "
            "(parse/build/brand/render/verify) пока скелеты — результат не годен к выдаче."
        )
    else:
        notes.append("Готово")

    progress.done(state.session_id, detail="готово" if verdict == "READY" else "draft")
    logger.info("node.finalize.done", session_id=state.session_id, verdict=verdict)
    return {
        "stage": Stage.DONE.value,
        "progress_pct": 100,
        "notes": notes,
        "artefacts": arts,
    }
