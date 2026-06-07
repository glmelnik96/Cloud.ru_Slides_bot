"""Task 2 (2026-06-07): whole-slide loss guard in classify_node.

Root cause: the LLM classifier can split a brief slide and mis-renumber, so a
whole brief slide silently vanishes from the classification output. There is no
deterministic check that every brief slide ``num`` is represented.

``_recover_dropped_slides`` is a post-classification guard: every brief slide
``num`` must be represented by >=1 classification slide whose ``_source_slide``
(or ``num``) maps to it. Unrepresented brief slides get a recovery slide built
from that brief slide's content:
  * table intent -> ``table_native``,
  * else -> card_grid (>=3 structured items) or a plain text/multicolumn slide.
"""
from __future__ import annotations

from graph.nodes.agents import _recover_dropped_slides


def _cls(slides):
    return {"slides": slides}


def test_missing_source_slide_gets_recovery_slide():
    """(a) N brief slides, one source slide unrepresented -> guard injects it."""
    brief = {"slides": [
        {"num": 1, "raw_title": "Заголовок", "raw_body": ["intro"], "intent": "text"},
        {"num": 2, "raw_title": "Контент", "raw_body": ["body two"], "intent": "text"},
        {"num": 3, "raw_title": "Итоги", "raw_body": ["wrap"], "intent": "text"},
    ]}
    # Classification dropped brief slide 2 entirely.
    cls = _cls([
        {"num": 1, "category": "title"},
        {"num": 3, "category": "text"},
    ])
    recovered = _recover_dropped_slides(cls, brief)
    assert recovered == [2]
    nums = [s["num"] for s in cls["slides"]]
    assert 2 in nums
    rec = next(s for s in cls["slides"] if s["num"] == 2)
    assert rec["_source_slide"] == 2
    # plain text body -> donor-route text slide, no native type, content preserved.
    assert rec.get("slide_type") is None
    assert rec["category"] == "text"


def test_no_injection_when_all_represented():
    """(b) every brief slide represented -> no false injection."""
    brief = {"slides": [
        {"num": 1, "raw_title": "A", "raw_body": ["a"], "intent": "text"},
        {"num": 2, "raw_title": "B", "raw_body": ["b"], "intent": "text"},
    ]}
    cls = _cls([
        {"num": 1, "category": "title"},
        {"num": 2, "category": "text"},
    ])
    before = len(cls["slides"])
    recovered = _recover_dropped_slides(cls, brief)
    assert recovered == []
    assert len(cls["slides"]) == before


def test_split_parts_credit_their_source_slide():
    """(c) a 3->(3,4) split where both parts carry _source_slide=3.

    Brief slide 3 is represented (both split parts credit it); brief slide 4
    is NOT represented by any slide -> only slide 4 needs recovery.
    """
    brief = {"slides": [
        {"num": 3, "raw_title": "Архитектура", "raw_body": ["arch"], "intent": "text"},
        {"num": 4, "raw_title": "DNS Resolvers", "raw_body": ["8.8.8.8", "1.1.1.1"],
         "intent": "table"},
    ]}
    cls = _cls([
        {"num": 3, "category": "text", "_source_slide": 3, "_split_part": "a"},
        {"num": 4, "category": "text", "_source_slide": 3, "_split_part": "b"},
    ])
    recovered = _recover_dropped_slides(cls, brief)
    # Brief 3 represented by the split parts; brief 4 dropped -> recovered.
    assert recovered == [4]
    rec = next(s for s in cls["slides"] if s.get("_source_slide") == 4)
    # table intent -> table_native with a valid table block.
    assert rec["slide_type"] == "table_native"
    assert rec["category"] == "table"
    assert rec["table"]["headers"]
    assert rec["table"]["data"]


def test_structured_body_recovers_as_card_grid():
    """A dropped slide with >=3 card-shaped body items -> card_grid native."""
    brief = {"slides": [
        {"num": 1, "raw_title": "T", "raw_body": ["a"], "intent": "text"},
        {"num": 2, "raw_title": "Преимущества", "intent": "text",
         "raw_body": [
             "Скорость — мгновенный отклик",
             "Цена — выгодные тарифы",
             "Поддержка — режим 24/7",
         ]},
    ]}
    cls = _cls([{"num": 1, "category": "title"}])
    recovered = _recover_dropped_slides(cls, brief)
    assert recovered == [2]
    rec = next(s for s in cls["slides"] if s["num"] == 2)
    assert rec["slide_type"] == "flow_diagram_native"
    assert rec["flow"]["preset"] == "card_grid"
    assert [c["title"] for c in rec["flow"]["cards"]] == [
        "Скорость", "Цена", "Поддержка"]
