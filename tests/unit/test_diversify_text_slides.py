"""F (2026-06-07): deterministic layout-diversity post-pass.

Taxonomy defect F: most content slides render as a flat "title + big text
block" donor instead of a richer archetype. ``_diversify_text_slides``
promotes a flat text/multicolumn slide whose brief body is a parallel list of
>=3 short, card-shaped items into a ``card_grid`` flow native. Prose bodies
(few long paragraphs) stay on the donor route. High precision by design.
"""
from __future__ import annotations

from graph.nodes.agents import _card_from_body_item, _diversify_text_slides


def _cls(slides):
    return {"slides": slides}


def test_labelled_list_becomes_card_grid():
    brief = {"slides": [{"num": 4, "raw_title": "Преимущества",
                         "raw_body": [
                             "Масштабируемость — рост до тысяч ядер",
                             "Тарификация — оплата за использование",
                             "Поддержка — режим 24/7 с SLA",
                         ]}]}
    cls = _cls([{"num": 4, "slide_type": None, "category": "text",
                 "kpi": None, "chart": None, "table": None, "flow": None}])
    n = _diversify_text_slides(cls, brief)
    assert n == 1
    s = cls["slides"][0]
    assert s["slide_type"] == "flow_diagram_native"
    assert s["category"] == "other"
    assert s["flow"]["preset"] == "card_grid"
    titles = [c["title"] for c in s["flow"]["cards"]]
    assert titles == ["Масштабируемость", "Тарификация", "Поддержка"]
    assert s["flow"]["cards"][0]["text"] == "рост до тысяч ядер"
    assert s["flow"]["cols"] == 2


def test_short_unlabelled_list_becomes_card_grid():
    brief = {"slides": [{"num": 2, "raw_title": "Сервисы",
                         "raw_body": ["Compute", "Storage", "Network", "Security"]}]}
    cls = _cls([{"num": 2, "slide_type": None, "category": "multicolumn"}])
    n = _diversify_text_slides(cls, brief)
    assert n == 1
    s = cls["slides"][0]
    assert [c["title"] for c in s["flow"]["cards"]] == [
        "Compute", "Storage", "Network", "Security"]
    assert s["flow"]["cols"] == 2  # 4 cards -> 2 cols


def test_prose_body_left_on_donor_route():
    long = (
        "Платформа показала уверенный рост по всем ключевым направлениям и "
        "вышла на плановые объёмы за отчётный период, число клиентов выросло"
    )
    brief = {"slides": [{"num": 5, "raw_title": "Итоги",
                         "raw_body": [long, long, long]}]}
    cls = _cls([{"num": 5, "slide_type": None, "category": "text"}])
    n = _diversify_text_slides(cls, brief)
    assert n == 0
    assert cls["slides"][0]["slide_type"] is None


def test_too_few_items_left_alone():
    brief = {"slides": [{"num": 6, "raw_title": "Вывод",
                         "raw_body": ["Один пункт", "Второй пункт"]}]}
    cls = _cls([{"num": 6, "slide_type": None, "category": "text"}])
    assert _diversify_text_slides(cls, brief) == 0
    assert cls["slides"][0]["slide_type"] is None


def test_native_and_split_slides_never_touched():
    brief = {"slides": [
        {"num": 7, "raw_body": ["A — a", "B — b", "C — c"]},
        {"num": 8, "raw_body": ["D — d", "E — e", "F — f"]},
    ]}
    cls = _cls([
        {"num": 7, "slide_type": "kpi_native", "category": "text"},
        {"num": 8, "slide_type": None, "category": "text", "_split_part": "a"},
    ])
    assert _diversify_text_slides(cls, brief) == 0
    assert cls["slides"][0]["slide_type"] == "kpi_native"
    assert cls["slides"][1]["slide_type"] is None


def test_more_than_eight_items_not_a_grid():
    brief = {"slides": [{"num": 9, "raw_title": "Список",
                         "raw_body": [f"Пункт {i}" for i in range(9)]}]}
    cls = _cls([{"num": 9, "slide_type": None, "category": "text"}])
    assert _diversify_text_slides(cls, brief) == 0


def test_six_cards_gets_three_columns():
    brief = {"slides": [{"num": 10, "raw_title": "Шесть",
                         "raw_body": [f"K{i}: v{i}" for i in range(6)]}]}
    cls = _cls([{"num": 10, "slide_type": None, "category": "text"}])
    assert _diversify_text_slides(cls, brief) == 1
    assert cls["slides"][0]["flow"]["cols"] == 3


def test_marker_only_lines_dropped():
    assert _card_from_body_item("1.") is None
    assert _card_from_body_item("   ") is None
    card = _card_from_body_item("Роль: senior разработчик")
    assert card == {"title": "Роль", "text": "senior разработчик"}
