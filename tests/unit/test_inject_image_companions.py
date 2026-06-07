"""Task 3: companion text slide injection for image_native + substantial body.

Root cause: the ``image_native`` renderer never renders body text, and the LLM
only emits a companion text slide when the body is card-shaped. For slides like
OBS/CCE (<=2 sections of prose + a dominant image) the body is silently dropped
— the image shows, the prose is lost. ``_inject_image_companions`` is the
deterministic mirror of the companion the LLM already creates for the
CONFIG/IOTDM-style structured slides: when a slide is routed to ``image_native``
AND its brief body is substantial AND no sibling text/card slide already exists
for that ``_source_slide``, a companion slide carrying the body is injected
(``card_grid`` when card-shaped, else a plain text slide the distributor fills).
"""
from __future__ import annotations

from graph.nodes.agents import _inject_image_companions


def _cls(slides):
    return {"slides": slides}


def _image_native(num, src=None):
    s = {
        "num": num, "slide_type": "image_native", "category": "image",
        "image": {"title": "Скриншот", "image_path": "/tmp/x.png",
                  "caption": "", "subcategory": "diagram", "frame": None},
        "kpi": None, "chart": None, "table": None, "flow": None,
    }
    if src is not None:
        s["_source_slide"] = src
    return s


def test_substantial_prose_body_injects_plain_text_companion():
    """image_native + substantial prose body + no sibling → plain-text companion.

    The body is prose (not card-shaped), so the companion is a plain text slide
    with no slide_type — the distributor fills it from the brief by
    ``_source_slide``. A fresh deck num (max+1) is allocated, never the source.
    """
    brief = {"slides": [{"num": 4, "raw_title": "OBS обзор",
                         "raw_body": [
                             "OBS — это открытая платформа для записи и "
                             "стриминга, поддерживающая множество источников.",
                             "Конфигурация сцен и переходов выполняется через "
                             "удобный графический интерфейс приложения.",
                         ]}]}
    cls = _cls([_image_native(4, src=4)])
    n = _inject_image_companions(cls, brief)
    assert n == 1
    assert len(cls["slides"]) == 2
    comp = cls["slides"][-1]
    assert comp["_source_slide"] == 4
    assert comp["num"] == 5  # fresh num = max(4) + 1, NOT the source num
    assert comp["slide_type"] is None
    assert comp["category"] in ("text", "multicolumn")
    # image_native slide left untouched
    assert cls["slides"][0]["slide_type"] == "image_native"


def test_card_shaped_body_injects_card_grid_companion():
    """A card-shaped substantial body → companion is a card_grid flow native."""
    brief = {"slides": [{"num": 7, "raw_title": "Возможности",
                         "raw_body": [
                             "Запись — захват экрана в высоком качестве",
                             "Стриминг — трансляция на любые платформы",
                             "Сцены — гибкое переключение источников",
                         ]}]}
    cls = _cls([_image_native(7, src=7)])
    n = _inject_image_companions(cls, brief)
    assert n == 1
    comp = cls["slides"][-1]
    assert comp["slide_type"] == "flow_diagram_native"
    assert comp["flow"]["preset"] == "card_grid"
    assert [c["title"] for c in comp["flow"]["cards"]] == [
        "Запись", "Стриминг", "Сцены"]
    assert comp["num"] == 8


def test_trivial_body_no_companion():
    """image_native + trivial/caption-sized body → NO companion injected."""
    brief = {"slides": [{"num": 3, "raw_title": "Скриншот",
                         "raw_body": ["подпись один", "подпись два"]}]}
    cls = _cls([_image_native(3, src=3)])
    n = _inject_image_companions(cls, brief)
    assert n == 0
    assert len(cls["slides"]) == 1


def test_no_body_no_companion():
    brief = {"slides": [{"num": 3, "raw_title": "Скриншот", "raw_body": []}]}
    cls = _cls([_image_native(3, src=3)])
    assert _inject_image_companions(cls, brief) == 0
    assert len(cls["slides"]) == 1


def test_existing_sibling_text_slide_no_duplicate():
    """A sibling text slide already covers this _source_slide → NO companion.

    Mirrors the CONFIG/IOTDM case where the LLM DID emit a companion text slide
    next to the image_native one; we must not duplicate it.
    """
    brief = {"slides": [{"num": 4, "raw_title": "OBS обзор",
                         "raw_body": [
                             "OBS — это открытая платформа для записи и "
                             "стриминга, поддерживающая множество источников.",
                             "Конфигурация сцен и переходов выполняется через "
                             "удобный графический интерфейс приложения.",
                         ]}]}
    cls = _cls([
        _image_native(4, src=4),
        {"num": 5, "slide_type": None, "category": "text", "_source_slide": 4},
    ])
    n = _inject_image_companions(cls, brief)
    assert n == 0
    assert len(cls["slides"]) == 2


def test_existing_sibling_card_grid_no_duplicate():
    """A sibling card_grid native for the same source also blocks the companion."""
    brief = {"slides": [{"num": 4, "raw_title": "OBS обзор",
                         "raw_body": [
                             "OBS — это открытая платформа для записи и "
                             "стриминга, поддерживающая множество источников.",
                             "Конфигурация сцен и переходов выполняется через "
                             "удобный графический интерфейс приложения.",
                         ]}]}
    cls = _cls([
        _image_native(4, src=4),
        {"num": 5, "slide_type": "flow_diagram_native", "category": "other",
         "_source_slide": 4, "flow": {"preset": "card_grid"}},
    ])
    assert _inject_image_companions(cls, brief) == 0
    assert len(cls["slides"]) == 2


def test_non_image_native_ignored():
    """A non-image_native slide with a big body is left entirely alone."""
    brief = {"slides": [{"num": 4, "raw_title": "T",
                         "raw_body": ["слово " * 30]}]}
    cls = _cls([{"num": 4, "slide_type": None, "category": "text",
                 "_source_slide": 4}])
    assert _inject_image_companions(cls, brief) == 0
    assert len(cls["slides"]) == 1


def test_split_part_image_native_never_touched():
    brief = {"slides": [{"num": 4, "raw_title": "T",
                         "raw_body": ["слово " * 30]}]}
    s = _image_native(4, src=4)
    s["_split_part"] = "1/2"
    cls = _cls([s])
    assert _inject_image_companions(cls, brief) == 0
    assert len(cls["slides"]) == 1


def test_fresh_num_avoids_collision_across_deck():
    """Fresh num is global max+1, not source+1 — avoids colliding with later nums."""
    brief = {"slides": [{"num": 2, "raw_title": "OBS",
                         "raw_body": [
                             "OBS — это открытая платформа для записи и "
                             "стриминга, поддерживающая множество источников.",
                             "Конфигурация сцен выполняется через интерфейс.",
                         ]}]}
    cls = _cls([
        {"num": 9, "slide_type": "title", "category": "title"},
        _image_native(2, src=2),
    ])
    n = _inject_image_companions(cls, brief)
    assert n == 1
    comp = next(s for s in cls["slides"]
                if s.get("_source_slide") == 2
                and s.get("slide_type") != "image_native")
    assert comp["num"] == 10  # max(9, 2) + 1, not source(2)+1
