"""infographic_node must degrade gracefully on bad LLM JSON.

Real incident (memory/manual_run_validation_2026_06_07.md): GLM-5.1 returned
truncated JSON at char ~15135 in the Infographic Maker step. ``call_and_parse``
exhausted its one-shot truncation auto-bump + single feedback retry and raised
``ValueError``. With no handling in ``infographic_node`` that propagated through
``graph.invoke()`` and failed the WHOLE session — no output pptx at all, even
though infographics are a purely cosmetic enrichment step.

The fix: infographic_node must catch the parse/validation failure, fall back to
an empty ``_DeckInfographics`` (so downstream ``assemble_plan_node`` simply
builds plain donor slides without infographic shapes), and return the SAME shape
as the happy path. These tests pin that contract for both error families
``call_and_parse`` raises (``ValueError`` for JSON decode, ``ValidationError``
for schema).
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from graph.nodes import agents
from llm.prompts import agent_06_infographic_maker


def _make_state(arts):
    """Minimal SessionState carrying artefacts (mirrors test_sparse_detector)."""
    from schemas.session import SessionInput, SessionState
    inp = SessionInput(
        session_id="test-infographic", user_id=1, chat_id=1,
        progress_message_id=0, mode="verstai", input_s3_key=None,
    )
    s = SessionState.from_input(inp)
    return s.model_copy(update={"artefacts": dict(arts)})


# Classification with two real slides: a successful run would produce infographic
# specs keyed by slide_num. The fallback must yield NO specs so assemble attaches
# no shapes for either slide.
_CLASSIFICATION = {"slides": [
    {"num": 1, "category": "title"},
    {"num": 2, "category": "process"},
]}
_CONTENT = {"slides": [
    {"slide_num": 1, "layout_idx": 0, "placeholder_assignments": []},
    {"slide_num": 2, "layout_idx": 34, "placeholder_assignments": []},
]}


def _build_validation_error() -> ValidationError:
    """A genuine pydantic ValidationError against the deck-infographics model.

    Feeding a non-list ``slides`` reproduces the schema-failure family that
    ``call_and_parse`` re-raises after its retry is exhausted.
    """
    with pytest.raises(ValidationError) as ei:
        agents._DeckInfographics.model_validate({"slides": "not-a-list"})
    return ei.value


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("JSONDecodeError: Expecting value at pos 15135"),
        _build_validation_error(),
    ],
    ids=["json_decode_error", "pydantic_validation_error"],
)
def test_infographic_node_degrades_on_bad_json(monkeypatch, exc):
    """A parse/validation failure degrades to no-infographic, never crashes."""
    def _boom(**kwargs):
        raise exc

    # Run fully offline: no Redis publish, no prompt build, no real LLM.
    monkeypatch.setattr(agents, "_emit", lambda *a, **k: None)
    monkeypatch.setattr(agent_06_infographic_maker, "build_messages",
                        lambda *a, **k: [])
    monkeypatch.setattr(agents, "call_and_parse", _boom)

    state = _make_state(arts={
        "classification": _CLASSIFICATION,
        "content": _CONTENT,
    })

    # Must NOT raise.
    patch = agents.infographic_node(state)

    # Same return shape / progress as the happy path.
    assert patch["stage"] == agents.Stage.DESIGNING.value
    assert patch["progress_pct"] == 70

    # Safe, schema-valid, downstream-tolerated fallback: empty slide list.
    info = patch["artefacts"]["infographics"]
    assert info == {"slides": []}
    # The fallback must round-trip through the real model (schema-valid).
    agents._DeckInfographics.model_validate(info)


def test_infographic_node_fallback_attaches_no_shapes_downstream():
    """The empty fallback yields an empty info_by_num so assemble attaches none.

    Mirrors the downstream consumption in assemble_plan_node:
        info_by_num = _by_num(infographics_slides, key="slide_num")
        info = info_by_num.get(num) or {}
        if info.get("infographic_type") and ... != "none": attach shapes
    With slides=[] the map is empty, so every lookup yields {} -> no shapes.
    """
    from graph.nodes.pipeline import _by_num

    fallback = agents._DeckInfographics(slides=[]).model_dump()
    info_by_num = _by_num(fallback.get("slides") or [], key="slide_num")
    assert info_by_num == {}
    # Lookups for any slide num degrade to the empty-dict / no-shape branch.
    assert (info_by_num.get(2) or {}).get("infographic_type") is None


def test_infographic_node_happy_path_unchanged(monkeypatch):
    """Happy path still stores the parsed model_dump and reports slide count."""
    class _FakeInfographics:
        slides = [object(), object()]  # len() only

        def model_dump(self):
            return {"slides": [{"slide_num": 2, "infographic_type": "process",
                                "shapes": [{"label": "x"}]}]}

    monkeypatch.setattr(agents, "_emit", lambda *a, **k: None)
    monkeypatch.setattr(agent_06_infographic_maker, "build_messages",
                        lambda *a, **k: [])
    monkeypatch.setattr(agents, "call_and_parse",
                        lambda **kw: (_FakeInfographics(), None))

    state = _make_state(arts={
        "classification": _CLASSIFICATION,
        "content": _CONTENT,
    })
    patch = agents.infographic_node(state)

    assert patch["progress_pct"] == 70
    assert patch["artefacts"]["infographics"] == {
        "slides": [{"slide_num": 2, "infographic_type": "process",
                    "shapes": [{"label": "x"}]}]
    }
