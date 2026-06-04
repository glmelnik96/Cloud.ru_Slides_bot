"""End-to-end smoke for the M3 script-wrapping pipeline nodes.

Bypasses LLM calls by feeding synthetic upstream artefacts (reused from
the WS-E probe fixtures) and exercises the deterministic, script-bound
half of the graph:

    parse_node  → ParsedDeck off the vendored Cloud.ru template
    assemble_plan_node  → Plan from synthetic classification/layouts/content
    build_node  → real .pptx on disk via build_v9
    brand_guard_node  → BrandReport on the built deck
    render_png_node  → PNG list (soft-fails if LibreOffice missing)
    process_verify_node  → VerifierVerdict aggregating the above

These tests do not require .env or network. They DO need the vendored
template at ``skill_assets/Cloud.ru_Template_2026.pptx``.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from graph.nodes.pipeline import (
    assemble_plan_node,
    brand_guard_node,
    build_node,
    parse_node,
    process_verify_node,
    render_png_node,
)
from schemas.session import SessionInput, SessionState
from schemas.slides import (
    BrandReport,
    ParsedDeck,
    Plan,
    VerifierVerdict,
)
from tests.probes import fixtures
from worker import skill_bridge


# ─── helpers ─────────────────────────────────────────────────────────────────

def _make_state(session_id: str, artefacts: dict[str, Any] | None = None,
                input_path: str | None = None) -> SessionState:
    """Build a minimal SessionState — the smoke tests don't touch Redis or
    the bot side, so we only need fields the pipeline nodes actually read.
    """
    inp = SessionInput(
        session_id=session_id,
        user_id=1,
        chat_id=1,
        progress_message_id=0,
        mode="verstai",
        input_s3_key=input_path,  # M3 interim: treated as local path
    )
    s = SessionState.from_input(inp)
    if artefacts:
        s = s.model_copy(update={"artefacts": dict(artefacts)})
    return s


def _has_soffice() -> bool:
    """LibreOffice availability gate — render_png_node and parse_node's
    first-slide grounding need it, but the smoke test must work both with
    and without (CI vs developer laptop)."""
    for name in ("soffice", "libreoffice"):
        if shutil.which(name):
            return True
    return False


# ─── parse_node ──────────────────────────────────────────────────────────────

def test_parse_node_template_roundtrip(tmp_path):
    """Parsing the vendored template yields a valid ParsedDeck with slide
    geometry and slide count matching the file on disk."""
    state = _make_state("sm-parse", input_path=str(skill_bridge.TEMPLATE_PATH))
    patch = parse_node(state)

    parsed = patch["artefacts"]["parsed_deck"]
    deck = ParsedDeck.model_validate(parsed)
    assert deck.slide_count > 0, "template should have slides"
    assert deck.slide_size.get("width_emu") or deck.slide_size.get("width"), \
        "slide_size should carry width"
    # If soffice is around, parse_node also primes vision grounding.
    if _has_soffice():
        pngs = patch["artefacts"].get("original_pngs") or []
        assert pngs, "first-slide PNG should be rendered when LibreOffice is available"
        assert Path(pngs[0]).is_file()


def test_parse_node_rejects_unknown_extension(tmp_path):
    fake = tmp_path / "draft.md"
    fake.write_text("# hi", encoding="utf-8")
    state = _make_state("sm-bad-ext", input_path=str(fake))
    with pytest.raises(NotImplementedError):
        parse_node(state)


def test_parse_node_no_input_raises():
    state = _make_state("sm-no-input")
    with pytest.raises(RuntimeError, match="no input file"):
        parse_node(state)


# ─── assemble_plan_node ──────────────────────────────────────────────────────

def _synthetic_upstream(size: fixtures.Size = "small") -> dict[str, Any]:
    """Build the artefacts a successful LLM half of the graph would have
    deposited by the time assemble_plan_node runs.
    """
    return {
        "brief": fixtures.make_brief(size),
        "classification": fixtures.make_classification(size),
        "layouts": fixtures.make_layouts(size),
        "content": fixtures.make_content(size),
        "copy_edited": fixtures.make_content(size),  # post-edit identity is fine
        "icons": {"slides": []},
        "infographics": {"slides": []},
    }


def test_assemble_plan_small_donor_route():
    """Small deck (3 slides) is all donor route — Plan must have 3
    PlanSlide entries with clone_from_slide set and a non-empty slot
    map. Slot key form depends on whether the chosen donor exists in
    donor-slot-map.yaml; we don't assert canonical names here because
    real Layout Designer runs can pick donors outside the map (a
    legitimate degraded mode build_v9 tolerates)."""
    arts = _synthetic_upstream("small")
    state = _make_state("sm-assemble", artefacts=arts)

    patch = assemble_plan_node(state)
    plan = Plan.model_validate(patch["artefacts"]["plan"])
    assert len(plan.slides) == 3
    for ps in plan.slides:
        assert ps.clone_from_slide is not None
        assert ps.slide_type is None
        assert ps.slots, "donor-route slide should carry slot contents"


def test_assemble_plan_big_native_blocks():
    """Big deck contains kpi_native / table_native / flow_diagram_native
    classifications — assemble_plan must route them as native PlanSlides
    with their matching data blocks present."""
    arts = _synthetic_upstream("big")
    state = _make_state("sm-assemble-big", artefacts=arts)

    patch = assemble_plan_node(state)
    plan = Plan.model_validate(patch["artefacts"]["plan"])

    natives_by_type: dict[str, int] = {}
    donors = 0
    for ps in plan.slides:
        if ps.slide_type:
            natives_by_type[ps.slide_type] = natives_by_type.get(ps.slide_type, 0) + 1
            # The required data block must be present for each native type.
            if ps.slide_type == "kpi_native":
                assert ps.kpi is not None
            elif ps.slide_type in ("chart_native", "chart_pptx_native"):
                assert ps.chart is not None
            elif ps.slide_type == "table_native":
                assert ps.table is not None
            elif ps.slide_type == "flow_diagram_native":
                assert ps.flow is not None
        else:
            donors += 1
    assert natives_by_type.get("kpi_native", 0) >= 1
    assert natives_by_type.get("table_native", 0) >= 1
    assert natives_by_type.get("flow_diagram_native", 0) >= 1
    assert donors >= 1


# ─── build_node + brand_guard_node ───────────────────────────────────────────

def test_build_then_brand_small():
    """Assemble → build → brand_guard end-to-end on the small fixture.
    Asserts a real .pptx lands on disk and BrandReport schema validates.
    """
    arts = _synthetic_upstream("small")
    state = _make_state("sm-build", artefacts=arts)
    patch_assemble = assemble_plan_node(state)
    state = state.model_copy(update={"artefacts": patch_assemble["artefacts"]})

    patch_build = build_node(state)
    pptx_path = Path(patch_build["artefacts"]["built_pptx_path"])
    assert pptx_path.is_file(), f"build_v9 did not produce {pptx_path}"
    assert pptx_path.stat().st_size > 1000, "built pptx suspiciously small"
    # result_s3_key interim: same path surfaced through state field.
    assert patch_build["result_s3_key"] == str(pptx_path)

    # Brand guard on the freshly built pptx.
    state = state.model_copy(update={"artefacts": patch_build["artefacts"]})
    patch_brand = brand_guard_node(state)
    report = BrandReport.model_validate(patch_brand["artefacts"]["brand_report"])
    assert report.verdict in ("OK", "WARN", "FAIL")
    assert 0 <= report.score_avg <= 100
    assert len(report.slides) >= 1
    assert patch_brand["brand_score"] == report.score_avg


# ─── render_png_node + process_verify_node ───────────────────────────────────

def test_full_chain_to_verifier_small():
    """Drive the entire script-wrapping chain on the small fixture and
    assert the final VerifierVerdict schema. PNG render is best-effort
    (soft-fails if soffice missing — verifier still synthesises)."""
    arts = _synthetic_upstream("small")
    state = _make_state("sm-full", artefacts=arts)

    state = state.model_copy(update={"artefacts": assemble_plan_node(state)["artefacts"]})
    state = state.model_copy(update={"artefacts": build_node(state)["artefacts"]})
    state = state.model_copy(update={"artefacts": brand_guard_node(state)["artefacts"]})
    render_patch = render_png_node(state)
    state = state.model_copy(update={"artefacts": render_patch["artefacts"]})

    rendered = render_patch["artefacts"].get("rendered_pngs", [])
    if _has_soffice():
        assert rendered, "render_png_node should produce PNGs when LibreOffice is present"
        for p in rendered:
            assert Path(p).is_file()
    # process_verify must produce a valid verdict regardless of soffice state
    # (Visual Verifier output absent — verifier handles that gracefully).
    patch_verify = process_verify_node(state)
    verdict = VerifierVerdict.model_validate(patch_verify["artefacts"]["verifier_verdict"])
    assert verdict.verdict in ("READY", "NEEDS_REWORK")
    # Each plan slide should have a checklist entry keyed by slide index.
    plan = Plan.model_validate(state.artefacts["plan"])
    for i in range(1, len(plan.slides) + 1):
        assert str(i) in verdict.checklist_results
