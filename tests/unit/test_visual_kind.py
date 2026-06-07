"""Deterministic visual_kind routing."""
from __future__ import annotations

from worker import skill_bridge

skill_bridge.install()

from visual_kind import (  # noqa: E402
    classify_visual_kind,
    RASTER_MIN_AREA_PX,
    STRUCTURED_MIN_NODES,
    STRUCTURED_MAX_NODES,
    DOMINANT_RASTER_FRACTION,
    DEFAULT_SLIDE_W_EMU,
    DEFAULT_SLIDE_H_EMU,
)

EMU = 9525

# Standard 16:9 slide area in px-at-96 (1280 x 720 = 921600 px²).
_SLIDE_AREA_PX = (DEFAULT_SLIDE_W_EMU / EMU) * (DEFAULT_SLIDE_H_EMU / EMU)


def _img_for_fraction(frac):
    """Square image (in EMU) covering ``frac`` of a default 16:9 slide."""
    side_px = (_SLIDE_AREA_PX * frac) ** 0.5
    return {"width_emu": int(side_px * EMU), "height_emu": int(side_px * EMU)}


def _node(text, order):
    return {"text": text, "left": order * 100 * EMU, "top": 200 * EMU,
            "w": 90 * EMU, "h": 40 * EMU, "order": order}


def test_none_when_normal_text():
    sd = {"title": "Заголовок", "body": ["абзац один", "абзац два"],
          "group_nodes": [], "images": []}
    assert classify_visual_kind(sd) == "none"


def test_structured_numbered_nodes():
    sd = {"title": None, "body": [],
          "group_nodes": [_node(f"Пункт {i}", i) for i in range(1, 6)],
          "images": []}
    assert classify_visual_kind(sd) == "structured"


def test_raster_large_picture():
    sd = {"title": None, "body": [], "group_nodes": [],
          "images": [{"width_emu": 1149 * EMU, "height_emu": 535 * EMU}]}
    assert classify_visual_kind(sd) == "raster"


def test_opaque_no_text_no_raster():
    sd = {"title": None, "body": [], "group_nodes": [],
          "images": [{"width_emu": 100 * EMU, "height_emu": 100 * EMU}]}  # icon-sized
    assert classify_visual_kind(sd) == "opaque"


def test_threshold_two_nodes_not_structured():
    sd = {"title": None, "body": [], "group_nodes": [_node("A", 1), _node("B", 2)],
          "images": []}
    assert classify_visual_kind(sd) != "structured"


def test_threshold_nine_nodes_falls_to_opaque():
    sd = {"title": None, "body": [],
          "group_nodes": [_node(f"N{i}", i) for i in range(1, 10)],
          "images": []}
    assert classify_visual_kind(sd) == "opaque"


def test_constants_sane():
    assert RASTER_MIN_AREA_PX == 200 * 200
    assert STRUCTURED_MIN_NODES == 3
    assert STRUCTURED_MAX_NODES == 8
    # Threshold must sit well above an icon (~4%) and below a half-slide diagram.
    assert 0.10 < DOMINANT_RASTER_FRACTION < 0.50


# --- hybrid text + dominant image recovery (the fix) ---------------------

def test_hybrid_text_with_dominant_image_is_raster():
    """Title + body + a half-slide image → recover image (was dropped as none)."""
    sd = {"title": "Архитектура", "body": ["описание один", "описание два"],
          "group_nodes": [], "images": [_img_for_fraction(0.50)]}
    assert classify_visual_kind(sd) == "raster"


def test_hybrid_text_with_small_icon_stays_none():
    """Title + body + a 180x180 px icon → text slide, image ignored (not hijacked)."""
    sd = {"title": "Преимущества", "body": ["пункт"],
          "group_nodes": [],
          "images": [{"width_emu": 180 * EMU, "height_emu": 180 * EMU}]}
    assert classify_visual_kind(sd) == "none"


def test_no_text_dominant_image_still_raster():
    sd = {"title": None, "body": [], "group_nodes": [],
          "images": [_img_for_fraction(0.50)]}
    assert classify_visual_kind(sd) == "raster"


def test_text_no_images_stays_none():
    sd = {"title": "Только текст", "body": ["а", "б"],
          "group_nodes": [], "images": []}
    assert classify_visual_kind(sd) == "none"


def test_hybrid_just_above_threshold_is_raster():
    sd = {"title": "T", "body": ["b"], "group_nodes": [],
          "images": [_img_for_fraction(DOMINANT_RASTER_FRACTION + 0.03)]}
    assert classify_visual_kind(sd) == "raster"


def test_hybrid_just_below_threshold_stays_none():
    sd = {"title": "T", "body": ["b"], "group_nodes": [],
          "images": [_img_for_fraction(DOMINANT_RASTER_FRACTION - 0.03)]}
    assert classify_visual_kind(sd) == "none"


def test_structured_diagram_unchanged_with_dominant_image_absent():
    """No normal text + grouped nodes → still structured (no regression)."""
    sd = {"title": None, "body": [],
          "group_nodes": [_node(f"Пункт {i}", i) for i in range(1, 6)],
          "images": []}
    assert classify_visual_kind(sd) == "structured"


def test_dominant_fraction_respects_explicit_slide_size():
    """When slide_data carries slide_size, fraction is computed against it."""
    # Tiny slide: a 300x300 px image is dominant relative to a 400x400 px slide.
    small_slide = 400 * EMU
    sd = {"title": "T", "body": ["b"], "group_nodes": [],
          "slide_size": {"width_emu": small_slide, "height_emu": small_slide},
          "images": [{"width_emu": 300 * EMU, "height_emu": 300 * EMU}]}
    assert classify_visual_kind(sd) == "raster"
