"""Deterministic visual-slide routing in classify_node."""
from __future__ import annotations

from graph.nodes.agents import _inject_visual_slides


def _cls(slides):
    return {"slides": slides}


def test_raster_forces_image_native_with_path():
    parsed = {"slides": [
        {"num": 3, "visual_kind": "raster", "title": "Архитектура",
         "image_path": "/tmp/x/slide3_img1.png"},
    ]}
    cls = _cls([{"num": 3, "slide_type": None, "category": "image",
                 "image": None, "kpi": None, "chart": None, "table": None, "flow": None}])
    counts = _inject_visual_slides(cls, parsed)
    assert counts["image"] == 1
    s = cls["slides"][0]
    assert s["slide_type"] == "image_native"
    assert s["image"]["image_path"] == "/tmp/x/slide3_img1.png"
    assert s["image"]["title"] == "Архитектура"


def test_opaque_without_image_path_is_left_alone():
    parsed = {"slides": [{"num": 5, "visual_kind": "opaque"}]}  # no image_path
    cls = _cls([{"num": 5, "slide_type": None, "image": None}])
    counts = _inject_visual_slides(cls, parsed)
    assert counts["image"] == 0
    assert cls["slides"][0]["slide_type"] is None


def test_structured_builds_card_grid_from_group_nodes():
    parsed = {"slides": [
        {"num": 8, "visual_kind": "structured", "title": "Этапы",
         "group_nodes": [
             {"text": "Шаг 1", "order": 1},
             {"text": "Шаг 2", "order": 2},
             {"text": "Шаг 3", "order": 3},
         ]},
    ]}
    cls = _cls([{"num": 8, "slide_type": None, "flow": None}])
    counts = _inject_visual_slides(cls, parsed)
    assert counts["flow"] == 1
    s = cls["slides"][0]
    assert s["slide_type"] == "flow_diagram_native"
    assert s["flow"]["preset"] == "card_grid"
    assert [c["title"] for c in s["flow"]["cards"]] == ["Шаг 1", "Шаг 2", "Шаг 3"]
    assert s["flow"]["cols"] == 2


def test_split_part_is_never_touched():
    parsed = {"slides": [{"num": 3, "visual_kind": "raster",
                          "image_path": "/tmp/x.png"}]}
    cls = _cls([{"num": 3, "_split_part": "1/2", "slide_type": None, "image": None}])
    counts = _inject_visual_slides(cls, parsed)
    assert counts["image"] == 0
    assert cls["slides"][0]["slide_type"] is None


def test_none_visual_kind_inert():
    parsed = {"slides": [{"num": 1, "visual_kind": "none", "title": "T"}]}
    cls = _cls([{"num": 1, "slide_type": None}])
    counts = _inject_visual_slides(cls, parsed)
    assert counts == {"image": 0, "flow": 0}
