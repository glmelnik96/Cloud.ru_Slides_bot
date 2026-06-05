"""D1: editorial single-series bar chart — per-bar green ramp + выноска overlay."""
from __future__ import annotations

from worker import skill_bridge

skill_bridge.install()
from pptx import Presentation  # noqa: E402

from chart_native_pptx import (  # noqa: E402
    _green_ramp, is_editorial_eligible, render_chart_pptx_slide,
)


def test_green_ramp_dark_to_bright_with_accent():
    ramp = _green_ramp(4, accent_idx=3)
    assert len(ramp) == 4
    # Accent bar is the brightest brand green (#26D07C).
    assert str(ramp[3]).upper() == "26D07C"
    # Earlier bars are darker (lower luminance) than the accent.
    def lum(c):
        h = str(c)
        return int(h[0:2], 16) + int(h[2:4], 16) + int(h[4:6], 16)
    assert lum(ramp[0]) < lum(ramp[3])


def test_editorial_eligible_only_single_series_bar():
    assert is_editorial_eligible(
        {"type": "bar", "style": "editorial",
         "series": [{"name": "a", "data": [1, 2, 3]}]}) is True
    # Multi-series → not eligible.
    assert is_editorial_eligible(
        {"type": "bar", "style": "editorial",
         "series": [{"name": "a", "data": [1]}, {"name": "b", "data": [2]}]}) is False
    # Non-bar → not eligible.
    assert is_editorial_eligible(
        {"type": "line", "style": "editorial",
         "series": [{"name": "a", "data": [1, 2]}]}) is False
    # No editorial style → not eligible.
    assert is_editorial_eligible(
        {"type": "bar", "series": [{"name": "a", "data": [1, 2]}]}) is False


def test_editorial_render_splits_bars_and_overlays_number():
    prs = Presentation(str(skill_bridge.TEMPLATE_PATH))
    layout = prs.slide_layouts[6] if len(prs.slide_layouts) > 6 else prs.slide_layouts[-1]
    slide = prs.slides.add_slide(layout)
    render_chart_pptx_slide(slide, {
        "title": "Динамика числа клиентов",
        "type": "bar", "style": "editorial",
        "x": [2023, 2024, 2025, 2026],
        "series": [{"name": "Клиенты", "data": [120, 340, 720, 1280]}],
        "accent_idx": 3,
    }, dark=True)
    # One native chart object with N single-value series (one per bar).
    charts = [s for s in slide.shapes if s.has_chart]
    assert len(charts) == 1
    assert len(list(charts[0].chart.series)) == 4
    # A large выноска number textbox carrying the peak value.
    texts = [s.text_frame.text for s in slide.shapes if s.has_text_frame]
    assert any("1280" in t for t in texts)
