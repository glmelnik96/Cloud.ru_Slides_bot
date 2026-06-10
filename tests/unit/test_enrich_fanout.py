"""B2: icons / infographic / copyedit run CONCURRENTLY in one fan-out node.

All three depend only on distribute output (classification + content) and
write disjoint artefact keys, so they are safe to parallelize. The fan-out
node must merge the three patches and report the terminal progress (75).
Concurrency is proven with a 3-party barrier inside the mocked LLM call:
sequential execution would deadlock the barrier and fail the test.
"""
from __future__ import annotations

import threading

import pytest

from graph.nodes import agents
from llm.prompts import (
    agent_05_icon_picker,
    agent_06_infographic_maker,
    agent_07_copy_editor,
)


def _make_state(arts):
    from schemas.session import SessionInput, SessionState
    inp = SessionInput(
        session_id="test-enrich", user_id=1, chat_id=1,
        progress_message_id=0, mode="verstai", input_s3_key=None,
    )
    s = SessionState.from_input(inp)
    return s.model_copy(update={"artefacts": dict(arts)})


_CLASSIFICATION = {"slides": [{"num": 1, "category": "title"}]}
_CONTENT = {"slides": [
    {"slide_num": 1, "layout_idx": 0, "placeholder_assignments": []},
]}


def _result_for(role):
    """Schema-valid empty result per role."""
    name = getattr(role, "name", str(role))
    if "ICON" in name:
        return agents._DeckIcons(slides=[])
    if "INFOGRAPHIC" in name:
        return agents._DeckInfographics(slides=[])
    return agents._DeckContentAssignment(slides=[])


@pytest.fixture()
def offline(monkeypatch):
    monkeypatch.setattr(agents, "_emit", lambda *a, **k: None)
    monkeypatch.setattr(agent_05_icon_picker, "build_messages", lambda *a, **k: [])
    monkeypatch.setattr(agent_06_infographic_maker, "build_messages", lambda *a, **k: [])
    monkeypatch.setattr(agent_07_copy_editor, "build_messages", lambda *a, **k: [])
    return monkeypatch


def _arts():
    return {"classification": _CLASSIFICATION, "content": _CONTENT}


def test_fanout_merges_all_three_artefacts(offline):
    def _fake(role=None, messages=None, model_cls=None, **kw):
        return _result_for(role), None

    offline.setattr(agents, "call_and_parse", _fake)
    patch = agents.enrich_fanout_node(_make_state(_arts()))
    arts = patch["artefacts"]
    assert arts["icons"] == {"slides": []}
    assert arts["infographics"] == {"slides": []}
    assert "copy_edited" in arts
    # Upstream artefacts preserved.
    assert arts["classification"] == _CLASSIFICATION
    assert patch["progress_pct"] == 75
    assert patch["stage"] == agents.Stage.DESIGNING.value


def test_fanout_actually_concurrent(offline):
    """If the three calls ran sequentially the barrier would time out."""
    barrier = threading.Barrier(3, timeout=10)

    def _fake(role=None, messages=None, model_cls=None, **kw):
        barrier.wait()  # raises BrokenBarrierError on timeout (sequential run)
        return _result_for(role), None

    offline.setattr(agents, "call_and_parse", _fake)
    patch = agents.enrich_fanout_node(_make_state(_arts()))
    assert "copy_edited" in patch["artefacts"]


def test_fanout_infographic_failure_still_degrades(offline):
    """The infographic degrade-to-empty behaviour survives the fan-out."""
    def _fake(role=None, messages=None, model_cls=None, **kw):
        if "INFOGRAPHIC" in getattr(role, "name", ""):
            raise ValueError("JSONDecodeError: truncated")
        return _result_for(role), None

    offline.setattr(agents, "call_and_parse", _fake)
    patch = agents.enrich_fanout_node(_make_state(_arts()))
    assert patch["artefacts"]["infographics"] == {"slides": []}
    assert "icons" in patch["artefacts"]
    assert "copy_edited" in patch["artefacts"]


def test_fanout_icon_failure_propagates(offline):
    """A hard failure in a non-degradable branch propagates (same as today)."""
    def _fake(role=None, messages=None, model_cls=None, **kw):
        if "ICON" in getattr(role, "name", ""):
            raise ValueError("hard fail")
        return _result_for(role), None

    offline.setattr(agents, "call_and_parse", _fake)
    with pytest.raises(ValueError, match="hard fail"):
        agents.enrich_fanout_node(_make_state(_arts()))


def test_graph_wires_fanout_between_distribute_and_assemble():
    from graph import graph as g
    assert hasattr(g, "N_ENRICH")
    compiled = g._build_graph()
    nodes = set(compiled.nodes)
    assert g.N_ENRICH in nodes
    for legacy in ("icons", "infographic", "copyedit"):
        assert legacy not in nodes
