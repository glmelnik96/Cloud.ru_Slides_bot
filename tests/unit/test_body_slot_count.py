"""Phase-1 auto-structuring: donor body-slot capacity helpers.

Anchors against the live donor-slot-map.yaml so the detector's capacity
counting can't silently drift if the slot map changes shape.
"""
from __future__ import annotations

from graph.donor_map import body_ph_indices, body_slot_count


def test_body_slot_count_known_donors() -> None:
    # content_text / 2col / 3col / 4block donors — see plan File Structure table.
    assert body_slot_count(21) == 1
    assert body_slot_count(28) == 2
    assert body_slot_count(34) == 3
    assert body_slot_count(29) == 4


def test_body_slot_count_native_and_unknown_is_zero() -> None:
    assert body_slot_count(0) == 0          # native render — no donor
    assert body_slot_count(999_999) == 0    # not in the slot map


def test_body_ph_indices_match_count() -> None:
    idxs = body_ph_indices(34)
    assert isinstance(idxs, set)
    assert len(idxs) == body_slot_count(34) == 3
    assert all(isinstance(i, int) for i in idxs)


def test_body_ph_indices_empty_for_native() -> None:
    assert body_ph_indices(0) == set()
