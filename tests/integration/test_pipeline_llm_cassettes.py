"""Cassette-driven integration tests for the LLM half of the pipeline.

Pairs with ``test_pipeline_smoke.py`` (which covers the deterministic,
script-wrapping half). Together they let us validate the whole v0.9 batch
flow end-to-end without a live Cloud.ru API key.

All 8 LLM agents are covered (01, 02, 03, 04, 05, 06, 07, 10). Cassettes
come from ``tests/probes/_artifacts/{agent_label}_{size}.txt``, captured
by the WS-E probe runner. Cassettes are real model responses — they are
the closest thing to "production traffic" we can put in unit tests.

The ``visual_verify_node`` test feeds it through the parse → assemble half
of the graph, since it requires a Plan + rendered PNG paths in artefacts.
"""
from __future__ import annotations

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
from llm.roles import Role
from schemas.session import SessionInput, SessionState
from schemas.slides import (
    Brief,
    DeckClassification,
    LayoutPlan,
    VisualVerdict,
)
from tests.integration.llm_cassettes import CassetteCallRole, load_cassette
from tests.probes import fixtures
from tests.probes._wrappers import DeckContent, DeckIcons, DeckInfographics


# ─── helpers ─────────────────────────────────────────────────────────────────

def _make_state(session_id: str, artefacts: dict[str, Any]) -> SessionState:
    """Minimal SessionState — these tests don't touch Redis or the bot."""
    inp = SessionInput(
        session_id=session_id,
        user_id=1,
        chat_id=1,
        progress_message_id=0,
        mode="verstai",
        input_s3_key=None,
    )
    s = SessionState.from_input(inp)
    return s.model_copy(update={"artefacts": dict(artefacts)})


@pytest.fixture(autouse=True)
def _stub_progress(monkeypatch):
    """Silence Redis publishes — nodes call ``progress.stage()`` which would
    otherwise attempt a Redis connection. ``publish`` already swallows
    exceptions, but stubbing keeps test logs clean."""
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)


# ─── 01 Brief Reader ─────────────────────────────────────────────────────────

def test_brief_node_cassette_small(monkeypatch):
    """Real Kimi vision response (small deck) → schema-valid Brief artefact."""
    arts = {"parsed_deck": fixtures.make_parsed_deck("small")}
    state = _make_state("c-brief-s", arts)

    cassette = CassetteCallRole({Role.BRIEF_PARSER: load_cassette("01_brief", "small")})
    monkeypatch.setattr("llm.output_parsers.call_role", cassette)

    patch = brief_node(state)
    brief = Brief.model_validate(patch["artefacts"]["brief"])
    assert brief.slide_count == 3
    assert len(brief.slides) == 3
    assert all(s.num >= 1 for s in brief.slides)
    # The node should have made exactly one call, against BRIEF_PARSER.
    assert len(cassette.calls) == 1
    assert cassette.calls[0].role is Role.BRIEF_PARSER


def test_brief_node_cassette_big(monkeypatch):
    """Bigger deck cassette — same node, bigger payload (12-slide brief)."""
    arts = {"parsed_deck": fixtures.make_parsed_deck("big")}
    state = _make_state("c-brief-b", arts)

    cassette = CassetteCallRole({Role.BRIEF_PARSER: load_cassette("01_brief", "big")})
    monkeypatch.setattr("llm.output_parsers.call_role", cassette)

    patch = brief_node(state)
    brief = Brief.model_validate(patch["artefacts"]["brief"])
    assert brief.slide_count >= 10  # big deck cassette is 12 slides


# ─── 02 Slide Classifier ─────────────────────────────────────────────────────

def test_classify_node_cassette(monkeypatch):
    """Real DeepSeek classifier response → valid DeckClassification."""
    arts = {"brief": fixtures.make_brief("big")}
    state = _make_state("c-cls", arts)

    cassette = CassetteCallRole({Role.CLASSIFIER: load_cassette("02_classifier", "big")})
    monkeypatch.setattr("llm.output_parsers.call_role", cassette)

    patch = classify_node(state)
    cls = DeckClassification.model_validate(patch["artefacts"]["classification"])
    assert len(cls.slides) >= 10
    # Sanity: classifier output should at least mention some known categories.
    cats = {s.category for s in cls.slides}
    assert cats & {"title", "text", "kpi", "table", "flow", "callout"}, \
        f"expected some standard categories, got {cats}"


# ─── 04 Layout Designer ──────────────────────────────────────────────────────

def test_design_node_cassette(monkeypatch):
    """Real DeepSeek designer response → valid LayoutPlan with per-slide donors."""
    arts = {"classification": fixtures.make_classification("big")}
    state = _make_state("c-design", arts)

    cassette = CassetteCallRole({Role.DESIGNER: load_cassette("04_designer", "big")})
    monkeypatch.setattr("llm.output_parsers.call_role", cassette)

    patch = design_node(state)
    layouts_raw = patch["artefacts"]["layouts"]
    # The node dumps with by_alias=True for build_v9 compatibility; LayoutPlan
    # accepts both (populate_by_name=True on its fields).
    plan = LayoutPlan.model_validate(layouts_raw)
    assert len(plan.slides) >= 10
    # At least some slides should carry a chosen donor or native marker.
    donors = [
        getattr(s, "layout_idx", None) or getattr(s, "donor", None)
        for s in plan.slides
    ]
    assert any(d is not None for d in donors), \
        "Layout Designer cassette should pick at least one donor/native"


# ─── 07 Copy Editor ──────────────────────────────────────────────────────────

def test_copyedit_node_cassette(monkeypatch):
    """Real GLM-OFF copyedit response → valid DeckContent under copy_edited."""
    arts = {"content": fixtures.make_content("big")}
    state = _make_state("c-edit", arts)

    cassette = CassetteCallRole({Role.COPY_EDITOR: load_cassette("07_copyedit", "big")})
    monkeypatch.setattr("llm.output_parsers.call_role", cassette)

    patch = copyedit_node(state)
    edited = DeckContent.model_validate(patch["artefacts"]["copy_edited"])
    assert len(edited.slides) >= 10
    # Copy Editor must populate edits_count (it's how Process Verifier scores).
    assert all(s.edits_count >= 0 for s in edited.slides)


# ─── 03 Content Distributor ──────────────────────────────────────────────────

@pytest.mark.parametrize("size", ["small", "medium", "big"])
def test_distribute_node_cassette(monkeypatch, size: str):
    """Real GLM-OFF distributor response → DeckContent under content."""
    arts = {
        "brief": fixtures.make_brief(size),
        "classification": fixtures.make_classification(size),
        "layouts": fixtures.make_layouts(size),
    }
    state = _make_state(f"c-dist-{size}", arts)

    cassette = CassetteCallRole({Role.DISTRIBUTOR: load_cassette("03_distributor", size)})
    monkeypatch.setattr("llm.output_parsers.call_role", cassette)

    patch = distribute_node(state)
    content = DeckContent.model_validate(patch["artefacts"]["content"])
    assert content.slides, f"distributor[{size}]: empty slides list"
    # Native slides (kpi/chart/table/flow) legitimately have empty
    # placeholder_assignments — Distributor skips them per its prompt. So
    # just assert at least one donor slide carries content.
    assert any(s.placeholder_assignments for s in content.slides), \
        f"distributor[{size}]: no slide carries placeholder content"


# ─── 05 Icon Picker ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("size", ["small", "medium", "big"])
def test_icons_node_cassette(monkeypatch, size: str):
    """Real GLM-OFF icon-picker response → DeckIcons under icons."""
    arts = {
        "classification": fixtures.make_classification(size),
        "content": fixtures.make_content(size),
    }
    state = _make_state(f"c-icons-{size}", arts)

    cassette = CassetteCallRole({Role.ICON_PICKER: load_cassette("05_icons", size)})
    monkeypatch.setattr("llm.output_parsers.call_role", cassette)

    patch = icons_node(state)
    icons = DeckIcons.model_validate(patch["artefacts"]["icons"])
    assert icons.slides, f"icon picker[{size}]: empty slides list"


# ─── 06 Infographic Maker ────────────────────────────────────────────────────

def test_infographic_node_cassette(monkeypatch):
    """Real GLM-OFF infographic-maker response → DeckInfographics under infographics."""
    arts = {
        "classification": fixtures.make_classification("big"),
        "content": fixtures.make_content("big"),
    }
    state = _make_state("c-info", arts)

    cassette = CassetteCallRole({Role.INFOGRAPHIC_MAKER: load_cassette("06_infographic", "big")})
    monkeypatch.setattr("llm.output_parsers.call_role", cassette)

    patch = infographic_node(state)
    infos = DeckInfographics.model_validate(patch["artefacts"]["infographics"])
    # The cassette covers a few slides where the big-deck classifier asked for
    # infographics. Just assert the shape is right — not every slide gets one.
    assert isinstance(infos.slides, list)


# ─── 10 Visual Verifier ──────────────────────────────────────────────────────

@pytest.mark.parametrize("size", ["small", "medium", "big"])
def test_visual_verify_node_cassette(monkeypatch, tmp_path: Path, size: str):
    """Real Kimi-vision visual-verifier response → VisualVerdict under visual_verdict.

    The node only runs when ``rendered_pngs`` are present in artefacts —
    we drop in a placeholder PNG (Kimi tolerates) and a synthetic Plan.
    """
    plan = fixtures.make_plan(size)
    placeholder = tmp_path / "slide-1.png"
    # Minimal 1×1 PNG, mirrors brief_node's vision-gate placeholder.
    placeholder.write_bytes(bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
    ))
    arts = {
        "plan": plan,
        "rendered_pngs": [str(placeholder)],
    }
    state = _make_state(f"c-vv-{size}", arts)

    cassette = CassetteCallRole({Role.VISUAL_VERIFIER: load_cassette("10_visual", size)})
    monkeypatch.setattr("llm.output_parsers.call_role", cassette)

    patch = visual_verify_node(state)
    vv = VisualVerdict.model_validate(patch["artefacts"]["visual_verdict"])
    assert vv.llm_verdict in ("READY", "NEEDS_REWORK")
    assert 0 <= vv.score_avg <= 5.0 or vv.score_avg == 0  # NEEDS_REWORK with 0 is fine
