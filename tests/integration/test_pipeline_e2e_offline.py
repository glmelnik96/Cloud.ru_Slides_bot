"""Offline end-to-end pipeline test.

Chains all 8 LLM agent nodes (with captured cassettes) plus all 6 script-
wrapping deterministic nodes, in the exact order ``graph/graph.py`` wires
them. Effectively runs the whole v0.9 batch pipeline against a real .pptx
template without any live API calls.

This is the closest thing to a real ``run_pipeline`` invocation we can put
in CI:

    parse_node          (real .pptx, optional LibreOffice for grounding PNG)
    brief_node          (cassette)
    classify_node       (cassette)
    design_node         (cassette)
    distribute_node     (cassette)
    icons_node          (cassette)
    infographic_node    (cassette)
    copyedit_node       (cassette)
    assemble_plan_node  (deterministic)
    build_node          (build_v9 → real .pptx on disk)
    brand_guard_node    (brand_guardian → BrandReport)
    render_png_node     (LibreOffice; soft-fails when missing)
    visual_verify_node  (cassette + 1×1 PNG placeholder when no render)
    process_verify_node (deterministic aggregator)
    finalize_node       (terminal progress event)

The cassettes were captured against the ``big`` deck fixture, so the
``parsed_deck`` artefact is also primed from ``fixtures.make_parsed_deck``
to keep the LLM stubs internally consistent.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from graph.nodes.agents import (
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
    process_verify_node,
    render_png_node,
)
from llm.roles import Role
from schemas.session import SessionInput, SessionState
from schemas.slides import (
    Brief,
    BrandReport,
    DeckClassification,
    LayoutPlan,
    Plan,
    VerifierVerdict,
    VisualVerdict,
)
from tests.integration.llm_cassettes import CassetteCallRole, load_cassette
from tests.probes import fixtures
from worker import skill_bridge


# ─── shared plumbing ─────────────────────────────────────────────────────────

def _has_soffice() -> bool:
    return any(shutil.which(name) for name in ("soffice", "libreoffice"))


def _make_state(session_id: str, input_path: str | None,
                artefacts: dict[str, Any] | None = None) -> SessionState:
    inp = SessionInput(
        session_id=session_id,
        user_id=1,
        chat_id=1,
        progress_message_id=0,
        mode="verstai",
        input_s3_key=input_path,
    )
    s = SessionState.from_input(inp)
    if artefacts:
        s = s.model_copy(update={"artefacts": dict(artefacts)})
    return s


@pytest.fixture(autouse=True)
def _stub_progress(monkeypatch):
    """Silence Redis publishes for the duration of the test."""
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)


def _all_cassettes() -> dict[Role, str]:
    """Map every LLM role used by the graph to its captured ``big`` cassette."""
    return {
        Role.BRIEF_PARSER: load_cassette("01_brief", "big"),
        Role.CLASSIFIER: load_cassette("02_classifier", "big"),
        Role.DESIGNER: load_cassette("04_designer", "big"),
        Role.DISTRIBUTOR: load_cassette("03_distributor", "big"),
        Role.ICON_PICKER: load_cassette("05_icons", "big"),
        Role.INFOGRAPHIC_MAKER: load_cassette("06_infographic", "big"),
        Role.COPY_EDITOR: load_cassette("07_copyedit", "big"),
        Role.VISUAL_VERIFIER: load_cassette("10_visual", "big"),
    }


def _placeholder_png(tmp_path: Path) -> Path:
    """Write a 1×1 PNG so render-less paths still satisfy visual_verify."""
    p = tmp_path / "placeholder.png"
    p.write_bytes(bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
    ))
    return p


# ─── full chain ──────────────────────────────────────────────────────────────

def test_full_pipeline_offline(monkeypatch, tmp_path: Path) -> None:
    """Drive every pipeline node end-to-end with cassettes + real scripts.

    Passes as long as each artefact schema-validates. Does NOT assert
    final verdict=READY — the cassette+fixture combo is heterogeneous and
    Visual Verifier was captured saying NEEDS_REWORK against a synthetic
    deck, so the realistic outcome here is NEEDS_REWORK with a real .pptx
    on disk.
    """
    cassette = CassetteCallRole(_all_cassettes())
    monkeypatch.setattr("llm.output_parsers.call_role", cassette)

    # Prime parsed_deck from the fixture so all downstream cassettes stay
    # internally consistent (the cassettes were captured against this exact
    # fixture). The real .pptx parse runs in test_pipeline_smoke.py.
    arts: dict[str, Any] = {
        "parsed_deck": fixtures.make_parsed_deck("big"),
    }
    state = _make_state("e2e-big", input_path=str(skill_bridge.TEMPLATE_PATH), artefacts=arts)

    # ── LLM half ────────────────────────────────────────────────────────────
    for node, key, schema in [
        (brief_node, "brief", Brief),
        (classify_node, "classification", DeckClassification),
        (design_node, "layouts", LayoutPlan),
        (distribute_node, "content", None),       # DeckContent wrapper, validated elsewhere
        (icons_node, "icons", None),
        (infographic_node, "infographics", None),
        (copyedit_node, "copy_edited", None),
    ]:
        patch = node(state)
        state = state.model_copy(update={"artefacts": patch["artefacts"]})
        assert key in state.artefacts, f"{node.__name__}: missing {key}"
        if schema is not None:
            schema.model_validate(state.artefacts[key])

    # ── Deterministic half ──────────────────────────────────────────────────
    state = state.model_copy(update={"artefacts": assemble_plan_node(state)["artefacts"]})
    plan = Plan.model_validate(state.artefacts["plan"])
    assert plan.slides, "assemble: empty plan"

    state = state.model_copy(update={"artefacts": build_node(state)["artefacts"]})
    built = Path(state.artefacts["built_pptx_path"])
    assert built.is_file() and built.stat().st_size > 1000

    state = state.model_copy(update={"artefacts": brand_guard_node(state)["artefacts"]})
    report = BrandReport.model_validate(state.artefacts["brand_report"])
    assert report.verdict in ("OK", "WARN", "FAIL")

    state = state.model_copy(update={"artefacts": render_png_node(state)["artefacts"]})
    if _has_soffice():
        rendered = state.artefacts.get("rendered_pngs") or []
        assert rendered, "render_png: empty list with soffice present"
        for p in rendered:
            assert Path(p).is_file()
    else:
        # No soffice — drop a placeholder so visual_verify has *something*.
        state = state.model_copy(update={"artefacts": {
            **state.artefacts,
            "rendered_pngs": [str(_placeholder_png(tmp_path))],
        }})

    state = state.model_copy(update={"artefacts": visual_verify_node(state)["artefacts"]})
    vv = VisualVerdict.model_validate(state.artefacts["visual_verdict"])
    assert vv.llm_verdict in ("READY", "NEEDS_REWORK")

    state = state.model_copy(update={"artefacts": process_verify_node(state)["artefacts"]})
    verdict = VerifierVerdict.model_validate(state.artefacts["verifier_verdict"])
    assert verdict.verdict in ("READY", "NEEDS_REWORK")
    # Plan has N slides → checklist must carry an entry per slide (1-indexed).
    for i in range(1, len(plan.slides) + 1):
        assert str(i) in verdict.checklist_results

    # ── Terminal node ────────────────────────────────────────────────────────
    final_patch = finalize_node(state)
    assert final_patch["stage"] == "done"
    assert final_patch["progress_pct"] == 100

    # Sanity: at least the 7 LLM agents were called once each. Visual Verifier
    # is only called when rendered_pngs is non-empty — which is always true in
    # this test (real PNGs from soffice, or placeholder fallback).
    called_roles = [c.role for c in cassette.calls]
    expected = {
        Role.BRIEF_PARSER, Role.CLASSIFIER, Role.DESIGNER,
        Role.DISTRIBUTOR, Role.ICON_PICKER, Role.INFOGRAPHIC_MAKER,
        Role.COPY_EDITOR, Role.VISUAL_VERIFIER,
    }
    assert expected <= set(called_roles), \
        f"missing role calls: {expected - set(called_roles)}"
