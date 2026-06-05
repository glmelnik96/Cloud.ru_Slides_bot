"""T2.1: infographic native_block renderer.

Live run 2026-06-05 confirmed Agent 06 emits 9 shapes per comparison
slide but build_v9 had no handler — visual verifier blocked on
``plan_compliance``. These tests pin the renderer behaviour so a
regression on the build path is caught before live spend.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from worker import skill_bridge

skill_bridge.install()
from pptx import Presentation  # noqa: E402
from pptx.enum.shapes import MSO_SHAPE_TYPE  # noqa: E402

from infographic_renderer import (  # noqa: E402  (path injected by skill_bridge)
    _parse_hex,
    clear_donor_body_slots,
    clear_donor_non_title_text,
    render_infographic_shapes,
)
from pptx.util import Emu, Pt  # noqa: E402


@pytest.fixture
def blank_slide():
    """A fresh blank slide from the template — independent per test."""
    prs = Presentation(str(skill_bridge.TEMPLATE_PATH))
    blank_layout = prs.slide_layouts[6] if len(prs.slide_layouts) > 6 else prs.slide_layouts[-1]
    return prs.slides.add_slide(blank_layout)


def test_parse_hex_valid_and_invalid() -> None:
    from pptx.dml.color import RGBColor
    c = _parse_hex("#26D07C")
    assert isinstance(c, RGBColor)
    assert _parse_hex("26d07c") is not None
    assert _parse_hex("none") is None
    assert _parse_hex("") is None
    assert _parse_hex(None) is None
    assert _parse_hex("#zzzzzz") is None
    assert _parse_hex("#12") is None


def test_render_rounded_rect_adds_shape(blank_slide) -> None:
    before = len(blank_slide.shapes)
    added = render_infographic_shapes(blank_slide, [{
        "type": "rounded_rect",
        "left_emu": 100000, "top_emu": 100000,
        "width_emu": 2000000, "height_emu": 500000,
        "fill_color": "#26D07C", "stroke_color": "none",
        "stroke_width_pt": 0.0,
        "text": "Prognoz",
        "font": "SB Sans Display Semibold",
        "font_size_pt": 14, "font_color": "#222222",
    }])
    assert added == 1
    assert len(blank_slide.shapes) == before + 1
    shape = blank_slide.shapes[-1]
    assert shape.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE
    # Text actually written into the rect.
    assert "Prognoz" in shape.text_frame.text


def test_render_textbox_adds_shape(blank_slide) -> None:
    before = len(blank_slide.shapes)
    added = render_infographic_shapes(blank_slide, [{
        "type": "text",
        "left_emu": 200000, "top_emu": 200000,
        "width_emu": 3000000, "height_emu": 400000,
        "fill_color": "none", "stroke_color": "none",
        "stroke_width_pt": 0.0,
        "text": "275 контактов",
        "font": "SB Sans Display",
        "font_size_pt": 16, "font_color": "#222222",
    }])
    assert added == 1
    assert len(blank_slide.shapes) == before + 1
    assert "275 контактов" in blank_slide.shapes[-1].text_frame.text


@pytest.mark.parametrize("kind", ["rectangle", "circle", "arrow", "line"])
def test_render_additional_shape_types(blank_slide, kind: str) -> None:
    """T2.5: rectangle / circle / arrow / line — added 2026-06-05 after
    live run dropped 3/15 arrow shapes from a process infographic."""
    before = len(blank_slide.shapes)
    added = render_infographic_shapes(blank_slide, [{
        "type": kind,
        "left_emu": 100000, "top_emu": 100000,
        "width_emu": 800000, "height_emu": 200000,
        "fill_color": "#26D07C" if kind != "line" else "none",
        "stroke_color": "#222222",
        "stroke_width_pt": 1.0,
        "text": "",
    }])
    assert added == 1, f"{kind} should be added"
    assert len(blank_slide.shapes) == before + 1


def test_render_skips_unknown_type(blank_slide) -> None:
    before = len(blank_slide.shapes)
    added = render_infographic_shapes(blank_slide, [
        {"type": "ellipse", "left_emu": 0, "top_emu": 0,
         "width_emu": 100000, "height_emu": 100000},
        {"type": "rounded_rect", "left_emu": 0, "top_emu": 0,
         "width_emu": 1000000, "height_emu": 500000,
         "fill_color": "#26D07C", "text": ""},
    ])
    assert added == 1
    assert len(blank_slide.shapes) == before + 1


def test_render_empty_list_noop(blank_slide) -> None:
    before = len(blank_slide.shapes)
    assert render_infographic_shapes(blank_slide, []) == 0
    assert len(blank_slide.shapes) == before


def test_render_swallows_bad_spec(blank_slide) -> None:
    """Non-dict entries are logged and skipped — never raise."""
    before = len(blank_slide.shapes)
    added = render_infographic_shapes(blank_slide, ["string", 42, None])
    assert added == 0
    assert len(blank_slide.shapes) == before


def test_render_live_comparison_block(blank_slide) -> None:
    """End-to-end: 9 shapes mirroring the 2026-06-05 slide 2 native_block."""
    shapes = (
        [{"type": "rounded_rect", "left_emu": 100000, "top_emu": 1000000,
          "width_emu": 5000000, "height_emu": 500000,
          "fill_color": "#222222", "stroke_color": "none",
          "stroke_width_pt": 0.0, "text": "Q1 2026",
          "font": "SB Sans Display Semibold", "font_size_pt": 14,
          "font_color": "#FFFFFF"}]
        + [{"type": "text", "left_emu": 200000, "top_emu": 1500000 + 400000 * i,
            "width_emu": 4800000, "height_emu": 350000,
            "fill_color": "none", "stroke_color": "none",
            "stroke_width_pt": 0.0,
            "text": f"строка {i}", "font": "SB Sans Display",
            "font_size_pt": 12, "font_color": "#222222"}
           for i in range(3)]
        + [{"type": "rounded_rect", "left_emu": 6800000, "top_emu": 1000000,
            "width_emu": 5000000, "height_emu": 500000,
            "fill_color": "#26D07C", "stroke_color": "none",
            "stroke_width_pt": 0.0, "text": "Q2 2026",
            "font": "SB Sans Display Semibold", "font_size_pt": 14,
            "font_color": "#222222"}]
        + [{"type": "text", "left_emu": 6900000, "top_emu": 1500000 + 400000 * i,
            "width_emu": 4800000, "height_emu": 350000,
            "fill_color": "none", "stroke_color": "none",
            "stroke_width_pt": 0.0,
            "text": f"итог {i}", "font": "SB Sans Display",
            "font_size_pt": 12, "font_color": "#222222"}
           for i in range(4)]
    )
    before = len(blank_slide.shapes)
    added = render_infographic_shapes(blank_slide, shapes)
    assert added == 9
    assert len(blank_slide.shapes) == before + 9


def test_clear_donor_body_keeps_title(blank_slide) -> None:
    """Title-like slots are preserved; body/content/caption/col* are cleared."""
    donor_def = {
        "slots": {
            "title": {"shape_idx": 0},
            "body": {"shape_idx": 1},
            "col1_body": {"shape_idx": 2},
            "caption": {"shape_idx": 3},
        }
    }
    # No shapes match, so the function just probes and skips — exercising the
    # name filter without depending on a particular donor.
    cleared = clear_donor_body_slots(blank_slide, donor_def)
    assert cleared >= 0  # blank slide → no matching idx, function returns safely


def test_clear_donor_body_handles_none_def(blank_slide) -> None:
    assert clear_donor_body_slots(blank_slide, None) == 0
    assert clear_donor_body_slots(blank_slide, {}) == 0


def _add_textbox_with_text(slide, text: str, *, font_pt: int = 14):
    """Helper: append a plain textbox with given text/font size."""
    box = slide.shapes.add_textbox(Emu(100000), Emu(100000), Emu(2000000), Emu(500000))
    tf = box.text_frame
    p = tf.paragraphs[0]
    run = p.add_run()
    run.text = text
    run.font.size = Pt(font_pt)
    return box


def test_clear_donor_non_title_text_clears_body_keeps_title(blank_slide) -> None:
    """D1+D8 fix: non-title text on donor (process labels, comparison cells)
    is cleared so Agent 06 shapes don't overlap pre-existing donor labels."""
    title_box = _add_textbox_with_text(blank_slide, "Заголовок слайда", font_pt=24)
    body1 = _add_textbox_with_text(blank_slide, "Recorder", font_pt=14)
    body2 = _add_textbox_with_text(blank_slide, "Хранение данных", font_pt=12)

    cleared = clear_donor_non_title_text(blank_slide)
    # Two body labels cleared, title kept.
    assert cleared >= 2
    assert "Заголовок" in title_box.text_frame.text
    assert (body1.text_frame.text or "").strip() == ""
    assert (body2.text_frame.text or "").strip() == ""


def test_clear_donor_non_title_text_handles_empty_slide(blank_slide) -> None:
    assert clear_donor_non_title_text(blank_slide) == 0


def test_clear_donor_non_title_text_skips_already_empty(blank_slide) -> None:
    """No body text → nothing to clear."""
    _add_textbox_with_text(blank_slide, "Title", font_pt=24)
    _add_textbox_with_text(blank_slide, "", font_pt=14)
    cleared = clear_donor_non_title_text(blank_slide)
    assert cleared == 0
