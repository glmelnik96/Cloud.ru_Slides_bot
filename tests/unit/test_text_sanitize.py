"""Text-rendering artifact fix (2026-06-07): control-char + markdown leak.

Two artifacts observed in live decks (session 81673):
  A. ``_X000B_`` — a vertical-tab (\\x0b) in a donor TITLE renders literally as
     the text ``_X000B_`` because python-pptx XML-escapes the control char.
  B. ``**bold**`` markdown leaks into donor body/title — the model emits
     markdown bold that is never stripped on renderer text sites.

``text_sanitize.sanitize_text`` is the shared cleaner. CRITICAL: it must NOT
strip ``**`` on any path that feeds ``kpi_emphasis.apply_kpi_emphasis`` (which
uses ``**…**`` as its own emphasis markers) — hence ``strip_markdown=False``.
"""
from __future__ import annotations

import pytest

from worker import skill_bridge

skill_bridge.install()

from text_sanitize import sanitize_text  # noqa: E402


# --- control characters -----------------------------------------------------
def test_vertical_tab_removed() -> None:
    """Artifact A root cause: \\x0b must not survive into output."""
    assert "\x0b" not in sanitize_text("ТЕХНИЧЕСКИЙ\x0bРАЗДЕЛ")


def test_vertical_tab_caller_converts_to_newline_then_sanitize_is_clean() -> None:
    """build_v5 converts \\x0b→\\n first; sanitize must leave that \\n intact."""
    converted = "A\x0bB".replace("\x0b", "\n")
    out = sanitize_text(converted)
    assert out == "A\nB"
    assert "\x0b" not in out


def test_other_control_chars_removed() -> None:
    raw = "x\x0cy\x07z\x1fw\x7fq\x00p"
    out = sanitize_text(raw)
    for ch in ("\x0c", "\x07", "\x1f", "\x7f", "\x00"):
        assert ch not in out
    assert out == "xyzwqp"


def test_newline_tab_cr_preserved() -> None:
    assert sanitize_text("a\nb\tc\rd") == "a\nb\tc\rd"


# --- markdown stripping (strip_markdown=True, the default) -------------------
def test_double_asterisk_bold_stripped() -> None:
    assert sanitize_text("**bold**") == "bold"


def test_double_asterisk_inline_stripped() -> None:
    assert sanitize_text("text **a** text") == "text a text"


def test_leak_example_ccm() -> None:
    """81673 slide 5: literal asterisks around a phrase must go."""
    assert sanitize_text("**CCM (Cloud Certificate Manager)**") == (
        "CCM (Cloud Certificate Manager)"
    )


def test_single_asterisk_word_wrap_stripped() -> None:
    assert sanitize_text("an *important* word") == "an important word"


# --- conservative asterisk handling -----------------------------------------
def test_math_asterisk_not_corrupted() -> None:
    """``2*3`` is multiplication, not emphasis — leave it alone."""
    assert sanitize_text("2*3") == "2*3"


def test_leading_bullet_asterisk_not_corrupted() -> None:
    """A leading ``* item`` bullet marker must survive (lone asterisk)."""
    assert sanitize_text("* item") == "* item"


# --- KPI-safe mode (strip_markdown=False) -----------------------------------
def test_strip_markdown_false_keeps_double_asterisk() -> None:
    out = sanitize_text("**emph**", strip_markdown=False)
    assert out == "**emph**"


def test_strip_markdown_false_still_removes_control_chars() -> None:
    out = sanitize_text("a\x0bb\x07c", strip_markdown=False)
    assert "\x0b" not in out
    assert "\x07" not in out
    assert "**" not in out  # nothing to strip, but also nothing corrupted


# --- guards -----------------------------------------------------------------
@pytest.mark.parametrize("val", ["", None, 0, [], 42])
def test_falsy_or_nonstr_returns_unchanged(val) -> None:
    assert sanitize_text(val) == val
