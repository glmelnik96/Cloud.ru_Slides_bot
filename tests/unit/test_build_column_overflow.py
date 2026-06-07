"""Part 2: build_v9 column-body overflow safety net.

The "ДЕЙСТВИЯ В ОФИСЕ" slide's right column (col2_body) overflowed off the
bottom edge: column-body slots are kind="other" (NOT line-balanced / NOT
vertically centred — columns of different length would misalign) and donor 28
carries no safe_max_chars, so neither the geo body-balance nor the legacy
char-shrink bounds them. ``_fit_column_body`` mirrors flow_renderer's card-body
fit (shrink→truncate) to keep the text on-slide.

The shrink/truncate geometry needs LibreOffice fonts (validated in a live
render); the extractable PURE piece is the slot-name matcher that decides which
slots get the net — pinned here so the branch can never silently widen to
title/subtitle/bodyN slots.
"""
from __future__ import annotations

from worker import skill_bridge

skill_bridge.install()

from build_v9 import _COL_BODY_RE, _fit_column_body  # noqa: E402


def test_column_pattern_matches_only_column_bodies() -> None:
    # Real donor-28 column slot names (donor-slot-map.yaml) + the bare form.
    assert _COL_BODY_RE.match("col1_body")
    assert _COL_BODY_RE.match("col2_body")
    assert _COL_BODY_RE.match("col_body")


def test_column_pattern_excludes_other_slots() -> None:
    # Must NOT touch title/subtitle/number or the bodyN slots (those keep their
    # own balance/anchor handling) — the net is column-only.
    for name in ("title", "subtitle", "number", "body", "body1", "body6",
                 "sub1", "colab_body", "col1_title"):
        assert not _COL_BODY_RE.match(name), name


def test_fit_column_body_noop_on_degenerate_box() -> None:
    """No fonts / degenerate geometry → returns (base_pt, text) unchanged, so
    the net can never render worse than before."""

    class _FakeShape:
        width = 0
        height = 0

    pt, txt = _fit_column_body(_FakeShape(), 20.0, "любой текст колонки")
    assert pt == 20.0
    assert txt == "любой текст колонки"


def test_fit_column_body_noop_on_empty_text() -> None:
    class _FakeShape:
        width = 1_000_000
        height = 1_000_000

    pt, txt = _fit_column_body(_FakeShape(), 20.0, "   ")
    assert pt == 20.0
    assert txt == "   "
