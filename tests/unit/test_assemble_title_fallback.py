"""D3: assemble_plan_node title fallback for donor slides.

Live run 2026-06-05 (run2.slide1): cover donor 4 rendered with empty
title bar because Agent 03 emitted no placeholder_assignment for the
title ph_idx. build_v9 then cleared the donor's "Заголовок" template
text, leaving the slide titleless.

The fix: when the donor schema has a "title" slot but slots["title"]
ends up empty, fall back to per-slide raw_title from the brief, then
brief.topic for slide 1.
"""
from __future__ import annotations

from typing import Any

from graph.nodes.pipeline import assemble_plan_node
from schemas.session import SessionInput, SessionState


def _make_state(artefacts: dict[str, Any]) -> SessionState:
    inp = SessionInput(
        session_id="d3-test",
        user_id=1,
        chat_id=1,
        progress_message_id=0,
        mode="verstai",
        input_s3_key=None,
    )
    s = SessionState.from_input(inp)
    return s.model_copy(update={"artefacts": dict(artefacts)})


def _base_artefacts(*, slide_title_in_content: bool, brief_raw_title: str | None,
                    brief_topic: str = "Quarterly review",
                    num: int = 1, donor: int = 4) -> dict[str, Any]:
    """Artefact bundle for a single donor slide.

    Donor 4 has a "title" slot at shape_idx=1 and "subtitle" at shape_idx=0
    (see donor-slot-map.yaml).
    """
    content_phs: list[dict[str, Any]] = [
        {"ph_idx": 0, "content": "Q1 2026", "ph_type": "TITLE"},  # subtitle slot
    ]
    if slide_title_in_content:
        content_phs.append({"ph_idx": 1, "content": "From Distributor", "ph_type": "TITLE"})

    brief_slides: list[dict[str, Any]] = []
    if brief_raw_title is not None:
        brief_slides.append({"num": num, "raw_title": brief_raw_title, "raw_body": []})

    return {
        "brief": {
            "topic": brief_topic,
            "slide_count": 1,
            "slides": brief_slides,
        },
        "classification": {
            "slides": [{"num": num, "category": "title", "subcategory_hint": "", "rationale": ""}],
        },
        "layouts": {
            "slides": [{"num": num, "layout_idx": donor}],
        },
        "content": {
            "slides": [{"slide_num": num, "placeholder_assignments": content_phs}],
        },
        "infographics": {"slides": []},
        "icons": {"slides": []},
    }


def test_title_filled_by_distributor_kept(monkeypatch) -> None:
    """No fallback when Agent 03 supplied the title."""
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)
    arts = _base_artefacts(slide_title_in_content=True, brief_raw_title="From Brief")
    state = _make_state(arts)
    out = assemble_plan_node(state)
    plan = out["artefacts"]["plan"]
    assert len(plan["slides"]) == 1
    assert plan["slides"][0]["slots"]["title"] == "From Distributor"


def test_title_missing_falls_back_to_brief_raw_title(monkeypatch) -> None:
    """Distributor omitted title → fall back to BriefSlide.raw_title."""
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)
    arts = _base_artefacts(slide_title_in_content=False,
                           brief_raw_title="Cover from brief")
    state = _make_state(arts)
    out = assemble_plan_node(state)
    plan = out["artefacts"]["plan"]
    assert plan["slides"][0]["slots"].get("title") == "Cover from brief"


def test_slide_1_title_falls_back_to_topic_when_no_raw_title(monkeypatch) -> None:
    """For slide 1 specifically, missing raw_title → use brief.topic."""
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)
    arts = _base_artefacts(slide_title_in_content=False, brief_raw_title=None,
                           brief_topic="Cloud.ru Year in Review", num=1)
    state = _make_state(arts)
    out = assemble_plan_node(state)
    plan = out["artefacts"]["plan"]
    assert plan["slides"][0]["slots"].get("title") == "Cloud.ru Year in Review"


def test_non_cover_title_missing_with_no_raw_title_stays_empty(monkeypatch) -> None:
    """For non-cover slides without raw_title we don't substitute the deck topic —
    that would put the deck title on every titleless slide. Just leave it empty
    and let build_v9 clear the donor placeholder."""
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)
    arts = _base_artefacts(slide_title_in_content=False, brief_raw_title=None,
                           brief_topic="Year Review", num=3)
    state = _make_state(arts)
    out = assemble_plan_node(state)
    plan = out["artefacts"]["plan"]
    # Title slot is absent or empty — never the deck topic.
    title_val = plan["slides"][0]["slots"].get("title", "")
    assert title_val == ""
