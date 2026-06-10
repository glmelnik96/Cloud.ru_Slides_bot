"""A3: when a slot lacks ``safe_max_chars``, the effective safe budget must
fall back to ``0.70 * max_chars`` instead of the hard ceiling ``max_chars``.

Covers all three consumers:
- graph.donor_map.effective_safe_max_chars (feeds Agent 03 slot specs)
- skill_assets/scripts/validate_plan.validate_slide (overflow WARNING gate)
- skill_assets/scripts/build_v9 proactive shrink guard (constant only —
  behaviour exercised indirectly via the helper semantics)
"""
from __future__ import annotations

from graph.donor_map import effective_safe_max_chars
from worker import skill_bridge

skill_bridge.install()

import validate_plan  # noqa: E402


# ---------------------------------------------------------------------------
# Shared helper semantics
# ---------------------------------------------------------------------------

def test_explicit_safe_max_chars_wins() -> None:
    assert effective_safe_max_chars({"safe_max_chars": 55, "max_chars": 80}) == 55


def test_missing_safe_max_falls_back_to_70_percent() -> None:
    assert effective_safe_max_chars({"max_chars": 100}) == 70


def test_fallback_truncates_to_int() -> None:
    assert effective_safe_max_chars({"max_chars": 55}) == 38  # int(38.5)


def test_both_absent_returns_none() -> None:
    assert effective_safe_max_chars({}) is None


def test_zero_safe_max_treated_as_absent() -> None:
    # YAML authors sometimes write 0 to mean "unset"; `or`-semantics preserved.
    assert effective_safe_max_chars({"safe_max_chars": 0, "max_chars": 100}) == 70


# ---------------------------------------------------------------------------
# validate_plan WARNING gate
# ---------------------------------------------------------------------------

def _donors(slot: dict) -> dict:
    return {7: {"category": "content", "slots": {"title": slot}}}


def _slide(text: str) -> dict:
    return {"clone_from_slide": 7, "slots": {"title": text}}


def test_validate_slide_warns_above_70pct_when_safe_absent() -> None:
    # max_chars=100, no safe_max_chars → warning threshold should be 70.
    donors = _donors({"shape_idx": 0, "max_chars": 100})
    _, errors, warnings = validate_plan.validate_slide(0, _slide("x" * 80), donors)
    assert not errors
    assert any("> safe 70" in w for w in warnings)


def test_validate_slide_silent_below_70pct_when_safe_absent() -> None:
    donors = _donors({"shape_idx": 0, "max_chars": 100})
    _, errors, warnings = validate_plan.validate_slide(0, _slide("x" * 60), donors)
    assert not errors
    assert not any("safe" in w for w in warnings)


def test_validate_slide_explicit_safe_max_still_used() -> None:
    donors = _donors({"shape_idx": 0, "max_chars": 100, "safe_max_chars": 90})
    _, errors, warnings = validate_plan.validate_slide(0, _slide("x" * 80), donors)
    assert not errors
    assert not any("safe" in w for w in warnings)
