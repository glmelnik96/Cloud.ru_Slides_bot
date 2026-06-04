"""Cassette-driven integration tests for the LLM half of the pipeline.

Pairs with ``test_pipeline_smoke.py`` (which covers the deterministic,
script-wrapping half). Together they let us validate the whole v0.9 batch
flow end-to-end without a live Cloud.ru API key:

    parse_node                ← test_pipeline_smoke
    brief_node                ← here (cassette: 01_brief)
    classify_node             ← here (cassette: 02_classifier)
    design_node               ← here (cassette: 04_designer)
    distribute_node           ← NOT covered (no artifact captured yet)
    icons_node                ← NOT covered (no artifact captured yet)
    infographic_node          ← NOT covered (failing artifact, schema bug TODO)
    copyedit_node             ← here (cassette: 07_copyedit)
    assemble_plan_node …      ← test_pipeline_smoke
    visual_verify_node        ← NOT covered (failing artifact, schema bug TODO)

The four covered nodes are the ones with valid captured artifacts from the
WS-E probe run. Distributor / Icon Picker probes never produced artifacts;
Infographic Maker / Visual Verifier produced malformed JSON we need to chase
in a separate prompt-tuning chunk.
"""
from __future__ import annotations

from typing import Any

import pytest

from graph.nodes.agents import (
    brief_node,
    classify_node,
    copyedit_node,
    design_node,
)
from llm.roles import Role
from schemas.session import SessionInput, SessionState
from schemas.slides import Brief, DeckClassification, LayoutPlan
from tests.integration.llm_cassettes import CassetteCallRole, load_cassette
from tests.probes import fixtures
from tests.probes._wrappers import DeckContent


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
