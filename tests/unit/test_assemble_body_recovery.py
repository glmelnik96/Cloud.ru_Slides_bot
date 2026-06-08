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
    """Task 4 (b) — no false drop: a genuinely-dropped brief line whose
    significant-word overlap with the title is below ``_COVERAGE_THRESHOLD``
    is still recovered. Proves the non-body coverage gate only suppresses
    lines already represented in a non-body slot, not real distinct content."""
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


# ── Task A: non-body coverage suppression + timeline-donor skip ────────────


def _multicolumn_artefacts(
    *,
    raw_body: list[str],
    body_slots: dict[str, str],
    header_slots: dict[str, str],
    title_content: str,
    num: int = 9,
    donor: int = 33,
) -> dict[str, Any]:
    """Multi-section "multicolumn" donor bundle (mirrors live donor 33/34).

    ``body_slots`` are BODY-type slots (bodyN), ``header_slots`` are the
    NON-body section-header placeholders (subN, ooxml OTHER). The fixture
    builds placeholder_assignments keyed by ph_idx using the donor's real
    slot_name_by_ph_idx map so assemble_plan_node translates them back to the
    canonical slot names (title/bodyN/subN).
    """
    from graph import donor_map

    name_to_ph = {
        name: ph for ph, name in donor_map.slot_name_by_ph_idx(donor).items()
    }
    phs: list[dict[str, Any]] = []
    title_ph = name_to_ph.get("title", 0)
    phs.append({"ph_idx": title_ph, "content": title_content, "ph_type": "TITLE"})
    for name, content in body_slots.items():
        phs.append({"ph_idx": name_to_ph[name], "content": content, "ph_type": "BODY"})
    for name, content in header_slots.items():
        phs.append({"ph_idx": name_to_ph[name], "content": content, "ph_type": "BODY"})
    return {
        "brief": {
            "topic": "Deck",
            "slide_count": 1,
            "slides": [{"num": num, "raw_title": title_content, "raw_body": raw_body}],
        },
        "classification": {"slides": [{
            "num": num, "category": "text",
            "subcategory_hint": "", "rationale": "",
        }]},
        "layouts": {"slides": [{"num": num, "layout_idx": donor}]},
        "content": {"slides": [{"slide_num": num, "placeholder_assignments": phs}]},
        "infographics": {"slides": []},
        "icons": {"slides": []},
    }


def test_section_headings_in_nonbody_slots_not_recovered(monkeypatch) -> None:
    """Task A Fix 1 — multi-section slide (deck3 slide 9 reproduction).

    The slide's own section headings live in NON-body header slots (subN,
    ooxml OTHER) and a title-variant lives in the title slot. They appear in
    the brief body too. The distributor correctly placed them in the header
    slots, so they show as "uncovered" against the BODY slots and the old
    recovery dumped them into the last body slot, overflowing the slide.

    The non-body coverage gate must suppress them: only a genuinely-dropped
    body line (absent from EVERY slot) may be recovered.
    """
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)
    raw_body = [
        "Галлюцинации LLM, низкая точность\n"
        "ТЕХНОЛОГИЧЕСКИЕ\n"
        "ОРГАНИЗАЦИОННЫЕ\n"
        "РЕГУЛЯТОРНЫЕ\n"
        "Барьеры применения ИИ-агентов на предприятии\n"
        "Совершенно потерянная уникальная строка контента"
    ]
    # Distributor placed only the one body line it kept; the other body slots
    # are empty (distributed body line-count < brief line-count → recovery is
    # NOT fast-gated out, so the suppression gate is genuinely exercised).
    body_slots = {
        "body1": "Галлюцинации LLM, низкая точность.",
        "body2": "",
        "body3": "",
        "body4": "",
        "body5": "",
        "body6": "",
    }
    header_slots = {
        "sub1": "ТЕХНОЛОГИЧЕСКИЕ",
        "sub2": "ОРГАНИЗАЦИОННЫЕ",
        "sub3": "РЕГУЛЯТОРНЫЕ",
        "sub4": "ЭКОНОМИЧЕСКИЕ",
        "sub5": "РИСКИ ДАННЫХ",
        "sub6": "УПРАВЛЕНЧЕСКИЕ",
    }
    state = _make_state(_multicolumn_artefacts(
        raw_body=raw_body,
        body_slots=body_slots,
        header_slots=header_slots,
        title_content="Барьеры применения ИИ-агентов",
    ))
    out = assemble_plan_node(state)
    slots = out["artefacts"]["plan"]["slides"][0]["slots"]
    last_body = slots["body6"]
    # Section headings (in subN slots) must NOT leak into the last body slot.
    assert "ТЕХНОЛОГИЧЕСКИЕ" not in last_body
    assert "ОРГАНИЗАЦИОННЫЕ" not in last_body
    assert "РЕГУЛЯТОРНЫЕ" not in last_body
    # The title-variant (overlaps the title slot) must NOT leak either.
    assert "Барьеры применения" not in last_body
    # The genuinely-dropped content line (absent from EVERY slot) IS recovered.
    assert "Совершенно потерянная уникальная строка контента" in last_body


def test_title_superset_body_line_not_recovered(monkeypatch) -> None:
    """Task A — title-VARIANT superset leak (deck3 slide 12 reproduction).

    The slide title is short ("ТРЕБОВАНИЯ ДЛЯ УСПЕШНОГО ЗАПУСКА", ~4 sig
    words). The brief carries a longer body bullet that is a SUPERSET of the
    title — the same title words plus extra trailing words ("...ПРОДУКТОВ,
    ИСПОЛЬЗУЮЩИХ ТЕХНОЛОГИИ ИИ-АГЕНТОВ", ~9 sig words).

    The candidate-denominator non-body gate computes |title ∩ candidate| /
    |candidate| = 4/9 ≈ 0.44 < threshold, so the superset bullet slips
    through and overflows the last body column. The symmetric non-body subset
    check (|candidate ∩ title| / |title| = 4/4 = 1.0 ≥ threshold) must
    suppress it.
    """
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)
    raw_body = [
        "Стабильная инфраструктура и зрелые процессы команды\n"
        "ТРЕБОВАНИЯ ДЛЯ УСПЕШНОГО ЗАПУСКА ПРОДУКТОВ, "
        "ИСПОЛЬЗУЮЩИХ ТЕХНОЛОГИИ ИИ-АГЕНТОВ"
    ]
    # Distributor kept ONLY the distinctive first line (anchor); the title-
    # superset line shows as "uncovered" against the body slots.
    body_slots = {
        "body1": "Стабильная инфраструктура и зрелые процессы команды.",
        "body2": "",
        "body3": "",
        "body4": "",
        "body5": "",
        "body6": "",
    }
    state = _make_state(_multicolumn_artefacts(
        raw_body=raw_body,
        body_slots=body_slots,
        header_slots={},
        title_content="ТРЕБОВАНИЯ ДЛЯ УСПЕШНОГО ЗАПУСКА",
    ))
    out = assemble_plan_node(state)
    slots = out["artefacts"]["plan"]["slides"][0]["slots"]
    last_body = slots["body6"]
    # The title-superset bullet must NOT leak into the last body slot.
    assert "ПРОДУКТОВ" not in last_body
    assert "ИИ-АГЕНТОВ" not in last_body
    assert "ТРЕБОВАНИЯ ДЛЯ УСПЕШНОГО ЗАПУСКА" not in last_body


# ── Part 1: recovery append cap (off-slide / cross-slide bleed guard) ──────


def _two_column_artefacts(
    *,
    raw_body: list[str],
    col1_body: str,
    col2_body: str,
    num: int = 5,
    donor: int = 28,
    title_content: str = "ДЕЙСТВИЯ В ОФИСЕ",
) -> dict[str, Any]:
    """Donor 28 = title(shape_idx 0) + col1_body(1) + col2_body(2), each
    column ``max_chars: 250`` (see donor-slot-map.yaml). Builds the
    placeholder_assignments keyed by the donor's real ph_idx map so
    assemble_plan_node translates them to col1_body/col2_body.
    """
    from graph import donor_map

    name_to_ph = {
        name: ph for ph, name in donor_map.slot_name_by_ph_idx(donor).items()
    }
    phs = [
        {"ph_idx": name_to_ph["title"], "content": title_content, "ph_type": "TITLE"},
        {"ph_idx": name_to_ph["col1_body"], "content": col1_body, "ph_type": "BODY"},
        {"ph_idx": name_to_ph["col2_body"], "content": col2_body, "ph_type": "BODY"},
    ]
    return {
        "brief": {
            "topic": "Deck",
            "slide_count": 1,
            "slides": [{"num": num, "raw_title": title_content, "raw_body": raw_body}],
        },
        "classification": {"slides": [{
            "num": num, "category": "text",
            "subcategory_hint": "", "rationale": "",
        }]},
        "layouts": {"slides": [{"num": num, "layout_idx": donor}]},
        "content": {"slides": [{"slide_num": num, "placeholder_assignments": phs}]},
        "infographics": {"slides": []},
        "icons": {"slides": []},
    }


def test_pathological_recovery_is_capped_to_budget(monkeypatch) -> None:
    """Part 1 — the ДЕЙСТВИЯ В ОФИСЕ reproduction.

    A near-duplicate-heavy source slide yields a brief with MANY long
    distinctive body lines. The distributor kept only one short anchor line,
    so every other brief line shows as "uncovered" and recovery would dump a
    huge wall of text into the last column (col2_body) — off-slide overflow.

    The cap must bound how much is appended: the resulting col2_body stays
    within the character budget (donor col ``max_chars`` 250, plus a small
    slack), only a SUBSET of the dropped lines is kept, and the rest are
    dropped. Earlier-appearing lines win.
    """
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)
    long_lines = [
        f"Уникальная распоряжение номер {i} с подробным описанием действий "
        f"сотрудника в офисном помещении при чрезвычайной ситуации сценарий {i}"
        for i in range(1, 11)
    ]
    raw_body = ["Короткий якорный пункт\n" + "\n".join(long_lines)]
    # Distributor kept ONLY the short anchor in col1; col2 is empty.
    col1_body = "Короткий якорный пункт."
    col2_body = ""
    state = _make_state(_two_column_artefacts(
        raw_body=raw_body, col1_body=col1_body, col2_body=col2_body,
    ))
    out = assemble_plan_node(state)
    slots = out["artefacts"]["plan"]["slides"][0]["slots"]
    last = slots["col2_body"]
    # Bounded: never an off-slide wall. Budget = donor max_chars (250) plus a
    # small slack for line joins.
    assert len(last) <= 300, f"col2_body length {len(last)} exceeded budget"
    # A subset was kept (not all 10 long lines).
    kept = [ln for ln in last.split("\n") if ln.strip()]
    assert 0 < len(kept) < 10
    # Earliest lines win the budget.
    assert "сценарий 1" in last


def test_dangling_heading_fragment_not_recovered(monkeypatch) -> None:
    """Part 1b — cross-slide heading-fragment bleed (deck3 slide 2 repro).

    A foreign slide's title ("ПАМЯТКА ПО ДЕЙСТВИЯМ РАБОТНИКОВ, ПОСЛЕ
    ОКОНЧАНИЯ ОБСТРЕЛА...") was split at the comma; its first half — a
    dangling fragment ending in a comma — leaked into this slide's brief
    body. It is genuinely "uncovered" against the distributed body and is
    not represented in this slide's own non-body slots (it belongs to a
    DIFFERENT slide), so the existing gates miss it and the cap kept it as
    the single recovered line → an ALL-CAPS heading bled into the last
    column.

    A complete body bullet never ends with a trailing comma/colon/dash, so
    such dangling fragments must be suppressed from recovery.
    """
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)
    raw_body = [
        "Короткий якорный пункт колонки\n"
        "ПАМЯТКА ПО ДЕЙСТВИЯМ РАБОТНИКОВ,\n"
        "Полноценный потерянный пункт про укрытие в подвале"
    ]
    col1_body = "Короткий якорный пункт колонки."
    col2_body = ""
    state = _make_state(_two_column_artefacts(
        raw_body=raw_body, col1_body=col1_body, col2_body=col2_body,
    ))
    out = assemble_plan_node(state)
    slots = out["artefacts"]["plan"]["slides"][0]["slots"]
    last = slots["col2_body"]
    # The dangling comma-terminated heading fragment must NOT be recovered.
    assert "ПАМЯТКА ПО ДЕЙСТВИЯМ РАБОТНИКОВ" not in last
    # The genuinely-dropped COMPLETE line is still recovered.
    assert "Полноценный потерянный пункт про укрытие" in last


def test_allcaps_slogan_banner_not_recovered(monkeypatch) -> None:
    """FIX7 — all-caps slogan/banner bleed (deck2/Памятки s2 repro).

    The source civil-defense памятка repeats a document banner at the top of
    every page: «ПАМЯТКА ПО ДЕЙСТВИЯМ РАБОТНИКОВ, ПО СИГНАЛУ «ВНИМАНИЕ ВСЕМ!
    ВОЗДУШНАЯ ТРЕВОГА!»». The comma-terminated first half is caught by the
    dangling-fragment gate (FIX5), but the second half is a complete-looking
    ALL-CAPS slogan ending in «!»» — it does NOT end in a dangling connector
    and is uncovered against the distributed body, so it leaked into the last
    column on slides 1 and 2.

    A multi-word ALL-CAPS slogan/banner is a document heading, never a body
    bullet, and must be suppressed from recovery. Mixed-case body bullets are
    unaffected.
    """
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)
    raw_body = [
        "Короткий якорный пункт колонки\n"
        "ПО СИГНАЛУ «ВНИМАНИЕ ВСЕМ! ВОЗДУШНАЯ ТРЕВОГА!»\n"
        "Полноценный потерянный пункт про укрытие в подвале"
    ]
    col1_body = "Короткий якорный пункт колонки."
    col2_body = ""
    state = _make_state(_two_column_artefacts(
        raw_body=raw_body, col1_body=col1_body, col2_body=col2_body,
    ))
    out = assemble_plan_node(state)
    slots = out["artefacts"]["plan"]["slides"][0]["slots"]
    last = slots["col2_body"]
    # The all-caps slogan banner must NOT be recovered into the column.
    assert "ВОЗДУШНАЯ ТРЕВОГА" not in last
    assert "ВНИМАНИЕ ВСЕМ" not in last
    # The genuinely-dropped COMPLETE (mixed-case) line is still recovered.
    assert "Полноценный потерянный пункт про укрытие" in last


def test_normal_small_recovery_unchanged_by_cap(monkeypatch) -> None:
    """Part 1 — the cap must NOT bite on the normal case: a couple of
    genuinely-dropped short lines are still fully recovered (regression
    guard that the budget is generous for ordinary slides)."""
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)
    raw_body = [
        "Первый якорный распознаваемый пункт колонки\n"
        "Второй потерянный короткий пункт\n"
        "Третий потерянный короткий пункт"
    ]
    # Distributor kept only the anchor; two short lines genuinely dropped.
    col1_body = "Первый якорный распознаваемый пункт колонки."
    col2_body = ""
    state = _make_state(_two_column_artefacts(
        raw_body=raw_body, col1_body=col1_body, col2_body=col2_body,
    ))
    out = assemble_plan_node(state)
    slots = out["artefacts"]["plan"]["slides"][0]["slots"]
    last = slots["col2_body"]
    assert "Второй потерянный короткий пункт" in last
    assert "Третий потерянный короткий пункт" in last


def test_timeline_donor_recovery_is_skipped(monkeypatch) -> None:
    """Task A Fix 2 — timeline donors have fixed-capacity stepN_body slots;
    appending recovered overflow into "the last body slot" is semantically
    wrong and overflows the slide (deck1 slide 7, donor 60).

    Recovery must be skipped entirely when the slide clones a timeline donor,
    even if a brief body line looks genuinely dropped.
    """
    monkeypatch.setattr("worker.progress.publish", lambda _ev: None)
    from graph import donor_map

    # Sanity: donor 60 is a real timeline donor (no monkeypatch needed).
    assert donor_map.is_timeline_donor(60) is True

    # Use the single-body-slot donor-21 fixture shape but point it at the
    # timeline donor by monkeypatching is_timeline_donor for the donor we use,
    # so the slot map / body-slot logic is exercised exactly as in production.
    raw_body = [
        "Запуск пилота в первом квартале\n"
        "Совершенно отдельный потерянный пункт"
    ]
    body_content = "Запуск пилота в первом квартале."
    state = _make_state(_artefacts(raw_body=raw_body, body_content=body_content))
    # Mark donor 21 as a timeline donor for this test only.
    monkeypatch.setattr(
        "graph.donor_map.is_timeline_donor",
        lambda d: int(d) == 21,
    )
    out = assemble_plan_node(state)
    body = out["artefacts"]["plan"]["slides"][0]["slots"]["body"]
    # Recovery skipped → body untouched, the "dropped" line NOT appended.
    assert body == "Запуск пилота в первом квартале."
    assert "Совершенно отдельный потерянный пункт" not in body
