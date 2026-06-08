"""FIX8: card_grid card sanitisation in _sanitize_native_block.

A fragmentary heading-heavy source slide (deck2/Памятки s4) yields a
flow_diagram_native card_grid whose ``cards`` list carries degenerate
entries: an orphan "!" card (from a stray raw_body line), and empty cards.
These render as blank/garbage cards. Drop cards with no meaningful content
deterministically so only real cards survive; legitimate cards untouched.
"""
from __future__ import annotations

from graph.nodes.pipeline import _sanitize_native_block


def _flow(cards):
    return {"preset": "card_grid", "cards": cards, "cols": 3}


def test_orphan_punctuation_card_dropped():
    block = _flow([
        {"title": "!", "text": ""},
        {"title": "Порядок действий", "text": "Не торопитесь выходить"},
    ])
    out = _sanitize_native_block("flow_diagram_native", "flow", block)
    titles = [c["title"] for c in out["cards"]]
    assert "!" not in titles
    assert "Порядок действий" in titles
    assert len(out["cards"]) == 1


def test_empty_cards_dropped():
    block = _flow([
        {"title": "", "text": ""},
        {"title": "   ", "text": "  "},
        {"title": "Реальная карточка", "text": "С содержанием"},
    ])
    out = _sanitize_native_block("flow_diagram_native", "flow", block)
    assert len(out["cards"]) == 1
    assert out["cards"][0]["title"] == "Реальная карточка"


def test_card_with_digits_only_title_kept():
    # A card whose only "content" is a number (e.g. emergency line "112") is
    # meaningful — has alphanumeric content — and must NOT be dropped.
    block = _flow([
        {"title": "112", "text": ""},
        {"title": "...", "text": ""},
    ])
    out = _sanitize_native_block("flow_diagram_native", "flow", block)
    titles = [c["title"] for c in out["cards"]]
    assert "112" in titles
    assert "..." not in titles


def test_meaningful_content_in_text_keeps_card():
    block = _flow([
        {"title": "!", "text": "Реальное содержание карточки"},
    ])
    out = _sanitize_native_block("flow_diagram_native", "flow", block)
    assert len(out["cards"]) == 1


def test_all_real_cards_untouched():
    cards = [
        {"title": "Шаг 1", "text": "Описание шага один"},
        {"title": "Шаг 2", "text": "Описание шага два"},
        {"title": "Шаг 3", "text": "Описание шага три"},
    ]
    out = _sanitize_native_block("flow_diagram_native", "flow", _flow(list(cards)))
    assert out["cards"] == cards


def test_non_card_grid_preset_untouched():
    # numbered_rows preset (different data key) must not be touched by the
    # card cleanup — it carries no ``cards``.
    block = {"preset": "numbered_rows", "rows": [{"title": "!", "text": ""}]}
    out = _sanitize_native_block("flow_diagram_native", "flow", block)
    assert out["rows"] == [{"title": "!", "text": ""}]
