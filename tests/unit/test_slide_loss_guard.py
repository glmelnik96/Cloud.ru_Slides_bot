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
    # The recovery slide credits brief slide 2 via _source_slide, but gets a
    # FRESH deck num (max existing + 1) so it can't collide with a split part.
    rec = next(s for s in cls["slides"] if s.get("_source_slide") == 2)
    assert rec["num"] != 2
    nums = [s["num"] for s in cls["slides"]]
    assert len(nums) == len(set(nums)), f"duplicate deck nums: {nums}"
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
        {"num": 3, "category": "text", "_source_slide": 3, "_split_part": "1/2"},
        {"num": 4, "category": "text", "_source_slide": 3, "_split_part": "2/2"},
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
    # Fresh deck num — must NOT collide with the existing split part num=4.
    assert rec["num"] != 4
    nums = [s["num"] for s in cls["slides"]]
    assert len(nums) == len(set(nums)), f"duplicate deck nums: {nums}"


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


def test_dl1_split_collision_recovery_uses_fresh_num():
    """Regression: the exact dl1 blocker — split renumber + dropped brief slide.

    Brief slide 3 splits into deck nums 3 AND 4 (both ``_source_slide=3``), and
    brief slide 4 (the DNS table) is dropped. The naive guard reused the brief
    num as the recovery deck num, injecting ``num=4`` which COLLIDES with the
    existing split part already at ``num=4``. Downstream ``_by_num`` /
    ``cls_by_num`` lookups are last-wins keyed by ``num``, so the collision
    silently corrupts slide identity. The fix allocates a fresh deck num while
    keeping ``_source_slide`` = brief num.
    """
    brief = {"slides": [
        {"num": 1, "raw_title": "Титул", "raw_body": ["intro"], "intent": "text"},
        {"num": 2, "raw_title": "Обзор", "raw_body": ["overview"], "intent": "text"},
        {"num": 3, "raw_title": "Архитектура", "raw_body": ["arch"], "intent": "text"},
        {"num": 4, "raw_title": "DNS Resolvers",
         "raw_body": ["8.8.8.8 — Google", "1.1.1.1 — Cloudflare"], "intent": "table"},
    ]}
    # Classifier split brief 3 into deck nums 3 and 4 (in-place renumber) and
    # dropped brief 4 entirely.
    cls = _cls([
        {"num": 1, "category": "title"},
        {"num": 2, "category": "text"},
        {"num": 3, "category": "text", "_source_slide": 3, "_split_part": "1/2"},
        {"num": 4, "category": "text", "_source_slide": 3, "_split_part": "2/2"},
    ])

    # Snapshot the existing split part at num=4 to prove it's untouched.
    split_part_b = next(s for s in cls["slides"]
                        if s["num"] == 4 and s.get("_split_part") == "2/2")
    split_part_b_before = dict(split_part_b)

    recovered = _recover_dropped_slides(cls, brief)

    # (1) brief slide 4 recovered, keyed by its brief num via _source_slide.
    assert recovered == [4]
    rec = next(s for s in cls["slides"] if s.get("_source_slide") == 4)
    assert rec["category"] == "table"
    assert rec["slide_type"] == "table_native"

    # (2) ALL deck nums are unique after recovery — no collision.
    nums = [s["num"] for s in cls["slides"]]
    assert len(nums) == len(set(nums)), f"duplicate deck nums: {nums}"
    # Recovery slide got a fresh num past the existing max (4), i.e. 5.
    assert rec["num"] == 5

    # (3) the existing split-part num=4 is untouched.
    survivors = [s for s in cls["slides"]
                 if s["num"] == 4 and s.get("_split_part") == "2/2"]
    assert len(survivors) == 1
    assert survivors[0] == split_part_b_before
    assert survivors[0]["_source_slide"] == 3
