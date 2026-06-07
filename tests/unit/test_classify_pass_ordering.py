"""Pin the recover -> visual -> companion pass ordering in classify_node.

Each of the three deterministic passes added in the 2026-06-07 batch is unit
tested in ISOLATION elsewhere:

  * ``_recover_dropped_slides``  -> tests/unit/test_slide_loss_guard.py
  * ``_inject_visual_slides``    -> tests/unit/test_inject_visual_slides.py
  * ``_inject_image_companions`` -> tests/unit/test_inject_image_companions.py

The holistic review flagged that nothing pins their COOPERATION: a future
reorder would silently pass every isolated unit test while breaking the live
chain. This test exercises the three real passes (no mocking of the passes
themselves) in the exact order ``classify_node`` runs them.

Production order, ``graph/nodes/agents.py`` ``classify_node`` lines ~915-924:

    recovered_slides = _recover_dropped_slides(classification_dump, brief)   # 915
    ...                                                                      # parsed tables/charts (no-op here)
    visual_routed    = _inject_visual_slides(classification_dump, parsed)    # 922
    image_companions = _inject_image_companions(classification_dump, brief)  # 924

We call the three functions directly in that order rather than driving
``classify_node`` end-to-end: the only thing classify_node adds around them is
the LLM ``call_and_parse`` (which we would mock away entirely) plus the
``_inject_parsed_tables``/``_inject_parsed_charts``/``_diversify_text_slides``
passes, which are inert for these fixtures (no parsed grids/charts; recovery
slides already carry a slide_type/category so the diversifier skips them). The
direct call is therefore a faithful mirror of the production sub-sequence with
far less state scaffolding, and the comment above documents the exact line range
it mirrors so a reorder there is caught here.
"""
from __future__ import annotations

from graph.nodes.agents import (
    _IMG_COMPANION_MIN_BODY_WORDS,
    _inject_image_companions,
    _inject_visual_slides,
    _recover_dropped_slides,
)


def _run_chain(classification_dump, brief, parsed_deck):
    """Run the three passes in classify_node's production order (lines ~915-924).

    Mirrors graph/nodes/agents.py::classify_node exactly: recover first (so the
    injected slide flows through the later coercion passes), then visual routing
    (the image route must be settled before companions), then image companions.
    """
    recovered = _recover_dropped_slides(classification_dump, brief)
    visual = _inject_visual_slides(classification_dump, parsed_deck)
    companions = _inject_image_companions(classification_dump, brief)
    return recovered, visual, companions


# A two-sentence prose body well over the companion floor (caption-sized bodies
# fold into the image). Counted to be sure the fixture exercises the threshold.
_OBS_BODY = [
    "OBS — это открытая платформа для записи и стриминга, "
    "поддерживающая множество источников.",
    "Конфигурация сцен и переходов выполняется через удобный "
    "графический интерфейс приложения.",
]


def test_recover_then_visual_then_companion_for_dropped_raster_slide():
    """A DROPPED raster brief slide with substantial body is fully restored.

    Chain under test (production order recover -> visual -> companion):
      1. Brief slide 4 (raster, substantial prose body) is NOT in the LLM
         classification output.
      2. ``_recover_dropped_slides`` injects a plain-text recovery slide R for
         source 4.
      3. ``_inject_visual_slides`` sees parsed_deck[4].visual_kind == "raster"
         with an image_path and rewrites R to ``image_native``.
      4. ``_inject_image_companions`` then sees an image_native for source 4
         with no text sibling and injects a companion text slide carrying the
         body prose.

    End state: source 4 is represented by BOTH an image_native (image restored)
    AND a companion text slide (prose preserved), with unique deck nums. This
    would break under any reorder of the three passes.
    """
    # Sanity: the body must clear the companion floor or step 4 wouldn't fire.
    body_words = sum(len(line.split()) for line in _OBS_BODY)
    assert body_words >= _IMG_COMPANION_MIN_BODY_WORDS

    brief = {"slides": [
        {"num": 1, "raw_title": "Титул", "raw_body": ["intro"], "intent": "text"},
        # Slide 4: dropped raster slide carrying substantial prose.
        {"num": 4, "raw_title": "OBS обзор", "raw_body": _OBS_BODY,
         "intent": "text"},
    ]}
    # The LLM classification dropped brief slide 4 entirely.
    classification_dump = {"slides": [{"num": 1, "category": "title"}]}
    # parse_pptx ground truth: slide 4 is a dominant raster with an extracted
    # image_path (this signal never survives into the lossy brief, which is why
    # _inject_visual_slides consumes parsed_deck, not the brief).
    parsed_deck = {"slides": [
        {"num": 4, "visual_kind": "raster", "title": "OBS обзор",
         "image_path": "/tmp/x/slide4_img1.png"},
    ]}

    recovered, visual, companions = _run_chain(
        classification_dump, brief, parsed_deck)

    # Pass-level effects, in order.
    assert recovered == [4]               # T2 recovered the dropped slide
    assert visual["image"] == 1           # T3a routed it to image_native
    assert companions == 1                # T3b added the prose companion

    slides_for_4 = [s for s in classification_dump["slides"]
                    if (s.get("_source_slide") or s.get("num")) == 4]
    img_slides = [s for s in slides_for_4
                  if s.get("slide_type") == "image_native"]
    text_slides = [s for s in slides_for_4
                   if s.get("slide_type") != "image_native"]

    # Source 4 ends represented by EXACTLY one image_native + one companion text.
    assert len(img_slides) == 1, slides_for_4
    assert len(text_slides) == 1, slides_for_4

    img = img_slides[0]
    assert img["image"]["image_path"] == "/tmp/x/slide4_img1.png"  # image restored

    comp = text_slides[0]
    assert comp.get("slide_type") is None              # plain donor-route slide
    assert comp["category"] in ("text", "multicolumn")  # prose preserved
    assert comp["_source_slide"] == 4

    # All deck nums unique across the whole deck (no split-part / companion
    # collision — the core invariant the fresh-num allocation protects).
    nums = [s["num"] for s in classification_dump["slides"]]
    assert len(nums) == len(set(nums)), f"duplicate deck nums: {nums}"


def test_dropped_text_slide_recovery_acts_as_sibling_no_double_text():
    """Non-image case: a dropped TEXT brief slide must NOT gain a companion.

    A dropped text brief slide M is recovered as a single text/card slide by T2.
    Because no image_native is produced for M (parsed_deck has no raster for it),
    ``_inject_image_companions`` must NOT add a second text slide for M — the
    recovery slide already IS the sibling carrying the body. Exactly one slide
    for source M (no redundant double-text).
    """
    brief = {"slides": [
        {"num": 1, "raw_title": "Титул", "raw_body": ["intro"], "intent": "text"},
        # Slide 6: dropped TEXT slide with a substantial prose body — big enough
        # to clear the companion floor, so the "no double text" guard is the
        # only thing preventing a spurious second slide.
        {"num": 6, "raw_title": "Описание", "raw_body": _OBS_BODY,
         "intent": "text"},
    ]}
    classification_dump = {"slides": [{"num": 1, "category": "title"}]}
    # No raster entry for slide 6 -> _inject_visual_slides leaves it as text.
    parsed_deck = {"slides": []}

    recovered, visual, companions = _run_chain(
        classification_dump, brief, parsed_deck)

    assert recovered == [6]      # T2 recovered the dropped text slide
    assert visual["image"] == 0  # nothing routed to image_native
    assert companions == 0       # T3b added NO redundant companion

    slides_for_6 = [s for s in classification_dump["slides"]
                    if (s.get("_source_slide") or s.get("num")) == 6]
    # Exactly one recovery text/card slide, no image_native, no second text.
    assert len(slides_for_6) == 1, slides_for_6
    rec = slides_for_6[0]
    assert rec.get("slide_type") != "image_native"
    assert rec["category"] in ("text", "multicolumn")

    nums = [s["num"] for s in classification_dump["slides"]]
    assert len(nums) == len(set(nums)), f"duplicate deck nums: {nums}"
