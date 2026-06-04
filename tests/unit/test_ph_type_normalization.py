"""T0.2 regression: distributor ph_type must accept LLM mirror-backs.

After 39× literal_error on the 2026-06-04 live run (LLM mirrored lowercase
slot_names like "title", "col1_body", "body_left" instead of the OOXML
enum), we added a `before` validator on PlaceholderAssignment.ph_type and
upstream translation in graph.donor_map.slot_specs_for_layouts.

These tests pin both layers so a future refactor doesn't regress either.
"""
from __future__ import annotations

import pytest

from schemas.slides import PlaceholderAssignment, _normalize_ph_type


@pytest.mark.parametrize("raw, expected", [
    # Canonical enums pass through.
    ("TITLE", "TITLE"),
    ("BODY", "BODY"),
    ("CONTENT", "CONTENT"),
    ("PICTURE", "PICTURE"),
    ("OBJECT", "OBJECT"),
    ("OTHER", "OTHER"),
    # Lowercase semantic names from donor YAML.
    ("title", "TITLE"),
    ("body", "BODY"),
    ("picture", "PICTURE"),
    ("image", "PICTURE"),
    ("logo", "PICTURE"),
    ("center_title", "CENTER_TITLE"),
    # Multi-column variants — substring match.
    ("col1_body", "BODY"),
    ("col2_body", "BODY"),
    ("body_left", "BODY"),
    ("col3_content", "CONTENT"),
    ("Title_Top", "TITLE"),
    # Unknown → OTHER.
    ("xyz_unknown", "OTHER"),
    # Empty defaults to BODY.
    ("", "BODY"),
    ("   ", "BODY"),
])
def test_normalize_ph_type(raw: str, expected: str) -> None:
    assert _normalize_ph_type(raw) == expected


def test_placeholder_assignment_accepts_lowercase_slot_name() -> None:
    """The 39× failure mode: distributor returns ph_type='title'."""
    pa = PlaceholderAssignment(ph_idx=1, ph_type="title", content="X")
    assert pa.ph_type == "TITLE"


def test_placeholder_assignment_accepts_multicolumn_variant() -> None:
    pa = PlaceholderAssignment(ph_idx=3, ph_type="col1_body", content="Y")
    assert pa.ph_type == "BODY"


def test_placeholder_assignment_unknown_becomes_other() -> None:
    pa = PlaceholderAssignment(ph_idx=2, ph_type="zzz_made_up", content="Z")
    assert pa.ph_type == "OTHER"


def test_normalize_ph_type_passes_non_string_through() -> None:
    # Pydantic should then produce its normal type error.
    assert _normalize_ph_type(123) == 123
    assert _normalize_ph_type(None) is None
