"""Progress message rendering: bar fill + stage labels + terminal templates."""
from __future__ import annotations

import pytest

from bot.i18n.progress import STAGE_RU, format_progress, format_terminal


def test_format_progress_zero_renders_empty_bar():
    out = format_progress("queued", 0)
    assert "В очереди" in out
    assert "0%" in out
    assert "█" not in out
    assert "░" * 12 in out


def test_format_progress_full_renders_full_bar():
    out = format_progress("done", 100)
    assert "100%" in out
    assert "█" * 12 in out
    assert "░" not in out


def test_format_progress_includes_detail_in_italics():
    out = format_progress("parsing", 50, "разбор XML")
    assert "<i>разбор XML</i>" in out


def test_format_progress_skips_detail_block_when_empty():
    out = format_progress("parsing", 50)
    assert "<i>" not in out


@pytest.mark.parametrize("pct,filled", [(0, 0), (8, 1), (50, 6), (92, 11), (100, 12)])
def test_format_progress_bar_lengths(pct, filled):
    out = format_progress("parsing", pct)
    assert out.count("█") == filled
    assert out.count("░") == 12 - filled


def test_format_terminal_done_uses_check_emoji():
    assert "✅" in format_terminal("done")


def test_format_terminal_cancelled():
    assert "🚫" in format_terminal("cancelled")


def test_format_terminal_failed_with_error_includes_it():
    out = format_terminal("failed", "timeout")
    assert "❌" in out
    assert "timeout" in out


def test_format_terminal_failed_without_error_omits_code_block():
    out = format_terminal("failed")
    assert "<code>" not in out


def test_format_terminal_halted_distinct_label():
    assert "⏸️" in format_terminal("halted")


def test_stage_glossary_covers_all_pipeline_stages():
    # If we add a new Stage, we want the user-facing label to follow.
    from schemas.session import Stage
    for s in Stage:
        assert s.value in STAGE_RU, f"missing RU label for {s.value}"
