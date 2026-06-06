"""Deterministic visual_kind routing."""
from __future__ import annotations

from worker import skill_bridge

skill_bridge.install()

from visual_kind import (  # noqa: E402
    classify_visual_kind,
    RASTER_MIN_AREA_PX,
    STRUCTURED_MIN_NODES,
    STRUCTURED_MAX_NODES,
)

EMU = 9525


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
