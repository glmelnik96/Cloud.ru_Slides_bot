"""#5: assemble_plan_node deterministic body-line recovery.

Live session 81673d112f964e85 slide 5 ("OBS: Custom SSL сертификаты"):
the brief body carried 3 content lines, but the Content Distributor
(Agent 03) — acting on its "слотов < контента → отбрось наименее важные"
instruction — emitted only 2 into donor 21's single body slot. The 3rd
line ("пользовательский домен, привязанный к бакету") was silently lost;
plan.json and the rendered PNG showed 2 bullets.

The fix: a deterministic safeguard in assemble_plan_node. When a donor
slide's distributed body omits a genuinely-dropped brief line, that line
is appended (\n-joined) to the last body slot — content is never lost.
The matcher is per-distributed-line + distinctive-token based and guards
against re-appending content the distributor merely rephrased/merged
(no duplication), and skips split-brief fragments to avoid cross-slide
contamination.
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


def _artefacts(
    *,
    raw_body: list[str],
    body_content: str,
    num: int = 5,
    donor: int = 21,
    brief_num: int | None = None,
    cls_extra: dict[str, Any] | None = None,
    title_content: str = "OBS: Custom SSL",
) -> dict[str, Any]:
    """Single-slide donor bundle. Donor 21 = title(shape_idx 0) +
    body(shape_idx 1) — a single body slot (see donor-slot-map.yaml).

    ``brief_num`` lets the brief slide carry a different num than the deck
    slide (to model post-split renumbering). ``cls_extra`` merges extra
    keys into the classification slide (e.g. ``_split_part`` /
    ``_source_slide``).
    """
    bnum = brief_num if brief_num is not None else num
    cls_slide: dict[str, Any] = {
        "num": num, "category": "text",
        "subcategory_hint": "", "rationale": "",
    }
    if cls_extra:
        cls_slide.update(cls_extra)
    return {
        "brief": {
            "topic": "Deck",
            "slide_count": 1,
            "slides": [{"num": bnum, "raw_title": "OBS", "raw_body": raw_body}],
        },
        "classification": {"slides": [cls_slide]},
        "layouts": {"slides": [{"num": num, "layout_idx": donor}]},
        "content": {
            "slides": [{
                "slide_num": num,
                "placeholder_assignments": [
                    {"ph_idx": 0, "content": title_content, "ph_type": "TITLE"},
                    {"ph_idx": 1, "content": body_content, "ph_type": "BODY"},
                ],
            }],
        },
        "infographics": {"slides": []},
        "icons": {"slides": []},
    }


def test_dropped_brief_line_is_recovered_into_body(monkeypatch) -> None:
    """The 81673 reproduction: brief has 3 body lines, distributor kept 2
    (reformatted, not rephrased). The 3rd genuinely-missing line must be
    recovered into the body slot — and ONLY that one line."""
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
    # Exactly ONE line recovered → 3 non-empty body lines (no over-reflow).
    non_empty = [ln for ln in body.split("\n") if ln.strip()]
    assert len(non_empty) == 3


def test_body_fully_covered_is_left_untouched(monkeypatch) -> None:
    """No-op: a slide whose distributed body already covers every brief
    line must NOT be reflowed — exact content preserved."""
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)
    raw_body = ["Первый уникальный пункт\nВторой особенный пункт"]
    body_content = "Первый уникальный пункт.\nВторой особенный пункт."
    state = _make_state(_artefacts(raw_body=raw_body, body_content=body_content))
    out = assemble_plan_node(state)
    body = out["artefacts"]["plan"]["slides"][0]["slots"]["body"]
    assert body == "Первый уникальный пункт.\nВторой особенный пункт."


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


# ── Review-mandated correctness cases ──────────────────────────────────────


def test_false_positive_shared_words_dropped_line_recovered(monkeypatch) -> None:
    """IMPORTANT 1 — pooled-word false positive.

    Two brief lines share common ≥3-char domain words ("бакет", "доступ").
    One line is genuinely dropped. A pooled bag-of-words matcher would see
    the shared words scattered across the kept line and mark the dropped
    line "covered" → silent loss. Per-line matching against a distinctive
    token must still recover it.
    """
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)
    raw_body = [
        "Доступ к бакету по протоколу HTTPS\n"
        "Доступ к бакету через приватную сеть VPC"
    ]
    # Distributor kept ONLY the first line; the VPC line is genuinely dropped.
    # Its shared words (доступ, бакету) all appear in the kept line, but its
    # distinctive tokens (приватную, сеть, VPC) do not.
    body_content = "Доступ к бакету по протоколу HTTPS."
    state = _make_state(_artefacts(raw_body=raw_body, body_content=body_content))
    out = assemble_plan_node(state)
    body = out["artefacts"]["plan"]["slides"][0]["slots"]["body"]
    assert "приватную сеть" in body or "VPC" in body
    non_empty = [ln for ln in body.split("\n") if ln.strip()]
    assert len(non_empty) == 2


def test_rephrase_merge_produces_no_duplication(monkeypatch) -> None:
    """CRITICAL 2 — legitimate rephrase/merge must NOT be re-appended.

    The distributor compresses two brief lines into one shorter rephrased
    line with low surface-word overlap. The originals must NOT be appended
    (no duplicate/redundant content), even though raw word-overlap is low.
    """
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)
    raw_body = [
        "Пользовательский домен привязанный к бакету\n"
        "Сертификат выпускается автоматически системой"
    ]
    # One rephrased/merged line, surface overlap with each original is low.
    body_content = "Поддержка кастомных доменов и автоматических SSL для бакетов."
    state = _make_state(_artefacts(raw_body=raw_body, body_content=body_content))
    out = assemble_plan_node(state)
    body = out["artefacts"]["plan"]["slides"][0]["slots"]["body"]
    # The rephrased line stands alone — no original verbatim re-appended.
    assert "Пользовательский домен привязанный" not in body
    assert "Сертификат выпускается автоматически" not in body
    assert body == body_content


def test_split_part_slide_is_skipped(monkeypatch) -> None:
    """CRITICAL 1 — split-brief fragments must be skipped.

    A classification slide carrying ``_split_part`` is a fragment of a
    brief slide whose body is divided across multiple deck slides. Per-part
    recovery is unsafe (we can't tell which fragment owns which brief line),
    so recovery must not run — body stays exactly as distributed.
    """
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)
    raw_body = ["Линия А\nЛиния Б\nЛиния В"]
    body_content = "Линия А."
    state = _make_state(_artefacts(
        raw_body=raw_body, body_content=body_content,
        cls_extra={"_split_part": 1, "_source_slide": 5},
    ))
    out = assemble_plan_node(state)
    body = out["artefacts"]["plan"]["slides"][0]["slots"]["body"]
    assert body == "Линия А."


def test_post_split_renumber_keys_off_source_slide(monkeypatch) -> None:
    """CRITICAL 1 — non-split slides key off ``_source_slide``.

    After an earlier split renumbered downstream slides, the deck ``num``
    no longer matches the brief ``num``. Recovery must look up the brief by
    ``_source_slide`` (the original brief num), NOT the shifted deck num —
    otherwise we'd compare against the wrong brief slide and could append a
    FOREIGN brief line (contamination).
    """
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)
    # Deck slide num=6 (shifted), but it maps back to brief slide num=5.
    raw_body = [
        "Уникальная фраза один альфа\nУникальная фраза два бета"
    ]
    body_content = "Уникальная фраза один альфа."
    state = _make_state(_artefacts(
        raw_body=raw_body, body_content=body_content,
        num=6, brief_num=5,
        cls_extra={"_source_slide": 5},
    ))
    out = assemble_plan_node(state)
    body = out["artefacts"]["plan"]["slides"][0]["slots"]["body"]
    # The genuinely-dropped second line (looked up via _source_slide=5) is
    # recovered — proving the lookup keyed off _source_slide, not num=6.
    assert "два бета" in body
    non_empty = [ln for ln in body.split("\n") if ln.strip()]
    assert len(non_empty) == 2


def test_no_foreign_contamination_when_source_slide_absent(monkeypatch) -> None:
    """CRITICAL 1 — guard: if the keyed brief slide has no body, nothing is
    appended (no foreign content pulled from a mis-keyed slide)."""
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)
    # Brief slide num=5 exists but the deck slide maps to a brief num (99)
    # that has no entry → empty brief body → no recovery, no contamination.
    raw_body = ["Эта линия принадлежит слайду 5"]
    body_content = "Совершенно другой контент."
    state = _make_state(_artefacts(
        raw_body=raw_body, body_content=body_content,
        num=6, brief_num=5,
        cls_extra={"_source_slide": 99},
    ))
    out = assemble_plan_node(state)
    body = out["artefacts"]["plan"]["slides"][0]["slots"]["body"]
    assert body == "Совершенно другой контент."
    assert "принадлежит слайду 5" not in body


# ── Task 4: title-duplicate-in-body filter ─────────────────────────────────


def test_recovered_line_equal_to_title_is_dropped(monkeypatch) -> None:
    """Task 4 (a) — a genuinely-dropped brief line whose NORMALIZED text
    equals the slide title must NOT be recovered into the body (it would
    duplicate the title as a trailing bullet).

    Brief has 2 lines: a distinctive one (kept → anchor) and a heading line
    that equals the title. The distributor dropped the heading line; without
    the filter, recovery would re-append it under the body → title shown
    twice. The title-equality filter must drop it.
    """
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)
    raw_body = [
        "Уникальная мысль про кластеры регионы\n"
        "Резервное копирование данных"
    ]
    # Distributor kept ONLY the distinctive line (the heading line, which
    # equals the title, was dropped).
    body_content = "Уникальная мысль про кластеры регионы."
    title_content = "Резервное копирование данных"
    state = _make_state(_artefacts(
        raw_body=raw_body, body_content=body_content,
        title_content=title_content,
    ))
    out = assemble_plan_node(state)
    slots = out["artefacts"]["plan"]["slides"][0]["slots"]
    body = slots["body"]
    # The title-equal line must NOT have been re-appended to the body.
    assert "Резервное копирование данных" not in body
    # The kept anchor line is untouched.
    assert body == "Уникальная мысль про кластеры регионы."


def test_distinct_dropped_line_kept_when_title_differs(monkeypatch) -> None:
    """Task 4 (b) — no false drop: a genuinely-dropped brief line that does
    NOT equal the title is still recovered. Proves the filter is full-equality
    against the title, not an over-broad gate that suppresses real content."""
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)
    raw_body = [
        "Уникальная мысль про кластеры регионы\n"
        "Резервное копирование данных"
    ]
    body_content = "Уникальная мысль про кластеры регионы."
    title_content = "Совсем другой заголовок слайда"
    state = _make_state(_artefacts(
        raw_body=raw_body, body_content=body_content,
        title_content=title_content,
    ))
    out = assemble_plan_node(state)
    body = out["artefacts"]["plan"]["slides"][0]["slots"]["body"]
    # The dropped line differs from the title → recovered as normal.
    assert "Резервное копирование данных" in body
    non_empty = [ln for ln in body.split("\n") if ln.strip()]
    assert len(non_empty) == 2
