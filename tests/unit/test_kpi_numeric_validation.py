"""Task 1: KPI integrity — numeric validation + demotion.

``_coerce_overflow_kpis`` now runs a deterministic numeric guard over the
LLM's KPI pairing (the model has no deterministic pairing algorithm and once
rendered the word "Прогноз" as a giant number):

  (a) a KPI ``value`` with NO digit is dropped (e.g. "Прогноз");
  (b) 0 valid numbers left → DEMOTE off ``kpi_native`` (content not lost as
      garbage — routed to a text/multicolumn slide);
  (c) >3 valid numbers → DEMOTE to ``card_grid`` preserving ALL number+label
      pairs (never silently ``nums[:3]`` — that drops money sums);
  (d) <=3 valid numeric numbers → unchanged.
"""
from __future__ import annotations

from graph.nodes.agents import _coerce_overflow_kpis, _kpi_value_has_digit


def _cls(numbers):
    return {"slides": [{
        "num": 1,
        "slide_type": "kpi_native",
        "category": "multicolumn",
        "kpi": {"title": "Итоги", "numbers": numbers},
        "chart": None, "table": None, "flow": None, "image": None,
    }]}


# --- digit detection -------------------------------------------------------

def test_value_has_digit_helper():
    assert _kpi_value_has_digit("84")
    assert _kpi_value_has_digit("1 200 руб")
    assert _kpi_value_has_digit("15%")
    assert _kpi_value_has_digit("+3,5 п.п.")
    assert not _kpi_value_has_digit("Прогноз")
    assert not _kpi_value_has_digit("")
    assert not _kpi_value_has_digit("—")


# --- (a) non-numeric value dropped ----------------------------------------

def test_non_numeric_value_dropped():
    cls = _cls([
        {"value": "84", "desc": "вовлечённость", "pct": True},
        {"value": "Прогноз", "desc": "на 2026 год"},
        {"value": "12", "desc": "инициатив"},
    ])
    touched = _coerce_overflow_kpis(cls)
    s = cls["slides"][0]
    assert touched == 1
    assert s["slide_type"] == "kpi_native"  # 2 valid remain → still kpi
    vals = [n["value"] for n in s["kpi"]["numbers"]]
    assert vals == ["84", "12"]  # "Прогноз" dropped, order preserved


# --- (b) 0 valid → demoted -------------------------------------------------

def test_zero_valid_demoted_off_kpi():
    cls = _cls([
        {"value": "Прогноз", "desc": "на 2026 год"},
        {"value": "—", "desc": "нет данных"},
    ])
    touched = _coerce_overflow_kpis(cls)
    s = cls["slides"][0]
    assert touched == 1
    assert s["slide_type"] is None  # demoted off kpi_native
    assert s["kpi"] is None
    assert s["category"] == "multicolumn"  # safe text fallback (body from brief)


# --- (c) >3 valid → demoted preserving ALL pairs ---------------------------

def test_more_than_three_valid_demoted_preserving_all_pairs():
    cls = _cls([
        {"value": "1 200 000 руб", "desc": "выручка"},
        {"value": "850 000 руб", "desc": "затраты"},
        {"value": "350 000 руб", "desc": "прибыль"},
        {"value": "29%", "desc": "маржа"},
        {"value": "12", "desc": "сделок"},
    ])
    touched = _coerce_overflow_kpis(cls)
    s = cls["slides"][0]
    assert touched == 1
    # NOT silently truncated to nums[:3]; demoted to card_grid.
    assert s["slide_type"] == "flow_diagram_native"
    assert s["category"] == "other"
    assert s["kpi"] is None
    cards = s["flow"]["cards"]
    assert len(cards) == 5  # ALL pairs preserved — no money sum lost
    assert cards[0] == {"title": "1 200 000 руб", "text": "выручка"}
    assert cards[3] == {"title": "29%", "text": "маржа"}
    assert s["flow"]["preset"] == "card_grid"


def test_more_than_three_after_dropping_non_numeric_demoted():
    # 5 entries, one non-numeric → 4 valid → still >3 → demote, 4 cards.
    cls = _cls([
        {"value": "100 руб", "desc": "a"},
        {"value": "Прогноз", "desc": "skip"},
        {"value": "200 руб", "desc": "b"},
        {"value": "300 руб", "desc": "c"},
        {"value": "400 руб", "desc": "d"},
        {"value": "500 руб", "desc": "e"},
    ])
    touched = _coerce_overflow_kpis(cls)
    s = cls["slides"][0]
    assert touched == 1
    assert s["slide_type"] == "flow_diagram_native"
    cards = s["flow"]["cards"]
    assert len(cards) == 5  # the 5 numeric ones; "Прогноз" dropped
    assert [c["title"] for c in cards] == [
        "100 руб", "200 руб", "300 руб", "400 руб", "500 руб"]


# --- (d) <=3 valid numeric → unchanged ------------------------------------

def test_three_valid_unchanged():
    numbers = [
        {"value": "84", "desc": "a", "pct": True},
        {"value": "12", "desc": "b"},
        {"value": "5", "desc": "c", "accent": True},
    ]
    cls = _cls([dict(n) for n in numbers])
    touched = _coerce_overflow_kpis(cls)
    s = cls["slides"][0]
    assert touched == 0
    assert s["slide_type"] == "kpi_native"
    assert s["kpi"]["numbers"] == numbers


def test_one_valid_unchanged():
    cls = _cls([{"value": "99%", "desc": "uptime"}])
    assert _coerce_overflow_kpis(cls) == 0
    assert cls["slides"][0]["slide_type"] == "kpi_native"
    assert len(cls["slides"][0]["kpi"]["numbers"]) == 1


def test_non_kpi_slides_untouched():
    cls = {"slides": [{"num": 1, "slide_type": "table_native",
                       "kpi": None, "table": {"headers": ["a"]}}]}
    assert _coerce_overflow_kpis(cls) == 0
