"""textfit: geometric (Pillow) text fitting against real box geometry."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skill_assets", "scripts"))

import font_resolver  # noqa: E402
import textfit  # noqa: E402

IN = 914400  # EMU per inch


@pytest.fixture
def font_path():
    # Other test modules monkeypatch the resolver dirs; start from a clean cache.
    font_resolver._fonts_dir.cache_clear()
    font_resolver.resolve.cache_clear()
    fp = font_resolver.resolve("SB Sans Display")
    assert fp, "brand OTF must be present for textfit tests"
    return fp


def _fit(font_path, text, **kw):
    base = dict(box_w_emu=6 * IN, box_h_emu=2 * IN, font_path=font_path,
               base_pt=88, min_pt=28, wrap=True)
    base.update(kw)
    return textfit.fit_text(text, **base)


def test_short_title_keeps_base_size(font_path):
    res = _fit(font_path, "Q3")
    assert res is not None
    assert res.size_pt == 88


def test_long_title_shrinks_below_base(font_path):
    res = _fit(font_path, "Платформа облачной инфраструктуры нового поколения")
    assert res is not None
    assert res.size_pt < 88


def test_longer_text_never_larger_than_shorter(font_path):
    short = _fit(font_path, "Cloud решения")
    long = _fit(font_path, "Cloud решения для крупного корпоративного бизнеса сегодня")
    assert long.size_pt <= short.size_pt


def test_clamps_at_min_pt_when_nothing_fits(font_path):
    # Absurdly long single token in a tiny box can't fit; clamp at the floor.
    res = _fit(font_path, "Суперкалифрагилистикэкспиалидоция" * 4,
               box_w_emu=1 * IN, box_h_emu=1 * IN, min_pt=20)
    assert res is not None
    assert res.size_pt == 20


def test_wrap_false_keeps_single_segment_line(font_path):
    # Numbers: one segment -> one line regardless of width.
    res = textfit.fit_text("199", box_w_emu=2 * IN, box_h_emu=1 * IN,
                           font_path=font_path, base_pt=66, min_pt=24, wrap=False)
    assert res is not None
    assert res.lines == 1


def test_short_text_in_tall_box_requests_centre(font_path):
    res = textfit.fit_text("Итоги", box_w_emu=6 * IN, box_h_emu=6 * IN,
                           font_path=font_path, base_pt=40, min_pt=28,
                           wrap=True, balance=True)
    assert res is not None
    assert res.anchor_middle is True


def test_balance_off_never_centres(font_path):
    res = textfit.fit_text("Итоги", box_w_emu=6 * IN, box_h_emu=6 * IN,
                           font_path=font_path, base_pt=40, min_pt=28,
                           wrap=True, balance=False)
    assert res.anchor_middle is False


def test_empty_text_returns_none(font_path):
    assert _fit(font_path, "   ") is None


def test_bad_geometry_returns_none(font_path):
    assert _fit(font_path, "Заголовок", box_w_emu=0) is None


def test_unreadable_font_returns_none():
    assert _fit("/no/such/font.otf", "Заголовок") is None
