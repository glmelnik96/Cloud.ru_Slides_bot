"""#5: assemble_plan_node deterministic body-line recovery.

Live session 81673d112f964e85 slide 5 ("OBS: Custom SSL сертификаты"):
the brief body carried 3 content lines, but the Content Distributor
(Agent 03) — acting on its "слотов < контента → отбрось наименее важные"
instruction — emitted only 2 into donor 21's single body slot. The 3rd
line ("пользовательский домен, привязанный к бакету") was silently lost;
plan.json and the rendered PNG showed 2 bullets.

The fix: a deterministic safeguard in assemble_plan_node. When a donor
slide's distributed body has FEWER non-empty lines than the brief body
for that slide, the missing brief lines are appended (\n-joined) to the
last body slot — content is never lost. Slides whose distributed body
already covers the brief are left untouched (no over-reflow).
"""
from __future__ import annotations

from typing import Any

from graph.nodes.pipeline import assemble_plan_node
from schemas.session import SessionInput, SessionState


def _make_state(artefacts: dict[str, Any]) -> SessionState:
    inp = SessionInput(
        session_id="recovery-test",
        user_id=1,
        chat_id=1,
        progress_message_id=0,
        mode="verstai",
        input_s3_key=None,
    )
    s = SessionState.from_input(inp)
    return s.model_copy(update={"artefacts": dict(artefacts)})


def _artefacts(*, raw_body: list[str], body_content: str,
               num: int = 5, donor: int = 21) -> dict[str, Any]:
    """Single-slide donor bundle. Donor 21 = title(shape_idx 0) +
    body(shape_idx 1) — a single body slot (see donor-slot-map.yaml)."""
    return {
        "brief": {
            "topic": "Deck",
            "slide_count": 1,
            "slides": [{"num": num, "raw_title": "OBS", "raw_body": raw_body}],
        },
        "classification": {
            "slides": [{"num": num, "category": "text",
                        "subcategory_hint": "", "rationale": ""}],
        },
        "layouts": {"slides": [{"num": num, "layout_idx": donor}]},
        "content": {
            "slides": [{
                "slide_num": num,
                "placeholder_assignments": [
                    {"ph_idx": 0, "content": "OBS: Custom SSL", "ph_type": "TITLE"},
                    {"ph_idx": 1, "content": body_content, "ph_type": "BODY"},
                ],
            }],
        },
        "infographics": {"slides": []},
        "icons": {"slides": []},
    }


def test_dropped_brief_line_is_recovered_into_body(monkeypatch) -> None:
    """The reproduction: brief has 3 body lines, distributor kept 2.
    The 3rd must be recovered into the body slot — no content lost."""
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)
    raw_body = [
        "HTTPS-доступ к бакетам через собственный домен:\n\n"
        "Сертификат через сервис CCM (Cloud Certificate Manager) \n"
        "пользовательский домен, привязанный к бакету"
    ]
    # Distributor output dropped the 3rd line.
    body_content = (
        "HTTPS-доступ к бакетам через собственный домен.\n"
        "Сертификат через сервис **CCM (Cloud Certificate Manager)**."
    )
    state = _make_state(_artefacts(raw_body=raw_body, body_content=body_content))
    out = assemble_plan_node(state)
    body = out["artefacts"]["plan"]["slides"][0]["slots"]["body"]
    # The dropped line's distinctive words must be present after recovery.
    assert "пользовательский домен" in body
    assert "привязанный к бакету" in body
    # The two kept lines survive too.
    assert "HTTPS-доступ к бакетам" in body
    assert "CCM" in body
    # All three source lines are now represented (≥3 non-empty body lines).
    non_empty = [ln for ln in body.split("\n") if ln.strip()]
    assert len(non_empty) >= 3


def test_body_fully_covered_is_left_untouched(monkeypatch) -> None:
    """No-op: a slide whose distributed body already covers every brief
    line must NOT be reflowed — exact content preserved."""
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)
    raw_body = ["Первый пункт\nВторой пункт"]
    body_content = "Первый пункт.\nВторой пункт."
    state = _make_state(_artefacts(raw_body=raw_body, body_content=body_content))
    out = assemble_plan_node(state)
    body = out["artefacts"]["plan"]["slides"][0]["slots"]["body"]
    assert body == "Первый пункт.\nВторой пункт."


def test_fewer_brief_lines_than_body_is_noop(monkeypatch) -> None:
    """When the distributor legitimately produced MORE lines than the brief
    (e.g. split a long sentence into two bullets), nothing is appended."""
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)
    raw_body = ["Одно длинное предложение про кластер и регионы"]
    body_content = (
        "Одно длинное предложение про кластер.\n"
        "И регионы покрыты полностью."
    )
    state = _make_state(_artefacts(raw_body=raw_body, body_content=body_content))
    out = assemble_plan_node(state)
    body = out["artefacts"]["plan"]["slides"][0]["slots"]["body"]
    assert body == body_content
