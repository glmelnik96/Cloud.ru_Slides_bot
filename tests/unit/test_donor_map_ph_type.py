"""T0.2 upstream: donor_map.slot_specs_for_layouts must translate semantic
slot names → OOXML PlaceholderType BEFORE sending them to the LLM.

Without this, the distributor LLM mirrors lowercase back and every
placeholder_assignment fails Pydantic validation.

Also covers T0.3 sanity: donor 53 now has remove_before_fill=[0].
"""
from __future__ import annotations

import yaml

from graph.donor_map import (
    _slot_name_to_ooxml,
    slot_specs_for_layouts,
    valid_donor_ids,
)
from worker import skill_bridge


def test_slot_name_to_ooxml_known_keys() -> None:
    assert _slot_name_to_ooxml("title") == "TITLE"
    assert _slot_name_to_ooxml("body") == "BODY"
    assert _slot_name_to_ooxml("center_title") == "CENTER_TITLE"
    assert _slot_name_to_ooxml("logo") == "PICTURE"


def test_slot_name_to_ooxml_substring_fallback() -> None:
    assert _slot_name_to_ooxml("col1_body") == "BODY"
    assert _slot_name_to_ooxml("body_left") == "BODY"
    assert _slot_name_to_ooxml("subtitle_top") == "TITLE"
    assert _slot_name_to_ooxml("xx_picture") == "PICTURE"


def test_slot_name_to_ooxml_unknown_returns_other() -> None:
    assert _slot_name_to_ooxml("zzz_made_up") == "OTHER"
    assert _slot_name_to_ooxml("") == "OTHER"


def test_slot_specs_emit_uppercase_ooxml_types() -> None:
    """Pick a handful of real donors and assert every ph_type is canonical."""
    canonical = {"TITLE", "CENTER_TITLE", "SUBTITLE", "BODY", "CONTENT",
                 "PICTURE", "OBJECT", "OTHER"}
    sample = sorted(valid_donor_ids())[:8]  # first 8 mapped donors
    specs = slot_specs_for_layouts(sample)
    assert specs, "expected at least one donor to produce specs"
    for layout_str, slot_list in specs.items():
        for spec in slot_list:
            assert spec["ph_type"] in canonical, (
                f"donor {layout_str}: slot {spec['slot_name']!r} "
                f"produced non-canonical ph_type {spec['ph_type']!r}"
            )
            # Must keep ph_idx + slot_name for traceability.
            assert isinstance(spec["ph_idx"], int)
            assert isinstance(spec["slot_name"], str)


def test_slot_specs_skip_native_and_unknown() -> None:
    # idx 0 = native render; unknown idx must be silently skipped.
    out = slot_specs_for_layouts([0, 999_999])
    assert out == {}


def test_donor_53_has_remove_before_fill() -> None:
    """T0.3 regression: donor 53 PNG placeholder must always be stripped."""
    with open(skill_bridge.DONOR_SLOT_MAP, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    d53 = raw["donors"][53]
    assert d53.get("remove_before_fill") == [0], (
        "donor 53 must have remove_before_fill=[0] to avoid "
        "PNG-заглушка warning on every build"
    )
