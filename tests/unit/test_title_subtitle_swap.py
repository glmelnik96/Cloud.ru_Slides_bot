"""Cover-slide title/subtitle swap-guard.

Live defect: on the cover/title slide the TITLE and SUBTITLE were swapped.
parse_pptx assigns the FIRST short text run as the slide title, so when a
source cover lists the event/date line ("Cloud Tech Day · 9 Июня 2026")
BEFORE the real product title ("Cloud.ru Advanced: …"), the date line wins
the title slot and the product name is demoted to the subtitle. Neither the
Brief Reader nor the Distributor de-prioritises date/event lines, so the swap
propagates into the final ``slots["title"]`` / ``slots["subtitle"]``.

assemble_plan_node carries a conservative deterministic swap-guard
(``_looks_like_date_or_event`` + a swap that runs ONLY for the cover slide:
donor has both a ``title`` and ``subtitle`` slot AND deck num == 1) that
restores the correct order. These tests pin that behaviour and its
false-positive guards.
"""
from __future__ import annotations

from typing import Any

from graph.nodes.pipeline import _looks_like_date_or_event, assemble_plan_node
from schemas.session import SessionInput, SessionState


def _make_state(artefacts: dict[str, Any]) -> SessionState:
    inp = SessionInput(
        session_id="swap-test",
        user_id=1,
        chat_id=1,
        progress_message_id=0,
        mode="verstai",
        input_s3_key=None,
    )
    s = SessionState.from_input(inp)
    return s.model_copy(update={"artefacts": dict(artefacts)})


def _cover_artefacts(
    *,
    title: str,
    subtitle: str,
    num: int = 1,
    donor: int = 4,
) -> dict[str, Any]:
    """Single cover-slide bundle on donor 4 (ph_idx 1=title, 0=subtitle)."""
    from graph import donor_map

    name_to_ph = {
        name: ph for ph, name in donor_map.slot_name_by_ph_idx(donor).items()
    }
    phs = [
        {"ph_idx": name_to_ph["title"], "content": title, "ph_type": "TITLE"},
        {"ph_idx": name_to_ph["subtitle"], "content": subtitle, "ph_type": "SUBTITLE"},
    ]
    return {
        "brief": {
            "topic": "Deck",
            "slide_count": 1,
            "slides": [{"num": num, "raw_title": title, "raw_body": []}],
        },
        "classification": {"slides": [{
            "num": num, "category": "title",
            "subcategory_hint": "", "rationale": "",
        }]},
        "layouts": {"slides": [{"num": num, "layout_idx": donor}]},
        "content": {"slides": [{
            "slide_num": num,
            "placeholder_assignments": phs,
        }]},
        "infographics": {"slides": []},
        "icons": {"slides": []},
    }


def _slots(out: dict[str, Any]) -> dict[str, Any]:
    return out["artefacts"]["plan"]["slides"][0]["slots"]


# ── _looks_like_date_or_event unit cases ───────────────────────────────────


def test_looks_like_date_positive_cases() -> None:
    assert _looks_like_date_or_event("9 Июня 2026")
    assert _looks_like_date_or_event("GoCloud 2026")
    assert _looks_like_date_or_event("Tech Day · 2026")
    assert _looks_like_date_or_event("Cloud Tech Day · 9 Июня 2026")
    assert _looks_like_date_or_event("09.06.2026")


def test_looks_like_date_negative_cases() -> None:
    assert not _looks_like_date_or_event("Cloud.ru Advanced")
    assert not _looks_like_date_or_event("Платформа для разработчиков")
    assert not _looks_like_date_or_event("")
    # Long product-y line with a year inside must not falsely trip.
    assert not _looks_like_date_or_event(
        "Cloud.ru Advanced: новые возможности платформы для ИИ в 2026"
    )


# ── swap behaviour through the real assemble code path ─────────────────────


def test_swap_happens_when_date_line_won_title(monkeypatch) -> None:
    """The reproduction: a date/event line landed in the title slot while a
    plausible product title sits in the subtitle. They must be swapped back."""
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)
    state = _make_state(_cover_artefacts(
        title="Cloud Tech Day · 9 Июня 2026",
        subtitle="Cloud.ru Advanced: новые возможности платформы",
    ))
    out = assemble_plan_node(state)
    slots = _slots(out)
    assert slots["title"] == "Cloud.ru Advanced: новые возможности платформы"
    assert slots["subtitle"] == "Cloud Tech Day · 9 Июня 2026"


def test_no_swap_for_normal_cover(monkeypatch) -> None:
    """A normal cover (product title + tagline) must be left untouched."""
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)
    state = _make_state(_cover_artefacts(
        title="Cloud.ru Advanced",
        subtitle="Платформа для ИИ",
    ))
    out = assemble_plan_node(state)
    slots = _slots(out)
    assert slots["title"] == "Cloud.ru Advanced"
    assert slots["subtitle"] == "Платформа для ИИ"


def test_no_swap_when_subtitle_also_date_like(monkeypatch) -> None:
    """If the subtitle is itself date/event-like, there is no better title
    candidate → no swap (don't trade one date line for another)."""
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)
    state = _make_state(_cover_artefacts(
        title="Cloud Tech Day · 9 Июня 2026",
        subtitle="GoCloud 2026",
    ))
    out = assemble_plan_node(state)
    slots = _slots(out)
    assert slots["title"] == "Cloud Tech Day · 9 Июня 2026"
    assert slots["subtitle"] == "GoCloud 2026"


def test_no_swap_when_subtitle_empty(monkeypatch) -> None:
    """No plausible title in the subtitle slot → nothing to swap with."""
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)
    state = _make_state(_cover_artefacts(
        title="9 Июня 2026",
        subtitle="",
    ))
    out = assemble_plan_node(state)
    slots = _slots(out)
    # Title stays (the D3 fallback may fill it, but it must NOT become "" via
    # a swap with an empty subtitle).
    assert slots.get("subtitle", "") == ""
    assert (slots.get("title") or "").strip() != ""


def test_no_swap_for_non_cover_slide(monkeypatch) -> None:
    """The guard runs ONLY for the cover (num==1). A later slide whose title
    happens to look date-like must NOT be swapped."""
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)
    state = _make_state(_cover_artefacts(
        title="9 Июня 2026",
        subtitle="Cloud.ru Advanced: новые возможности платформы",
        num=3,
    ))
    out = assemble_plan_node(state)
    slots = _slots(out)
    assert slots["title"] == "9 Июня 2026"
    assert slots["subtitle"] == "Cloud.ru Advanced: новые возможности платформы"
